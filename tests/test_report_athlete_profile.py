"""Bloque 4: seccion "PERFIL DEL ATLETA" + narrativa condicional por objetivo
en los reportes individuales (PDF profe/atleta/cliente + hoja Excel).

Escrito ANTES de tocar modules/athlete_profile.py ni modules/report_generator.py
(test-first, pedido explicito del usuario). Cada test referencia al menos un
simbolo nuevo (funcion privada o constante) que todavia no existe en
report_generator.py, para que la corrida completa de este archivo falle por
AttributeError, no por AssertionError -- eso prueba que la premisa de cada
test es correcta antes de escribir produccion.

Las dos excepciones deliberadas son los "regression guards" (perfil ausente
no debe cambiar nada): tambien empiezan llamando al simbolo nuevo (para
fallar igual que el resto hoy), pero su assertion de fondo ya es verdadera
hoy y debe seguir siendolo despues de implementar -- no son casos que deban
"pasar a fallar y despues pasar", sino guardas que nunca deben empezar a
fallar.
"""

from __future__ import annotations

import re
import unicodedata
import unittest
from datetime import datetime as real_datetime
from unittest.mock import patch

import pandas as pd

import modules.report_generator as report_generator
from modules.athlete_profile import OBJETIVO_OPTIONS, get_comparison_cohort
from modules.report_generator import (
    build_executive_summary_df,
    build_interpretation_sheet,
    generate_module_insights,
    generate_visual_report_pdf,
)

from tests.test_professional_pdf_report import (
    FixedProfessionalReportDate,
    _professional_state_with_force_time,
)


def _pdf_page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def _normalized_story_text(text: str) -> str:
    repaired = report_generator._repair_mojibake_text(text)
    return unicodedata.normalize("NFD", repaired).encode("ascii", "ignore").decode("ascii").lower()


def _story_plain_text(flowable: object) -> list[str]:
    if flowable is None:
        return []
    if isinstance(flowable, (list, tuple)):
        lines: list[str] = []
        for item in flowable:
            lines.extend(_story_plain_text(item))
        return lines
    if hasattr(flowable, "getPlainText"):
        try:
            return [str(flowable.getPlainText())]
        except Exception:
            return []
    if hasattr(flowable, "_cellvalues"):
        lines: list[str] = []
        for row in getattr(flowable, "_cellvalues", []) or []:
            lines.extend(_story_plain_text(row))
        return lines
    return []


class FixedReportDate(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 5, 12, 0, tzinfo=tz)


def _rendered_pdf_and_story_text(
    state: dict[str, object],
    athlete: str,
    audience: str,
    now_cls: type[real_datetime],
) -> tuple[bytes, str]:
    from reportlab.platypus import SimpleDocTemplate

    captured: dict[str, object] = {}
    original_build = SimpleDocTemplate.build

    def capture_build(self, flowables, *args, **kwargs):
        captured["story"] = list(flowables)
        return original_build(self, flowables, *args, **kwargs)

    with patch.object(report_generator, "datetime", now_cls):
        with patch.object(SimpleDocTemplate, "build", capture_build):
            pdf = generate_visual_report_pdf(state, athlete, audience)

    assert pdf is not None
    story_text = _normalized_story_text(" ".join(_story_plain_text(captured.get("story", []))))
    return pdf, story_text


