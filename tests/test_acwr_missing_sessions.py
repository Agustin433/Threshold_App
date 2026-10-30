import unittest
import unittest.mock

import numpy as np
import pandas as pd

import local_store
from modules.load_monitoring import (
    ACWR_STATUS_INCOMPLETE,
    ACWR_STATUS_OK,
    ACWR_STATUS_SHORT_HISTORY,
    DAY_STATUS_LOGGED,
    DAY_STATUS_MISSING,
    DAY_STATUS_REST,
    acwr_unavailable_reason,
    calc_acwr,
    calc_monotony_strain,
    latest_training_day_row,
)

DAYS = pd.date_range("2026-08-03", "2026-10-04", freq="D")
TRAINED = [day for day in DAYS if day.weekday() in (0, 1, 3, 4)]


def _acwr(logged_dates, load=480.0, training_dates=TRAINED):
    return calc_acwr(
        pd.Series([load] * len(logged_dates)),
        pd.DatetimeIndex(logged_dates),
        training_dates=training_dates,
    )


class AcwrMissingSessionsTest(unittest.TestCase):
    def test_trained_day_without_srpe_is_missing_not_rest(self):
        result = _acwr(TRAINED[::4]).set_index("Date")

        self.assertEqual(result.loc[TRAINED[0], "Dia_Estado"], DAY_STATUS_LOGGED)
        self.assertEqual(result.loc[TRAINED[1], "Dia_Estado"], DAY_STATUS_MISSING)
        self.assertEqual(result.loc[pd.Timestamp("2026-08-05"), "Dia_Estado"], DAY_STATUS_REST)

    def test_low_compliance_does_not_emit_acwr_or_zone(self):
        # ~25% de las sesiones reportadas: el modelo anterior daba una zona
        # (Optimo o Alto riesgo segun que dia cayera la sesion reportada).
        last = _acwr(TRAINED[::4]).iloc[-1]

        self.assertTrue(pd.isna(last["ACWR_EWMA"]))
        self.assertEqual(last["ACWR_Estado"], ACWR_STATUS_INCOMPLETE)
        self.assertEqual(last["Zona"], "Sin datos")
        self.assertIn("sesiones sin sRPE en 28 días", acwr_unavailable_reason(last))

    def test_occasional_forgotten_session_is_imputed_close_to_true_value(self):
        full = _acwr(TRAINED).iloc[-1]
        partial = _acwr([day for index, day in enumerate(TRAINED) if index % 5]).iloc[-1]

        self.assertEqual(partial["ACWR_Estado"], ACWR_STATUS_OK)
        self.assertAlmostEqual(float(partial["ACWR_EWMA"]), float(full["ACWR_EWMA"]), delta=0.03)

    def test_imputed_load_never_enters_reported_srpe(self):
        result = _acwr([day for index, day in enumerate(TRAINED) if index % 5])
        imputed = result[result["sRPE_imputado"]]

        self.assertFalse(imputed.empty)
        self.assertTrue((imputed["sRPE_diario"] == 0).all())
        self.assertTrue((imputed["sRPE_modelo"] > 0).all())

    def test_without_ledger_unreported_days_stay_rest(self):
        result = _acwr(TRAINED[::4], training_dates=None)

        self.assertFalse(result["Dia_Estado"].eq(DAY_STATUS_MISSING).any())
        self.assertEqual(int(result["Faltantes_28d"].max()), 0)

    def test_short_history_does_not_emit_acwr(self):
        # Con adjust=False el EWMA arranca en el primer valor y el ACWR del
        # primer dia es exactamente 1.0 ("Optimo") por construccion.
        result = calc_acwr(pd.Series([400.0] * 10), pd.date_range("2026-09-01", periods=10, freq="D"))

        self.assertTrue(result["ACWR_EWMA"].isna().all())
        self.assertTrue(result["ACWR_Estado"].eq(ACWR_STATUS_SHORT_HISTORY).all())

    def test_zero_chronic_load_is_not_subcarga(self):
        values = [0.0] * 40
        result = calc_acwr(pd.Series(values), pd.date_range("2026-08-01", periods=40, freq="D"))

        self.assertFalse(result["Zona"].eq("Subcarga").any())

    def test_latest_row_is_last_trained_day_even_if_unreported(self):
        logged = [day for day in TRAINED if day <= pd.Timestamp("2026-09-20")]
        result = _acwr(logged)
        latest = latest_training_day_row(result).iloc[0]

        self.assertEqual(pd.Timestamp(latest["Date"]), TRAINED[-1])
        self.assertEqual(latest["Dia_Estado"], DAY_STATUS_MISSING)
        self.assertTrue(pd.isna(latest["ACWR_EWMA"]))

    def test_monotony_is_not_computed_for_week_with_unreported_sessions(self):
        mono = calc_monotony_strain(_acwr(TRAINED[::4]))
        last_week = mono.iloc[-1]

        self.assertTrue(pd.isna(last_week["Monotonia"]))
        self.assertTrue(pd.isna(last_week["Strain"]))
        self.assertEqual(last_week["Monotony_Status"], "incomplete_log")
        self.assertGreater(int(last_week["Sesiones_sin_registro"]), 0)

    def test_monotony_unchanged_for_fully_reported_week(self):
        mono = calc_monotony_strain(_acwr(TRAINED))

        self.assertEqual(mono.iloc[-1]["Monotony_Status"], "standard")
        self.assertTrue(np.isfinite(float(mono.iloc[-1]["Monotonia"])))


