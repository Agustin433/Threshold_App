"""Shared load monitoring calculations."""

from __future__ import annotations

import unicodedata

import numpy as np
import pandas as pd

from modules.data_loader import raw_session_date_column
from modules.metrics import calculate_monotony

ACWR_ZONES = (
    (0.00, 0.80, "Subcarga", "#4A9FD4"),
    (0.80, 1.30, "Optimo", "#4FC97E"),
    (1.30, 1.50, "Precaucion", "#E8C84A"),
    (1.50, 9.99, "Alto riesgo", "#D94F4F"),
)

# Etiquetas acentuadas para superficies de lectura (PDF, narrativa). Las claves
# son las canonicas sin acento, que son las que viajan en los DataFrames y
# contra las que filtran los paneles.
ACWR_ZONE_DISPLAY_LABELS = {
    "Subcarga": "Subcarga",
    "Optimo": "Óptimo",
    "Precaucion": "Precaución",
    "Alto riesgo": "Alto riesgo",
    "Sin datos": "Sin datos",
}

# Constantes de suavizado EWMA segun Williams et al. (2017): lambda = 2/(N+1).
# Se derivan de la ventana en dias en vez de hardcodear el alpha, para que la
# ventana quede explicita y no vuelvan a divergir entre superficies.
ACWR_ACUTE_DAYS = 7
ACWR_CHRONIC_DAYS = 28
ACWR_ACUTE_ALPHA = 2 / (ACWR_ACUTE_DAYS + 1)
ACWR_CHRONIC_ALPHA = 2 / (ACWR_CHRONIC_DAYS + 1)

MONOTONY_HIGH = 2.0
ACWR_CONTEXT_DEFAULT_WEEKS = 16
ACWR_SPIKE_THRESHOLD_PCT = 50.0
ACWR_CONTEXT_COLUMNS = [
    "Athlete",
    "week_start",
    "is_current_week",
    "weekly_sRPE",
    "weekly_sRPE_model",
    "sessions_count",
    "sessions_done",
    "sessions_missing",
    "missing_frac_acute",
    "missing_frac_chronic",
    "chronic_4w",
    "chronic_weeks",
    "acwr_rolling_1_4",
    "acwr_rolling_ma4",
    "weekly_change_pct",
    "spike_flag",
    "context_status",
    "ACWR_EWMA_last",
    "monotony",
    "strain",
]


def _classify_acwr(value: float) -> str:
    """Zona de ACWR con limite superior inclusivo.

    El rango operativo de referencia es 0.80-1.30 *inclusive*, asi que un ACWR
    de exactamente 1.30 es "Optimo" y no "Precaucion". Antes esta funcion usaba
    `lower <= value < upper`, lo que la dejaba como la unica superficie de la
    app que clasificaba 1.30 como precaucion.
    """
    if pd.isna(value):
        return "Sin datos"
    if value < 0.80:
        return "Subcarga"
    if value <= 1.30:
        return "Optimo"
    if value <= 1.50:
        return "Precaucion"
    return "Alto riesgo"


_ACWR_ZONE_COLORS = {label: color for _, _, label, color in ACWR_ZONES}

# Nombre publico: cualquier superficie que necesite clasificar un ACWR debe
# usar este, nunca reimplementar los umbrales.
classify_acwr_zone = _classify_acwr


def _acwr_color(value: float) -> str:
    if pd.isna(value):
        return "#5A6A7A"
    return _ACWR_ZONE_COLORS.get(_classify_acwr(value), "#D94F4F")


# --- Calidad del dato para ACWR ------------------------------------------
# Un dia sin sRPE puede ser descanso (carga 0 real) o una sesion entrenada que
# el atleta no reporto (dato faltante). El modelo anterior trataba ambos como
# 0, lo que deprime la carga cronica y produce ACWR ~1 "Optimo" a partir de
# dos numeros chicos (auditoria externa, oct/2026; ver Williams 2017 y Lolli
# 2019 sobre sensibilidad del ACWR a la serie de entrada). Cuando hay un
# registro de sesiones realizadas (Raw Workouts), los dias entrenados sin
# sRPE se marcan como faltantes en vez de 0.
DAY_STATUS_LOGGED = "registrado"
DAY_STATUS_MISSING = "sin_registro"
DAY_STATUS_REST = "descanso"