def _profile_df(athlete: str, **overrides: object) -> pd.DataFrame:
    row = {
        "Athlete": athlete,
        "Fecha_nacimiento": "2000-01-01",
        "Altura_cm": 178.0,
        "Peso_kg": 75.0,
        "Contexto": "Club",
        "Deporte": "Handball",
        "Nivel": "Competitivo",
        "Objetivo_primario": "Fuerza máxima",
        "Objetivos_secundarios": "",
        "Objetivo_otro_texto": "",
        "Es_RTP": False,
        "Fecha_actualizacion": "2026-07-01",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _jump_df_with_imtp_relpf(athlete: str, value: float = 45.0) -> pd.DataFrame:
    return pd.DataFrame([{"Athlete": athlete, "Date": "2026-06-01", "IMTP_relPF": value}])


def _minimal_report_state(athlete: str = "Ana Lopez") -> dict[str, object]:
    return {
        "rpe_df": pd.DataFrame(
            [
                {"Athlete": athlete, "Date": "2026-04-28", "sRPE": 320},
                {"Athlete": athlete, "Date": "2026-04-30", "sRPE": 340},
                {"Athlete": athlete, "Date": "2026-05-04", "sRPE": 300},
                {"Athlete": athlete, "Date": "2026-05-05", "sRPE": 300},
            ]
        ),
        "wellness_df": pd.DataFrame(
            [
                {"Athlete": athlete, "Date": "2026-04-28", "Sueno_hs": 7.2, "Estres": 3, "Dolor": 2, "Wellness_Score": 8.0},
                {"Athlete": athlete, "Date": "2026-05-04", "Sueno_hs": 6.6, "Estres": 5, "Dolor": 3, "Wellness_Score": 6.8},
            ]
        ),
        "completion_df": pd.DataFrame(
            [{"Athlete": athlete, "Date": "2026-04-30", "Assigned": 10, "Completed": 9, "Pct": 90}]
        ),
        "jump_df": pd.DataFrame(
            [
                {
                    "Athlete": athlete,
                    "Date": "2026-05-01",
                    "CMJ_cm": 32,
                    "SJ_cm": 29,
                    "DJ_drop_height_cm": 47.65,
                    "DJ_cm": 25,
                    "DJ_tc_ms": 230,
                    "DRI": 1.4,
                    "IMTP_N": 1800,
                    "EUR": 1.1,
                    "NM_Profile": "Reactivo",
                }
            ]
        ),
        "raw_df": None,
        "maxes_df": None,
        "rep_load_df": None,
        "acwr_dict": {
            athlete: pd.DataFrame(
                [
                    {"Date": "2026-04-28", "sRPE_diario": 320, "ACWR_EWMA": 1.05, "Zona": "Optimo"},
                    {"Date": "2026-05-05", "sRPE_diario": 300, "ACWR_EWMA": 0.98, "Zona": "Optimo"},
                ]
            )
        },
        "mono_dict": {
            athlete: pd.DataFrame([{"Semana": "2026-04-27", "Carga_Semanal": 660, "Monotonia": 1.3, "Strain": 858}])
        },
    }


class ResolveAthleteProfileRowTest(unittest.TestCase):
    def test_missing_key_returns_none(self):
        self.assertIsNone(report_generator._resolve_athlete_profile_row({}, "Ana Lopez"))

    def test_empty_df_returns_none(self):
        state = {"athlete_profile_df": pd.DataFrame()}
        self.assertIsNone(report_generator._resolve_athlete_profile_row(state, "Ana Lopez"))

    def test_no_matching_row_returns_none(self):
        state = {"athlete_profile_df": _profile_df("Bruno Rey")}
        self.assertIsNone(report_generator._resolve_athlete_profile_row(state, "Ana Lopez"))

    def test_matching_row_is_returned(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez")}
        row = report_generator._resolve_athlete_profile_row(state, "Ana Lopez")
        self.assertIsNotNone(row)
        self.assertEqual(row["Athlete"], "Ana Lopez")

    def test_duplicate_rows_returns_last(self):
        df = pd.concat(
            [
                _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima"),
                _profile_df("Ana Lopez", Objetivo_primario="Hipertrofia"),
            ],
            ignore_index=True,
        )
        state = {"athlete_profile_df": df}
        row = report_generator._resolve_athlete_profile_row(state, "Ana Lopez")
        self.assertEqual(row["Objetivo_primario"], "Hipertrofia")


class BuildAthleteProfileInsightTest(unittest.TestCase):
    def test_no_profile_df_in_state_returns_none_gating(self):
        self.assertIsNone(report_generator._build_athlete_profile_insight({}, "Ana Lopez"))

    def test_todos_scope_returns_none(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez")}
        self.assertIsNone(report_generator._build_athlete_profile_insight(state, "Todos"))

    def test_missing_row_returns_missing_state(self):
        state = {"athlete_profile_df": _profile_df("Bruno Rey")}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        self.assertEqual(insight["state"], "missing")

    def test_incomplete_row_flags_missing_field(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Nivel="")}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        self.assertEqual(insight["state"], "incomplete")
        self.assertIn("Nivel", insight.get("missing_fields", []))

    def test_complete_profile_without_secondary_objectives(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez")}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        self.assertEqual(insight["state"], "complete")
        joined = " ".join(insight.get("focuses", [])).lower()
        self.assertNotIn("secundario", joined)

    def test_secondary_objectives_are_listed_up_to_three(self):
        state = {
            "athlete_profile_df": _profile_df(
                "Ana Lopez", Objetivos_secundarios="Hipertrofia|Resistencia física"
            )
        }
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        joined = " ".join(insight.get("focuses", []))
        self.assertIn("Hipertrofia", joined)
        self.assertIn("Resistencia física", joined)

    def test_more_than_three_secondary_objectives_are_truncated(self):
        secondary = "|".join(o for o in OBJETIVO_OPTIONS if o != "Fuerza máxima")  # 8 valores
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivos_secundarios=secondary)}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        joined = " ".join(insight.get("focuses", []))
        self.assertIn("+5 más", joined)

    def test_is_rtp_true(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Es_RTP=True)}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        self.assertTrue(insight.get("is_rtp"))

    def test_is_rtp_false(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Es_RTP=False)}
        insight = report_generator._build_athlete_profile_insight(state, "Ana Lopez")
        self.assertFalse(insight.get("is_rtp"))


