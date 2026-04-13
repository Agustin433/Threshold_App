"""Data quality summaries for the load monitoring workflow."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


DATASET_CONFIG = (
    ("rpe_df", "RPE + Tiempo", ("Date",)),
    ("wellness_df", "Wellness", ("Date",)),
    ("completion_df", "Completion", ("Date",)),
    ("raw_df", "Raw Workouts", ("Assigned Date", "Date")),
    ("maxes_df", "Maxes", ("Added Date", "Date")),
    ("jump_df", "Evaluaciones", ("Date",)),
)


def _reference_timestamp(reference_date=None) -> pd.Timestamp:
    if reference_date is None:
        return pd.Timestamp(datetime.now()).normalize()
    return pd.Timestamp(reference_date).normalize()


def _coerce_dates(df: pd.DataFrame | None, candidates: tuple[str, ...]) -> pd.Series:
    if df is None:
        return pd.Series(dtype="datetime64[ns]")
    for column in candidates:
        if column in df.columns:
            return pd.to_datetime(df[column], errors="coerce").dt.normalize()
    return pd.Series(index=df.index, dtype="datetime64[ns]")


def _athlete_series(df: pd.DataFrame | None) -> pd.Series:
    if df is None:
        return pd.Series(dtype=object)
    for column in ("Athlete", "Name"):
        if column in df.columns:
            return (
                df[column]
                .where(df[column].notna(), "")
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
            )
    return pd.Series(index=df.index, dtype=object)


def _format_date(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _window_bounds(reference_date=None, window_days: int = 42) -> tuple[pd.Timestamp, pd.Timestamp]:
    reference_ts = _reference_timestamp(reference_date)
    window_start = reference_ts - pd.Timedelta(days=max(window_days - 1, 0))
    return window_start, reference_ts


def _max_gap_between_dates(dates: pd.Series) -> int:
    unique_dates = sorted(pd.to_datetime(dates, errors="coerce").dropna().dt.normalize().unique().tolist())
    if len(unique_dates) < 2:
        return 0
    max_gap = 0
    for current, nxt in zip(unique_dates, unique_dates[1:]):
        gap_days = int((pd.Timestamp(nxt) - pd.Timestamp(current)).days) - 1
        max_gap = max(max_gap, max(gap_days, 0))
    return max_gap


def _longest_missing_streak(dates: pd.Series, window_start: pd.Timestamp, reference_ts: pd.Timestamp):
    normalized = sorted(pd.to_datetime(dates, errors="coerce").dropna().dt.normalize().unique().tolist())
    if not normalized:
        return None

    full_range = pd.date_range(window_start, reference_ts, freq="D")
    present = set(pd.to_datetime(normalized))
    missing = [day for day in full_range if day not in present]
    if not missing:
        return None

    best_start = missing[0]
    best_end = missing[0]
    best_len = 1
    current_start = missing[0]
    current_end = missing[0]
    current_len = 1

    for day in missing[1:]:
        if (day - current_end).days == 1:
            current_end = day
            current_len += 1
        else:
            if current_len > best_len:
                best_start, best_end, best_len = current_start, current_end, current_len
            current_start = day
            current_end = day
            current_len = 1

    if current_len > best_len:
        best_start, best_end, best_len = current_start, current_end, current_len

    if best_len <= 7:
        return None
    return best_len, best_start, best_end


def _dataset_summary_row(
    dataset_key: str,
    label: str,
    df: pd.DataFrame | None,
    date_candidates: tuple[str, ...],
    window_start: pd.Timestamp,
    reference_ts: pd.Timestamp,
) -> dict[str, object]:
    if df is None or df.empty:
        return {
            "Dataset": label,
            "Estado": "❌ vacio",
            "Filas": 0,
            "Atletas unicos": 0,
            "Fecha mas nueva": "-",
            "Fecha mas vieja": "-",
            "Dias con dato": 0,
            "Huecos (dias)": 0,
        }

    dates = _coerce_dates(df, date_candidates)
    valid_mask = dates.notna()
    valid_df = df.loc[valid_mask].copy()
    valid_dates = dates.loc[valid_mask]
    if valid_df.empty:
        return {
            "Dataset": label,
            "Estado": "❌ vacio",
            "Filas": int(len(df)),
            "Atletas unicos": int(_athlete_series(df).dropna().nunique()),
            "Fecha mas nueva": "-",
            "Fecha mas vieja": "-",
            "Dias con dato": 0,
            "Huecos (dias)": 0,
        }

    latest_date = valid_dates.max()
    window_mask = (valid_dates >= window_start) & (valid_dates <= reference_ts)
    window_df = valid_df.loc[window_mask].copy()
    window_dates = valid_dates.loc[window_mask]

    days_since_last = int((reference_ts - latest_date).days)
    if days_since_last <= 14:
        status = "✅ cargado"
    else:
        status = "⚠️ parcial"

    return {
        "Dataset": label,
        "Estado": status,
        "Filas": int(len(window_df)),
        "Atletas unicos": int(_athlete_series(window_df).dropna().nunique()),
        "Fecha mas nueva": _format_date(latest_date),
        "Fecha mas vieja": _format_date(window_dates.min() if not window_dates.empty else pd.NaT),
        "Dias con dato": int(window_dates.nunique()),
        "Huecos (dias)": int(_max_gap_between_dates(window_dates)),
    }


def _build_dataset_summary(dataset_frames: dict[str, pd.DataFrame | None], window_start: pd.Timestamp, reference_ts: pd.Timestamp) -> pd.DataFrame:
    rows = [
        _dataset_summary_row(key, label, dataset_frames.get(key), date_candidates, window_start, reference_ts)
        for key, label, date_candidates in DATASET_CONFIG
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "Dataset",
            "Estado",
            "Filas",
            "Atletas unicos",
            "Fecha mas nueva",
            "Fecha mas vieja",
            "Dias con dato",
            "Huecos (dias)",
        ],
    )


def _build_raw_category_breakdown(
    raw_df: pd.DataFrame | None,
    window_start: pd.Timestamp,
    reference_ts: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, float]]:
    columns = ["Categoria", "Filas", "% del raw"]
    summary = {
        "total_rows": 0.0,
        "classified_rows": 0.0,
        "untagged_rows": 0.0,
        "invalid_rows": 0.0,
        "classified_pct": 0.0,
        "untagged_pct": 0.0,
    }
    if raw_df is None or raw_df.empty or "stimulus_category" not in raw_df.columns:
        return pd.DataFrame(columns=columns), summary

    raw_dates = _coerce_dates(raw_df, ("Assigned Date", "Date"))
    raw_window = raw_df.loc[(raw_dates >= window_start) & (raw_dates <= reference_ts)].copy()
    if raw_window.empty:
        return pd.DataFrame(columns=columns), summary

    categories = (
        raw_window["stimulus_category"]
        .fillna("untagged")
        .astype(str)
        .str.strip()
        .replace("", "untagged")
    )
    breakdown = (
        categories.value_counts(dropna=False)
        .rename_axis("Categoria")
        .reset_index(name="Filas")
    )
    total_rows = float(len(raw_window))
    breakdown["% del raw"] = ((breakdown["Filas"] / total_rows) * 100).round(1)

    untagged_rows = float((categories == "untagged").sum())
    invalid_rows = float((categories == "invalid").sum())
    classified_rows = float(total_rows - untagged_rows - invalid_rows)
    summary = {
        "total_rows": total_rows,
        "classified_rows": classified_rows,
        "untagged_rows": untagged_rows,
        "invalid_rows": invalid_rows,
        "classified_pct": round((classified_rows / total_rows) * 100, 1) if total_rows > 0 else 0.0,
        "untagged_pct": round((untagged_rows / total_rows) * 100, 1) if total_rows > 0 else 0.0,
    }
    return breakdown[columns], summary


def _build_athlete_summary(
    rpe_df: pd.DataFrame | None,
    wellness_df: pd.DataFrame | None,
    athletes_list: list[str] | None,
    window_start: pd.Timestamp,
    reference_ts: pd.Timestamp,
    window_days: int,
) -> pd.DataFrame:
    columns = [
        "Atleta",
        "Dias con sRPE",
        "Dias con Wellness",
        "% cobertura sRPE",
        "% cobertura Wellness",
        "Ultimo sRPE",
        "Ultimo Wellness",
        "Semaforo",
    ]
    if rpe_df is None or rpe_df.empty or wellness_df is None or wellness_df.empty:
        return pd.DataFrame(columns=columns)

    athletes = [athlete for athlete in (athletes_list or []) if athlete]
    if not athletes:
        return pd.DataFrame(columns=columns)

    rpe_dates = _coerce_dates(rpe_df, ("Date",))
    rpe_mask = rpe_dates.notna() & (rpe_dates >= window_start) & (rpe_dates <= reference_ts)
    rpe_window = rpe_df.loc[rpe_mask].copy()
    rpe_window_dates = rpe_dates.loc[rpe_mask]
    rpe_window["_quality_date"] = rpe_window_dates.values
    if "sRPE" in rpe_window.columns:
        rpe_window["sRPE"] = pd.to_numeric(rpe_window["sRPE"], errors="coerce")

    wellness_dates = _coerce_dates(wellness_df, ("Date",))
    wellness_mask = wellness_dates.notna() & (wellness_dates >= window_start) & (wellness_dates <= reference_ts)
    wellness_window = wellness_df.loc[wellness_mask].copy()
    wellness_window["_quality_date"] = wellness_dates.loc[wellness_mask].values

    rpe_full = rpe_df.copy()
    rpe_full["_quality_date"] = _coerce_dates(rpe_df, ("Date",)).values
    if "sRPE" in rpe_full.columns:
        rpe_full["sRPE"] = pd.to_numeric(rpe_full["sRPE"], errors="coerce")
    wellness_full = wellness_df.copy()
    wellness_full["_quality_date"] = _coerce_dates(wellness_df, ("Date",)).values

    rows: list[dict[str, object]] = []
    for athlete in sorted(set(athletes)):
        athlete_rpe = rpe_window[rpe_window.get("Athlete", pd.Series(index=rpe_window.index, dtype=object)) == athlete]
        if "sRPE" in athlete_rpe.columns:
            athlete_rpe = athlete_rpe[athlete_rpe["sRPE"] > 0]
        athlete_wellness = wellness_window[
            wellness_window.get("Athlete", pd.Series(index=wellness_window.index, dtype=object)) == athlete
        ]

        srpe_days = int(athlete_rpe["_quality_date"].dropna().nunique())
        wellness_days = int(athlete_wellness["_quality_date"].dropna().nunique())
        srpe_pct = round((srpe_days / window_days) * 100, 1) if window_days > 0 else 0.0
        wellness_pct = round((wellness_days / srpe_days) * 100, 1) if srpe_days > 0 else 0.0

        athlete_rpe_full = rpe_full[rpe_full.get("Athlete", pd.Series(index=rpe_full.index, dtype=object)) == athlete]
        if "sRPE" in athlete_rpe_full.columns:
            athlete_rpe_full = athlete_rpe_full[athlete_rpe_full["sRPE"] > 0]
        athlete_wellness_full = wellness_full[
            wellness_full.get("Athlete", pd.Series(index=wellness_full.index, dtype=object)) == athlete
        ]

        if srpe_pct >= 80 and wellness_pct >= 70:
            traffic_light = "🟢 Verde"
        elif srpe_pct < 60 or wellness_pct < 50:
            traffic_light = "🔴 Rojo"
        else:
            traffic_light = "🟡 Amarillo"

        rows.append(
            {
                "Atleta": athlete,
                "Dias con sRPE": srpe_days,
                "Dias con Wellness": wellness_days,
                "% cobertura sRPE": srpe_pct,
                "% cobertura Wellness": wellness_pct,
                "Ultimo sRPE": _format_date(athlete_rpe_full["_quality_date"].max() if not athlete_rpe_full.empty else pd.NaT),
                "Ultimo Wellness": _format_date(
                    athlete_wellness_full["_quality_date"].max() if not athlete_wellness_full.empty else pd.NaT
                ),
                "Semaforo": traffic_light,
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _build_alerts(
    dataset_summary: pd.DataFrame,
    athlete_summary: pd.DataFrame,
    dataset_frames: dict[str, pd.DataFrame | None],
    athletes_list: list[str] | None,
    window_start: pd.Timestamp,
    reference_ts: pd.Timestamp,
) -> list[str]:
    alerts: list[str] = []
    athletes = [athlete for athlete in (athletes_list or []) if athlete]

    rpe_df = dataset_frames.get("rpe_df")
    if rpe_df is not None and not rpe_df.empty and athletes:
        rpe_dates = _coerce_dates(rpe_df, ("Date",))
        rpe_window_mask = rpe_dates.notna() & (rpe_dates >= reference_ts - pd.Timedelta(days=6)) & (rpe_dates <= reference_ts)
        rpe_recent = rpe_df.loc[rpe_window_mask].copy()
        if "sRPE" in rpe_recent.columns:
            rpe_recent["sRPE"] = pd.to_numeric(rpe_recent["sRPE"], errors="coerce")
            rpe_recent = rpe_recent[rpe_recent["sRPE"] > 0]
        recent_athletes = set(_athlete_series(rpe_recent).dropna().tolist())
        for athlete in sorted(set(athletes) - recent_athletes):
            alerts.append(f"⚠️ {athlete} - sin sRPE registrado en los ultimos 7 dias")

    for dataset_key, label, date_candidates in (("rpe_df", "RPE + Tiempo", ("Date",)), ("wellness_df", "Wellness", ("Date",))):
        df = dataset_frames.get(dataset_key)
        if df is None or df.empty:
            continue
        dates = _coerce_dates(df, date_candidates)
        window_dates = dates[(dates >= window_start) & (dates <= reference_ts)]
        gap = _longest_missing_streak(window_dates, window_start, reference_ts)
        if gap is not None:
            gap_days, gap_start, gap_end = gap
            alerts.append(
                f"⚠️ {label} - hueco de {gap_days} dias entre {_format_date(gap_start)} y {_format_date(gap_end)}"
            )

    if not athlete_summary.empty:
        for _, row in athlete_summary.iterrows():
            srpe_pct = float(row["% cobertura sRPE"])
            wellness_pct = float(row["% cobertura Wellness"])
            if srpe_pct > 0 and wellness_pct < (srpe_pct * 0.5):
                alerts.append(f"⚠️ {row['Atleta']} - wellness incompleto respecto a sesiones registradas")

    raw_df = dataset_frames.get("raw_df")
    if raw_df is not None and not raw_df.empty:
        raw_dates = _coerce_dates(raw_df, ("Assigned Date", "Date"))
        raw_window = raw_df.loc[(raw_dates >= window_start) & (raw_dates <= reference_ts)].copy()
        if not raw_window.empty:
            if "is_untagged" in raw_window.columns:
                untagged_ratio = raw_window["is_untagged"].fillna(False).astype(bool).mean()
                if untagged_ratio > 0.20:
                    alerts.append(
                        f"⚠️ Raw workouts - {untagged_ratio * 100:.0f}% de ejercicios sin categoria asignada"
                    )
            if "is_invalid" in raw_window.columns:
                invalid_count = int(raw_window["is_invalid"].fillna(False).astype(bool).sum())
                if invalid_count > 0:
                    alerts.append(f'⚠️ Raw workouts - {invalid_count} fila(s) con tag invalido ("ju")')
            if {"stimulus_category", "Result"}.issubset(raw_window.columns):
                zero_result = raw_window[
                    raw_window["stimulus_category"].eq("strength_loaded")
                    & pd.to_numeric(raw_window["Result"], errors="coerce").eq(0)
                ]
                if not zero_result.empty:
                    alerts.append(f"⚠️ Raw workouts - {len(zero_result)} fila(s) con Result = 0 en strength_loaded")
            if "Reps" in raw_window.columns:
                zero_reps = raw_window[pd.to_numeric(raw_window["Reps"], errors="coerce").eq(0)]
                if not zero_reps.empty:
                    alerts.append(f"⚠️ Raw workouts - {len(zero_reps)} fila(s) con Reps = 0")

    jump_df = dataset_frames.get("jump_df")
    if jump_df is not None and not jump_df.empty:
        jump_dates = _coerce_dates(jump_df, ("Date",))
        latest_jump = jump_dates.max()
        if pd.notna(latest_jump):
            days_since_jump = int((reference_ts - latest_jump).days)
            if days_since_jump > 30:
                alerts.append(
                    f"⚠️ Evaluaciones - ultimo test hace {days_since_jump} dias. Considerar nueva toma."
                )

    return alerts


def compute_data_quality_report(
    rpe_df,
    wellness_df,
    completion_df,
    raw_df,
    maxes_df,
    jump_df,
    athletes_list,
    window_days: int = 42,
    reference_date=None,
) -> dict[str, object]:
    window_start, reference_ts = _window_bounds(reference_date=reference_date, window_days=window_days)
    dataset_frames = {
        "rpe_df": rpe_df,
        "wellness_df": wellness_df,
        "completion_df": completion_df,
        "raw_df": raw_df,
        "maxes_df": maxes_df,
        "jump_df": jump_df,
    }

    dataset_summary = _build_dataset_summary(dataset_frames, window_start, reference_ts)
    raw_category_breakdown, raw_classification_summary = _build_raw_category_breakdown(
        raw_df,
        window_start,
        reference_ts,
    )
    athlete_summary = _build_athlete_summary(
        rpe_df,
        wellness_df,
        athletes_list,
        window_start,
        reference_ts,
        window_days,
    )
    alerts = _build_alerts(dataset_summary, athlete_summary, dataset_frames, athletes_list, window_start, reference_ts)

    return {
        "dataset_summary": dataset_summary,
        "raw_category_breakdown": raw_category_breakdown,
        "raw_classification_summary": raw_classification_summary,
        "athlete_summary": athlete_summary,
        "alerts": alerts,
    }