ACWR_STATUS_OK = "ok"
ACWR_STATUS_INCOMPLETE = "registro_incompleto"
ACWR_STATUS_SHORT_HISTORY = "historial_insuficiente"
ACWR_STATUS_NO_CHRONIC = "sin_carga_cronica"

# Con la ventana cronica sin llenar, el EWMA (adjust=False) arranca en el
# primer valor y el ACWR da exactamente 1.0 el primer dia: zona "Optimo" por
# construccion, no por carga.
ACWR_MIN_HISTORY_DAYS = ACWR_CHRONIC_DAYS
# Fraccion maxima de sesiones entrenadas sin sRPE tolerada en cada ventana.
# Por encima, el ACWR depende mas de los huecos (o de la imputacion) que de
# la carga reportada y no se emite.
ACWR_MAX_MISSING_FRAC_CHRONIC = 0.30
ACWR_MAX_MISSING_FRAC_ACUTE = 0.34
# Monotonia (Foster) de una semana con sesiones sin reportar: la SD semanal
# queda dominada por los ceros falsos, no por la variabilidad real.
MONOTONY_MAX_MISSING_FRAC = 0.34


def athlete_match_key(value: object) -> str:
    """Clave de cruce entre exports: sin tildes, espacios repetidos ni mayusculas.

    El RPE y el Raw Workouts vienen de exports distintos; "Díaz" vs "Diaz"
    haria que el registro de sesiones no matchee en silencio (y el ACWR y la
    cobertura volverian a tratar las sesiones sin sRPE como descanso).
    """
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", " ".join(str(value).strip().split()))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def training_dates_by_athlete(raw_df: pd.DataFrame | None) -> dict[str, pd.DatetimeIndex]:
    """Fechas con sesion realizada por atleta (clave `athlete_match_key`), segun Raw Workouts.

    Es el registro independiente que permite distinguir un dia de descanso de
    una sesion entrenada sin sRPE. Supone que el export de Raw Workouts solo
    trae series efectivamente registradas (los bloques "No Exercises Completed
    Yet" se descartan al parsear).
    """
    if raw_df is None or raw_df.empty:
        return {}
    athlete_col = "Athlete" if "Athlete" in raw_df.columns else "Name" if "Name" in raw_df.columns else None
    # Dia en que la sesion se hizo, no el asignado: con la fecha asignada,
    # solo el 59% de los dias con sRPE caia en un dia "entrenado" del export
    # real (91% con la fecha completada) y el modelo inventaba faltantes.
    date_col = raw_session_date_column(raw_df)
    if athlete_col is None or date_col is None:
        return {}
    ledger = pd.DataFrame(
        {
            "key": raw_df[athlete_col].map(athlete_match_key),
            "Date": pd.to_datetime(raw_df[date_col], errors="coerce").dt.normalize(),
        }
    ).dropna()
    ledger = ledger[ledger["key"] != ""]
    return {
        key: pd.DatetimeIndex(group["Date"].unique()).sort_values()
        for key, group in ledger.groupby("key")
    }


def training_dates_for_athlete(raw_df: pd.DataFrame | None, athlete: object) -> pd.DatetimeIndex | None:
    return training_dates_by_athlete(raw_df).get(athlete_match_key(athlete))


def _normalized_training_dates(training_dates) -> pd.DatetimeIndex:
    if training_dates is None:
        return pd.DatetimeIndex([])
    values = pd.to_datetime(pd.Series(list(training_dates)), errors="coerce").dropna()
    if values.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(values.dt.normalize().unique()).sort_values()


def _rolling_logged_median(logged: pd.Series, window: int) -> pd.Series:
    """Mediana movil de las sesiones REPORTADAS (sRPE>0) de los dias previos.

    Se usa solo para imputar sesiones entrenadas sin sRPE. Toma la mediana
    individual del propio atleta (no del grupo) y excluye el dia actual para
    no imputar un dia con un valor que depende de si mismo.
    """
    sessions_only = logged.where(logged > 0)
    trailing = sessions_only.shift(1).rolling(window, min_periods=1).median()
    expanding = sessions_only.shift(1).expanding(min_periods=1).median()
    return trailing.fillna(expanding)