class ResolveObjectiveGuidanceTest(unittest.TestCase):
    def test_no_profile_returns_inactive(self):
        guidance = report_generator._resolve_objective_guidance({}, "Ana Lopez")
        self.assertFalse(guidance.get("active"))

    def test_no_objetivo_primario_returns_inactive(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertFalse(guidance.get("active"))

    def test_fuerza_maxima_with_imtp_relpf_has_anchor_sentence(self):
        state = {
            "athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima"),
            "jump_df": _jump_df_with_imtp_relpf("Ana Lopez", 45.0),
        }
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("active"))
        self.assertIn("45", guidance.get("anchor_sentence", ""))

    def test_fuerza_maxima_without_imtp_relpf_still_active_with_fallback(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("active"))
        self.assertTrue(guidance.get("anchor_sentence"))

    def test_hipertrofia_suppresses_nm_profile_and_prioritizes_sessions(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Hipertrofia")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("active"))
        self.assertTrue(guidance.get("suppress_nm_profile"))
        priority = guidance.get("priority_metrics", [])
        self.assertIn("sessions_count", priority)
        self.assertIn("wellness_compliance", priority)
        full_text = " ".join(str(v) for v in guidance.values() if isinstance(v, str))
        self.assertNotIn("NM_Profile", full_text)
        self.assertNotIn("radar", full_text.lower())

    def test_recomposicion_corporal_same_as_hipertrofia_rule(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Recomposición corporal")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("suppress_nm_profile"))

    def test_prevencion_de_lesiones_prioritizes_asymmetries(self):
        state = {
            "athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Prevención de lesiones"),
            "jump_df": pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-06-01", "IMTP_asym_pct": 8.5}]),
        }
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("active"))
        priority = guidance.get("priority_metrics", [])
        self.assertTrue(any("asym" in str(m).lower() for m in priority))
        self.assertIn("wellness_compliance", priority)

    def test_salud_general_uses_plain_language(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Salud general y calidad de vida")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        full_text = " ".join(str(v) for v in guidance.values() if isinstance(v, str)).lower()
        self.assertNotIn("z-score", full_text)
        self.assertNotIn("ssc", full_text)
        self.assertNotIn("nm_profile", full_text)

    def test_resistencia_fisica_has_fixed_limitation_note(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Resistencia física")}
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("active"))
        self.assertTrue(guidance.get("limitation_note"))

    def test_rendimiento_deportivo_especifico_is_inactive_default(self):
        state = {
            "athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Rendimiento deportivo específico")
        }
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertFalse(guidance.get("active"))

    def test_rtp_and_fuerza_maxima_are_additive_not_exclusive(self):
        state = {
            "athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima", Es_RTP=True),
            "jump_df": pd.DataFrame(
                [{"Athlete": "Ana Lopez", "Date": "2026-06-01", "IMTP_relPF": 45.0, "IMTP_asym_pct": 8.5}]
            ),
        }
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez")
        self.assertTrue(guidance.get("anchor_sentence"))
        priority = guidance.get("priority_metrics", [])
        self.assertIn("wellness_compliance", priority)
        self.assertTrue(any("asym" in str(m).lower() for m in priority))

    def test_cliente_audience_never_uses_technical_jargon(self):
        state = {
            "athlete_profile_df": _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima"),
            "jump_df": _jump_df_with_imtp_relpf("Ana Lopez", 45.0),
        }
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez", audience="cliente")
        anchor = guidance.get("anchor_sentence", "").lower()
        self.assertNotIn("imtp", anchor)
        self.assertNotIn("z-score", anchor)
        self.assertNotIn("cuadrante", anchor)


