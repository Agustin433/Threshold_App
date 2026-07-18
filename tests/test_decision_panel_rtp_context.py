"""End-to-end checks for the Bloque 3 (Panel de Decision) Contexto filter and
RTP handling. `render_decision_panel()` is tightly coupled to Streamlit
widgets and session_state, so these drive the real app.py script via
`streamlit.testing.v1.AppTest` against an isolated local store instead of
unit-testing extracted logic (none of this logic was extracted out of
app.py, by design).
"""

from __future__ import annotations

import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

APP_PY_PATH = Path(__file__).resolve().parent.parent / "app.py"
TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_decision_panel"

TODAY = pd.Timestamp.today().normalize()


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = None
    try:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_root = TEST_TMP_ROOT / f"decision_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True, exist_ok=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        yield store_dir
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        if TEST_TMP_ROOT.exists() and not any(TEST_TMP_ROOT.iterdir()):
            TEST_TMP_ROOT.rmdir()


def _seed_decision_fixture(store_dir: Path) -> None:
    """Two athletes with an identical sRPE history (ACWR ~1.17, in the band
    where RTP and non-RTP thresholds diverge: Optima vs Precaucion) and an
    identical Mixto/EUR=1.067 jump profile (which naturally falls into the
    "desarrollo de potencia" bucket). One is Es_RTP, the other isn't, so any
    difference between them is attributable only to the RTP flag.
    """
    dates = pd.date_range(end=TODAY, periods=28, freq="D")
    chronic = [300.0] * 21
    acute = [420.0] * 7  # -> ACWR_EWMA ~= 1.17 (Optima for non-RTP, Precaucion for RTP)
    srpe_sequence = chronic + acute

    rows = []
    for athlete, sequence in (
        ("Ana Rtp", srpe_sequence),
        ("Bruno Nortp", srpe_sequence),
        ("Caro Gym", [200.0] * 28),
        ("Dani Sinperfil", srpe_sequence),
    ):
        for day, value in zip(dates, sequence):
            rows.append({"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "sRPE": value})
    pd.DataFrame(rows).to_csv(store_dir / "rpe_history.csv", index=False)

    eval_rows = [
        {"Athlete": "Ana Rtp", "Date": TODAY.strftime("%Y-%m-%d"), "CMJ_cm": 32, "SJ_cm": 30, "EUR": 1.0667},
        {"Athlete": "Bruno Nortp", "Date": TODAY.strftime("%Y-%m-%d"), "CMJ_cm": 32, "SJ_cm": 30, "EUR": 1.0667},
    ]
    pd.DataFrame(eval_rows).to_csv(store_dir / "evaluations_history.csv", index=False)

    import local_store as local_store_module
    import importlib

    local_store_module = importlib.reload(local_store_module)
    local_store_module.upsert_athlete_profile(
        {
            "Athlete": "Ana Rtp", "Contexto": "Club", "Deporte": "Handball", "Nivel": "Competitivo",
            "Objetivo_primario": "Fuerza máxima", "Es_RTP": True,
        }
    )
    local_store_module.upsert_athlete_profile(
        {
            "Athlete": "Bruno Nortp", "Contexto": "Club", "Deporte": "Handball", "Nivel": "Competitivo",
            "Objetivo_primario": "Fuerza máxima", "Es_RTP": False,
        }
    )
    local_store_module.upsert_athlete_profile(
        {
            "Athlete": "Caro Gym", "Contexto": "Gimnasio", "Deporte": "Ninguno / Poblacion general",
            "Nivel": "Recreativo", "Objetivo_primario": "Salud general y calidad de vida", "Es_RTP": False,
        }
    )
    # "Dani Sinperfil" intentionally has no athlete_profile_df row at all.


def _run_decision_panel() -> AppTest:
    at = AppTest.from_file(str(APP_PY_PATH), default_timeout=120)
    at.run()
    assert not at.exception, f"initial run raised: {at.exception}"
    nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
    nav.set_value("Decision").run()
    assert not at.exception, f"navigating to Decision raised: {at.exception}"
    return at


class DecisionPanelContextoFilterTest(unittest.TestCase):
    def test_contexto_filter_excludes_wrong_contexto_and_unprofiled_athletes(self):
        with isolated_store() as store_dir:
            _seed_decision_fixture(store_dir)
            at = _run_decision_panel()

            risk_df_todos = at.dataframe[0].value
            self.assertEqual(
                set(risk_df_todos["Atleta"].str.replace("  🔶 RTP", "", regex=False)),
                {"Ana Rtp", "Bruno Nortp", "Caro Gym", "Dani Sinperfil"},
            )

            ctx_select = next(s for s in at.selectbox if s.label == "Contexto")
            ctx_select.set_value("Club").run()
            self.assertFalse(at.exception, at.exception)

            risk_df_club = at.dataframe[0].value
            club_athletes = set(risk_df_club["Atleta"].str.replace("  🔶 RTP", "", regex=False))
            self.assertEqual(club_athletes, {"Ana Rtp", "Bruno Nortp"})
            self.assertNotIn("Caro Gym", club_athletes)
            self.assertNotIn("Dani Sinperfil", club_athletes)

            caption_texts = [c.value for c in at.caption]
            unprofiled_captions = [text for text in caption_texts if "sin perfil no se muestran" in text]
            self.assertEqual(len(unprofiled_captions), 1)
            self.assertIn("1 atleta(s)", unprofiled_captions[0])


class DecisionPanelRtpZoneThresholdTest(unittest.TestCase):
    def test_rtp_athlete_gets_more_conservative_zone_for_same_acwr(self):
        with isolated_store() as store_dir:
            _seed_decision_fixture(store_dir)
            at = _run_decision_panel()

            risk_df = at.dataframe[0].value
            rows_by_athlete = {
                row["Atleta"].replace("  🔶 RTP", ""): row for _, row in risk_df.iterrows()
            }

            ana = rows_by_athlete["Ana Rtp"]
            bruno = rows_by_athlete["Bruno Nortp"]

            # Same underlying ACWR (both athletes share the exact same sRPE history).
            self.assertEqual(ana["ACWR EWMA"], bruno["ACWR EWMA"])

            # RTP threshold is more conservative: 1.17 lands in "Precaucion" for
            # RTP (0.8-1.1 Optima, 1.1-1.3 Precaucion) but "Optima" for a
            # standard athlete (0.8-1.3 Optima).
            self.assertEqual(ana["Zona"], "Precaucion")
            self.assertEqual(bruno["Zona"], "Optima")

            # RTP chip only on the RTP athlete's row.
            ana_row = risk_df.loc[risk_df["Atleta"].str.startswith("Ana Rtp")].iloc[0]
            bruno_row = risk_df.loc[risk_df["Atleta"] == "Bruno Nortp"].iloc[0]
            self.assertIn("RTP", ana_row["Atleta"])
            self.assertNotIn("RTP", bruno_row["Atleta"])


class DecisionPanelRtpDevelopmentColumnTest(unittest.TestCase):
    def test_rtp_athlete_is_excluded_from_power_column(self):
        with isolated_store() as store_dir:
            _seed_decision_fixture(store_dir)
            at = _run_decision_panel()

            markdown_values = [m.value for m in at.markdown]
            base_idx = next(i for i, v in enumerate(markdown_values) if v == "**Necesitan trabajo de fuerza base**")
            power_idx = next(i for i, v in enumerate(markdown_values) if v == "**Necesitan desarrollo de potencia**")
            complete_idx = next(i for i, v in enumerate(markdown_values) if v == "**Perfil completo / mantencion**")

            base_block = markdown_values[base_idx:power_idx]
            power_block = markdown_values[power_idx:complete_idx]
            complete_block = markdown_values[complete_idx:]

            # Bruno has the identical Mixto/EUR profile and is NOT RTP: lands
            # in the power (B) column via the normal classification rules.
            self.assertTrue(any("Bruno Nortp" in v for v in power_block))

            # Ana has the exact same profile but IS RTP: must never appear in
            # the power column, must appear elsewhere (A or C) with the note.
            self.assertFalse(any("Ana Rtp" in v for v in power_block))
            redirected_block = [v for v in (base_block + complete_block) if "Ana Rtp" in v]
            self.assertEqual(len(redirected_block), 1)
            self.assertIn("RTP", redirected_block[0])
            self.assertIn("priorizar criterio clínico", redirected_block[0])


if __name__ == "__main__":
    unittest.main()
