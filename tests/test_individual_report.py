"""PR B: reportes de atleta y cliente muestran lo que hay (PDF + dashboard).

Casos reales (Supabase, 04/11/2026): Tomas De La Vega, Ignacio De La Vega,
Agustin Giffon y Pablo Holgado.
"""

from __future__ import annotations

import re
import unicodedata
import unittest
from datetime import datetime
from io import BytesIO

import pandas as pd
from pypdf import PdfReader

import modules.report_generator as rg
from modules import athlete_report as ar
from modules.app_clock import frozen_app_now
from modules.jump_analysis import UNUSUAL_CHANGE_NOTE, _prepare_jump_df, build_jump_delta_display_table, compute_evaluation_changes
from modules.report_messages import ATHLETE_FORBIDDEN_PHRASES, NEXT_STEPS_MAX
from modules.strength_estimates import (
    ESTIMATED_STRENGTH_LABEL,
    MAIN_BARBELL_LIFTS,
    epley_1rm,
    estimated_strength_by_day,
    new_main_lift_bests,
    rolling_best_envelope,
)
from charts.load_charts import chart_estimated_strength

NOW = datetime(2026, 11, 4, 12, 0)


def _history(rows: list[dict[str, object]]) -> pd.DataFrame:
    base = {"Source": "platform", "BW_kg": 80.0}
    return _prepare_jump_df(pd.DataFrame([{**base, **row} for row in rows]))


TOMAS = [
    {"Athlete": "Tomas De La Vega", "Date": "2025-11-13", "CMJ_cm": 41.78, "CMJ_flight_ms": 547, "IMTP_N": 2565.0},
    {"Athlete": "Tomas De La Vega", "Date": "2026-10-21", "CMJ_cm": 43.62, "CMJ_flight_ms": 599, "IMTP_N": 3638.0},
]
IGNACIO = [
    {"Athlete": "Ignacio De La Vega", "Date": "2025-11-04", "CMJ_cm": 35.51, "CMJ_flight_ms": 528},
    {"Athlete": "Ignacio De La Vega", "Date": "2025-12-17", "CMJ_cm": 42.54, "CMJ_flight_ms": 561},
    {"Athlete": "Ignacio De La Vega", "Date": "2026-05-20", "CMJ_cm": 41.1, "CMJ_flight_ms": 570},
    {"Athlete": "Ignacio De La Vega", "Date": "2026-10-08", "CMJ_cm": 46.04, "CMJ_flight_ms": 614},
]
HOLGADO = [
    {"Athlete": "Pablo Holgado", "Date": "2025-12-19", "CMJ_cm": 41.49, "CMJ_flight_ms": 566},
    {"Athlete": "Pablo Holgado", "Date": "2026-02-02", "CMJ_cm": 41.25, "CMJ_flight_ms": 553},
    {"Athlete": "Pablo Holgado", "Date": "2026-10-22", "CMJ_cm": 51.32, "CMJ_flight_ms": 648},
]
GIFFON = [
    {"Athlete": "Agustin Giffon", "Date": "2026-05-22", "BW_kg": 77.0, "CMJ_cm": 58.0, "CMJ_flight_ms": 547,
     "DJ_cm": 30.0, "DJ_tc_ms": 222.0, "DJ_drop_height_cm": 30.0, "IMTP_N": 3084.0},
]


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(text.split())