class RtpClinicalNoteTest(unittest.TestCase):
    def test_true_bool_returns_disclaimer(self):
        row = _profile_df("Ana Lopez", Es_RTP=True).iloc[0]
        self.assertEqual(report_generator._rtp_clinical_note(row), report_generator.RTP_CLINICAL_DISCLAIMER)

    def test_false_bool_returns_none(self):
        row = _profile_df("Ana Lopez", Es_RTP=False).iloc[0]
        self.assertIsNone(report_generator._rtp_clinical_note(row))

    def test_false_string_returns_none(self):
        row = _profile_df("Ana Lopez", Es_RTP="False").iloc[0]
        self.assertIsNone(report_generator._rtp_clinical_note(row))

    def test_none_row_returns_none(self):
        self.assertIsNone(report_generator._rtp_clinical_note(None))

    def test_disclaimer_present_regardless_of_objetivo_primario(self):
        for objetivo in OBJETIVO_OPTIONS:
            with self.subTest(objetivo=objetivo):
                row = _profile_df("Ana Lopez", Objetivo_primario=objetivo, Es_RTP=True).iloc[0]
                self.assertEqual(
                    report_generator._rtp_clinical_note(row), report_generator.RTP_CLINICAL_DISCLAIMER
                )


class QuadrantCohortFootnoteTest(unittest.TestCase):
    def test_matches_get_comparison_cohort_label(self):
        profile_df = pd.concat(
            [
                _profile_df("Ana Lopez", Deporte="Handball", Nivel="Competitivo"),
                _profile_df("Bruno Rey", Deporte="Handball", Nivel="Competitivo"),
                _profile_df("Caro Diaz", Deporte="Handball", Nivel="Competitivo"),
            ],
            ignore_index=True,
        )
        jump_df = pd.DataFrame(
            [
                {"Athlete": "Ana Lopez", "Date": "2026-06-01", "CMJ_cm": 35},
                {"Athlete": "Bruno Rey", "Date": "2026-06-01", "CMJ_cm": 40},
                {"Athlete": "Caro Diaz", "Date": "2026-06-01", "CMJ_cm": 38},
            ]
        )
        state = {"athlete_profile_df": profile_df, "jump_df": jump_df}
        expected = get_comparison_cohort("Ana Lopez", jump_df, profile_df)
        footnote = report_generator._quadrant_cohort_footnote(state, "Ana Lopez")
        self.assertIn(expected["cohort_label"], footnote)

    def test_missing_inputs_do_not_raise_and_fall_back(self):
        footnote = report_generator._quadrant_cohort_footnote({}, "Ana Lopez")
        self.assertIsNotNone(footnote)
        self.assertIn("Comparación", footnote)