def calc_acwr(
    srpe_series: pd.Series,
    dates: pd.DatetimeIndex,
    training_dates=None,
) -> pd.DataFrame:
    """Serie diaria canonica de ACWR EWMA usada en toda la app.

    `training_dates` (opcional) son las fechas con sesion realizada segun un
    registro independiente del sRPE (Raw Workouts). Con ese registro:

    - dia con sRPE           -> "registrado"
    - dia entrenado sin sRPE -> "sin_registro" (faltante, NO 0)
    - dia sin ninguno de los dos -> "descanso" (0 real)

    `sRPE_diario` conserva solo la carga reportada (faltantes y descansos en
    0), igual que antes, para que totales semanales y conteos de sesiones no
    mezclen carga inventada. El EWMA usa `sRPE_modelo`, donde cada faltante se
    imputa con la mediana individual de sus sesiones reportadas de los 28 dias
    previos. El ACWR solo se emite (`ACWR_Estado == "ok"`) si el historial
    llena la ventana cronica y la fraccion de faltantes en las ventanas
    aguda y cronica esta bajo umbral; si no, queda NaN y zona "Sin datos".

    Sin `training_dates` no hay forma de distinguir descanso de faltante: los
    dias sin sRPE se tratan como descanso y el gate de faltantes no actua.
    """
    raw = pd.Series(pd.to_numeric(pd.Series(srpe_series).values, errors="coerce"), index=pd.DatetimeIndex(dates).normalize())
    # sRPE <= 0 no es un reporte de sesion (suele ser RPE o duracion vacios
    # que dieron 0): se trata como dia sin reporte, no como carga 0 reportada.
    raw = raw[raw > 0]
    logged_by_day = raw.groupby(raw.index).sum().sort_index()
    trained = _normalized_training_dates(training_dates)

    if logged_by_day.empty:
        start = trained.min() if len(trained) else None
    else:
        start = logged_by_day.index.min()
    if start is None:
        return pd.DataFrame(
            columns=[
                "Date", "sRPE_diario", "Dia_Estado", "sRPE_modelo", "sRPE_imputado",
                "Aguda_7d", "Cronica_28d", "ACWR_Classic", "EWMA_Aguda", "EWMA_Cronica",
                "Sesiones_7d", "Sesiones_28d",
                "Faltantes_7d", "Faltantes_28d", "Frac_faltante_7d", "Frac_faltante_28d",
                "Dias_historial", "ACWR_EWMA", "ACWR_Estado", "ACWR", "Zona", "Zona_Color",
            ]
        )
    end_candidates = [logged_by_day.index.max()] if not logged_by_day.empty else []
    trained = trained[trained >= start]
    if len(trained):
        end_candidates.append(trained.max())
    end = max(end_candidates)
    calendar = pd.date_range(start, end, freq="D")

    logged = logged_by_day.reindex(calendar)
    has_log = logged.notna()
    is_trained = pd.Series(calendar.isin(trained), index=calendar)
    status = pd.Series(DAY_STATUS_REST, index=calendar, dtype=object)
    status[has_log] = DAY_STATUS_LOGGED
    status[~has_log & is_trained] = DAY_STATUS_MISSING
    is_missing = status.eq(DAY_STATUS_MISSING)

    logged_filled = logged.fillna(0.0)
    imputation = _rolling_logged_median(logged_filled, ACWR_CHRONIC_DAYS)
    model_load = logged_filled.copy()
    model_load[is_missing] = imputation[is_missing]
    # Un faltante sin ninguna sesion reportada previa no se puede imputar; se
    # deja en 0 para el EWMA, pero el gate de faltantes ya lo marca.
    model_load = model_load.fillna(0.0)

    result = pd.DataFrame(
        {
            "Date": calendar,
            "sRPE_diario": logged_filled.to_numpy(dtype=float),
            "Dia_Estado": status.to_numpy(),
            "sRPE_modelo": model_load.to_numpy(dtype=float),
            "sRPE_imputado": is_missing.to_numpy(dtype=bool),
        }
    )
    result["Aguda_7d"] = result["sRPE_modelo"].rolling(7, min_periods=1).mean()
    result["Cronica_28d"] = result["sRPE_modelo"].rolling(28, min_periods=1).mean()
    # DEPRECATED: kept only as a legacy reference for historical inspection.
    result["ACWR_Classic"] = np.where(
        result["Cronica_28d"] > 0,
        result["Aguda_7d"] / result["Cronica_28d"].where(result["Cronica_28d"] > 0),
        np.nan,
    )

    # Williams et al. 2017. Antes se usaban 0.28 y 0.07, que no corresponden a
    # ninguna ventana entera: implicaban ~6.1 y ~27.6 dias en vez de 7 y 28.
    result["EWMA_Aguda"] = result["sRPE_modelo"].ewm(alpha=ACWR_ACUTE_ALPHA, adjust=False).mean()
    result["EWMA_Cronica"] = result["sRPE_modelo"].ewm(alpha=ACWR_CHRONIC_ALPHA, adjust=False).mean()

    missing_int = is_missing.astype(int).reset_index(drop=True)
    trained_int = status.isin([DAY_STATUS_LOGGED, DAY_STATUS_MISSING]).astype(int).reset_index(drop=True)
    result["Faltantes_7d"] = missing_int.rolling(ACWR_ACUTE_DAYS, min_periods=1).sum().astype(int)
    result["Faltantes_28d"] = missing_int.rolling(ACWR_CHRONIC_DAYS, min_periods=1).sum().astype(int)
    trained_7 = trained_int.rolling(ACWR_ACUTE_DAYS, min_periods=1).sum()
    trained_28 = trained_int.rolling(ACWR_CHRONIC_DAYS, min_periods=1).sum()
    result["Sesiones_7d"] = trained_7.astype(int)
    result["Sesiones_28d"] = trained_28.astype(int)
    result["Frac_faltante_7d"] = (result["Faltantes_7d"] / trained_7.where(trained_7 > 0)).fillna(0.0)
    result["Frac_faltante_28d"] = (result["Faltantes_28d"] / trained_28.where(trained_28 > 0)).fillna(0.0)
    result["Dias_historial"] = np.arange(1, len(result) + 1)

    ratio = result["EWMA_Aguda"] / result["EWMA_Cronica"].where(result["EWMA_Cronica"] > 0)
    acwr_status = pd.Series(ACWR_STATUS_OK, index=result.index, dtype=object)
    acwr_status[ratio.isna()] = ACWR_STATUS_NO_CHRONIC
    acwr_status[result["Dias_historial"] < ACWR_MIN_HISTORY_DAYS] = ACWR_STATUS_SHORT_HISTORY
    incomplete = (result["Frac_faltante_28d"] > ACWR_MAX_MISSING_FRAC_CHRONIC) | (
        result["Frac_faltante_7d"] > ACWR_MAX_MISSING_FRAC_ACUTE
    )
    acwr_status[incomplete & acwr_status.eq(ACWR_STATUS_OK)] = ACWR_STATUS_INCOMPLETE
    result["ACWR_EWMA"] = ratio.where(acwr_status.eq(ACWR_STATUS_OK))
    result["ACWR_Estado"] = acwr_status

    result["ACWR"] = result["ACWR_EWMA"]
    result["Zona"] = result["ACWR"].apply(_classify_acwr)
    result["Zona_Color"] = result["ACWR"].apply(_acwr_color)
    return result


