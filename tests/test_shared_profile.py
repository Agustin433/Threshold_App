"""PR Q: primera carga. Mismos resultados antes y despues.

- El perfil compuesto se calcula una vez por contenido del historial y se
  comparte entre Hoy (Perfiles de desarrollo) y el payload del PDF.
- Hoy prepara el plantel completo y filtra la fuente despues (reusa la
  preparacion de los insights): igual a filtrar antes.
- `professional_athlete_history` es el mismo recorte que hacia el PDF.
- `calc_monotony_strain` prepara la serie una vez por atleta: igual al
  calculo semana por semana original.
- `normalize_athlete_name` memoizado: igual a la version sin memo.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import modules.derived_cache as derived_cache
from modules import report_generator as rg
from modules.athlete_names import _normalize_name_text, normalize_athlete_name
from modules.jump_analysis import (
    _compute_composite_profile_snapshot,
    _pattern_matches,
    _prepare_jump_df,
    build_composite_profile_snapshot,
    filter_by_source,
)
from modules.load_monitoring import calc_monotony_strain

ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = Path(__file__).resolve().parent / ".tmp_shared_profile"


def _seeded_state() -> dict[str, object]:
    """Store sintetico chico con plataforma y no-plataforma (ver benchmark_views)."""
    original = os.environ.get("THRESHOLD_STORE_DIR")
    tmp = TMP_ROOT / uuid.uuid4().hex[:8]
    store = tmp / "store"
    store.mkdir(parents=True)
    try:
        os.environ["THRESHOLD_STORE_DIR"] = str(store)
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import benchmark_views
        finally:
            sys.path.pop(0)
        benchmark_views.seed_store(store, n_athletes=16, days_back=120, raw_rows=None, maxes_rows=60, flight_times=True)
        import local_store

        local_store = importlib.reload(local_store)
        state = local_store.load_recent_state()
        full = local_store.load_full_history_state(keys=["rpe_df"])
        state["rpe_full"] = full["rpe_df"]
        return state
    finally:
        if original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original
        shutil.rmtree(tmp, ignore_errors=True)
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()


STATE = _seeded_state()


def _assert_snapshot_equal(test: unittest.TestCase, left, right) -> None:
    (row_a, src_a), (row_b, src_b) = left, right
    if row_a is None or row_b is None:
        test.assertIs(row_a, row_b)
    else:
        pd.testing.assert_series_equal(row_a, row_b, check_exact=True)
    pd.testing.assert_frame_equal(src_a.reset_index(drop=True), src_b.reset_index(drop=True), check_exact=True)


class PrepareThenFilterTest(unittest.TestCase):
    def test_prepare_all_then_filter_equals_filter_then_prepare(self):
        jump_df, profile_df = STATE["jump_df"], STATE["athlete_profile_df"]
        prepared_all = _prepare_jump_df(jump_df, profile_df=profile_df)
        for source in ("platform", "nonplatform"):
            with self.subTest(source=source):
                after = filter_by_source(prepared_all, source).reset_index(drop=True)
                before = _prepare_jump_df(filter_by_source(jump_df, source), profile_df=profile_df)
                self.assertFalse(before.empty)
                # Identico (indice incluido, una vez reiniciado): Hoy lo deja en el
                # memo como si fuera la preparacion filtrada (derived_cache.prime).
                pd.testing.assert_frame_equal(after, before, check_exact=True)


class PrimedPreparationTest(unittest.TestCase):
    def setUp(self):
        self.session = {}
        patcher = patch.object(derived_cache, "_session_state", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pdf_reuses_hoy_preparation(self):
        import modules.jump_analysis as ja

        jump_df, profile_df = STATE["jump_df"], STATE["athlete_profile_df"]
        original = ja._compute_prepared_jump_df
        with patch.object(ja, "_compute_prepared_jump_df", wraps=original) as computed:
            # Hoy: prepara el plantel completo, filtra la fuente y la deja en el memo.
            prepared = filter_by_source(_prepare_jump_df(jump_df, profile_df=profile_df), "platform")
            derived_cache.prime(
                "jump_analysis._prepare_jump_df", prepared.reset_index(drop=True), filter_by_source(jump_df, "platform"), profile_df
            )
            self.assertEqual(computed.call_count, 1)
            # Atleta > Resumen / PDF: prepara lo ya filtrado -> sale del memo.
            pdf_state = {"jump_df": filter_by_source(jump_df, "platform"), "athlete_profile_df": profile_df}
            history = rg._professional_jump_history(pdf_state, "Todos")
        self.assertEqual(computed.call_count, 1, "el PDF volvio a preparar las evaluaciones")
        pd.testing.assert_frame_equal(history, rg.professional_athlete_history(prepared, "Todos"), check_exact=True)


class AthleteHistoryTest(unittest.TestCase):
    def _old_history(self, prepared: pd.DataFrame, athlete: str) -> pd.DataFrame:
        # Recorte original de _professional_jump_history (antes de PR Q).
        data = prepared.copy()
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
        data["Athlete"] = data["Athlete"].astype(str).str.strip()
        data = data.dropna(subset=["Date"])
        if athlete != "Todos":
            data = data[rg._professional_athlete_mask(data["Athlete"], athlete)]
        if data.empty:
            return pd.DataFrame()
        return data.sort_values(["Athlete", "Date"]).reset_index(drop=True)

    def test_professional_athlete_history_is_the_same_cut(self):
        prepared = _prepare_jump_df(STATE["jump_df"], profile_df=STATE["athlete_profile_df"])
        for athlete in ["Todos", *sorted(prepared["Athlete"].unique())]:
            with self.subTest(athlete=athlete):
                pd.testing.assert_frame_equal(
                    rg.professional_athlete_history(prepared, athlete), self._old_history(prepared, athlete),
                    check_exact=True,
                )


class SharedCompositeTest(unittest.TestCase):
    def setUp(self):
        self.session = {}
        patcher = patch.object(derived_cache, "_session_state", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _platform_prepared(self) -> pd.DataFrame:
        return filter_by_source(
            _prepare_jump_df(STATE["jump_df"], profile_df=STATE["athlete_profile_df"]), "platform"
        )

    def test_cached_snapshot_equals_direct_computation(self):
        prepared = self._platform_prepared()
        team = rg.professional_athlete_history(prepared, "Todos")
        for athlete in sorted(team["Athlete"].unique()):
            history = rg.professional_athlete_history(team, athlete)
            with self.subTest(athlete=athlete):
                _assert_snapshot_equal(self, build_composite_profile_snapshot(history), _compute_composite_profile_snapshot(history))
                # Segunda llamada: sale del memo y es igual.
                _assert_snapshot_equal(self, build_composite_profile_snapshot(history), _compute_composite_profile_snapshot(history))

    def test_hoy_and_pdf_share_the_same_snapshot(self):
        import modules.jump_analysis as ja

        prepared = self._platform_prepared()
        team = rg.professional_athlete_history(prepared, "Todos")
        athlete = sorted(team["Athlete"].unique())[0]
        original = ja._compute_composite_profile_snapshot
        with patch.object(ja, "_compute_composite_profile_snapshot", wraps=original) as computed:
            # Hoy (Perfiles de desarrollo) arma el perfil compuesto de cada atleta...
            for name in sorted(team["Athlete"].unique()):
                build_composite_profile_snapshot(rg.professional_athlete_history(team, name))
            hoy_calls = computed.call_count
            # ...y el PDF del mismo atleta (fuente plataforma, como Atleta > Resumen) lo reutiliza.
            pdf_state = {
                "jump_df": filter_by_source(STATE["jump_df"], "platform"),
                "athlete_profile_df": STATE["athlete_profile_df"],
            }
            payload = rg._build_professional_composite_profile_payload(pdf_state, athlete)
        self.assertEqual(hoy_calls, team["Athlete"].nunique())
        self.assertEqual(computed.call_count, hoy_calls, "el PDF recalculo el perfil compuesto")
        self.assertEqual(payload.get("state"), "available")


class DevelopmentCountsBeforeAfterTest(unittest.TestCase):
    """Perfiles de desarrollo: la historia por atleta cambio de armado (para
    compartir el perfil compuesto con el PDF); el patron resultante es el mismo."""

    def test_reactivity_patterns_match_previous_slicing(self):
        prepared = filter_by_source(
            _prepare_jump_df(STATE["jump_df"], profile_df=STATE["athlete_profile_df"]), "platform"
        )
        frame = prepared.copy()
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.normalize()
        frame = frame.dropna(subset=["Athlete", "Date"])
        team = rg.professional_athlete_history(prepared, "Todos")
        for reference in (frame["Date"].max(), frame["Date"].max() - pd.Timedelta(days=40)):
            scoped = frame[frame["Date"] <= reference]
            for athlete in sorted(scoped["Athlete"].unique()):
                old_history = scoped[scoped["Athlete"] == athlete].sort_values("Date")
                new_history = rg.professional_athlete_history(team, athlete)
                if (new_history["Date"] > reference).any():
                    new_history = new_history[new_history["Date"] <= reference].reset_index(drop=True)
                old_row, _ = _compute_composite_profile_snapshot(old_history)
                new_row, _ = _compute_composite_profile_snapshot(new_history)
                with self.subTest(athlete=athlete, reference=str(reference.date())):
                    self.assertEqual(
                        [] if old_row is None else _pattern_matches(old_row),
                        [] if new_row is None else _pattern_matches(new_row),
                    )
                    if old_row is not None:
                        pd.testing.assert_series_equal(
                            old_row.drop(labels=["Profile_Composed"], errors="ignore"),
                            new_row.drop(labels=["Profile_Composed"], errors="ignore"),
                            check_exact=True,
                        )


def _reference_calendar_week_loads(series: pd.Series, week_end: pd.Timestamp) -> pd.Series:
    """Implementacion original (antes de PR Q), para comparar."""
    end = pd.Timestamp(week_end).normalize()
    start = end - pd.Timedelta(days=6)
    loads = series.copy()
    loads.index = pd.to_datetime(loads.index, errors="coerce").normalize()
    loads = loads.dropna()
    scoped = loads.loc[(loads.index >= start) & (loads.index <= end)]
    if not scoped.empty:
        scoped = scoped.groupby(scoped.index).sum()
    return scoped.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)


class MonotonyStrainEquivalenceTest(unittest.TestCase):
    def _reference(self, srpe_daily: pd.DataFrame) -> pd.DataFrame:
        import modules.load_monitoring as lm

        with patch.object(lm, "_calendar_week_loads", lambda series, week, **_: _reference_calendar_week_loads(series, week)):
            return lm.calc_monotony_strain(srpe_daily)

    def test_same_result_as_week_by_week_original(self):
        import local_store

        acwr, _ = local_store.build_load_models(STATE["rpe_full"], weeks=None)
        cases = list(acwr.values())
        duplicated = pd.concat([cases[0], cases[0].head(5)]).sample(frac=1, random_state=1)
        with_nan = cases[1].copy()
        with_nan.loc[with_nan.index[::9], "sRPE_diario"] = np.nan
        cases += [duplicated, with_nan, cases[2].head(4)]
        for index, case in enumerate(cases):
            with self.subTest(case=index):
                pd.testing.assert_frame_equal(calc_monotony_strain(case), self._reference(case), check_exact=True)


class NormalizeNameMemoTest(unittest.TestCase):
    def test_memo_matches_uncached(self):
        names = [
            "CASTAÑO", "gaston castaño", "McDonald", "d'andrea", "  ana   lopez ", "JUAN-PEREZ",
            "o'neill", "Ana​Lopez", "", "   ",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(normalize_athlete_name(name), _normalize_name_text.__wrapped__(name))
        self.assertEqual(normalize_athlete_name(None), "")
        self.assertEqual(normalize_athlete_name(float("nan")), "")
        self.assertEqual(normalize_athlete_name(123), "123")


if __name__ == "__main__":
    unittest.main()