class BuildInterpretationSheetAthleteProfileTest(unittest.TestCase):
    def test_athlete_profile_row_present_when_profile_complete(self):
        state = {"athlete_profile_df": _profile_df("Ana Lopez")}
        sheet = build_interpretation_sheet(state, "Ana Lopez", "profe")
        self.assertIn("Athlete_Profile", sheet["Modulo"].values)
        row = sheet.loc[sheet["Modulo"] == "Athlete_Profile"].iloc[0]
        self.assertTrue(str(row["Lectura"]).strip())
        self.assertIn("Fuerza máxima", row["Próximos focos"])

    def test_athlete_profile_row_absent_without_profile_df(self):
        state = {}
        self.assertIsNone(report_generator._build_athlete_profile_insight(state, "Ana Lopez"))
        sheet = build_interpretation_sheet(state, "Ana Lopez", "profe")
        self.assertNotIn("Athlete_Profile", sheet["Modulo"].values)


class ProfessionalPdfAthleteProfileTest(unittest.TestCase):
    def test_rtp_true_shows_disclaimer_and_stays_within_page_ceiling(self):
        state = _professional_state_with_force_time()
        state["athlete_profile_df"] = _profile_df("Ana Lopez", Es_RTP=True)
        expected_fragment = _normalized_story_text(report_generator.RTP_CLINICAL_DISCLAIMER.split(".")[0])
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe", FixedProfessionalReportDate)
        self.assertIn(expected_fragment, text)
        self.assertLessEqual(_pdf_page_count(pdf), 10)

    def test_rtp_false_never_shows_disclaimer(self):
        state = _professional_state_with_force_time()
        state["athlete_profile_df"] = _profile_df("Ana Lopez", Es_RTP=False)
        expected_fragment = _normalized_story_text(report_generator.RTP_CLINICAL_DISCLAIMER.split(".")[0])
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe", FixedProfessionalReportDate)
        self.assertNotIn(expected_fragment, text)


class ProfessionalPdfWorstCaseAndRegressionTest(unittest.TestCase):
    """El pedido explicito del usuario: peor caso de longitud de contenido
    (RTP + objetivo primario largo + los 8 objetivos secundarios posibles)
    no debe empujar el PDF profe mas alla del techo de 10 paginas ya
    vigente en tests/test_professional_pdf_report.py."""

    def test_worst_case_rtp_long_objective_and_all_secondary_objectives_stays_within_page_ceiling(self):
        state = _professional_state_with_force_time()
        all_secondary = "|".join(o for o in OBJETIVO_OPTIONS if o != "Rehabilitación y retorno deportivo (RTP)")
        state["athlete_profile_df"] = _profile_df(
            "Ana Lopez",
            Objetivo_primario="Rehabilitación y retorno deportivo (RTP)",
            Objetivos_secundarios=all_secondary,
            Es_RTP=True,
        )
        expected_fragment = _normalized_story_text(report_generator.RTP_CLINICAL_DISCLAIMER.split(".")[0])
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe", FixedProfessionalReportDate)
        self.assertIn(expected_fragment, text)
        self.assertLessEqual(_pdf_page_count(pdf), 10)

    def test_no_profile_df_in_state_never_shows_disclaimer_or_profile_section(self):
        state = _professional_state_with_force_time()
        self.assertIsNone(report_generator._build_athlete_profile_insight(state, "Ana Lopez"))
        expected_fragment = _normalized_story_text(report_generator.RTP_CLINICAL_DISCLAIMER.split(".")[0])
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "profe", FixedProfessionalReportDate)
        self.assertNotIn(expected_fragment, text)
        self.assertLessEqual(_pdf_page_count(pdf), 10)