class BuildLoadModelsLedgerTest(unittest.TestCase):
    def test_ledger_matches_athlete_names_without_accents(self):
        rpe_df = pd.DataFrame(
            [{"Athlete": "Mariano Díaz Romero", "Date": day, "sRPE": 480.0} for day in TRAINED[::4]]
        )
        raw_df = pd.DataFrame(
            [{"Athlete": "mariano diaz romero", "Assigned Date": day, "Exercise": "Back Squat"} for day in TRAINED]
        )

        acwr_dict, _ = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
        result = next(iter(acwr_dict.values()))

        self.assertTrue(result["Dia_Estado"].eq(DAY_STATUS_MISSING).any())
        self.assertEqual(latest_training_day_row(result).iloc[0]["ACWR_Estado"], ACWR_STATUS_INCOMPLETE)

    def test_without_raw_df_models_are_built_as_before(self):
        rpe_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in TRAINED])

        acwr_dict, _ = local_store.build_load_models(rpe_df, weeks=None)

        self.assertEqual(latest_training_day_row(acwr_dict["Ana Lopez"]).iloc[0]["ACWR_Estado"], ACWR_STATUS_OK)


class ProfessionalReportUsesModelGateTest(unittest.TestCase):
    def _state(self, logged_dates):
        rpe_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in logged_dates])
        raw_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Assigned Date": day, "Exercise": "Back Squat"} for day in TRAINED])
        acwr_dict, mono_dict = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
        # Wellness completo: el semaforo de cobertura solo depende del sRPE.
        wellness_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "Wellness_Score": 20.0} for day in TRAINED])
        return {
            "rpe_df": rpe_df,
            "raw_df": raw_df,
            "wellness_df": wellness_df,
            "acwr_dict": acwr_dict,
            "mono_dict": mono_dict,
        }

    def test_low_compliance_shows_no_acwr_zone_in_load_card_or_signals(self):
        from modules import report_generator

        state = self._state(TRAINED[::4])
        payload = report_generator._build_professional_load_tolerance_payload(state, "Ana Lopez", {})
        rows = dict(payload["rows"])

        self.assertTrue(rows["ACWR EWMA"].startswith("No calculable"))
        self.assertIn("sesiones sin sRPE", rows["ACWR EWMA"])
        self.assertEqual(rows["Zona ACWR"], report_generator.PROFESSIONAL_ACWR_GATED_ZONE_TEXT)
        self.assertNotIn("Optimo", " ".join(rows.values()))
        self.assertIn("no calculable", payload["risk_line"].lower())

        summary = report_generator.build_executive_summary_df(state, "Ana Lopez")
        self.assertNotIn("ACWR EWMA", summary.columns)

    def test_full_compliance_keeps_acwr_zone(self):
        from modules import report_generator

        state = self._state(TRAINED)
        with unittest.mock.patch.object(
            report_generator, "_professional_report_today", return_value=pd.Timestamp("2026-10-06")
        ):
            payload = report_generator._build_professional_load_tolerance_payload(state, "Ana Lopez", {})
        rows = dict(payload["rows"])

        self.assertFalse(rows["ACWR EWMA"].startswith("No calculable"))
        self.assertEqual(rows["Zona ACWR"], "Optimo")


