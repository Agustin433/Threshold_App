"""El z del plantel se calcula una vez por cambio de datos, no por rerun.

`calc_zscores` sobre 18 atletas cuesta ~450 ms y corria en el render del Team
view, mas una vez por cada cuadrante: cada uno llamaba a `_prepare_jump_df` de
nuevo porque nada marcaba el frame como ya preparado. Eran ~1,9 s por click, y
crece lineal con las filas.
"""

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from modules.jump_analysis import (
    JUMP_PREPARED_COLUMN,
    NON_NUMERIC_EVALUATION_COLUMNS,
    _prepare_jump_df,
)


def _jump_rows(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Athlete": f"Atleta {index}",
                "Date": "2026-05-01",
                "Source": "platform",
                "BW_kg": 72 + index,
                "CMJ_cm": 32.0 + index * 0.4,
                "SJ_cm": 29.0 + index * 0.3,
                "DJ_cm": 24.0 + index * 0.2,
                "DJ_tc_ms": 220 - index,
                "DJ_drop_height_cm": 30,
                "IMTP_N": 1900 + index * 40,
            }
            for index in range(n)
        ]
    )


def _profiles(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Athlete": f"Atleta {index}",
                "Deporte": "Handball",
                "Nivel": "Competitivo",
                "Sexo": "M",
            }
            for index in range(n)
        ]
    )


class JumpPreparedMarkerTest(unittest.TestCase):
    def test_prepare_marks_the_frame_as_prepared(self):
        prepared = _prepare_jump_df(_jump_rows(), profile_df=_profiles())

        self.assertIn(JUMP_PREPARED_COLUMN, prepared.columns)
        self.assertTrue(prepared[JUMP_PREPARED_COLUMN].all())

    def test_marker_survives_the_numeric_coercion(self):
        # `_prepare_jump_df` convierte a numerico todo lo que no este declarado
        # como no numerico. Sin registrarlo, el marcador se volveria NaN y el
        # cortocircuito no dispararia nunca.
        self.assertIn(JUMP_PREPARED_COLUMN, NON_NUMERIC_EVALUATION_COLUMNS)

        twice = _prepare_jump_df(
            _prepare_jump_df(_jump_rows(), profile_df=_profiles()), profile_df=_profiles()
        )
        self.assertTrue(twice[JUMP_PREPARED_COLUMN].all())

    def test_charts_reuse_a_prepared_frame_instead_of_recomputing(self):
        import charts.dashboard_charts as charts_module

        prepared = _prepare_jump_df(_jump_rows(), profile_df=_profiles())
        with patch.object(charts_module, "_prepare_jump_df") as mocked:
            reused = charts_module._prepare_frame(prepared)

        mocked.assert_not_called()
        self.assertEqual(len(reused), len(prepared))

    def test_charts_still_prepare_a_raw_frame(self):
        import charts.dashboard_charts as charts_module

        raw = _jump_rows()
        with patch.object(
            charts_module, "_prepare_jump_df", return_value=pd.DataFrame({"Athlete": ["x"]})
        ) as mocked:
            charts_module._prepare_frame(raw)

        mocked.assert_called_once()

    def test_reused_frame_carries_the_same_zscores(self):
        # La memoizacion no puede cambiar resultados: el frame reutilizado tiene
        # que ser identico al que se recalcularia.
        import charts.dashboard_charts as charts_module

        prepared = _prepare_jump_df(_jump_rows(), profile_df=_profiles())
        recomputed = charts_module._prepare_frame(_jump_rows(), _profiles())
        reused = charts_module._prepare_frame(prepared)

        for column in sorted(c for c in prepared.columns if c.endswith("_Z")):
            pd.testing.assert_series_equal(
                pd.to_numeric(reused[column], errors="coerce"),
                pd.to_numeric(recomputed[column], errors="coerce"),
                check_names=False,
            )