def _pdf_pages(pdf: bytes) -> list[str]:
    return [_normalized(page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages]


# ── 1. Lo que lograste ────────────────────────────────────────────────────
class AchievementsTests(unittest.TestCase):
    def test_tomas_compares_against_full_history_by_flight_time(self):
        # 13/11/2025 -> 21/10/2026: la evaluacion vieja esta fuera de cualquier
        # ventana de 6 semanas y se compara igual.
        items = ar.evaluation_achievements(compute_evaluation_changes(_history(TOMAS)), "atleta")
        texts = " ".join(item["text"] for item in items)
        self.assertIn("Salto CMJ (por tiempo de vuelo): 36.7 cm → 44.0 cm", texts)
        self.assertIn("13/11/2025 → 21/10/2026", texts)
        # Primer IMTP: 2565 -> 3638 N (+41.8%) es implausible: solo PDF profe.
        self.assertNotIn("IMTP", texts)

    def test_ignacio_cmj_improvement_uses_flight_time_across_eras(self):
        # PR C: 20/05/2026 (Valkyria) -> 08/10/2026 (Involution): el impulso no
        # se compara entre eras; el vuelo si (misma plataforma).
        items = ar.evaluation_achievements(compute_evaluation_changes(_history(IGNACIO)), "atleta")
        self.assertTrue(
            any(item["text"].startswith("Salto CMJ (por tiempo de vuelo): 39.8 cm → 46.2 cm") for item in items)
        )
        self.assertFalse(any(item["text"].startswith("Salto CMJ: ") for item in items))

    def test_holgado_unusual_jump_change_is_hidden_from_athlete(self):
        changes = compute_evaluation_changes(_history(HOLGADO))
        flight = changes[changes["Variable"] == "CMJ_ft_cm"].iloc[0]
        self.assertAlmostEqual(float(flight["Valor_anterior"]), 37.5, places=1)
        self.assertAlmostEqual(float(flight["Valor_actual"]), 51.5, places=1)
        self.assertTrue(bool(flight["Unusual"]))
        self.assertEqual(ar.evaluation_achievements(changes, "atleta"), [])
        self.assertTrue(ar.unusual_changes_for_professional(changes))
        table = build_jump_delta_display_table(changes)
        self.assertIn(UNUSUAL_CHANGE_NOTE, table.set_index("Variable").loc["CMJ (por tiempo de vuelo)", "Senal"])

    def test_professional_change_payload_flags_unusual_change(self):
        state = {"jump_df": pd.DataFrame([{**row, "Source": "platform", "BW_kg": 80.0} for row in HOLGADO])}
        payload = rg._build_professional_change_payload(state, "Pablo Holgado")
        self.assertTrue(any(UNUSUAL_CHANGE_NOTE in item for item in payload["to_verify"]))

    def test_only_relevant_improvements_are_celebrated(self):
        changes = pd.DataFrame(
            [
                {"Variable": "CMJ_cm", "Signal": "sin cambio relevante", "Valor_actual": 40.2, "Valor_anterior": 40.0, "Unusual": False},
                {"Variable": "IMTP_N", "Signal": "caida relevante", "Valor_actual": 2900.0, "Valor_anterior": 3100.0, "Unusual": False},
                {"Variable": "EUR", "Signal": "mejora relevante", "Valor_actual": 1.1, "Valor_anterior": 1.0, "Unusual": False},
            ]
        )
        self.assertEqual(ar.evaluation_achievements(changes, "atleta"), [])

    def test_reference_when_nothing_beats_threshold(self):
        # Giffon: una sola evaluacion; CMJ por impulso excluido -> referencia por vuelo.
        lines = ar.reference_lines(_history(GIFFON), "atleta")
        joined = " · ".join(lines)
        self.assertIn("Salto CMJ (por tiempo de vuelo) 36.7 cm (22/05/2026)", joined)
        self.assertIn("Fuerza máxima (IMTP) 3084 N (22/05/2026)", joined)

    def test_client_labels_avoid_technical_terms(self):
        items = ar.evaluation_achievements(compute_evaluation_changes(_history(TOMAS)), "cliente")
        texts = " ".join(item["text"] for item in items).lower()
        for term in ("imtp", "cmj", "rsi"):
            self.assertNotIn(term, texts)

    def test_sessions_and_best_marks(self):
        self.assertEqual(ar.sessions_achievement(0, "atleta"), None)
        # Tomas: 1 sesion en 6 semanas -> no se muestra (< 1 por semana).
        self.assertIsNone(ar.sessions_achievement(1, "atleta"))
        self.assertIsNone(ar.sessions_achievement(5, "atleta"))
        self.assertIn("6 sesiones completadas", ar.sessions_achievement(6, "atleta")["text"])
        self.assertIn("16 sesiones completadas", ar.sessions_achievement(16, "atleta")["text"])
        best = ar.best_mark_achievements(
            [{"Lift": "Sentadilla trasera", "Value": 110.0, "Previous": 99.0, "Date": pd.Timestamp("2026-10-21")}],
            "atleta",
        )
        self.assertEqual(best[0]["text"], "Nueva mejor marca en Sentadilla trasera: 110 kg (antes 99 kg), 21/10/2026.")


# ── 2-4. Coherencia texto-dato ────────────────────────────────────────────
class LoadCoherenceTests(unittest.TestCase):
    GIFFON_LOAD = {
        "analysis_week_label": "19/10/2026 - 25/10/2026",
        "last_week_total": 998.0,
        "analysis_week_sessions_with_srpe": 3,
        "weekly_change_pct": -4.130643611911624,
        "weekly_change_blocked": False,
    }

    def test_giffon_label_is_descriptive_and_weekly_sign_holds(self):
        # ACWR 1.32 ("Precaucion" en el PDF profe) -> atleta: etiqueta descriptiva.
        reading = ar.load_reading(
            self.GIFFON_LOAD,
            evaluable=True,
            zone="Precaucion",
            acwr=1.32,
            client_trend="Más exigente que las anteriores",
            audience="atleta",
        )
        text = " ".join(reading["sentences"]).lower()
        self.assertEqual(reading["headline"], "Más alta que tu promedio")
        self.assertIn("por encima de tu promedio de las semanas previas", text)
        self.assertIn("4.1% menos carga que la anterior", text)
        self.assertNotIn("la última semana fue más exigente", text)
        joined = _normalized(reading["headline"] + " " + text + " " + " ".join(a for a, _ in reading["rows"]))
        for word in ("precaucion", "alto riesgo", "subcarga", "optimo", "zona"):
            self.assertNotIn(word, joined)

    def test_descriptive_labels(self):
        for trend, label in (
            ("Más exigente que las anteriores", "Más alta que tu promedio"),
            ("Similar a las anteriores", "Similar a tu promedio"),
            ("Más liviana que las anteriores", "Más baja que tu promedio"),
        ):
            for audience in ("atleta", "cliente"):
                with self.subTest(trend=trend, audience=audience):
                    reading = ar.load_reading(
                        self.GIFFON_LOAD, evaluable=True, zone="Alto riesgo", acwr=1.6, client_trend=trend, audience=audience
                    )
                    self.assertEqual(reading["headline"], label)

    def test_weekly_sentence_matches_sign(self):
        for pct, word in ((12.0, "más"), (-12.0, "menos")):
            with self.subTest(pct=pct):
                self.assertIn(f"{abs(pct):.1f}% {word} carga", ar.weekly_change_sentence(pct, None))

    def test_client_load_never_mentions_acwr_or_zones(self):
        reading = ar.load_reading(
            self.GIFFON_LOAD,
            evaluable=True,
            zone="Precaucion",
            acwr=1.32,
            client_trend="Más exigente que las anteriores",
            audience="cliente",
        )
        text = _normalized(" ".join(reading["sentences"]) + " " + " ".join(f"{a} {b}" for a, b in reading["rows"]))
        for word in ("acwr", "precaucion", "zona"):
            self.assertNotIn(word, text)
        self.assertEqual(reading["headline"], "Más alta que tu promedio")

    def test_not_evaluable_load_has_no_section(self):
        self.assertIsNone(
            ar.load_reading(self.GIFFON_LOAD, evaluable=False, zone=None, acwr=None, client_trend=None, audience="atleta")
        )


class WellnessCoherenceTests(unittest.TestCase):
    def _context(self, score: float, days: int) -> dict[str, object]:
        return {
            "analysis_week_label": "19/10/2026 - 25/10/2026",
            "last_week_summary": {"score_mean": score, "score_n": days, "sleep_mean": 6.0, "stress_mean": 6.3, "pain_mean": 6.0},
        }

    def test_attention_never_reads_as_fine(self):
        # Giffon: 13.7/30 en 3 dias -> Atencion.
        reading = ar.wellness_reading(self._context(13.666, 3))
        self.assertEqual(reading["label"], "Atención")
        self.assertEqual(reading["score"], 13.7)
        self.assertIn("pide atención", reading["sentence"])
        for phrase in ("acompaña", "sin alerta", "sin señales"):
            self.assertNotIn(phrase, reading["sentence"])
        self.assertEqual(reading["rows"][0], ("Bienestar (19/10/2026–25/10/2026)", "13.7 /30 (Atención)"))

    def test_sentence_follows_classification(self):
        for score, label in ((25.0, "Óptimo"), (20.0, "Aceptable"), (13.0, "Atención"), (8.0, "Crítico")):
            with self.subTest(score=score):
                reading = ar.wellness_reading(self._context(score, 4))
                self.assertEqual(reading["label"], label)
                self.assertEqual(reading["sentence"], ar.WELLNESS_SENTENCES[label])

    def test_less_than_three_days_has_no_section(self):
        self.assertIsNone(ar.wellness_reading(self._context(21.5, 2)))


class FocusAndStepsTests(unittest.TestCase):
    def test_never_recommends_metrics_the_athlete_does_not_have(self):
        # Tomas: sin SJ ni EUR.
        profile = {
            "training_priority_detailed": "Mantener el bloque actual y volver a medir para confirmar. Seguir de cerca CMJ, SJ, EUR.",
            "kpi_to_track": ["CMJ_cm", "SJ_cm", "EUR", "DJ_RSI", "IMTP_relPF"],
        }
        history = _history(TOMAS)
        text = ar.focus_text(profile, history, "atleta")
        # PR C: "Seguir de cerca ..." queda solo en el PDF profe.
        self.assertNotIn("Seguir de cerca", text)
        self.assertNotIn("SJ", text)
        self.assertNotIn("EUR", text)
        # El orden por |z| (maximo 2) sigue disponible para el profe.
        self.assertLessEqual(len(ar.top_kpis(profile["kpi_to_track"], history)), 2)

    def test_next_steps_are_capped_and_positive(self):
        steps = ar.next_steps(
            has_evaluation=True,
            has_comparison=False,
            evaluation_stale=True,
            load_available=False,
            wellness_available=False,
            audience="atleta",
        )
        self.assertEqual(len(steps), NEXT_STEPS_MAX)
        self.assertTrue(steps[0].startswith("Repetí la evaluación"))
        self.assertEqual(steps[1], "Registrá tu RPE al terminar cada sesión: con 3 por semana ya podemos leer tu carga.")

    def test_giffon_has_imtp_and_is_not_asked_to_complete_it(self):
        payload = {"flags": ["missing_imtp", "imtp_reference_missing", "insufficient_pattern_evidence"]}
        self.assertNotIn("Completar IMTP", rg._neuromuscular_priority_detailed(payload))
        self.assertNotIn("Completar la referencia de fuerza", rg._neuromuscular_priority_short(payload))
        self.assertNotIn("imtp", rg._neuromuscular_priority_short(payload).lower())

    def test_overdue_next_evaluation(self):
        line = ar.next_evaluation_line("2026-05-22", "2026-11-04")
        self.assertEqual(line, "Ya corresponde una nueva evaluación: la última fue el 22/05/2026.")

    def test_dictionary_only_has_terms_in_the_report(self):
        lines = ar.dictionary_lines("Salto CMJ 46 cm y RPE de la sesión")
        terms = [line.split(":")[0] for line in lines]
        self.assertEqual(terms, ["CMJ", "RPE"])


class ImtpAndHighlightsTests(unittest.TestCase):
    def test_tomas_imtp_across_eras_is_not_comparable(self):
        # PR C: 13/11/2025 (Valkyria sin straps) -> 21/10/2026 (Involution).
        changes = compute_evaluation_changes(_history(TOMAS)).set_index("Variable")
        self.assertEqual(changes.loc["IMTP_N", "Signal"], "no comparable por era")
        self.assertTrue(pd.isna(changes.loc["IMTP_N", "Valor_anterior"]))
        self.assertFalse(any("IMTP" in item["text"] for item in ar.evaluation_achievements(changes.reset_index(), "atleta")))

    def test_tomas_first_imtp_is_professional_only(self):
        # Misma era declarada: aca se controla la plausibilidad (> +25%).
        same_era = [{**row, "Device": "involution_straps"} for row in TOMAS]
        changes = compute_evaluation_changes(_history(same_era))
        imtp = changes[changes["Variable"] == "IMTP_N"].iloc[0]
        self.assertTrue(bool(imtp["Unusual"]))
        self.assertFalse(any("IMTP" in item["text"] for item in ar.evaluation_achievements(changes, "atleta")))
        self.assertFalse(any("Fuerza" in item["text"] for item in ar.evaluation_achievements(changes, "cliente")))
        notes = ar.unusual_changes_for_professional(changes)
        self.assertTrue(any("verificar familiarización/protocolo" in line for line in notes))
        state = {"jump_df": pd.DataFrame([{**row, "Source": "platform", "BW_kg": 80.0} for row in same_era])}
        payload = rg._build_professional_change_payload(state, "Tomas De La Vega")
        self.assertTrue(any("verificar familiarización/protocolo" in item for item in payload["to_verify"]))

    def test_imtp_single_line_with_relative_in_parentheses(self):
        # Ignacio 20/05 -> 08/10/2026: 3235 -> 3491 N (+7.9%), 37.2 -> 39.9 N/kg.
        changes = pd.DataFrame(
            [
                {"Variable": "IMTP_N", "Signal": "mejora relevante", "Valor_actual": 3491.17, "Valor_anterior": 3235.0,
                 "Fecha_actual": "2026-10-08", "Fecha_anterior": "2026-05-20", "Delta_pct": 7.9, "Unusual": False},
                {"Variable": "IMTP_relPF", "Signal": "mejora relevante", "Valor_actual": 39.92, "Valor_anterior": 37.18,
                 "Fecha_actual": "2026-10-08", "Fecha_anterior": "2026-05-20", "Delta_pct": 7.4, "Unusual": False},
            ]
        )
        items = ar.evaluation_achievements(changes, "atleta")
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["text"],
            "Fuerza máxima (IMTP): 3235 N → 3491 N (+256 N; 37.2 → 39.9 N/kg), 20/05/2026 → 08/10/2026.",
        )

    def test_highlights_are_capped_at_two_by_z(self):
        # Ignacio (PDF profe): SJ (+1.63), CMJ (+1.23), DJ (+1.25), DJ RSI (+1.20), IMTP (+0.57).
        self.assertEqual(ar.top_strengths("SJ (+1.63), CMJ (+1.23), DJ (+1.25), DJ RSI (+1.20), IMTP (+0.57)"), "SJ, DJ")
        history = pd.DataFrame(
            [{"Date": "2026-10-08", "CMJ_cm": 46.0, "CMJ_Z": 1.23, "SJ_cm": 43.5, "SJ_Z": 1.63, "EUR": 1.06, "EUR_Z": -0.59,
              "DJ_RSI": 2.29, "DJ_RSI_Z": 1.20, "IMTP_relPF": 39.9, "IMTP_relPF_Z": 0.57}]
        )
        kpis = ["CMJ_cm", "SJ_cm", "EUR", "DJ_RSI", "IMTP_relPF"]
        self.assertEqual(ar.top_kpis(kpis, history), ["SJ", "CMJ"])


