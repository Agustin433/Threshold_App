"""Cuadrante Fuerza vs Explosividad del gimnasio (IMTP vs CMJ por vuelo).

Un mapa del gimnasio con meta: todos apuntan a "Completo". No es una norma
de literatura: las metas son del gimnasio, por sexo, editables por el profe.

- Eje X: IMTP relativo bruto (N/kg), ultima toma disponible, en % de la meta.
- Eje Y: CMJ por tiempo de vuelo (cm), ultima toma valida, en % de la meta.
- Metas por defecto: CMJ varones 40 cm, mujeres 30 cm. IMTP: mediana actual
  de la era vigente por sexo (una toma por atleta), rotulada "provisoria";
  sin datos en la era vigente para un sexo, la meta queda sin definir.
- Metas configuradas: historial con fecha de cambio (CSV local + Supabase,
  tabla dataset_rows, dataset_key "quadrant_goals"); vale la ultima.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from modules.athlete_profile import Sexo, normalize_sexo
from modules.measurement_eras import CURRENT_ERA, era_series

METRIC_IMTP = "IMTP_relPF"
METRIC_CMJ = "CMJ_ft_cm"
METRIC_LABELS = {METRIC_IMTP: "IMTP relativo", METRIC_CMJ: "CMJ por vuelo"}
METRIC_UNITS = {METRIC_IMTP: "N/kg", METRIC_CMJ: "cm"}
DEFAULT_CMJ_GOALS = {Sexo.MASCULINO: 40.0, Sexo.FEMENINO: 30.0}
SEXES = (Sexo.MASCULINO, Sexo.FEMENINO)
SEX_SHORT = {Sexo.MASCULINO: "varones", Sexo.FEMENINO: "mujeres"}

GOAL_SOURCE_DEFAULT = "por defecto"
GOAL_SOURCE_PROVISIONAL = "provisoria"
GOAL_SOURCE_CONFIGURED = "configurada"
GOAL_SOURCE_UNDEFINED = "sin definir"

STALE_WEEKS = 12
PREVIOUS_PROTOCOL_TEXT = "protocolo anterior"
STALE_TEXT = "más de 12 semanas"
PROFESSIONAL_PROTOCOL_NOTE = "con el protocolo anterior el IMTP suele dar más bajo (~30%); posición orientativa"

QUADRANT_COMPLETE = "Completo"
QUADRANT_STRONG = "Fuerte - falta explosividad"
QUADRANT_EXPLOSIVE = "Explosivo - falta fuerza"
QUADRANT_BASE = "Base"
WHAT_TO_WORK = {
    QUADRANT_BASE: "Fuerza primero: es la base para todo lo demás.",
    QUADRANT_EXPLOSIVE: "Fuerza máxima: tu salto ya está en la meta; la fuerza lo va a sostener y potenciar.",
    QUADRANT_STRONG: "Potencia, pliometría y balística: tenés la fuerza, falta expresarla rápido.",
    QUADRANT_COMPLETE: "Mantener y transferir al deporte.",
}

AGE_GROUPS = ("<18", "18-29", "30-44", "45+")
AGE_UNKNOWN = "edad sin cargar"

GOALS_DATASET_KEY = "quadrant_goals"
GOALS_FILENAME = "quadrant_goals.csv"
GOALS_COLUMNS = ["Sexo", "Metrica", "Meta", "Fecha_cambio"]


# ── Metas ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Goal:
    sexo: Sexo
    metric: str
    value: float | None
    source: str
    changed_at: pd.Timestamp | None = None
    n: int = 0

    @property
    def defined(self) -> bool:
        return self.value is not None and self.value > 0

    def label(self) -> str:
        unit = METRIC_UNITS[self.metric]
        if not self.defined:
            return f"{METRIC_LABELS[self.metric]} {SEX_SHORT[self.sexo]}: sin definir"
        text = f"{METRIC_LABELS[self.metric]} {SEX_SHORT[self.sexo]} {self.value:.1f} {unit}"
        if self.source == GOAL_SOURCE_PROVISIONAL:
            text += " (provisoria)"
        elif self.source == GOAL_SOURCE_CONFIGURED and self.changed_at is not None:
            text += f" (desde {self.changed_at:%d/%m/%Y})"
        return text


def _latest_per_athlete(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=["Athlete", "Date", "value", "era"])
    data = frame.copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    data["value"] = pd.to_numeric(data[column], errors="coerce")
    data["era"] = era_series(data)
    data = data.dropna(subset=["Date", "value"]).sort_values("Date")
    return data.groupby("Athlete", as_index=False).last()[["Athlete", "Date", "value", "era"]]


def provisional_imtp_goal(jump_df: pd.DataFrame | None, sexes: dict[str, Sexo], sexo: Sexo) -> tuple[float | None, int]:
    """Mediana de la ultima IMTP relativa por atleta en la era vigente, por sexo."""
    latest = _latest_per_athlete(jump_df, METRIC_IMTP)
    if latest.empty:
        return None, 0
    latest = latest[(latest["era"] == CURRENT_ERA) & (latest["Athlete"].map(sexes) == sexo)]
    if latest.empty:
        return None, 0
    return float(latest["value"].median()), int(len(latest))


def current_goals(
    goal_history: pd.DataFrame | None,
    jump_df: pd.DataFrame | None,
    sexes: dict[str, Sexo],
) -> dict[tuple[Sexo, str], Goal]:
    """Meta vigente por (sexo, metrica): la ultima configurada o la de por defecto."""
    goals: dict[tuple[Sexo, str], Goal] = {}
    for sexo in SEXES:
        goals[(sexo, METRIC_CMJ)] = Goal(sexo, METRIC_CMJ, DEFAULT_CMJ_GOALS[sexo], GOAL_SOURCE_DEFAULT)
        value, n = provisional_imtp_goal(jump_df, sexes, sexo)
        goals[(sexo, METRIC_IMTP)] = Goal(
            sexo, METRIC_IMTP, value, GOAL_SOURCE_PROVISIONAL if value is not None else GOAL_SOURCE_UNDEFINED, n=n
        )
    if goal_history is not None and not goal_history.empty and set(GOALS_COLUMNS).issubset(goal_history.columns):
        history = goal_history.copy()
        history["Fecha_cambio"] = pd.to_datetime(history["Fecha_cambio"], errors="coerce")
        history["Meta"] = pd.to_numeric(history["Meta"], errors="coerce")
        history = history.dropna(subset=["Fecha_cambio", "Meta"]).sort_values("Fecha_cambio")
        for _, row in history.iterrows():
            sexo = normalize_sexo(row["Sexo"])
            metric = str(row["Metrica"])
            if sexo in SEXES and metric in METRIC_LABELS and float(row["Meta"]) > 0:
                goals[(sexo, metric)] = Goal(
                    sexo, metric, float(row["Meta"]), GOAL_SOURCE_CONFIGURED, pd.Timestamp(row["Fecha_cambio"])
                )
    return goals


def goals_legend_lines(goals: dict[tuple[Sexo, str], Goal]) -> list[str]:
    """Una linea por metrica: 'CMJ por vuelo: varones 40.0 cm · mujeres 30.0 cm'."""
    lines = []
    for metric in (METRIC_CMJ, METRIC_IMTP):
        parts = []
        for sexo in SEXES:
            goal = goals[(sexo, metric)]
            if not goal.defined:
                parts.append(f"{SEX_SHORT[sexo]} sin definir")
                continue
            text = f"{SEX_SHORT[sexo]} {goal.value:.1f} {METRIC_UNITS[metric]}"
            if goal.source == GOAL_SOURCE_PROVISIONAL:
                text += " (provisoria)"
            elif goal.source == GOAL_SOURCE_CONFIGURED and goal.changed_at is not None:
                text += f" (desde {goal.changed_at:%d/%m/%Y})"
            parts.append(text)
        lines.append(f"{METRIC_LABELS[metric]}: " + " · ".join(parts))
    return lines


def goals_legend(goals: dict[tuple[Sexo, str], Goal]) -> str:
    return "Metas — " + " | ".join(goals_legend_lines(goals))


def short_name(athlete: str) -> str:
    """'Ignacio De La Vega' -> 'Ignacio D.' (rotulo corto en el grafico)."""
    parts = str(athlete).split()
    if len(parts) < 2:
        return str(athlete)
    return f"{parts[0]} {parts[1][0]}."


# ── Persistencia de metas (CSV local + Supabase) ────────────────────────────
def goals_path(store_dir: Path | None = None) -> Path:
    if store_dir is None:
        from local_store import STORE_DIR

        store_dir = STORE_DIR
    return Path(store_dir) / GOALS_FILENAME


def load_goal_history(store_dir: Path | None = None) -> pd.DataFrame:
    """Historial de metas: local, y si Supabase esta habilitado, union con el remoto."""
    path = goals_path(store_dir)
    local = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=GOALS_COLUMNS)
    remote = pd.DataFrame(columns=GOALS_COLUMNS)
    try:
        from modules.remote_store import load_remote_quadrant_goals

        remote = load_remote_quadrant_goals()
    except Exception:
        remote = pd.DataFrame(columns=GOALS_COLUMNS)
    merged = pd.concat([local, remote], ignore_index=True, sort=False).reindex(columns=GOALS_COLUMNS)
    if merged.empty:
        return merged
    return merged.drop_duplicates(subset=["Sexo", "Metrica", "Fecha_cambio"]).reset_index(drop=True)


def goal_row_key(row: dict[str, object]) -> str:
    key = {column: str(row.get(column)) for column in ("Sexo", "Metrica", "Fecha_cambio")}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()


def save_goal(
    sexo: object,
    metric: str,
    value: float,
    *,
    changed_at: object | None = None,
    store_dir: Path | None = None,
    remote: bool = True,
) -> dict[str, object]:
    """Agrega una meta al historial (nunca pisa las anteriores) y la sube a Supabase."""
    sexo_value = normalize_sexo(sexo)
    if sexo_value not in SEXES:
        raise ValueError("La meta necesita sexo (Masculino o Femenino).")
    if metric not in METRIC_LABELS:
        raise ValueError(f"Métrica desconocida: {metric}")
    if value is None or float(value) <= 0:
        raise ValueError("La meta tiene que ser mayor que 0.")
    if changed_at is None:
        from modules.app_clock import app_now

        changed_at = app_now()
    row = {
        "Sexo": str(sexo_value),
        "Metrica": metric,
        "Meta": round(float(value), 2),
        "Fecha_cambio": pd.Timestamp(changed_at).isoformat(timespec="seconds"),
    }
    path = goals_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=GOALS_COLUMNS)
    pd.concat([existing, pd.DataFrame([row])], ignore_index=True).reindex(columns=GOALS_COLUMNS).to_csv(path, index=False)
    remote_result: dict[str, object] = {"enabled": False, "upserted": 0}
    if remote:
        from modules.remote_store import save_remote_quadrant_goal

        remote_result = save_remote_quadrant_goal(row, row_key=goal_row_key(row))
    return {"row": row, "remote": remote_result}


# ── Ubicacion de cada atleta ────────────────────────────────────────────────
def age_group(birth_date: object, today: object) -> str:
    birth = pd.to_datetime(birth_date, errors="coerce")
    if pd.isna(birth):
        return AGE_UNKNOWN
    now = pd.Timestamp(today)
    age = now.year - birth.year - ((now.month, now.day) < (birth.month, birth.day))
    if age < 18:
        return "<18"
    if age < 30:
        return "18-29"
    if age < 45:
        return "30-44"
    return "45+"


def quadrant_of(pct_imtp: float, pct_cmj: float) -> str:
    strong = pct_imtp >= 100.0
    explosive = pct_cmj >= 100.0
    if strong and explosive:
        return QUADRANT_COMPLETE
    if strong:
        return QUADRANT_STRONG
    if explosive:
        return QUADRANT_EXPLOSIVE
    return QUADRANT_BASE


@dataclass
class Placement:
    athlete: str
    sexo: Sexo
    pct_imtp: float
    pct_cmj: float
    imtp: float
    cmj: float
    imtp_date: pd.Timestamp
    cmj_date: pd.Timestamp
    imtp_era: str
    cmj_era: str
    age_group: str
    previous_protocol: bool = False
    stale: bool = False
    quadrant: str = ""
    history: list["Placement"] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.previous_protocol or self.stale

    @property
    def evaluation_date(self) -> pd.Timestamp:
        return min(self.imtp_date, self.cmj_date)

    def note(self, professional: bool = False) -> str | None:
        """'Evaluación 22/05/2026 · protocolo anterior' (+ aclaracion para el profe)."""
        if not self.flagged:
            return None
        parts = [f"Evaluación {self.evaluation_date:%d/%m/%Y}"]
        if self.previous_protocol:
            parts.append(PREVIOUS_PROTOCOL_TEXT)
        if self.stale:
            parts.append(STALE_TEXT)
        text = " · ".join(parts)
        if professional and self.previous_protocol:
            text += f" — {PROFESSIONAL_PROTOCOL_NOTE}"
        return text

    @property
    def crosses_protocol(self) -> bool:
        """El recorrido (ubicacion anterior -> actual) cruza eras de medicion."""
        if not self.history:
            return False
        previous = self.history[-1]
        return previous.imtp_era != self.imtp_era or previous.cmj_era != self.cmj_era


@dataclass
class QuadrantMap:
    placements: list[Placement]
    unplaced: list[tuple[str, str]]
    goals: dict[tuple[Sexo, str], Goal]
    legend: str

    @property
    def legend_lines(self) -> list[str]:
        return goals_legend_lines(self.goals)


def _placement_at(
    athlete: str,
    rows: pd.DataFrame,
    sexo: Sexo,
    goals: dict[tuple[Sexo, str], Goal],
    today: pd.Timestamp,
    age: str,
) -> Placement | None:
    imtp = rows.dropna(subset=["imtp"])
    cmj = rows.dropna(subset=["cmj"])
    if imtp.empty or cmj.empty:
        return None
    imtp_row, cmj_row = imtp.iloc[-1], cmj.iloc[-1]
    imtp_goal, cmj_goal = goals[(sexo, METRIC_IMTP)], goals[(sexo, METRIC_CMJ)]
    placement = Placement(
        athlete=athlete,
        sexo=sexo,
        pct_imtp=round(float(imtp_row["imtp"]) / float(imtp_goal.value) * 100.0, 1),
        pct_cmj=round(float(cmj_row["cmj"]) / float(cmj_goal.value) * 100.0, 1),
        imtp=float(imtp_row["imtp"]),
        cmj=float(cmj_row["cmj"]),
        imtp_date=pd.Timestamp(imtp_row["Date"]),
        cmj_date=pd.Timestamp(cmj_row["Date"]),
        imtp_era=str(imtp_row["era"]),
        cmj_era=str(cmj_row["era"]),
        age_group=age,
    )
    placement.previous_protocol = placement.imtp_era != CURRENT_ERA or placement.cmj_era != CURRENT_ERA
    placement.stale = placement.evaluation_date < today - pd.Timedelta(weeks=STALE_WEEKS)
    placement.quadrant = quadrant_of(placement.pct_imtp, placement.pct_cmj)
    return placement


def build_quadrant_map(
    jump_df: pd.DataFrame | None,
    profile_df: pd.DataFrame | None,
    *,
    today: object,
    goal_history: pd.DataFrame | None = None,
) -> QuadrantMap:
    """Ubica a todos los atletas con evaluacion (los que tienen sexo y meta)."""
    today_ts = pd.Timestamp(today).normalize()
    profiles = profile_df if profile_df is not None and not profile_df.empty else pd.DataFrame(columns=["Athlete"])
    sexes = {
        str(name).strip(): normalize_sexo(sexo)
        for name, sexo in zip(profiles.get("Athlete", []), profiles.get("Sexo", []))
    }
    births = {str(name).strip(): birth for name, birth in zip(profiles.get("Athlete", []), profiles.get("Fecha_nacimiento", []))}
    goals = current_goals(goal_history, jump_df, sexes)
    placements: list[Placement] = []
    unplaced: list[tuple[str, str]] = []
    if jump_df is None or jump_df.empty or "Athlete" not in jump_df.columns:
        return QuadrantMap(placements, unplaced, goals, goals_legend(goals))

    data = jump_df.copy()
    data["Athlete"] = data["Athlete"].astype(str).str.strip()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    data["imtp"] = pd.to_numeric(data.get(METRIC_IMTP), errors="coerce") if METRIC_IMTP in data.columns else float("nan")
    data["cmj"] = pd.to_numeric(data.get(METRIC_CMJ), errors="coerce") if METRIC_CMJ in data.columns else float("nan")
    data["era"] = era_series(data)
    data = data.dropna(subset=["Date"]).sort_values("Date")
    data = data[data["Date"] <= today_ts]

    for athlete, rows in data.groupby("Athlete", sort=True):
        if rows["imtp"].isna().all() and rows["cmj"].isna().all():
            continue
        sexo = sexes.get(athlete, Sexo.NO_ESPECIFICADO)
        if sexo not in SEXES:
            unplaced.append((athlete, "sin sexo en el perfil (no hay meta)"))
            continue
        if not goals[(sexo, METRIC_IMTP)].defined:
            unplaced.append((athlete, f"meta de IMTP {SEX_SHORT[sexo]} sin definir"))
            continue
        if rows["imtp"].isna().all() or rows["cmj"].isna().all():
            missing = "IMTP" if rows["imtp"].isna().all() else "CMJ por vuelo"
            unplaced.append((athlete, f"falta {missing}"))
            continue
        age = age_group(births.get(athlete), today_ts)
        # Una ubicacion por evaluacion (con lo ultimo disponible hasta esa fecha).
        history: list[Placement] = []
        for date in sorted(rows["Date"].unique()):
            placement = _placement_at(athlete, rows[rows["Date"] <= date], sexo, goals, today_ts, age)
            if placement is None:
                continue
            if history and (history[-1].imtp, history[-1].cmj) == (placement.imtp, placement.cmj):
                continue
            history.append(placement)
        if not history:
            continue
        current = history[-1]
        current.history = history[:-1]
        placements.append(current)
    return QuadrantMap(placements, unplaced, goals, goals_legend(goals))


def athlete_summary(quadrant_map: QuadrantMap, athlete: str) -> dict[str, str] | None:
    """Cuadrante del atleta y "que trabajar" en una frase (PDF atleta/cliente)."""
    key = str(athlete).strip().casefold()
    for placement in quadrant_map.placements:
        if placement.athlete.casefold() == key:
            return {
                "quadrant": placement.quadrant,
                "what_to_work": WHAT_TO_WORK[placement.quadrant],
                "sentence": f"Hoy estás en {placement.quadrant}. Qué trabajar: {WHAT_TO_WORK[placement.quadrant]}",
                "note": placement.note(professional=False) or "",
            }
    return None