def latest_training_day_row(acwr_df: pd.DataFrame | None) -> pd.DataFrame:
    """Fila del ultimo dia entrenado (reportado o no) de un frame de `calc_acwr`.

    Antes cada superficie tomaba el ultimo dia con sRPE>0: un atleta que
    entrena pero dejo de reportar quedaba mostrando para siempre el ACWR de su
    ultimo registro. Frames sin `Dia_Estado` (viejos o armados a mano) siguen
    usando la regla anterior.
    """
    if acwr_df is None or acwr_df.empty:
        return pd.DataFrame()
    if "Dia_Estado" in acwr_df.columns:
        return acwr_df[acwr_df["Dia_Estado"].ne(DAY_STATUS_REST)].tail(1)
    if "sRPE_diario" not in acwr_df.columns:
        return acwr_df.tail(1)
    return acwr_df[pd.to_numeric(acwr_df["sRPE_diario"], errors="coerce") > 0].tail(1)


def acwr_unavailable_reason(row: pd.Series | None) -> str:
    """Motivo legible de un ACWR no emitido; "" si el ACWR es valido."""
    if row is None:
        return ""
    status = str(row.get("ACWR_Estado") or "").strip()
    if not status or status == ACWR_STATUS_OK:
        return ""
    if status == ACWR_STATUS_INCOMPLETE:
        missing = pd.to_numeric(pd.Series([row.get("Faltantes_28d")]), errors="coerce").iloc[0]
        sessions = pd.to_numeric(pd.Series([row.get("Sesiones_28d")]), errors="coerce").iloc[0]
        if pd.notna(missing) and pd.notna(sessions):
            return f"{int(missing)} de {int(sessions)} sesiones sin sRPE en 28 días"
        return "sesiones entrenadas sin sRPE"
    if status == ACWR_STATUS_SHORT_HISTORY:
        days = pd.to_numeric(pd.Series([row.get("Dias_historial")]), errors="coerce").iloc[0]
        if pd.notna(days):
            return f"historial de {int(days)} de {ACWR_MIN_HISTORY_DAYS} días"
        return "historial insuficiente"
    return "sin carga crónica"