# ── 8. Fuerza estimada ────────────────────────────────────────────────────
class StrengthEstimateTests(unittest.TestCase):
    def test_epley(self):
        self.assertAlmostEqual(epley_1rm(100, 5), 100 * (1 + 5 / 30))
        self.assertEqual(epley_1rm(120, 1), 120.0)
        self.assertIsNone(epley_1rm(60, 12))
        self.assertIsNone(epley_1rm(60, 0))

    def test_only_main_lifts_and_best_per_day(self):
        raw = pd.DataFrame(
            [
                {"Athlete": "A", "Fecha_sesion": "2026-10-01", "Exercise": "Barbell Back Squat", "Result": 100, "Reps": 5},
                {"Athlete": "A", "Fecha_sesion": "2026-10-01", "Exercise": "Barbell Back Squat", "Result": 110, "Reps": 3},
                {"Athlete": "A", "Fecha_sesion": "2026-10-01", "Exercise": "Barbell Back Squat", "Result": 60, "Reps": 15},
                {"Athlete": "A", "Fecha_sesion": "2026-10-01", "Exercise": "Hang Power Clean", "Result": 80, "Reps": 3},
                {"Athlete": "A", "Fecha_sesion": "2026-10-01", "Exercise": "Db Bench Press", "Result": 30, "Reps": 8},
            ]
        )
        result = estimated_strength_by_day(raw, "A")
        self.assertEqual(result["Lift"].tolist(), ["Sentadilla trasera"])
        self.assertAlmostEqual(float(result["e1RM_kg"].iloc[0]), 110 * (1 + 3 / 30))
        self.assertNotIn("hang power clean", MAIN_BARBELL_LIFTS)
        self.assertIn("no es un 1RM medido", ESTIMATED_STRENGTH_LABEL)

    def test_rolling_envelope_hides_technical_day(self):
        # Giffon: sentadilla 110 (29/09), 105 (06/10), 99 (16/10), 55 (20/10, dia tecnico).
        daily = pd.DataFrame(
            [
                {"Date": pd.Timestamp(day), "Lift": "Sentadilla trasera", "e1RM_kg": value}
                for day, value in (("2026-09-29", 110.0), ("2026-10-06", 105.0), ("2026-10-16", 99.0), ("2026-10-20", 55.0))
            ]
        )
        envelope = rolling_best_envelope(daily, today="2026-11-04").set_index("Date")
        self.assertEqual(float(envelope.loc[pd.Timestamp("2026-10-20"), "e1RM_kg"]), 99.0)
        self.assertEqual(float(envelope.loc[pd.Timestamp("2026-10-06"), "e1RM_kg"]), 110.0)
        self.assertEqual(float(envelope["e1RM_day_kg"].min()), 55.0)

    def test_lifts_without_recent_data_are_dropped(self):
        # Tomas: datos solo 25/08-01/09 -> sin grafico al 04/11.
        daily = pd.DataFrame(
            [
                {"Date": pd.Timestamp("2026-08-25"), "Lift": "Press de banca", "e1RM_kg": 50.0},
                {"Date": pd.Timestamp("2026-09-01"), "Lift": "Sentadilla frontal", "e1RM_kg": 65.0},
            ]
        )
        self.assertTrue(rolling_best_envelope(daily, today="2026-11-04").empty)
        mixed = pd.concat(
            [daily, pd.DataFrame([{"Date": pd.Timestamp("2026-10-30"), "Lift": "Peso muerto", "e1RM_kg": 140.0}])]
        )
        self.assertEqual(rolling_best_envelope(mixed, today="2026-11-04")["Lift"].unique().tolist(), ["Peso muerto"])
        self.assertIsNone(chart_estimated_strength(rolling_best_envelope(daily, today="2026-11-04"), theme={}))

    def test_new_best_needs_a_previous_mark(self):
        maxes = pd.DataFrame(
            [
                {"Athlete": "A", "Exercise Name": "Barbell Back Squat", "Max Value": 99, "Added Date": "2026-08-01"},
                {"Athlete": "A", "Exercise Name": "Barbell Back Squat", "Max Value": 110, "Added Date": "2026-10-21"},
                {"Athlete": "A", "Exercise Name": "Barbell Bench Press", "Max Value": 80, "Added Date": "2026-10-20"},
                {"Athlete": "A", "Exercise Name": "Band Pull Apart", "Max Value": 15, "Added Date": "2026-10-20"},
            ]
        )
        bests = new_main_lift_bests(maxes, "A", window_start="2026-09-23", window_end="2026-11-04")
        self.assertEqual([(b["Lift"], b["Value"], b["Previous"]) for b in bests], [("Sentadilla trasera", 110.0, 99.0)])


