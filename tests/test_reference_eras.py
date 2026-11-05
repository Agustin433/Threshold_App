"""PR C: referencia de z-scores, radar y eras de medicion."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from modules import athlete_report as ar
from modules.athlete_profile import (
    DEMAND_ENDURANCE,
    DEMAND_GENERAL,
    DEMAND_RACKET_COMBAT,
    DEMAND_STRENGTH_POWER,
    DEMAND_TEAM,
    demand_group,
    evaluation_sexo_check,
    primary_deporte,
)
from modules.jump_analysis import (
    RADAR_MODE_PERCENTILE,
    _prepare_jump_df,
    compute_evaluation_changes,
    radar_axis_values,
    radar_reference_caption,
)
from modules.measurement_eras import (
    ERA_CHANGE_SIGNAL,
    ERA_INVOLUTION_STRAPS,
    ERA_VALKYRIA_NO_STRAPS,
    ERA_VALKYRIA_STRAPS,
    era_from_date,
    is_era_dependent,
)
from modules.reference_engine import LEVEL_DEMAND, LEVEL_SEX, LEVEL_SPORT, parse_reference
from modules.zscore_sources import (
    REFERENCE_TABLES,
    ZSource,
    context_references,
    lookup_reference,
    validate_reference_tables,
)


def _profile(name: str, sexo: str = "Masculino", deporte: str = "Fútbol", nivel: str = "Recreativo") -> dict:
    return {"Athlete": name, "Sexo": sexo, "Deporte": deporte, "Nivel": nivel}


def _take(name: str, date: str, *, device: str = ERA_INVOLUTION_STRAPS, **metrics) -> dict:
    return {"Athlete": name, "Date": date, "Source": "platform", "Device": device, "BW_kg": 80.0, **metrics}


def _team(n: int, *, sexo: str = "Masculino", deporte: str = "Fútbol", nivel: str = "Recreativo",
          prefix: str = "M", base: float = 30.0, date: str = "2026-10-10", device: str = ERA_INVOLUTION_STRAPS):
    takes, profiles = [], []
    for index in range(n):
        name = f"{prefix} {index:02d}"
        takes.append(_take(name, date, device=device, DJ_cm=base + index, DJ_tc_ms=220.0 - index,
                           DJ_drop_height_cm=30.0, IMTP_N=3000.0 + 40 * index))
        profiles.append(_profile(name, sexo, deporte, nivel))
    return takes, profiles


def _prepare(takes: list[dict], profiles: list[dict]) -> pd.DataFrame:
    return _prepare_jump_df(pd.DataFrame(takes), profile_df=pd.DataFrame(profiles))


class OneTakePerAthleteTests(unittest.TestCase):
    def test_cohort_size_counts_athletes_and_four_takes_count_once(self):
        takes, profiles = _team(8)
        # El atleta 00 tiene 4 tomas: aporta solo la ultima.
        for day, height in ((1, 50.0), (2, 51.0), (3, 52.0)):
            takes.append(_take("M 00", f"2026-10-0{day}", DJ_cm=height, DJ_tc_ms=200.0, DJ_drop_height_cm=30.0))
        prepared = _prepare(takes, profiles)
        latest = prepared[(prepared["Athlete"] == "M 01")].iloc[-1]
        self.assertEqual(int(latest["DJ_height_Z_cohort_n"]), 8)
        info = parse_reference(latest["DJ_height_Z_reference_source"])
        self.assertEqual(info["size"], 8)
        self.assertEqual(len(info["athletes"]), 8)
        values = [30.0 + index for index in range(8)]  # M 00 entra con su ultima toma (30.0, 10/10)
        expected = (31.0 - np.mean(values)) / np.std(values, ddof=1)
        self.assertAlmostEqual(float(latest["DJ_height_Z"]), round(expected, 2), places=2)

    def test_twelve_month_window(self):
        takes, profiles = _team(8)
        takes.append(_take("M 00", "2025-06-01", DJ_cm=10.0, DJ_tc_ms=300.0, DJ_drop_height_cm=30.0))
        prepared = _prepare(takes, profiles)
        old = prepared[prepared["Date"] == pd.Timestamp("2025-06-01")].iloc[0]
        info = parse_reference(old["DJ_height_Z_reference_source"])
        # La toma de hace mas de 12 meses se puntua contra la referencia, pero
        # no la integra.
        self.assertTrue(pd.notna(old["DJ_height_Z"]))
        self.assertEqual(info["date_min"], "10/10/2026")


class NoIntraIndividualTests(unittest.TestCase):
    def test_own_series_never_gives_radar_z(self):
        takes = [_take("Solo", f"2026-10-0{day}", DJ_cm=30.0 + day, DJ_tc_ms=210.0, DJ_drop_height_cm=30.0)
                 for day in (1, 2, 3, 4)]
        prepared = _prepare(takes, [_profile("Solo")])
        self.assertTrue(prepared["DJ_height_Z"].isna().all())
        self.assertFalse(prepared["DJ_height_Z_source"].eq(str(ZSource.INTRA_INDIVIDUAL)).any())
        self.assertEqual(radar_axis_values(prepared.iloc[-1])["axes"], [])

    def test_lorenzo_two_takes_no_longer_plus_minus_one(self):
        # Lorenzo / Florencia Romano Coll: 2 tomas, antes z = +/-1 siempre.
        takes = [_take("Nicolas Lorenzo", "2026-05-18", DJ_cm=30.0, DJ_tc_ms=210.0, DJ_drop_height_cm=30.0),
                 _take("Nicolas Lorenzo", "2026-09-28", DJ_cm=33.0, DJ_tc_ms=205.0, DJ_drop_height_cm=30.0)]
        prepared = _prepare(takes, [])
        self.assertTrue(prepared["DJ_height_Z"].isna().all())


class LadderTests(unittest.TestCase):
    def test_sport_level_first(self):
        takes, profiles = _team(8)
        prepared = _prepare(takes, profiles)
        info = parse_reference(prepared.iloc[0]["DJ_height_Z_reference_source"])
        self.assertEqual(info["level"], LEVEL_SPORT)

    def test_demand_group_when_sport_is_small(self):
        football, football_profiles = _team(4, prefix="F")
        handball, handball_profiles = _team(4, deporte="Handball", prefix="H", base=40.0)
        prepared = _prepare(football + handball, football_profiles + handball_profiles)
        info = parse_reference(prepared.iloc[0]["DJ_height_Z_reference_source"])
        self.assertEqual(info["level"], LEVEL_DEMAND)
        self.assertEqual(info["size"], 8)

    def test_sex_level_when_groups_are_small(self):
        football, fp = _team(4, prefix="F")
        tennis, tp = _team(4, deporte="Tenis", prefix="T", base=40.0)
        prepared = _prepare(football + tennis, fp + tp)
        info = parse_reference(prepared.iloc[0]["DJ_height_Z_reference_source"])
        self.assertEqual(info["level"], LEVEL_SEX)

    def test_five_to_seven_gives_percentile_never_z(self):
        takes, profiles = _team(6)
        prepared = _prepare(takes, profiles)
        row = prepared[prepared["Athlete"] == "M 05"].iloc[-1]
        self.assertTrue(pd.isna(row["DJ_height_Z"]))
        self.assertEqual(row["DJ_height_Z_source"], str(ZSource.COHORT_RANK))
        self.assertEqual(float(row["DJ_height_Z_percentile"]), 100.0)
        self.assertEqual(int(row["DJ_height_Z_cohort_n"]), 6)
        payload = radar_axis_values(row)
        self.assertEqual(payload["mode"], RADAR_MODE_PERCENTILE)
        self.assertTrue(all(0 <= value <= 100 for value in payload["values"]))
        self.assertIn("percentiles", radar_reference_caption(row))

    def test_fewer_than_five_no_radar(self):
        takes, profiles = _team(4)
        prepared = _prepare(takes, profiles)
        row = prepared.iloc[0]
        self.assertTrue(pd.isna(row["DJ_height_Z"]))
        self.assertTrue(pd.isna(row["DJ_height_Z_percentile"]))
        self.assertEqual(radar_axis_values(row)["axes"], [])
        self.assertIn("todavía no hay grupo de comparación", radar_reference_caption(row))

    def test_never_mixes_sexes(self):
        men, mp = _team(10, prefix="M")
        women, wp = _team(4, sexo="Femenino", prefix="W", base=25.0)
        prepared = _prepare(men + women, mp + wp)
        woman = prepared[prepared["Athlete"] == "W 00"].iloc[-1]
        self.assertTrue(pd.isna(woman["DJ_height_Z"]))
        man = prepared[prepared["Athlete"] == "M 00"].iloc[-1]
        info = parse_reference(man["DJ_height_Z_reference_source"])
        self.assertTrue(all(name.startswith("M ") for name in info["athletes"]))

    def test_without_sex_no_group(self):
        takes, profiles = _team(9)
        profiles[0]["Sexo"] = None
        prepared = _prepare(takes, profiles)
        row = prepared[prepared["Athlete"] == "M 00"].iloc[-1]
        self.assertTrue(pd.isna(row["DJ_height_Z"]))


class EraTests(unittest.TestCase):
    def test_era_dependent_metrics(self):
        for metric in ("IMTP_N", "IMTP_relPF", "IMTP_rfd_50_N_s", "CMJ_cm", "SJ_cm", "CMJ_peak_power_W", "CMJ_RSI", "EUR"):
            self.assertTrue(is_era_dependent(metric), metric)
        for metric in ("CMJ_ft_cm", "SJ_ft_cm", "DJ_cm", "DJ_RSI", "DJ_tc_ms", "CMJ_flight_ms", "CMJ_peak_force_N"):
            self.assertFalse(is_era_dependent(metric), metric)

    def test_era_from_date(self):
        self.assertEqual(era_from_date("2025-12-24"), ERA_VALKYRIA_NO_STRAPS)
        self.assertEqual(era_from_date("2026-01-29"), ERA_VALKYRIA_STRAPS)
        self.assertEqual(era_from_date("2026-09-30"), ERA_VALKYRIA_STRAPS)
        self.assertEqual(era_from_date("2026-10-01"), ERA_INVOLUTION_STRAPS)

    def test_imtp_cohort_never_mixes_eras_but_flight_heights_do(self):
        old, op = _team(5, prefix="V", device=ERA_VALKYRIA_STRAPS, date="2026-05-10")
        new, np_ = _team(5, prefix="I", base=34.0, device=ERA_INVOLUTION_STRAPS)
        prepared = _prepare(old + new, op + np_)
        row = prepared[prepared["Athlete"] == "I 00"].iloc[-1]
        # IMTP relativo: solo 5 en la era Involution -> percentil, sin z.
        self.assertTrue(pd.isna(row["IMTP_relPF_Z"]))
        imtp_info = parse_reference(row["IMTP_relPF_Z_reference_source"])
        self.assertEqual(imtp_info["era"], ERA_INVOLUTION_STRAPS)
        self.assertTrue(all(name.startswith("I ") for name in imtp_info["athletes"]))
        # DJ (vuelo): las dos eras juntas -> 10 atletas, z.
        dj_info = parse_reference(row["DJ_height_Z_reference_source"])
        self.assertEqual(dj_info["size"], 10)
        self.assertEqual(dj_info["era"], "todas")
        self.assertTrue(pd.notna(row["DJ_height_Z"]))

    def test_ignacio_imtp_not_comparable_but_flight_cmj_is(self):
        # Ignacio De La Vega: 20/05/2026 (Valkyria con straps) -> 08/10/2026 (Involution).
        history = _prepare_jump_df(pd.DataFrame([
            _take("Ignacio De La Vega", "2026-05-20", device=ERA_VALKYRIA_STRAPS, BW_kg=87.0,
                  CMJ_cm=41.1, CMJ_flight_ms=570, IMTP_N=3235.0),
            _take("Ignacio De La Vega", "2026-10-08", device=ERA_INVOLUTION_STRAPS, BW_kg=87.45,
                  CMJ_cm=46.04, CMJ_flight_ms=614, IMTP_N=3491.17),
        ]))
        changes = compute_evaluation_changes(history).set_index("Variable")
        self.assertEqual(changes.loc["IMTP_N", "Signal"], ERA_CHANGE_SIGNAL)
        self.assertEqual(changes.loc["IMTP_relPF", "Signal"], ERA_CHANGE_SIGNAL)
        self.assertEqual(changes.loc["CMJ_cm", "Signal"], ERA_CHANGE_SIGNAL)
        flight = changes.loc["CMJ_ft_cm"]
        self.assertAlmostEqual(float(flight["Valor_anterior"]), 39.8, places=1)
        self.assertAlmostEqual(float(flight["Valor_actual"]), 46.2, places=1)
        self.assertEqual(flight["Signal"], "mejora relevante")
        texts = [item["text"] for item in ar.evaluation_achievements(changes.reset_index(), "atleta")]
        self.assertFalse(any("IMTP" in text for text in texts))
        self.assertTrue(any(text.startswith("Salto CMJ (por tiempo de vuelo): 39.8 cm → 46.2 cm") for text in texts))

    def test_profe_change_table_says_software_protocol(self):
        from modules.jump_analysis import build_jump_delta_display_table

        history = _prepare_jump_df(pd.DataFrame([
            _take("A", "2026-05-20", device=ERA_VALKYRIA_STRAPS, IMTP_N=3235.0),
            _take("A", "2026-10-08", device=ERA_INVOLUTION_STRAPS, IMTP_N=3491.0),
        ]))
        table = build_jump_delta_display_table(compute_evaluation_changes(history)).set_index("Variable")
        self.assertIn("no comparable: cambio de software/protocolo", table.loc["IMTP", "Senal"])


class DemandGroupTests(unittest.TestCase):
    def test_map(self):
        cases = {
            "Fútbol": DEMAND_TEAM, "Handball": DEMAND_TEAM, "Hockey sobre césped": DEMAND_TEAM,
            "Rugby": DEMAND_TEAM, "Básquet": DEMAND_TEAM, "Vóley": DEMAND_TEAM,
            "Tenis": DEMAND_RACKET_COMBAT, "Pádel": DEMAND_RACKET_COMBAT, "Taekwondo": DEMAND_RACKET_COMBAT,
            "Boxeo": DEMAND_RACKET_COMBAT, "Running": DEMAND_ENDURANCE, "Trail Running": DEMAND_ENDURANCE,
            "Ciclismo": DEMAND_ENDURANCE, "Bicicleta": DEMAND_ENDURANCE, "Natación": DEMAND_ENDURANCE,
            "Halterofilia": DEMAND_STRENGTH_POWER, "Lanzamientos": DEMAND_STRENGTH_POWER,
            "Saltos": DEMAND_STRENGTH_POWER, None: DEMAND_GENERAL, "Ballet": DEMAND_GENERAL,
        }
        for sport, group in cases.items():
            with self.subTest(sport=sport):
                self.assertEqual(demand_group(sport), group)

    def test_composite_sports_take_the_first(self):
        self.assertEqual(primary_deporte("Futbol/ padel"), "Fútbol")
        self.assertEqual(primary_deporte("Futbol y Ballet acuático"), "Fútbol")
        self.assertEqual(primary_deporte("Taekwondo y Calistenia"), "Taekwondo")
        self.assertEqual(demand_group("Taekwondo y Calistenia"), DEMAND_RACKET_COMBAT)


class LiteratureTests(unittest.TestCase):
    def test_tables_are_valid(self):
        self.assertEqual(validate_reference_tables(), [])
        bad = ({"metric": "IMTP_relPF", "deporte": "x", "nivel": "x", "sexo": "Masculino", "instrument_class": "platform",
                "mean": 1, "sd": 1, "n": 1, "source": "x", "eras": (), "nivel_uso": "z"},)
        self.assertTrue(any("normalizacion" in error for error in validate_reference_tables(bad)))

    def test_mcmahon_mrsi(self):
        entries = [entry for entry in REFERENCE_TABLES if entry["metric"] == "CMJ_RSI"]
        self.assertEqual({(e["subgroup"], e["mean"], e["sd"], e["n"]) for e in entries},
                         {("forwards", 0.44, 0.08, 66), ("backs", 0.49, 0.08, 55)})
        self.assertTrue(all("10.3390/s22228669" in str(e["source"]) for e in entries))

    def test_era_must_be_compatible(self):
        kwargs = dict(deporte="Rugby League", nivel="Alto rendimiento", sexo="Masculino", use="z")
        self.assertIsNotNone(lookup_reference("CMJ_RSI", era=ERA_INVOLUTION_STRAPS, **kwargs))
        self.assertIsNone(lookup_reference("CMJ_RSI", era=ERA_VALKYRIA_STRAPS, **kwargs))

    def test_higher_level_is_context_only(self):
        # Burgos (rugby recreativo): McMahon es contexto, nunca z.
        self.assertIsNone(lookup_reference("CMJ_RSI", deporte="Rugby", nivel="Recreativo", sexo="Masculino",
                                           era=ERA_INVOLUTION_STRAPS, use="z"))
        self.assertEqual(len(context_references("CMJ_RSI", deporte="Rugby", sexo="Masculino")), 2)


class FormTests(unittest.TestCase):
    def test_sex_is_required_without_profile(self):
        self.assertFalse(evaluation_sexo_check(None, "Agustin Giffon", "Usar el del perfil")["ok"])
        result = evaluation_sexo_check(None, "Agustin Giffon", "Masculino")
        self.assertTrue(result["ok"])
        self.assertTrue(result["save"])

    def test_profile_sex_is_enough(self):
        profiles = pd.DataFrame([_profile("Ana", "Femenino")])
        result = evaluation_sexo_check(profiles, "Ana", "Usar el del perfil")
        self.assertTrue(result["ok"])
        self.assertFalse(result["save"])

    def test_device_is_persisted(self):
        from modules.data_loader import EVALUATION_DB_COLUMN_MAP, EVALUATION_PERSIST_COLUMNS

        self.assertEqual(EVALUATION_DB_COLUMN_MAP["Device"], "device")
        self.assertIn("Device", EVALUATION_PERSIST_COLUMNS)


class CaptionTests(unittest.TestCase):
    def test_caption_names_level_era_n_and_dates(self):
        takes, profiles = _team(8)
        prepared = _prepare(takes, profiles)
        caption = radar_reference_caption(prepared.iloc[0])
        self.assertIn("cohorte deporte + nivel + sexo", caption)
        self.assertIn("8 atletas", caption)
        self.assertIn("tomas de 10/10/2026 a 10/10/2026", caption)


if __name__ == "__main__":
    unittest.main()