def _calendar_week_loads(series: pd.Series, week_end: pd.Timestamp) -> pd.Series:
    end = pd.Timestamp(week_end).normalize()
    start = end - pd.Timedelta(days=6)
    loads = series.copy()
    loads.index = pd.to_datetime(loads.index, errors="coerce").normalize()
    loads = loads.dropna()
    scoped = loads.loc[(loads.index >= start) & (loads.index <= end)]
    if not scoped.empty:
        scoped = scoped.groupby(scoped.index).sum()
    return scoped.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)


def calc_monotony_strain(srpe_daily: pd.DataFrame) -> pd.DataFrame:
    """Weekly monotony and strain according to Foster."""
    daily = srpe_daily.copy()
    daily["Date"] = pd.to_datetime(daily["Date"], errors="coerce").dt.normalize()
    daily["sRPE_diario"] = pd.to_numeric(daily["sRPE_diario"], errors="coerce")
    daily = daily.dropna(subset=["Date", "sRPE_diario"])
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "Semana",
                "Carga_Total",
                "Media",
                "SD",
                "Monotonia",
                "Monotony_Status",
                "Monotony_Warning",
                "Strain",
                "Alerta",
            ]
        )

    series = daily.groupby("Date")["sRPE_diario"].sum().sort_index()
    weekly = series.resample("W").agg(["sum", "mean"]).reset_index()
    weekly.columns = ["Semana", "Carga_Total", "Media"]
    calendar_loads_by_week = {week: _calendar_week_loads(series, week) for week, _ in series.resample("W")}
    weekly["Media"] = weekly["Semana"].map(lambda week: float(calendar_loads_by_week[week].mean()))
    weekly["SD"] = weekly["Semana"].map(lambda week: float(calendar_loads_by_week[week].std(ddof=0)))
    monotony_by_week = {week: calculate_monotony(loads) for week, loads in calendar_loads_by_week.items()}
    weekly["Monotonia"] = weekly["Semana"].map(lambda week: monotony_by_week[week].value)
    weekly["Monotony_Status"] = weekly["Semana"].map(lambda week: monotony_by_week[week].method)
    weekly["Monotony_Warning"] = weekly["Semana"].map(lambda week: monotony_by_week[week].warning)
    weekly["Monotonia"] = pd.to_numeric(weekly["Monotonia"], errors="coerce")
    if "Dia_Estado" in srpe_daily.columns:
        status = srpe_daily[["Date", "Dia_Estado"]].copy()
        status["Date"] = pd.to_datetime(status["Date"], errors="coerce").dt.normalize()
        status = status.dropna(subset=["Date"]).set_index("Date")["Dia_Estado"]
        missing_by_week = status.eq(DAY_STATUS_MISSING).resample("W").sum()
        trained_by_week = status.isin([DAY_STATUS_LOGGED, DAY_STATUS_MISSING]).resample("W").sum()
        missing_frac = (missing_by_week / trained_by_week.where(trained_by_week > 0)).fillna(0.0)
        weekly["Sesiones_sin_registro"] = weekly["Semana"].map(missing_by_week).fillna(0).astype(int)
        incomplete_weeks = weekly["Semana"].map(missing_frac).fillna(0.0) > MONOTONY_MAX_MISSING_FRAC
        # .mask() arma columnas nuevas en lugar de escribir in-place con .loc:
        # con pandas 3 (copy-on-write) las columnas creadas con .map pueden
        # quedar respaldadas por arrays de solo lectura y .loc[...] = ... falla
        # con "Cannot modify read-only array".
        weekly["Monotonia"] = weekly["Monotonia"].mask(incomplete_weeks, np.nan)
        weekly["Monotony_Status"] = weekly["Monotony_Status"].mask(incomplete_weeks, "incomplete_log")
        weekly["Monotony_Warning"] = weekly["Monotony_Warning"].mask(incomplete_weeks, "sesiones_sin_registro")
    weekly["Strain"] = np.where(
        weekly["Monotony_Status"].eq("standard"),
        weekly["Carga_Total"] * weekly["Monotonia"],
        np.nan,
    )
    weekly["Alerta"] = weekly["Monotonia"].gt(MONOTONY_HIGH).fillna(False)
    return weekly