# ── PDF atleta / cliente ──────────────────────────────────────────────────
def _pdf_state(jump_rows: list[dict[str, object]], *, with_wellness: bool = False) -> dict[str, object]:
    athlete = jump_rows[0]["Athlete"]
    state: dict[str, object] = {
        "jump_df": pd.DataFrame([{"Source": "platform", "BW_kg": 80.0, **row} for row in jump_rows]),
        "rpe_df": None,
        "wellness_df": None,
        "completion_df": pd.DataFrame([{"Athlete": athlete, "Assigned": 40, "Completed": 30, "Pct": 75.0}]),
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {},
        "mono_dict": {},
    }
    if with_wellness:
        state["wellness_df"] = pd.DataFrame(
            [
                {"Athlete": athlete, "Date": f"2026-10-{day}", "Sueno_hs": 6.0, "Estres": 6, "Dolor": 6, "Wellness_Score": 13.0}
                for day in (20, 22, 23)
            ]
        )
    return state


class IndividualPdfTests(unittest.TestCase):
    def _pdf(self, state: dict[str, object], athlete: str, audience: str = "atleta") -> list[str]:
        with frozen_app_now(NOW):
            pdf = rg.generate_visual_report_pdf(state, athlete, audience)
        self.assertIsNotNone(pdf)
        return _pdf_pages(pdf)

    def test_tomas_shows_improvements_on_first_page(self):
        pages = self._pdf(_pdf_state(TOMAS), "Tomas De La Vega")
        self.assertIn("lo que lograste", pages[0])
        self.assertIn("por tiempo de vuelo", pages[0])
        self.assertIn("36.7 cm -> 44.0 cm", pages[0])
        self.assertIn("datos hasta 21/10/2026", pages[0])

    def test_forbidden_phrases_and_no_empty_pages(self):
        for rows, athlete in ((TOMAS, "Tomas De La Vega"), (GIFFON, "Agustin Giffon")):
            for audience in ("atleta", "cliente"):
                with self.subTest(athlete=athlete, audience=audience):
                    pages = self._pdf(_pdf_state(rows), athlete, audience)
                    joined = " ".join(pages)
                    for phrase in ATHLETE_FORBIDDEN_PHRASES:
                        self.assertNotIn(_normalized(phrase), joined)
                    self.assertNotIn("confianza", joined)
                    self.assertNotIn("completar imtp", joined)
                    self.assertTrue(all(len(page) > 80 for page in pages))
                    self.assertLessEqual(joined.count("foco del proximo bloque"), 1)
                    # Sin sRPE ni bienestar: proximos pasos, no secciones vacias.
                    self.assertNotIn("carga reciente", joined)
                    self.assertIn("proximos pasos", joined)

    def test_single_wellness_value_in_cover_and_section(self):
        pages = self._pdf(_pdf_state(TOMAS, with_wellness=True), "Tomas De La Vega")
        joined = " ".join(pages)
        self.assertEqual(len(set(re.findall(r"(\d+\.\d) ?/30", joined))), 1)
        # PR H: sin la tabla de la ultima semana completa (una sola ventana).
        self.assertNotIn("(19/10/2026-25/10/2026)", joined)
        # PR G: 3 registros en 6 semanas -> "pocos registros"; un solo valor,
        # el de la ventana de 6 semanas (PR H: la tabla ya no esta).
        self.assertIn("promedio de estas semanas: 13.0/30 (atencion)", joined)
        self.assertNotIn("13.0 /30 (atencion)", joined)

    def test_client_pdf_keeps_plain_language(self):
        joined = " ".join(self._pdf(_pdf_state(TOMAS), "Tomas De La Vega", "cliente"))
        for term in ("imtp", "acwr", "z-score", "cuadrante", "rfd", "zona"):
            self.assertNotIn(term, joined)
        self.assertIn("reporte de progreso", joined)

    def test_dictionary_is_never_alone_on_a_page(self):
        for audience in ("atleta", "cliente"):
            pages = self._pdf(_pdf_state(TOMAS), "Tomas De La Vega", audience)
            for page in pages:
                if "diccionario" in page:
                    self.assertIn("proximos pasos", page)