class EnsurePreparedJumpDfTest(unittest.TestCase):
    """Memo en `session_state`, con el mismo patron que `prepared_raw_df`."""

    def _module(self):
        import modules.page_state as page_state_module

        return importlib.reload(page_state_module)

    def test_reuses_while_the_version_does_not_change(self):
        page_state = self._module()
        frame = _jump_rows()
        prepared = _prepare_jump_df(frame, profile_df=_profiles())
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state, "st", fake_st), patch.object(
            page_state, "current_jump_state_version", return_value=(("jump_df", True, 1, 10),)
        ), patch.object(page_state, "prepare_jump_df", return_value=prepared) as mocked:
            first = page_state.ensure_prepared_jump_df(frame, source="platform")
            second = page_state.ensure_prepared_jump_df(frame, source="platform")

        self.assertIs(first, prepared)
        self.assertIs(second, prepared)
        self.assertEqual(mocked.call_count, 1)

    def test_rebuilds_when_the_store_version_changes(self):
        page_state = self._module()
        frame = _jump_rows()
        first_frame = _prepare_jump_df(frame, profile_df=_profiles())
        second_frame = _prepare_jump_df(_jump_rows(9), profile_df=_profiles(9))
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state, "st", fake_st), patch.object(
            page_state,
            "current_jump_state_version",
            side_effect=[(("jump_df", True, 1, 10),), (("jump_df", True, 2, 10),)],
        ), patch.object(
            page_state, "prepare_jump_df", side_effect=[first_frame, second_frame]
        ) as mocked:
            first = page_state.ensure_prepared_jump_df(frame, source="platform")
            second = page_state.ensure_prepared_jump_df(frame, source="platform")

        self.assertIs(first, first_frame)
        self.assertIs(second, second_frame)
        self.assertEqual(mocked.call_count, 2)

    def test_rebuilds_when_the_measurement_source_changes(self):
        # Plataforma y no-plataforma son poblaciones distintas: si la fuente no
        # entra en la firma, el frame de una se mostraria como el de la otra.
        page_state = self._module()
        frame = _jump_rows()
        platform_frame = _prepare_jump_df(frame, profile_df=_profiles())
        manual_frame = _prepare_jump_df(_jump_rows(9), profile_df=_profiles(9))
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state, "st", fake_st), patch.object(
            page_state, "current_jump_state_version", return_value=(("jump_df", True, 1, 10),)
        ), patch.object(
            page_state, "prepare_jump_df", side_effect=[platform_frame, manual_frame]
        ) as mocked:
            first = page_state.ensure_prepared_jump_df(frame, source="platform")
            second = page_state.ensure_prepared_jump_df(frame, source="manual")

        self.assertIs(first, platform_frame)
        self.assertIs(second, manual_frame)
        self.assertEqual(mocked.call_count, 2)

    def test_force_reload_rebuilds(self):
        page_state = self._module()
        frame = _jump_rows()
        prepared = _prepare_jump_df(frame, profile_df=_profiles())
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state, "st", fake_st), patch.object(
            page_state, "current_jump_state_version", return_value=(("jump_df", True, 1, 10),)
        ), patch.object(page_state, "prepare_jump_df", return_value=prepared) as mocked:
            page_state.ensure_prepared_jump_df(frame, source="platform")
            page_state.ensure_prepared_jump_df(frame, source="platform", force_reload=True)

        self.assertEqual(mocked.call_count, 2)

    def test_empty_frame_returns_empty_without_preparing(self):
        page_state = self._module()
        fake_st = SimpleNamespace(session_state={})

        with patch.object(page_state, "st", fake_st), patch.object(
            page_state, "prepare_jump_df"
        ) as mocked:
            result = page_state.ensure_prepared_jump_df(pd.DataFrame(), source="platform")

        self.assertTrue(result.empty)
        mocked.assert_not_called()

    def test_invalidating_the_store_clears_the_memo(self):
        page_state = self._module()
        fake_st = SimpleNamespace(
            session_state={
                page_state.PREPARED_JUMP_DF_KEY: _jump_rows(),
                page_state.PREPARED_JUMP_DF_SIGNATURE_KEY: ("firma",),
            }
        )

        with patch.object(page_state, "st", fake_st):
            page_state.invalidate_prepared_jump_df()

        self.assertIsNone(fake_st.session_state[page_state.PREPARED_JUMP_DF_KEY])
        self.assertIsNone(fake_st.session_state[page_state.PREPARED_JUMP_DF_SIGNATURE_KEY])


if __name__ == "__main__":
    unittest.main()