class AthletePdfAthleteProfileTest(unittest.TestCase):
    def test_profile_content_appears_and_page_count_matches_baseline(self):
        state = _minimal_report_state()
        state["athlete_profile_df"] = _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima")
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez", audience="atleta")
        self.assertTrue(guidance.get("active"))

        baseline_state = _minimal_report_state()
        baseline_pdf, _ = _rendered_pdf_and_story_text(baseline_state, "Ana Lopez", "atleta", FixedReportDate)
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "atleta", FixedReportDate)

        expected_fragment = _normalized_story_text(guidance.get("anchor_sentence", ""))
        self.assertTrue(expected_fragment)
        self.assertIn(expected_fragment, text)
        # El template atleta no tiene margen incluso para una sola linea de
        # contenido nuevo (verificado: bloque combinado de ~113 caracteres
        # igual desborda). +1 pagina es el costo minimo posible del Bloque 4
        # en este template, confirmado tambien en el peor caso
        # RTP+guia+disclaimer, no un problema de implementacion.
        self.assertEqual(_pdf_page_count(pdf), _pdf_page_count(baseline_pdf) + 1)


class ClientPdfAthleteProfileTest(unittest.TestCase):
    def test_jargon_ban_still_holds_with_fuerza_maxima_guidance_active(self):
        state = _minimal_report_state()
        state["athlete_profile_df"] = _profile_df("Ana Lopez", Objetivo_primario="Fuerza máxima")
        guidance = report_generator._resolve_objective_guidance(state, "Ana Lopez", audience="cliente")
        self.assertTrue(guidance.get("active"))

        baseline_state = _minimal_report_state()
        baseline_pdf, _ = _rendered_pdf_and_story_text(baseline_state, "Ana Lopez", "cliente", FixedReportDate)
        pdf, text = _rendered_pdf_and_story_text(state, "Ana Lopez", "cliente", FixedReportDate)

        self.assertNotIn("z-score", text)
        self.assertNotIn("imtp", text)
        self.assertNotIn("cuadrante", text)
        expected_fragment = _normalized_story_text(guidance.get("anchor_sentence", ""))
        self.assertTrue(expected_fragment)
        self.assertIn(expected_fragment, text)
        self.assertEqual(_pdf_page_count(pdf), _pdf_page_count(baseline_pdf))


class AudienceBlocksRtpDisclaimerTest(unittest.TestCase):
    """Red de seguridad: _audience_blocks() solo se alcanza para alcance
    "Todos" o como fallback si las ramas dedicadas por audiencia fallan,
    pero si eso pasa con un atleta RTP igual debe llevar el disclaimer."""

    def _blocks_for(self, es_rtp: bool, audience: str) -> list[dict[str, object]]:
        state = _minimal_report_state()
        state["athlete_profile_df"] = _profile_df(
            "Ana Lopez", Objetivo_primario="Fuerza máxima", Es_RTP=es_rtp
        )
        summary_df = build_executive_summary_df(state, "Ana Lopez", audience)
        insights = generate_module_insights(state, "Ana Lopez", audience)
        return report_generator._audience_blocks(state, "Ana Lopez", summary_df, insights, audience)

    def test_rtp_true_inserts_disclaimer_block(self):
        for audience in ("profe", "cliente", "atleta"):
            with self.subTest(audience=audience):
                blocks = self._blocks_for(True, audience)
                joined = " ".join(str(block.get("summary", "")) for block in blocks)
                self.assertIn(report_generator.RTP_CLINICAL_DISCLAIMER, joined)

    def test_rtp_false_never_inserts_disclaimer_block(self):
        for audience in ("profe", "cliente", "atleta"):
            with self.subTest(audience=audience):
                blocks = self._blocks_for(False, audience)
                joined = " ".join(str(block.get("summary", "")) for block in blocks)
                self.assertNotIn(report_generator.RTP_CLINICAL_DISCLAIMER, joined)


if __name__ == "__main__":
    unittest.main()