class DashboardAndPdfSharePayloadTests(unittest.TestCase):
    def test_payload_is_the_single_source(self):
        state = _pdf_state(TOMAS)
        with frozen_app_now(NOW):
            payload = rg.build_individual_report_payload(state, "Tomas De La Vega", "atleta")
            pdf = rg.generate_visual_report_pdf(state, "Tomas De La Vega", "atleta")
        joined = " ".join(_pdf_pages(pdf))
        for item in payload["achievements"]:
            self.assertIn(_normalized(item["text"].replace("→", "->"))[:40], joined)


class DashboardAchievementsAppTest(unittest.TestCase):
    """El dashboard muestra "Lo que lograste" con el mismo payload que el PDF."""

    def test_profile_view_shows_achievements(self):
        import os
        import shutil
        import uuid
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        app_path = Path(__file__).resolve().parent.parent / "app.py"
        tmp_root = Path(__file__).resolve().parent / f".tmp_achievements_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True)
        original = os.environ.get("THRESHOLD_STORE_DIR")
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        try:
            pd.DataFrame([{"Source": "platform", "BW_kg": 80.0, **row} for row in TOMAS]).to_csv(
                store_dir / "evaluations_history.csv", index=False
            )
            import importlib

            import local_store

            importlib.reload(local_store)
            at = AppTest.from_file(str(app_path), default_timeout=120)
            at.run()
            self.assertFalse(at.exception, at.exception)
            nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
            nav.set_value("Profile").run()
            self.assertFalse(at.exception, at.exception)
            markdown = " ".join(str(item.value) for item in at.markdown)
            self.assertIn("Lo que lograste", markdown)
            self.assertIn("Salto CMJ (por tiempo de vuelo): 36.7 cm → 44.0 cm", markdown)
        finally:
            if original is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = original
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