class WeeklyAcwrMissingSessionsTest(unittest.TestCase):
    def _weekly(self, logged_dates):
        rpe_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in logged_dates])
        raw_df = pd.DataFrame([{"Athlete": "Ana Lopez", "Assigned Date": day, "Exercise": "Back Squat"} for day in TRAINED])
        acwr_dict, _ = local_store.build_load_models(rpe_df, weeks=None, raw_df=raw_df)
        summaries = local_store.build_weekly_summaries(
            rpe_df, None, raw_df, acwr_dict=acwr_dict, today=pd.Timestamp("2026-10-12")
        )
        return summaries["weekly_load"]

    def test_weekly_summary_counts_sessions_done_and_missing(self):
        weekly = self._weekly(TRAINED[::4])
        last = weekly.iloc[-1]

        self.assertEqual(int(last["sessions_done"]), 4)
        self.assertGreater(int(last["sessions_missing"]), 0)
        self.assertGreater(float(last["weekly_sRPE_model"]), float(last["weekly_sRPE"]))

    def test_trained_week_without_any_srpe_is_kept(self):
        # Semana 21/09: entrena 4 veces, no reporta ninguna. Si se borrara,
        # la cronica "4 semanas previas" tomaria otras semanas.
        logged = [day for day in TRAINED if not pd.Timestamp("2026-09-21") <= day <= pd.Timestamp("2026-09-27")]
        weekly = self._weekly(logged)

        self.assertIn(pd.Timestamp("2026-09-21"), set(pd.to_datetime(weekly["week_start"])))

    def test_weekly_acwr_not_emitted_with_unreported_sessions(self):
        from modules.load_monitoring import build_weekly_acwr_context

        context = build_weekly_acwr_context(self._weekly(TRAINED[::4]), "Ana Lopez", weeks=None)
        last = context.iloc[-1]

        self.assertEqual(last["context_status"], "incomplete_log")
        self.assertTrue(pd.isna(last["acwr_rolling_1_4"]))
        self.assertTrue(pd.isna(last["acwr_rolling_ma4"]))
        self.assertTrue(pd.isna(last["weekly_change_pct"]))
        self.assertFalse(bool(last["spike_flag"]))

    def test_weekly_acwr_full_compliance_is_standard(self):
        from modules.load_monitoring import build_weekly_acwr_context

        context = build_weekly_acwr_context(self._weekly(TRAINED), "Ana Lopez", weeks=None)
        last = context.iloc[-1]

        self.assertEqual(last["context_status"], "standard")
        self.assertAlmostEqual(float(last["acwr_rolling_1_4"]), 1.0, places=2)

    def test_chart_stacks_estimated_load_and_marks_incomplete_weeks(self):
        from charts.load_charts import chart_weekly_acwr_context
        from modules.load_monitoring import build_weekly_acwr_context
        from tests.test_weekly_acwr_context import _chart_theme

        context = build_weekly_acwr_context(self._weekly(TRAINED[::4]), "Ana Lopez", weeks=None)
        names = [trace.name for trace in chart_weekly_acwr_context(context, "Ana Lopez", theme=_chart_theme()).data]

        self.assertIn("Carga semanal", names)
        self.assertIn("Estimada (sesiones sin sRPE)", names)
        self.assertIn("ACWR no calculable (sesiones sin sRPE)", names)

    def test_pdf_weekly_change_is_blocked_with_unreported_sessions(self):
        from modules import report_generator

        state = {"rpe_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": day, "sRPE": 480.0} for day in TRAINED[::4]])}
        state["raw_df"] = pd.DataFrame([{"Athlete": "Ana Lopez", "Assigned Date": day, "Exercise": "Squat"} for day in TRAINED])
        acwr_dict, mono_dict = local_store.build_load_models(state["rpe_df"], weeks=None, raw_df=state["raw_df"])
        state.update({"acwr_dict": acwr_dict, "mono_dict": mono_dict})
        state["weekly_summaries"] = local_store.build_weekly_summaries(
            state["rpe_df"], None, state["raw_df"], acwr_dict=acwr_dict, today=pd.Timestamp("2026-10-06")
        )
        with unittest.mock.patch.object(report_generator, "_professional_report_today", return_value=pd.Timestamp("2026-10-06")):
            internal = report_generator._build_professional_internal_load_context(state, "Ana Lopez")
            payload = report_generator._build_professional_load_tolerance_payload(state, "Ana Lopez", internal)

        self.assertTrue(internal["weekly_change_blocked"])
        self.assertIsNone(internal["weekly_change_pct"])
        rows = dict(payload["rows"])
        self.assertNotRegex(rows.get("Cambio vs semana previa", ""), r"^[+-]\d")