WEEKLY_COMPARISON_COLUMNS = [
    "Athlete",
    "weekly_sRPE",
    "weekly_sRPE_prev",
    "load_model",
    "load_model_prev",
    "sessions_count",
    "sessions_done",
    "sessions_missing",
    "missing_frac",
    "missing_frac_prev",
    "comparable",
    "delta_sRPE",
    "delta_pct",
]


def _weekly_session_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["weekly_sRPE"] = pd.to_numeric(result.get("weekly_sRPE"), errors="coerce").fillna(0.0)
    reported = pd.to_numeric(result.get("sessions_count"), errors="coerce").fillna(0.0) if "sessions_count" in result.columns else pd.Series(0.0, index=result.index)
    result["sessions_count"] = reported
    result["sessions_done"] = (
        pd.to_numeric(result["sessions_done"], errors="coerce").fillna(reported) if "sessions_done" in result.columns else reported
    )
    result["sessions_missing"] = (
        pd.to_numeric(result["sessions_missing"], errors="coerce").fillna(0.0) if "sessions_missing" in result.columns else 0.0
    )
    result["load_model"] = (
        pd.to_numeric(result["weekly_sRPE_model"], errors="coerce").fillna(result["weekly_sRPE"])
        if "weekly_sRPE_model" in result.columns
        else result["weekly_sRPE"]
    )
    result["missing_frac"] = (result["sessions_missing"] / result["sessions_done"].where(result["sessions_done"] > 0)).fillna(0.0)
    return result


