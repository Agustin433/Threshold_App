"""Compuerta de procedencia del z-score.

Un z-score solo es interpretable si el desvio contra el que se calcula
corresponde a la poblacion del atleta y al instrumento con el que se midio.
Antes la app derivaba el desvio como `excellent - mean`, que no es un desvio
sino aproximadamente dos, y lo aplicaba a cualquier atleta sin mirar sexo,
deporte, nivel ni dispositivo.

Estos tests fijan la regla dura: **ningun atleta recibe un z prestado**. Si no
hay poblacion publicada que le corresponda, o la cohorte no llega al minimo, la
metrica resuelve a una banda de criterio o a lectura intra-individual, nunca a
un z calculado con un desvio ajeno.

Se escriben antes que la implementacion a pedido explicito del usuario.
"""

from __future__ import annotations

import unittest

from modules.zscore_sources import (
    ZSource,
    lookup_reference,
    resolve_z_source,
)
from modules.athlete_profile import Sexo, normalize_sexo
from modules.evaluation_sources import SOURCE_NONPLATFORM, SOURCE_PLATFORM


# Rugby League / Alto rendimiento es la unica poblacion con tabla verificada
# cargada hoy, asi que los tests de literatura se apoyan en ella. El plantel
# real del usuario (handball, futbol) todavia no tiene tabla propia y por eso
# resuelve a banda de criterio, que es justamente lo que el gate debe hacer.
def _profile(
    athlete: str = "Ana Lopez",
    *,
    deporte: str | None = "Rugby League",
    nivel: str | None = "Alto rendimiento",
    sexo: str = Sexo.FEMENINO,
) -> dict[str, object]:
    return {"Athlete": athlete, "Deporte": deporte, "Nivel": nivel, "Sexo": sexo}


class SexoEnumTest(unittest.TestCase):
    def test_sexo_is_a_closed_enum_not_a_free_string(self):
        self.assertEqual({Sexo.MASCULINO, Sexo.FEMENINO, Sexo.NO_ESPECIFICADO}, set(Sexo))

    def test_unknown_and_blank_values_resolve_to_no_especificado(self):
        # Nunca inventar un sexo: lo desconocido se declara desconocido.
        for value in ("", None, float("nan"), "otro", "x", "  "):
            with self.subTest(value=value):
                self.assertEqual(normalize_sexo(value), Sexo.NO_ESPECIFICADO)

    def test_the_string_False_does_not_become_a_valid_sexo(self):
        # Guarda explicita contra el clasico bool("False") == True: si el campo
        # viajara como booleano o string libre, "False" podria colarse como
        # valor valido y terminar seleccionando una tabla de referencia.
        self.assertEqual(normalize_sexo("False"), Sexo.NO_ESPECIFICADO)
        self.assertEqual(normalize_sexo(False), Sexo.NO_ESPECIFICADO)
        self.assertEqual(normalize_sexo(True), Sexo.NO_ESPECIFICADO)

    def test_accepted_spellings_map_to_the_enum(self):
        for value in ("M", "m", "Masculino", "masculino"):
            self.assertEqual(normalize_sexo(value), Sexo.MASCULINO)
        for value in ("F", "f", "Femenino", "femenino"):
            self.assertEqual(normalize_sexo(value), Sexo.FEMENINO)


