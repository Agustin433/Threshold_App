"""Referencia de los z-scores: contra quien se compara cada toma.

Reglas (PR C):

1. Una toma por atleta. La referencia de una metrica toma, de cada atleta del
   grupo, su ultima toma valida de los ultimos 12 meses, dentro de la misma
   fuente y la misma era de medicion. El atleta evaluado entra con esa misma
   toma. `cohort_size` = atletas (no filas) con dato valido.
2. Las tomas historicas se puntuan contra la referencia de su propia era.
3. Escalera, en orden:
   literatura (deporte + nivel + sexo + instrumento + era compatible)
   -> cohorte Deporte+Nivel+Sexo (>= 8 atletas)
   -> Grupo de demanda + Sexo (>= 8)
   -> Sexo (>= 8)
   -> percentil si 5-7 atletas (posicion entre N, nunca z)
   -> < 5: sin grupo de comparacion (sin radar).
   Nunca se mezclan sexos ni eras. Sin sexo no hay grupo.
4. La serie propia del atleta (INTRA_INDIVIDUAL) no produce z de radar: la
   comparacion consigo mismo vive en "Lo que lograste" y en la tabla de
   cambios, con umbral max(TE, SWC).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from modules.athlete_profile import (
    DEMAND_GROUP_LABELS,
    NIVEL_OPTIONS,
    Sexo,
    demand_group,
    normalize_sexo,
    primary_deporte,
)
from modules.evaluation_sources import MIN_COHORT_RANK_SIZE, MIN_COHORT_SIZE, DEFAULT_SOURCE, normalize_source
from modules.measurement_eras import era_label, era_series, is_era_dependent, metric_era
from modules.zscore_sources import ZSource, lookup_reference

REFERENCE_WINDOW_DAYS = 365

LEVEL_LITERATURE = "literatura"
LEVEL_SPORT = "deporte_nivel_sexo"
LEVEL_DEMAND = "grupo_sexo"
LEVEL_SEX = "sexo"
LEVEL_NONE = "sin_grupo"

LEVEL_ORDER = (LEVEL_SPORT, LEVEL_DEMAND, LEVEL_SEX)

NO_GROUP_TEXT = "todavía no hay grupo de comparación"


@dataclass(frozen=True)
class AthleteKey:
    sexo: Sexo
    deporte: str | None
    nivel: str | None
    grupo: str

    def level_key(self, level: str) -> tuple[object, ...] | None:
        if self.sexo is Sexo.NO_ESPECIFICADO:
            return None
        if level == LEVEL_SPORT:
            if not self.deporte or not self.nivel:
                return None
            return (self.sexo, self.deporte, self.nivel)
        if level == LEVEL_DEMAND:
            return (self.sexo, self.grupo)
        if level == LEVEL_SEX:
            return (self.sexo,)
        return None


@dataclass
class Reference:
    level: str
    era: str
    source: str
    members: dict[str, float] = field(default_factory=dict)
    member_dates: dict[str, pd.Timestamp] = field(default_factory=dict)
    mean: float | None = None
    sd: float | None = None
    literature: dict[str, object] | None = None

    @property
    def size(self) -> int:
        return len(self.members)

    def describe(self, *, sexo: Sexo | None = None, key: AthleteKey | None = None) -> str:
        """'nivel|era|n|fecha_min|fecha_max|atletas' para viajar en el frame."""
        dates = list(self.member_dates.values())
        dmin = min(dates).strftime("%d/%m/%Y") if dates else ""
        dmax = max(dates).strftime("%d/%m/%Y") if dates else ""
        names = ";".join(sorted(self.members))
        return "|".join([self.level, self.era, str(self.size), dmin, dmax, names])


def parse_reference(text: object) -> dict[str, object] | None:
    raw = str(text or "")
    if not raw or raw.lower() == "nan":
        return None
    parts = raw.split("|")
    if len(parts) < 6:
        return None
    level, era, size, dmin, dmax, names = parts[:6]
    return {
        "level": level,
        "era": era,
        "size": int(size or 0),
        "date_min": dmin,
        "date_max": dmax,
        "athletes": [name for name in names.split(";") if name],
    }


LEVEL_LABELS = {
    LEVEL_LITERATURE: "referencia publicada",
    LEVEL_SPORT: "cohorte deporte + nivel + sexo",
    LEVEL_DEMAND: "cohorte grupo de demanda + sexo",
    LEVEL_SEX: "cohorte por sexo",
    LEVEL_NONE: "sin grupo de comparación",
}


def reference_caption(info: dict[str, object] | None) -> str:
    """'Referencia: <escalon>, era <device>, N atletas, tomas de <min> a <max>'."""
    if not info:
        return f"Referencia: {NO_GROUP_TEXT}."
    level = LEVEL_LABELS.get(str(info.get("level")), str(info.get("level")))
    return (
        f"Referencia: {level}, era {era_label(info.get('era'))}, {info.get('size')} atletas, "
        f"tomas de {info.get('date_min')} a {info.get('date_max')}."
    )


def athlete_key(profile: dict[str, object] | None) -> AthleteKey:
    profile = profile or {}
    nivel = str(profile.get("Nivel") or "").strip()
    nivel = nivel if nivel in NIVEL_OPTIONS else None
    deporte_raw = profile.get("Deporte")
    return AthleteKey(
        sexo=normalize_sexo(profile.get("Sexo")),
        deporte=primary_deporte(deporte_raw),
        nivel=nivel,
        grupo=demand_group(deporte_raw),
    )


class ReferenceEngine:
    """Resuelve, por metrica, la referencia de cada toma de un frame preparado."""

    def __init__(self, frame: pd.DataFrame, profile_lookup: dict[str, dict[str, object]] | None):
        self.frame = frame
        self.keys = {name: athlete_key(profile) for name, profile in (profile_lookup or {}).items()}
        self.athletes = frame["Athlete"].astype(str).str.strip() if "Athlete" in frame.columns else pd.Series("", index=frame.index)
        self.dates = pd.to_datetime(frame["Date"], errors="coerce") if "Date" in frame.columns else pd.Series(pd.NaT, index=frame.index)
        self.sources = (
            frame["Source"].map(normalize_source) if "Source" in frame.columns else pd.Series(DEFAULT_SOURCE, index=frame.index)
        )
        self.eras = era_series(frame) if not frame.empty else pd.Series(dtype=object)
        self._cache: dict[tuple[object, ...], Reference] = {}

    def _pool(self, values: pd.Series, era: str, source: str, metric: str) -> pd.DataFrame:
        partition = values.notna() & (self.sources == source)
        if is_era_dependent(metric):
            partition &= self.eras == era
        pool = pd.DataFrame(
            {"athlete": self.athletes[partition], "date": self.dates[partition], "value": values[partition]}
        )
        return pool.dropna(subset=["date"])

    def reference(self, metric: str, values: pd.Series, *, level: str, key: tuple[object, ...], era: str, source: str) -> Reference:
        cache_key = (metric, level, key, era, source)
        if cache_key in self._cache:
            return self._cache[cache_key]
        pool = self._pool(values, era, source, metric)
        ref = Reference(level=level, era=metric_era(metric, era), source=source)
        if not pool.empty:
            anchor = pool["date"].max()
            pool = pool[pool["date"] >= anchor - pd.Timedelta(days=REFERENCE_WINDOW_DAYS)]
            for athlete, athlete_rows in pool.sort_values("date").groupby("athlete"):
                athlete_key_value = self.keys.get(athlete)
                if athlete_key_value is None or athlete_key_value.level_key(level) != key:
                    continue
                last = athlete_rows.iloc[-1]
                ref.members[athlete] = float(last["value"])
                ref.member_dates[athlete] = pd.Timestamp(last["date"])
        if ref.size >= 2:
            member_values = np.array(list(ref.members.values()), dtype=float)
            ref.mean = float(member_values.mean())
            ref.sd = float(member_values.std(ddof=1))
        self._cache[cache_key] = ref
        return ref

    def resolve(self, metric: str, *, invert: bool = False) -> pd.DataFrame:
        """z, origen, percentil, rango, n y descripcion de la referencia por fila."""
        values = pd.to_numeric(self.frame[metric], errors="coerce") if metric in self.frame.columns else pd.Series(np.nan, index=self.frame.index)
        out = pd.DataFrame(
            {
                "z": np.nan,
                "origin": str(ZSource.REFERENCE_BAND),
                "percentile": np.nan,
                "rank": pd.Series(pd.NA, index=self.frame.index, dtype="Int64"),
                "cohort_n": pd.Series(pd.NA, index=self.frame.index, dtype="Int64"),
                "reference": "",
            },
            index=self.frame.index,
        )
        for idx in self.frame.index:
            value = values.at[idx]
            if pd.isna(value):
                continue
            athlete = self.athletes.at[idx]
            key = self.keys.get(athlete)
            if key is None or key.sexo is Sexo.NO_ESPECIFICADO:
                continue
            source = self.sources.at[idx]
            era = self.eras.at[idx]
            profile_era = metric_era(metric, era)

            literature = lookup_reference(
                metric,
                deporte=key.deporte,
                nivel=key.nivel,
                sexo=key.sexo,
                instrument_class=source,
                era=profile_era,
                use="z",
            )
            if literature is not None:
                raw = (float(value) - float(literature["mean"])) / float(literature["sd"])
                out.at[idx, "z"] = -raw if invert else raw
                out.at[idx, "origin"] = str(ZSource.LITERATURE_Z)
                out.at[idx, "cohort_n"] = int(literature.get("n") or 0)
                out.at[idx, "reference"] = "|".join(
                    [LEVEL_LITERATURE, profile_era, str(literature.get("n") or 0), "", "", str(literature.get("source") or "")]
                )
                continue

            chosen: Reference | None = None
            for level in LEVEL_ORDER:
                level_key = key.level_key(level)
                if level_key is None:
                    continue
                ref = self.reference(metric, values, level=level, key=level_key, era=era, source=source)
                if ref.size >= MIN_COHORT_SIZE and ref.sd:
                    chosen = ref
                    break
            if chosen is not None:
                raw = (float(value) - float(chosen.mean)) / float(chosen.sd)
                out.at[idx, "z"] = -raw if invert else raw
                out.at[idx, "origin"] = str(ZSource.COHORT_Z)
                out.at[idx, "cohort_n"] = chosen.size
                out.at[idx, "reference"] = chosen.describe()
                continue

            broad_key = key.level_key(LEVEL_SEX)
            broad = self.reference(metric, values, level=LEVEL_SEX, key=broad_key, era=era, source=source)
            if MIN_COHORT_RANK_SIZE <= broad.size < MIN_COHORT_SIZE:
                others = [v for name, v in broad.members.items() if name != athlete]
                n = len(others) + 1
                below = sum(1 for v in others if v < float(value))
                above = sum(1 for v in others if v > float(value))
                pct = 100.0 * below / (n - 1) if n > 1 else 50.0
                out.at[idx, "percentile"] = round(100.0 - pct if invert else pct, 1)
                out.at[idx, "rank"] = (below + 1) if invert else (above + 1)
                out.at[idx, "origin"] = str(ZSource.COHORT_RANK)
                out.at[idx, "cohort_n"] = n
                out.at[idx, "reference"] = broad.describe()
        return out


def level_label(level: object) -> str:
    return LEVEL_LABELS.get(str(level), str(level))


def demand_label(group: object) -> str:
    return DEMAND_GROUP_LABELS.get(str(group), str(group))


def z_interval(z: object, n: object) -> tuple[float, float] | None:
    """Intervalo aproximado del z por la incertidumbre del SD de la cohorte.

    SE(SD) ~ SD / sqrt(2(n-1)) (aproximacion normal). Con SD +/- SE(SD) el
    mismo valor da z / (1 + k) y z / (1 - k), con k = 1 / sqrt(2(n-1)). No
    incluye la incertidumbre de la media ni el error tipico de la medicion.
    """
    try:
        z_value = float(z)
        n_value = int(n)
    except (TypeError, ValueError):
        return None
    if np.isnan(z_value) or n_value < 3:
        return None
    k = 1.0 / np.sqrt(2.0 * (n_value - 1))
    low, high = z_value / (1.0 + k), z_value / (1.0 - k)
    return (min(low, high), max(low, high))


def format_z_with_interval(z: object, n: object) -> str:
    """'+1.0 (0.8 a 1.3), n=9'. Un decimal: con n chico mas decimales serian ruido."""
    try:
        z_value = float(z)
    except (TypeError, ValueError):
        return "—"
    if np.isnan(z_value):
        return "—"
    interval = z_interval(z_value, n)
    if interval is None:
        return f"{z_value:+.1f}"
    low, high = interval
    return f"{z_value:+.1f} ({low:.1f} a {high:.1f}), n={int(n)}"