class CompareWeeklyLoadTest(unittest.TestCase):
    def _week(self, athlete, reported, model, done, missing):
        return {
            "Athlete": athlete,
            "weekly_sRPE": reported,
            "weekly_sRPE_model": model,
            "sessions_count": done - missing,
            "sessions_done": done,
            "sessions_missing": missing,
        }

    def test_week_with_unreported_sessions_is_not_comparable(self):
        from modules.load_monitoring import compare_weekly_load

        current = pd.DataFrame([self._week("Ana", 480, 1920, 4, 3)])
        previous = pd.DataFrame([self._week("Ana", 1920, 1920, 4, 0)])
        row = compare_weekly_load(current, previous).iloc[0]

        self.assertFalse(bool(row["comparable"]))
        self.assertTrue(pd.isna(row["delta_sRPE"]))
        self.assertTrue(pd.isna(row["delta_pct"]))

    def test_fully_reported_weeks_compare_model_load(self):
        from modules.load_monitoring import compare_weekly_load

        current = pd.DataFrame([self._week("Ana", 2400, 2400, 5, 0)])
        previous = pd.DataFrame([self._week("Ana", 1920, 1920, 4, 0)])
        row = compare_weekly_load(current, previous).iloc[0]

        self.assertTrue(bool(row["comparable"]))
        self.assertAlmostEqual(float(row["delta_sRPE"]), 480.0)
        self.assertAlmostEqual(float(row["delta_pct"]), 25.0)

    def test_no_previous_week_row_means_real_zero_load(self):
        from modules.load_monitoring import compare_weekly_load

        row = compare_weekly_load(pd.DataFrame([self._week("Ana", 960, 960, 2, 0)]), pd.DataFrame()).iloc[0]

        self.assertTrue(bool(row["comparable"]))
        self.assertAlmostEqual(float(row["delta_sRPE"]), 960.0)

    def test_frames_without_session_ledger_behave_as_before(self):
        from modules.load_monitoring import compare_weekly_load

        current = pd.DataFrame([{"Athlete": "Ana", "weekly_sRPE": 900, "sessions_count": 3}])
        previous = pd.DataFrame([{"Athlete": "Ana", "weekly_sRPE": 600, "sessions_count": 2}])
        row = compare_weekly_load(current, previous).iloc[0]

        self.assertTrue(bool(row["comparable"]))
        self.assertAlmostEqual(float(row["delta_sRPE"]), 300.0)


if __name__ == "__main__":
    unittest.main()