class LiteratureGateTest(unittest.TestCase):
    def test_female_cmj_never_resolves_against_a_male_reference(self):
        """El caso que el usuario pidio fijar primero.

        Existe tabla de varones para esta poblacion y no existe de mujeres. La
        atleta no debe heredarla: ni el enum ni el desvio pueden salir de ahi.
        """
        male_reference = lookup_reference(
            "CMJ_cm", deporte="Rugby League", nivel="Alto rendimiento", sexo=Sexo.MASCULINO
        )
        self.assertIsNotNone(male_reference, "el fixture necesita una tabla de varones para que el test tenga sentido")
        self.assertIsNone(
            lookup_reference("CMJ_cm", deporte="Rugby League", nivel="Alto rendimiento", sexo=Sexo.FEMENINO),
            "el test deja de ser discriminante si se agrega una tabla de mujeres para esta poblacion",
        )

        decision = resolve_z_source(
            "CMJ_cm",
            profile=_profile(sexo=Sexo.FEMENINO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIsNot(decision.z_source, ZSource.LITERATURE_Z)
        self.assertIsNone(decision.sd)
        self.assertNotEqual(decision.sd, male_reference["sd"])

        # Control: el mismo perfil en varon si alcanza la tabla, asi que la
        # diferencia la produce el sexo y no una tabla ausente para todos.
        male = resolve_z_source(
            "CMJ_cm",
            profile=_profile(sexo=Sexo.MASCULINO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIs(male.z_source, ZSource.LITERATURE_Z)
        self.assertEqual(male.sd, male_reference["sd"])

    def test_no_especificado_never_reaches_literature_z(self):
        # Un perfil sin sexo cargado no puede elegir tabla: no hay poblacion.
        decision = resolve_z_source(
            "CMJ_cm",
            profile=_profile(sexo=Sexo.NO_ESPECIFICADO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIsNot(decision.z_source, ZSource.LITERATURE_Z)

    def test_athlete_without_population_gets_no_z(self):
        """El otro caso que el usuario pidio fijar primero.

        Sin deporte ni nivel no hay poblacion de referencia, y con una sola
        medicion tampoco hay lectura intra-individual.
        """
        decision = resolve_z_source(
            "CMJ_cm",
            profile=_profile(deporte=None, nivel=None, sexo=Sexo.NO_ESPECIFICADO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIs(decision.z_source, ZSource.REFERENCE_BAND)
        self.assertIsNone(decision.sd, "no debe exponerse un desvio cuando no hay poblacion")

    def test_instrument_class_must_match_the_reference(self):
        # Las normas publicadas de CMJ salen de plataforma (impulso-momento).
        # Un dato de tiempo de vuelo no puede leerse contra esa tabla.
        platform = resolve_z_source(
            "CMJ_cm",
            profile=_profile(sexo=Sexo.MASCULINO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        mat = resolve_z_source(
            "CMJ_cm",
            profile=_profile(sexo=Sexo.MASCULINO),
            source=SOURCE_NONPLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIs(
            platform.z_source,
            ZSource.LITERATURE_Z,
            "el control de plataforma debe alcanzar la tabla para que el test discrimine",
        )
        self.assertIsNot(
            mat.z_source,
            ZSource.LITERATURE_Z,
            "un dato de tiempo de vuelo se leyo contra una referencia de plataforma",
        )
        self.assertIsNone(mat.sd)

    def test_literature_sd_is_never_borrowed_across_populations(self):
        """Una poblacion sin tabla propia no hereda el desvio de otra."""
        exotic = resolve_z_source(
            "CMJ_cm",
            profile=_profile(deporte="Curling", nivel="Recreativo", sexo=Sexo.MASCULINO),
            source=SOURCE_PLATFORM,
            cohort_size=0,
            measurement_count=1,
        )
        self.assertIsNot(exotic.z_source, ZSource.LITERATURE_Z)
        self.assertIsNone(exotic.sd)


class CohortGateTest(unittest.TestCase):
    def _decide(self, cohort_size: int, measurement_count: int = 1):
        return resolve_z_source(
            "SJ_cm",  # sin tabla publicada: aisla el camino de cohorte
            profile=_profile(sexo=Sexo.FEMENINO),
            source=SOURCE_PLATFORM,
            cohort_size=cohort_size,
            measurement_count=measurement_count,
        )

    def test_cohort_below_minimum_never_produces_cohort_z(self):
        # Prohibido en cualquier circunstancia, no solo por defecto.
        for size in range(0, 8):
            with self.subTest(cohort_size=size):
                self.assertIsNot(self._decide(size).z_source, ZSource.COHORT_Z)

    def test_cohort_at_or_above_minimum_enables_cohort_z(self):
        self.assertIs(self._decide(8).z_source, ZSource.COHORT_Z)
        self.assertIs(self._decide(25).z_source, ZSource.COHORT_Z)

    def test_insufficient_cohort_falls_back_inside_the_same_enum(self):
        """El gate de cohorte no es un interruptor separado.

        Con muestra insuficiente la decision resuelve a otro miembro del enum,
        nunca a "cohorte apagada" como estado paralelo.
        """
        decision = self._decide(3)
        self.assertIn(
            decision.z_source,
            {ZSource.INTRA_INDIVIDUAL, ZSource.REFERENCE_BAND},
        )
        self.assertTrue(decision.reason, "la decision debe explicar por que no hay z de cohorte")

    def test_intra_individual_needs_enough_measurements(self):
        # Con una sola toma no hay serie propia contra la cual comparar.
        self.assertIs(self._decide(3, measurement_count=1).z_source, ZSource.REFERENCE_BAND)
        self.assertIs(self._decide(3, measurement_count=2).z_source, ZSource.INTRA_INDIVIDUAL)


class DecisionContractTest(unittest.TestCase):
    def test_every_decision_declares_its_origin_and_reason(self):
        cases = [
            dict(profile=_profile(sexo=Sexo.MASCULINO), source=SOURCE_PLATFORM, cohort_size=0, measurement_count=1),
            dict(profile=_profile(sexo=Sexo.NO_ESPECIFICADO), source=SOURCE_NONPLATFORM, cohort_size=12, measurement_count=5),
            dict(profile=_profile(deporte=None, nivel=None), source=SOURCE_PLATFORM, cohort_size=3, measurement_count=2),
        ]
        for kwargs in cases:
            with self.subTest(**{k: str(v)[:24] for k, v in kwargs.items()}):
                decision = resolve_z_source("CMJ_cm", **kwargs)
                self.assertIsInstance(decision.z_source, ZSource)
                self.assertTrue(decision.reason)
                self.assertTrue(decision.label)

    def test_only_literature_z_exposes_a_standard_deviation(self):
        # Un SD visible implica una poblacion publicada detras. Si el z sale de
        # cohorte o de la serie propia, el desvio se calcula sobre los datos y
        # no debe presentarse como si viniera de la literatura.
        decision = resolve_z_source(
            "SJ_cm",
            profile=_profile(sexo=Sexo.FEMENINO),
            source=SOURCE_PLATFORM,
            cohort_size=12,
            measurement_count=4,
        )
        self.assertIs(decision.z_source, ZSource.COHORT_Z)
        self.assertIsNone(decision.sd)


if __name__ == "__main__":
    unittest.main()


class StaleZScoreLeakTest(unittest.TestCase):
    """Un z guardado de una version anterior no puede resucitar.

    El historial persistido trae columnas `*_Z` calculadas con el benchmark
    sintetico que se elimino. Si la procedencia resuelve a banda de criterio,
    ese valor viejo no debe reaparecer: seria un desvio prestado entrando por
    la puerta de atras.
    """

    def test_reference_band_clears_a_previously_stored_z(self):
        import pandas as pd

        from modules.jump_analysis import calc_zscores

        frame = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": pd.Timestamp("2026-05-01"),
                    "Source": SOURCE_PLATFORM,
                    "CMJ_cm": 41.0,
                    "CMJ_Z": 0.87,  # residuo del benchmark sintetico anterior
                }
            ]
        )
        # Sin profile_df no hay poblacion ni cohorte: debe caer a banda.
        result = calc_zscores(frame.copy(), profile_df=None)

        self.assertEqual(result.loc[0, "CMJ_Z_source"], str(ZSource.REFERENCE_BAND))
        self.assertTrue(
            pd.isna(result.loc[0, "CMJ_Z"]),
            "un z almacenado sobrevivio a una decision de banda de criterio",
        )
