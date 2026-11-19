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

from modules.app_clock import app_today

APP_PY_PATH = Path(__file__).resolve().parent.parent / "app.py"
TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_decision_panel"

TODAY = app_today()  # mismo "hoy" que la app (hora Argentina)


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
    # PR P: Decision -> Hoy (los bloques semanales viven ahi, debajo de las senales).
    nav.set_value("Hoy").run()
    assert not at.exception, f"navigating to Hoy raised: {at.exception}"
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
    def test_acwr_is_context_without_zones_and_rtp_is_still_marked(self):
        # PR K: sin semaforo de ACWR (ni el umbral mas conservador de RTP):
        # el valor es contexto (Impellizzeri 2020). El chip RTP se mantiene.
        with isolated_store() as store_dir:
            _seed_decision_fixture(store_dir)
            at = _run_decision_panel()

            risk_df = at.dataframe[0].value
            rows_by_athlete = {
                row["Atleta"].replace("  🔶 RTP", ""): row for _, row in risk_df.iterrows()
            }

            ana = rows_by_athlete["Ana Rtp"]
            bruno = rows_by_athlete["Bruno Nortp"]
            self.assertEqual(ana["ACWR EWMA (contexto)"], bruno["ACWR EWMA (contexto)"])
            self.assertNotIn("Zona", risk_df.columns)

            ana_row = risk_df.loc[risk_df["Atleta"].str.startswith("Ana Rtp")].iloc[0]
            bruno_row = risk_df.loc[risk_df["Atleta"] == "Bruno Nortp"].iloc[0]
            self.assertIn("RTP", ana_row["Atleta"])
            self.assertNotIn("RTP", bruno_row["Atleta"])
            text = " ".join(str(item.value) for item in [*at.markdown, *at.caption])
            self.assertNotIn("zona de riesgo", text.lower().replace("sin zonas de riesgo", ""))


class DecisionPanelDevelopmentProfilesTest(unittest.TestCase):
    """PR P: "Perfiles de desarrollo" cuenta atletas por cuadrante del mapa y
    por perfil de reactividad (patrones A, B, E). Las columnas por EUR (y su
    redireccion de RTP) se sacaron: el mapa del gimnasio cubre fuerza base."""

    def test_counts_by_map_quadrant_and_reactivity_profile(self):
        with isolated_store() as store_dir:
            _seed_decision_fixture(store_dir)
            at = _run_decision_panel()

            frames = [element.value for element in at.dataframe]
            frames = [frame.data if hasattr(frame, "data") else frame for frame in frames]
            quadrants = next(frame for frame in frames if "Cuadrante del mapa" in frame.columns)
            reactivity = next(frame for frame in frames if "Perfil de reactividad" in frame.columns)

            self.assertEqual(
                quadrants["Cuadrante del mapa"].tolist(),
                ["Completo", "Fuerte - falta explosividad", "Explosivo - falta fuerza", "Base", "Sin ubicar"],
            )
            # Mismo criterio que el mapa de Equipo: sin IMTP ni CMJ por vuelo el
            # atleta no entra al mapa (ni como "sin ubicar").
            self.assertEqual(int(quadrants["Atletas"].sum()), 0)

            labels = reactivity["Perfil de reactividad"].tolist()
            self.assertEqual(len(labels), 4)  # A, B, E + sin patron
            self.assertTrue(labels[0].startswith("Patrón A"))
            self.assertTrue(labels[1].startswith("Patrón B"))
            self.assertTrue(labels[2].startswith("Patrón E"))
            self.assertFalse(any("Patrón C" in label or "Patrón D" in label for label in labels))
            self.assertEqual(int(reactivity["Atletas"].sum()), 2)

            markdown = " ".join(str(item.value) for item in at.markdown)
            for removed in ("Necesitan trabajo de fuerza base", "Necesitan desarrollo de potencia", "Perfil completo / mantencion"):
                self.assertNotIn(removed, markdown)


if __name__ == "__main__":
    unittest.main()