def compare_weekly_load(current_load: pd.DataFrame | None, previous_load: pd.DataFrame | None) -> pd.DataFrame:
    """Comparacion por atleta de una semana contra la anterior (consecutiva).

    Usa la carga del modelo (reportada + sesiones sin sRPE imputadas) y marca
    `comparable=False` cuando cualquiera de las dos semanas tiene sesiones
    sin sRPE por encima de ACWR_MAX_MISSING_FRAC_ACUTE: ahi la diferencia
    mide huecos de reporte, no carga, y `delta_sRPE`/`delta_pct` quedan NaN.
    Un atleta sin fila la semana anterior no entreno esa semana (las
    semanas entrenadas sin sRPE se conservan en el resumen semanal), asi
    que su carga previa es 0 real y la comparacion es valida.
    """
    if current_load is None or current_load.empty or "Athlete" not in current_load.columns:
        return pd.DataFrame(columns=WEEKLY_COMPARISON_COLUMNS)
    current = _weekly_session_columns(current_load)
    if previous_load is not None and not previous_load.empty and "Athlete" in previous_load.columns:
        previous = _weekly_session_columns(previous_load)[["Athlete", "weekly_sRPE", "load_model", "missing_frac"]].rename(
            columns={"weekly_sRPE": "weekly_sRPE_prev", "load_model": "load_model_prev", "missing_frac": "missing_frac_prev"}
        )
        result = current.merge(previous, on="Athlete", how="left")
    else:
        result = current.assign(weekly_sRPE_prev=np.nan, load_model_prev=np.nan, missing_frac_prev=np.nan)
    result["weekly_sRPE_prev"] = result["weekly_sRPE_prev"].fillna(0.0)
    result["load_model_prev"] = result["load_model_prev"].fillna(0.0)
    result["missing_frac_prev"] = result["missing_frac_prev"].fillna(0.0)
    result["missing_frac_prev"] = pd.to_numeric(result["missing_frac_prev"], errors="coerce").fillna(0.0)
    result["comparable"] = (
        (result["missing_frac"] <= ACWR_MAX_MISSING_FRAC_ACUTE) & (result["missing_frac_prev"] <= ACWR_MAX_MISSING_FRAC_ACUTE)
    ).astype(bool)
    delta = result["load_model"] - result["load_model_prev"]
    result["delta_sRPE"] = delta.where(result["comparable"])
    result["delta_pct"] = (delta / result["load_model_prev"].where(result["load_model_prev"] > 0) * 100.0).where(
        result["comparable"]
    )
    return result[[*WEEKLY_COMPARISON_COLUMNS, *[c for c in result.columns if c not in WEEKLY_COMPARISON_COLUMNS]]]


