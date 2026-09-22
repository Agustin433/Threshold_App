"""El eje X del cuadrante secundario tiene que ser uno y estar declarado.

CMJ y Jump Momentum ordenan al mismo plantel al revés: en McMahon et al. 2022
los backs saltan 2,3 cm más que los forwards y los forwards tienen 22,3 N·s más
de momentum. Elegir el eje decide quién aparece a la derecha del cuadrante, así
que la elección no puede quedar implícita ni resolverse distinto en el dashboard
y en el reporte.
"""

import unittest

import pandas as pd

from modules.jump_analysis import (
    COLLISION_DEPORTES,
    HEAVY_BW_THRESHOLD_KG,
    choose_secondary_quadrant_x_spec,
)
from modules.report_generator import _build_professional_quadrant_sections
from modules.zscore_sources import ZSource


def _declare(frame: pd.DataFrame) -> pd.DataFrame:
    """Sella procedencia sobre los z que el fixture inyecta."""
    result = frame.copy()
    for column in [col for col in result.columns if str(col).endswith("_Z")]:
        result[f"{column}_source"] = str(ZSource.COHORT_Z)
    return result


def _team(bw_values: list[float], deporte: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    jump_df = pd.DataFrame(
        [
            {
                "Athlete": f"Atleta {index}",
                "Date": "2026-05-01",
                "BW_kg": bw,
                "CMJ_cm": 34.0,
                "Jump_Momentum": 250.0,
                "IMTP_relPF": 39.5,
                "CMJ_Z": 0.20,
                "Jump_Momentum_Z": 0.30,
                "IMTP_relPF_Z": 0.40,
            }
            for index, bw in enumerate(bw_values)
        ]
    )
    profile_df = pd.DataFrame(
        [
            {
                "Athlete": f"Atleta {index}",
                "Deporte": deporte or "Vóley",
                "Nivel": "Competitivo",
                "Sexo": "M",
            }
            for index in range(len(bw_values))
        ]
    )
    return _declare(jump_df), profile_df


class SecondaryQuadrantAxisTest(unittest.TestCase):
    def test_light_team_uses_cmj(self):
        jump_df, profile_df = _team([70, 72, 74, 76])
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertEqual(spec.x_col, "CMJ_Z")
        self.assertIn("CMJ", spec.x_label)

    def test_heavy_team_uses_jump_momentum(self):
        jump_df, profile_df = _team([98, 102, 96, 105])
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertEqual(spec.x_col, "Jump_Momentum_Z")
        self.assertIn("Momentum", spec.x_label)

    def test_single_heavy_athlete_does_not_flip_axis_for_a_light_team(self):
        # La regla vieja promediaba: un solo pesado corria el eje de todo el
        # plantel, incluido el liviano a quien el momentum perjudica.
        jump_df, profile_df = _team([62, 64, 130])
        mean_bw = jump_df["BW_kg"].mean()
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertGreater(mean_bw, HEAVY_BW_THRESHOLD_KG)
        self.assertEqual(spec.x_col, "CMJ_Z")

    def test_majority_decides_not_the_mean(self):
        jump_df, profile_df = _team([86, 87, 88, 40])
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertEqual(spec.x_col, "Jump_Momentum_Z")

    def test_collision_sport_resolves_through_the_normalizer(self):
        # No por substring: "rugby" en texto libre agarraba cualquier grafia y
        # concatenaba todo el plantel, asi que un solo rugbier movia a los 18.
        jump_df, profile_df = _team([70, 72, 74, 76], deporte="RUGBY")
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertIn("Rugby", COLLISION_DEPORTES)
        self.assertEqual(spec.x_col, "Jump_Momentum_Z")

    def test_single_collision_athlete_does_not_flip_a_non_collision_team(self):
        jump_df, profile_df = _team([70, 72, 74, 76, 78, 80])
        profile_df.loc[0, "Deporte"] = "Rugby"
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertEqual(spec.x_col, "CMJ_Z")

    def test_reason_names_the_criterion_that_decided(self):
        heavy_spec = choose_secondary_quadrant_x_spec(*_team([98, 102, 96, 105]))
        light_spec = choose_secondary_quadrant_x_spec(*_team([70, 72, 74, 76]))

        for spec in (heavy_spec, light_spec):
            self.assertTrue(spec.reason.strip(), spec)
            self.assertIn(str(int(HEAVY_BW_THRESHOLD_KG)), spec.reason)

    def test_split_team_declares_that_the_choice_is_not_clean(self):
        jump_df, profile_df = _team([70, 72, 74, 96, 98, 102])
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertTrue(spec.is_ambiguous)
        self.assertIn("repartido", spec.reason.lower())

    def test_unanimous_team_is_not_flagged_as_split(self):
        spec = choose_secondary_quadrant_x_spec(*_team([70, 72, 74, 76]))

        self.assertFalse(spec.is_ambiguous)

    def test_team_without_body_mass_falls_back_to_cmj_and_says_so(self):
        jump_df, profile_df = _team([70, 72])
        jump_df["BW_kg"] = pd.NA
        spec = choose_secondary_quadrant_x_spec(jump_df, profile_df=profile_df)

        self.assertEqual(spec.x_col, "CMJ_Z")
        self.assertIn("sin peso", spec.reason.lower())


class SecondaryQuadrantAxisAgreementTest(unittest.TestCase):
    """Pantalla y reporte no pueden elegir ejes distintos para el mismo plantel."""

    def _state(self, bw_values: list[float], deporte: str | None = None) -> dict:
        jump_df, profile_df = _team(bw_values, deporte)
        return {"jump_df": jump_df, "athlete_profile_df": profile_df}

    def test_report_uses_the_same_axis_as_the_dashboard(self):
        for bw_values in ([70, 72, 74, 76], [98, 102, 96, 105]):
            with self.subTest(bw_values=bw_values):
                state = self._state(bw_values)
                expected = choose_secondary_quadrant_x_spec(
                    state["jump_df"], profile_df=state["athlete_profile_df"]
                )
                section = _build_professional_quadrant_sections(state, "Atleta 0")[0]

                self.assertEqual(section["x_col"], expected.x_col)

    def test_report_label_matches_the_column_it_plots(self):
        # El label estaba fijo en "CMJ z": si el reporte agarraba
        # `Jump_Momentum_Z` porque faltaba `CMJ_Z`, lo rotulaba igual.
        state = self._state([98, 102, 96, 105])
        section = _build_professional_quadrant_sections(state, "Atleta 0")[0]

        self.assertEqual(section["x_col"], "Jump_Momentum_Z")
        self.assertIn("Momentum", str(section["x_label"]))

    def test_report_plots_cmj_when_momentum_column_leads_the_frame(self):
        # El reporte tomaba la primera columna presente en el frame, no la que
        # la regla elegia, asi que el orden de columnas podia decidir el eje.
        state = self._state([70, 72, 74, 76])
        jump_df = state["jump_df"]
        state["jump_df"] = jump_df[
            ["Jump_Momentum_Z", "Jump_Momentum_Z_source", *[
                col for col in jump_df.columns
                if col not in {"Jump_Momentum_Z", "Jump_Momentum_Z_source"}
            ]]
        ]
        section = _build_professional_quadrant_sections(state, "Atleta 0")[0]

        self.assertEqual(section["x_col"], "CMJ_Z")

    def test_report_carries_the_reason_so_the_pdf_can_declare_it(self):
        state = self._state([98, 102, 96, 105])
        section = _build_professional_quadrant_sections(state, "Atleta 0")[0]

        self.assertTrue(str(section["axis_reason"]).strip())


if __name__ == "__main__":
    unittest.main()
