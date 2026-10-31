"""Modelos de carga (ACWR, monotonia, cronica) sobre la historia COMPLETA.

Produccion (31/10): el estado de sesion trae solo 6 semanas (load_recent_state)
y los modelos se calculaban sobre esa ventana: la EWMA cronica arrancaba de
cero dentro de la ventana y, en el PDF de un atleta con sRPE desde julio, la
cronica recien aparecia el 12/10. Ahora se calcula con toda la historia y
despues se recorta para mostrar.
"""

from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from modules.app_clock import frozen_app_now
from tests.test_phase2_history import isolated_store

NOW = pd.Timestamp("2026-10-29 12:00")
ATHLETE = "Ana Lopez"
DAYS = pd.date_range("2026-04-27", "2026-10-25", freq="D")  # ~6 meses
TRAINED = [day for day in DAYS if day.weekday() in (0, 1, 3, 4)]


class LoadModelsUseFullHistoryTest(unittest.TestCase):
    def test_six_months_of_srpe_have_chronic_from_first_visible_week(self):
        import modules.page_state as page_state_module
        from charts.report_charts import weekly_load_frame

        with isolated_store() as (local_store, _tmp), frozen_app_now(NOW):
            page_state_module = importlib.reload(page_state_module)
            local_store.save_dataset(
                "rpe_df",
                pd.DataFrame([{"Athlete": ATHLETE, "Date": day, "sRPE": 450.0, "RPE": 6, "Time": 75} for day in TRAINED]),
            )
            local_store.save_dataset(
                "raw_df",
                pd.DataFrame(
                    [{"Athlete": ATHLETE, "Assigned Date": day, "Exercise Name": "Back Squat", "Set Number": 1} for day in TRAINED]
                ),
            )
            recent = local_store.load_recent_state(weeks=local_store.RECENT_WEEKS)
            self.assertLess(len(recent["rpe_df"]), len(TRAINED))  # la sesion solo trae la ventana
            fake_st = SimpleNamespace(session_state=dict(recent))
            with patch.object(page_state_module, "st", fake_st):
                page_state_module.ensure_load_state(ensure_base_state=False)
            acwr = fake_st.session_state["acwr_dict"][ATHLETE]
            weekly = fake_st.session_state["weekly_summaries"]["weekly_load"]

        # Solo se muestra la ventana reciente...
        self.assertGreaterEqual(pd.to_datetime(acwr["Date"]).min(), pd.Timestamp("2026-09-01"))
        # ...pero calculada con toda la historia: desde el primer dia visible
        # el ACWR es valido y la cronica ya esta en regimen (480 UA/dia
        # entrenado x 4/7 ~ 257 UA/dia), no arrancando de cero.
        first = acwr.sort_values("Date").iloc[0]
        self.assertEqual(first["ACWR_Estado"], "ok")
        self.assertAlmostEqual(float(first["EWMA_Cronica"]), 450.0 * 4 / 7, delta=25)
        frame = weekly_load_frame(weekly[weekly["Athlete"] == ATHLETE], acwr, weeks=None)
        visible = frame[frame["has_data"]]
        self.assertTrue(visible["chronic_weekly"].notna().all(), visible[["week_start", "chronic_weekly"]])

    def test_falls_back_to_session_data_if_history_unavailable(self):
        import modules.page_state as page_state_module

        recent = pd.DataFrame([{"Athlete": ATHLETE, "Date": "2026-10-20", "sRPE": 300.0}])
        with patch.object(page_state_module, "ensure_full_history_state", side_effect=OSError("sin store")):
            rpe, raw = page_state_module.load_model_history_source(recent, None)
        self.assertIs(rpe, recent)
        self.assertIsNone(raw)


class MonotonyMinimumInReportsTest(unittest.TestCase):
    """3 sesiones/semana (todas con sRPE): ningun reporte muestra monotonia."""

    def test_athlete_pdf_does_not_show_monotony_with_three_sessions(self):
        import re
        import unicodedata
        from io import BytesIO

        from pypdf import PdfReader

        import local_store
        from modules import report_generator

        days = [day for day in pd.date_range("2026-08-03", "2026-10-25") if day.weekday() in (0, 2, 4)]
        rpe = pd.DataFrame([{"Athlete": ATHLETE, "Date": day, "sRPE": 400.0} for day in days])
        raw = pd.DataFrame([{"Athlete": ATHLETE, "Assigned Date": day, "Exercise Name": "Back Squat"} for day in days])
        acwr, mono = local_store.build_load_models(rpe, weeks=None, raw_df=raw)
        self.assertTrue(mono[ATHLETE]["Monotonia"].isna().all())
        self.assertTrue(mono[ATHLETE]["Monotony_Status"].eq("few_sessions").all())
        state = {
            "rpe_df": rpe,
            "raw_df": raw,
            "acwr_dict": acwr,
            "mono_dict": mono,
            "weekly_summaries": local_store.build_weekly_summaries(rpe, None, raw, acwr_dict=acwr, today=NOW.normalize()),
        }
        with frozen_app_now(NOW):
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, "atleta")
        text = " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages)
        text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()
        text = " ".join(text.split())
        self.assertIsNone(re.search(r"monotonia (semanal: )?\d", text), text[:400])
        self.assertIn("no calculable (minimo 4 sesiones", text)


if __name__ == "__main__":
    unittest.main()