def build_weekly_acwr_context(
    weekly_load_df: pd.DataFrame | None,
    athlete: str | None = None,
    *,
    weeks: int | None = ACWR_CONTEXT_DEFAULT_WEEKS,
    spike_threshold_pct: float = ACWR_SPIKE_THRESHOLD_PCT,
) -> pd.DataFrame:
    """Build uncoupled weekly ACWR context from canonical weekly load.

    The chronic load is the mean of the previous four weekly loads, so the
    current week never appears in its own denominator.
    """
    if weekly_load_df is None or weekly_load_df.empty:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)
    required_cols = {"Athlete", "week_start", "weekly_sRPE"}
    if not required_cols.issubset(weekly_load_df.columns):
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    source = weekly_load_df.copy()
    source["Athlete"] = source["Athlete"].astype(str).str.strip()
    source["week_start"] = pd.to_datetime(source["week_start"], errors="coerce").dt.normalize()
    source["weekly_sRPE"] = pd.to_numeric(source["weekly_sRPE"], errors="coerce")
    source = source.dropna(subset=["Athlete", "week_start", "weekly_sRPE"])
    if athlete and athlete != "Todos":
        source = source[source["Athlete"].eq(str(athlete).strip())]
    if source.empty:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    for column in ["sessions_count", "ACWR_EWMA_last", "monotony", "strain"]:
        if column in source.columns:
            source[column] = pd.to_numeric(source[column], errors="coerce")
        else:
            source[column] = np.nan
    # Sin registro de sesiones (frames viejos o armados a mano) la semana
    # cuenta como completamente reportada, igual que antes.
    if "sessions_done" in source.columns:
        source["sessions_done"] = pd.to_numeric(source["sessions_done"], errors="coerce").fillna(source["sessions_count"])
    else:
        source["sessions_done"] = source["sessions_count"]
    source["sessions_missing"] = (
        pd.to_numeric(source["sessions_missing"], errors="coerce").fillna(0.0)
        if "sessions_missing" in source.columns
        else 0.0
    )
    source["weekly_sRPE_model"] = (
        pd.to_numeric(source["weekly_sRPE_model"], errors="coerce").fillna(source["weekly_sRPE"])
        if "weekly_sRPE_model" in source.columns
        else source["weekly_sRPE"]
    )
    if "is_current_week" not in source.columns:
        source["is_current_week"] = False
    source["is_current_week"] = source["is_current_week"].fillna(False).astype(bool)

    rows: list[pd.DataFrame] = []
    for athlete_name, athlete_df in source.sort_values("week_start").groupby("Athlete", sort=True):
        athlete_df = athlete_df.sort_values("week_start").reset_index(drop=True)
        # El cociente usa la carga del modelo (reportada + sesiones sin sRPE
        # imputadas con la mediana individual). La carga reportada sola hacia
        # que una semana con sesiones sin reportar pareciera una descarga.
        load = athlete_df["weekly_sRPE_model"].astype(float)
        chronic = load.shift(1).rolling(4, min_periods=1).mean()
        chronic_weeks = load.shift(1).rolling(4, min_periods=1).count()
        done = athlete_df["sessions_done"].astype(float)
        missing = athlete_df["sessions_missing"].astype(float)
        acute_missing_frac = (missing / done.where(done > 0)).fillna(0.0)
        chronic_done = done.shift(1).rolling(4, min_periods=1).sum()
        chronic_missing = missing.shift(1).rolling(4, min_periods=1).sum()
        chronic_missing_frac = (chronic_missing / chronic_done.where(chronic_done > 0)).fillna(0.0)
        incomplete = (acute_missing_frac > ACWR_MAX_MISSING_FRAC_ACUTE) | (
            chronic_missing_frac > ACWR_MAX_MISSING_FRAC_CHRONIC
        )
        athlete_df["missing_frac_acute"] = acute_missing_frac
        athlete_df["missing_frac_chronic"] = chronic_missing_frac
        athlete_df["chronic_4w"] = chronic
        athlete_df["chronic_weeks"] = chronic_weeks.astype("Int64")
        acwr = pd.Series(np.where(chronic.gt(0), load / chronic, np.nan), index=athlete_df.index)
        athlete_df["acwr_rolling_1_4"] = acwr.where(~incomplete)
        # La media movil promedia solo semanas validas, pero no se muestra en
        # una semana incompleta: ahi taparia el ACWR no emitido.
        athlete_df["acwr_rolling_ma4"] = (
            pd.Series(athlete_df["acwr_rolling_1_4"])
            .rolling(4, min_periods=1)
            .mean()
            .where(~incomplete)
            .to_numpy()
        )
        previous_load = load.shift(1)
        # La variacion semanal compara dos semanas: si cualquiera de las dos
        # tiene sesiones sin sRPE por encima del umbral, el % mide huecos.
        change_incomplete = (acute_missing_frac > ACWR_MAX_MISSING_FRAC_ACUTE) | (
            acute_missing_frac.shift(1).fillna(0.0) > ACWR_MAX_MISSING_FRAC_ACUTE
        )
        athlete_df["weekly_change_pct"] = pd.Series(
            np.where(
                previous_load.gt(0),
                ((load - previous_load) / previous_load) * 100.0,
                np.nan,
            ),
            index=athlete_df.index,
        ).where(~change_incomplete)
        athlete_df["spike_flag"] = athlete_df["weekly_change_pct"].ge(spike_threshold_pct).fillna(False)
        athlete_df["context_status"] = np.select(
            [
                athlete_df["chronic_weeks"].fillna(0).eq(0),
                athlete_df["chronic_4w"].fillna(0).le(0),
                incomplete,
                athlete_df["chronic_weeks"].fillna(0).lt(4),
            ],
            ["insufficient_history", "invalid_chronic", "incomplete_log", "limited_history"],
            default="standard",
        )
        athlete_df["Athlete"] = athlete_name
        rows.append(athlete_df)

    if not rows:
        return pd.DataFrame(columns=ACWR_CONTEXT_COLUMNS)

    result = pd.concat(rows, ignore_index=True, sort=False)
    result = result.sort_values(["Athlete", "week_start"]).reset_index(drop=True)
    if weeks is not None and weeks > 0:
        result = (
            result.groupby("Athlete", group_keys=False)
            .tail(int(weeks))
            .reset_index(drop=True)
        )

    for column in ACWR_CONTEXT_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan
    return result[ACWR_CONTEXT_COLUMNS]
