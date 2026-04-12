"""Shared file parsers for TeamBuildr and force plate exports."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

_DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}$"
)

TAG_CATEGORY_MAP = {
    "Dominante de Cadera": "strength_loaded",
    "Dominante de Rodilla": "strength_loaded",
    "Empuje Horizontal": "strength_loaded",
    "Empuje Vertical": "strength_loaded",
    "Traccion Horizontal": "strength_loaded",
    "Traccion Vertical": "strength_loaded",
    "Jump_Loaded": "strength_loaded",
    "Stance_SingleLeg": "strength_loaded",
    "Stance_Split": "strength_loaded",
    "Biceps": "strength_loaded",
    "Triceps": "strength_loaded",
    "Ham_Curl": "strength_loaded",
    "Neck": "strength_loaded",
    "Accessories MMII": "strength_loaded",
    "Accessories MMSS": "strength_loaded",
    "DLO": "olympic_derivatives",
    "Jump_Ballistic": "plyo_jump",
    "Jump_Plyo": "plyo_jump",
    "Balistic MMSS": "plyo_jump",
    "Plyo MMSS": "plyo_jump",
    "Split_Jump": "plyo_jump",
    "Catch_Landing": "landing_mechanics",
    "Iso_Overcoming": "iso",
    "Iso_Yielding": "iso",
    "OSCI": "iso",
    "Core": "core_stability",
    "Stretch MMII": "mobility_prehab",
    "Stretch MMSS": "mobility_prehab",
    "Wall Drill": "mobility_prehab",
    "ju": "invalid",
}

_TAG_TOKEN_RE = re.compile(r"[|,;/]+")

_CMJ_MAP = {
    "Height Jump (cm)": ("CMJ_cm", "max"),
    "RSI": ("CMJ_RSI", "max"),
    "Concentric Time (ms)": ("CMJ_conc_ms", "min"),
    "Braking Time (ms)": ("CMJ_brake_ms", "min"),
    "Contraction Time (ms)": ("CMJ_contraction_ms", "min"),
    "Propulsive Max Force (N)": ("CMJ_propulsive_PF_N", "max"),
    "Maximum propulsive power (w)": ("CMJ_peak_power_W", "max"),
    "Propuslive Asymmetry Max Force (%)": ("CMJ_asym_pct", "mean"),
    "Propulsive Asymmetry Max Force (%)": ("CMJ_asym_pct", "mean"),
    "Braking Asymmetry Max Force (%)": ("CMJ_brake_asym_pct", "mean"),
    "Propulsive Relative Impulse (N*s/Kg)": ("CMJ_rel_impulse", "max"),
    "Landing Max Force (N)": ("CMJ_landing_force_N", "max"),
    "Landing Asymmetry Max Force (%)": ("CMJ_landing_asym_pct", "mean"),
    "Stabilization Time (ms)": ("CMJ_stabilization_ms", "min"),
    "weight (kg)": ("BW_kg", "mean"),
    "Flight Time (ms)": ("CMJ_flight_ms", "max"),
}

_SJ_MAP = {
    "Height Jump (cm)": ("SJ_cm", "max"),
    "RSI": ("SJ_RSI", "max"),
    "Concentric Time (ms)": ("SJ_conc_ms", "min"),
    "Propulsive Max Force (N)": ("SJ_peak_force_N", "max"),
    "Maximum propulsive power (w)": ("SJ_peak_power_W", "max"),
    "Propuslive Asymmetry Max Force (%)": ("SJ_asym_pct", "mean"),
    "weight (kg)": ("BW_kg", "mean"),
    "Flight Time (ms)": ("SJ_flight_ms", "max"),
}

_DJ_MAP = {
    "Height Jump (cm)": ("DJ_cm", "max"),
    "Contact Time (ms)": ("DJ_tc_ms", "min"),
    "RSI": ("DRI", "max"),
    "Asimmetry (%)": ("DJ_asym_pct", "mean"),
    "Force Contact Max (N)": ("DJ_peak_force_N", "max"),
    "Flight Time (ms)": ("DJ_flight_ms", "max"),
    "Force Left Contact Max (N)": ("DJ_force_L_N", "max"),
    "Force Right Contact Max (N)": ("DJ_force_R_N", "max"),
}

_IMTP_MAP = {
    "Force Max (N)": ("IMTP_N", "max"),
    "Force Avg (N)": ("IMTP_avg_N", "mean"),
    "RFD at 50 (N/s)": ("RFD_50", "max"),
    "RFD at 100 (N/s)": ("RFD_100", "max"),
    "RFD at 150 (N/s)": ("RFD_150", "max"),
    "RFD at 250 (N/s)": ("RFD_250", "max"),
    "Asimmetry (%)": ("IMTP_asym_pct", "mean"),
    "Pre-tension (N)": ("IMTP_pretension", "mean"),
    "Time Max Force (s)": ("IMTP_time_max_s", "mean"),
    "Force Left Max (N)": ("IMTP_force_L_N", "max"),
    "Force Right Max (N)": ("IMTP_force_R_N", "max"),
}

TEST_MAPS = {"CMJ": _CMJ_MAP, "SJ": _SJ_MAP, "DJ": _DJ_MAP, "IMTP": _IMTP_MAP}
LOCAL_ONLY_EVALUATION_COLUMNS = {
    "CMJ_propulsive_PF_N",
    "CMJ_rel_impulse",
    "CMJ_landing_force_N",
    "CMJ_landing_asym_pct",
    "CMJ_stabilization_ms",
}
RAW_EVALUATION_COLUMNS = sorted(
    {
        metric_name
        for test_map in TEST_MAPS.values()
        for metric_name, _ in test_map.values()
    }
)
EVALUATION_PERSIST_COLUMNS = ["Athlete", "Date"] + RAW_EVALUATION_COLUMNS
EVALUATION_DB_COLUMN_MAP = {
    "Athlete": "athlete",
    "Date": "date",
    **{col: col.lower() for col in RAW_EVALUATION_COLUMNS if col not in LOCAL_ONLY_EVALUATION_COLUMNS},
}
SUPABASE_EVALUATIONS_TABLE = "evaluations"

UPLOAD_CONTRACTS: dict[str, dict[str, object]] = {
    "rpe": {
        "label": "RPE + Tiempo",
        "extensions": ("xlsx",),
        "expected_format": "TeamBuildr Questionnaire Report (.xlsx)",
        "examples": ("questionnaire-report.xlsx",),
    },
    "wellness": {
        "label": "Wellness 3Q",
        "extensions": ("xlsx",),
        "expected_format": "TeamBuildr Questionnaire Report (.xlsx)",
        "examples": ("questionnaire-report_wellness.xlsx",),
    },
    "completion": {
        "label": "Completion Report",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Completion Report (.csv)",
        "examples": ("completion.csv",),
    },
    "rep_load": {
        "label": "Rep/Load Report",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Rep/Load Report (.csv)",
        "examples": ("rep_load.csv",),
    },
    "raw_workouts": {
        "label": "Raw Data Report - Workouts",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Raw Data Report - Workouts (.csv)",
        "examples": ("raw_workouts.csv",),
    },
    "maxes": {
        "label": "Raw Data Report - Maxes",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Raw Data Report - Maxes (.csv)",
        "examples": ("maxes.csv",),
    },
    "forceplate": {
        "label": "Evaluacion individual",
        "extensions": ("xlsx",),
        "expected_format": "Export de plataforma de fuerza (.xlsx)",
        "examples": ("cmj.xlsx", "sj.xlsx", "dj.xlsx", "imtp.xlsx"),
    },
}


def _read_xlsx_rows(file_bytes: bytes) -> list[list[object]]:
    with zipfile.ZipFile(BytesIO(file_bytes)) as workbook:
        namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with workbook.open("xl/sharedStrings.xml") as file:
            ss_tree = ET.parse(file)
            strings = []
            for si in ss_tree.findall(f".//{{{namespace}}}si"):
                texts = si.findall(f".//{{{namespace}}}t")
                strings.append("".join(t.text or "" for t in texts))
        with workbook.open("xl/worksheets/sheet1.xml") as file:
            tree = ET.parse(file)
            rows = []
            for row in tree.findall(f".//{{{namespace}}}row"):
                cells = []
                for cell in row.findall(f"{{{namespace}}}c"):
                    cell_type = cell.get("t", "")
                    value_el = cell.find(f"{{{namespace}}}v")
                    if value_el is None:
                        cells.append("")
                    elif cell_type == "s":
                        index = int(value_el.text)
                        cells.append(strings[index] if index < len(strings) else "")
                    else:
                        cells.append(value_el.text or "")
                rows.append(cells)
    return rows


def _safe_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _wellness_score(sueno, estres, dolor):
    values = [value for value in [sueno, estres, dolor] if value is not None]
    return sum(values) if values else None


def _preview_columns(df: pd.DataFrame, limit: int = 10) -> str:
    cols = [str(col) for col in df.columns[:limit]]
    if len(df.columns) > limit:
        cols.append("...")
    return ", ".join(cols) if cols else "sin columnas detectadas"


def _missing_columns_message(
    report_name: str,
    df: pd.DataFrame,
    missing_map: dict[str, list[str]],
) -> str:
    parts = [
        f"{label}: {', '.join(options)}"
        for label, options in missing_map.items()
    ]
    return (
        f"El {report_name} no tiene columnas reconocibles para "
        f"{'; '.join(parts)}. "
        f"Columnas detectadas: {_preview_columns(df)}."
    )


def _preview_values(series: pd.Series, limit: int = 5) -> str:
    examples: list[str] = []
    for value in series.tolist():
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text in examples:
            continue
        examples.append(text)
        if len(examples) >= limit:
            break
    return ", ".join(examples) if examples else "sin ejemplos legibles"


def _resolve_filename(file_or_name) -> str:
    if isinstance(file_or_name, str):
        return file_or_name
    return str(getattr(file_or_name, "name", "") or "")


def _ensure_supported_extension(
    file_or_name,
    report_name: str,
    allowed_extensions: tuple[str, ...],
) -> None:
    filename = _resolve_filename(file_or_name)
    if not filename:
        return

    suffix = Path(filename).suffix.lower().lstrip(".")
    allowed = {ext.lower().lstrip(".") for ext in allowed_extensions}
    if suffix in allowed:
        return

    expected = ", ".join(f".{ext}" for ext in sorted(allowed))
    raise ValueError(
        f"{report_name}: formato no soportado para {filename}. "
        f"Subi un archivo {expected}."
    )


def _require_valid_dates(
    df: pd.DataFrame,
    report_name: str,
    parsed_date_col: str,
    source_date_col: str,
) -> pd.DataFrame:
    valid_df = df.dropna(subset=[parsed_date_col]).copy()
    if not valid_df.empty:
        return valid_df

    examples = _preview_values(df[source_date_col]) if source_date_col in df.columns else "sin ejemplos legibles"
    raise ValueError(
        f"{report_name}: se leyeron {len(df)} fila(s), pero ninguna fecha fue valida en "
        f"'{source_date_col}'. Ejemplos detectados: {examples}."
    )


def _require_numeric_content(
    df: pd.DataFrame,
    report_name: str,
    column_name: str,
    label: str,
) -> None:
    if column_name in df.columns and df[column_name].notna().any():
        return
    raise ValueError(
        f"{report_name}: no se detectaron valores numericos validos para {label}."
    )


def _require_any_numeric_content(
    df: pd.DataFrame,
    report_name: str,
    columns: dict[str, str],
) -> None:
    for column_name in columns:
        if column_name in df.columns and df[column_name].notna().any():
            return

    labels = ", ".join(columns.values())
    raise ValueError(
        f"{report_name}: no se detectaron valores numericos validos para {labels}."
    )


def _read_csv_with_fallback(file, **kwargs) -> pd.DataFrame:
    """Read CSV exports with multiple encoding fallbacks."""
    if isinstance(file, (str, os.PathLike, Path)):
        return pd.read_csv(file, **kwargs)

    raw_bytes = None
    if hasattr(file, "getvalue"):
        raw_bytes = file.getvalue()
    elif hasattr(file, "read"):
        raw_bytes = file.read()
        if hasattr(file, "seek"):
            file.seek(0)

    if raw_bytes is None:
        return pd.read_csv(file, **kwargs)
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8")

    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
    first_error = None

    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(raw_bytes), encoding=encoding, **kwargs)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            if first_error is None:
                first_error = exc

    sniff_kwargs = dict(kwargs)
    sniff_kwargs.setdefault("sep", None)
    sniff_kwargs.setdefault("engine", "python")
    for encoding in encodings:
        try:
            return pd.read_csv(BytesIO(raw_bytes), encoding=encoding, **sniff_kwargs)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError):
            continue

    filename = getattr(file, "name", "archivo CSV")
    raise ValueError(
        f"No se pudo leer {filename} como CSV. Probe UTF-8, UTF-8-SIG, CP1252 y Latin-1."
    ) from first_error


def parse_xlsx_questionnaire(
    file_bytes: bytes,
    mode: str = "rpe",
    filename: str | None = None,
) -> pd.DataFrame:
    """Parse TeamBuildr questionnaire report exports."""
    if mode not in {"rpe", "wellness"}:
        raise ValueError("Modo de cuestionario no soportado. Usa 'rpe' o 'wellness'.")
    contract_key = "rpe" if mode == "rpe" else "wellness"
    contract = UPLOAD_CONTRACTS[contract_key]
    _ensure_supported_extension(
        filename,
        str(contract["label"]),
        tuple(contract["extensions"]),
    )

    try:
        rows = _read_xlsx_rows(file_bytes)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(
            "El archivo debe ser un .xlsx valido exportado desde TeamBuildr Questionnaire Report."
        ) from exc

    records = []
    current_athlete = None
    dated_rows = 0
    athlete_blocks = 0

    for row in rows:
        if not row or all(value in ("", "-", None) for value in row):
            continue

        first = str(row[0]).strip()
        is_date = bool(_DATE_RE.match(first))

        if (
            first not in ("Name", "Athlete")
            and not is_date
            and len(row) > 1
            and any(char.isalpha() for char in first)
        ):
            current_athlete = first
            athlete_blocks += 1
            continue

        if not current_athlete or not is_date:
            continue

        dated_rows += 1
        try:
            date = pd.to_datetime(first, format="%b %d, %Y")
        except Exception:
            continue

        values = [value for value in row[1:] if value not in ("", "-", None, "Range Average")]
        if mode == "rpe":
            rpe_value = _safe_float(values[0]) if len(values) > 0 else None
            time_value = _safe_float(values[1]) if len(values) > 1 else None
            if rpe_value is not None:
                srpe = rpe_value * time_value if time_value else None
                records.append(
                    {
                        "Date": date,
                        "Athlete": current_athlete,
                        "RPE": rpe_value,
                        "Duration_min": time_value,
                        "sRPE": srpe,
                    }
                )
        elif mode == "wellness":
            sueno = _safe_float(values[0]) if len(values) > 0 else None
            estres = _safe_float(values[1]) if len(values) > 1 else None
            dolor = _safe_float(values[2]) if len(values) > 2 else None
            if any(value is not None for value in [sueno, estres, dolor]):
                records.append(
                    {
                        "Date": date,
                        "Athlete": current_athlete,
                        "Sueno_hs": sueno,
                        "Estres": estres,
                        "Dolor": dolor,
                        "Wellness_Score": _wellness_score(sueno, estres, dolor),
                    }
                )

    if not records:
        report_label = str(contract["label"])
        if athlete_blocks == 0:
            raise ValueError(
                f"El archivo de {report_label} se pudo abrir, pero no se detectaron bloques de atletas. "
                "Verifica que sea el export correcto de TeamBuildr Questionnaire Report."
            )
        if dated_rows == 0:
            raise ValueError(
                f"El archivo de {report_label} se pudo abrir, pero no se detectaron filas con fecha "
                "en formato TeamBuildr (por ejemplo: Apr 06, 2026)."
            )
        raise ValueError(
            f"El archivo de {report_label} se pudo abrir, pero no produjo registros validos. "
            "Verifica que sea el export correcto de TeamBuildr y que incluya atletas, fechas y respuestas."
        )

    return pd.DataFrame(records)


def parse_completion_report(file) -> pd.DataFrame:
    _ensure_supported_extension(
        file,
        str(UPLOAD_CONTRACTS["completion"]["label"]),
        tuple(UPLOAD_CONTRACTS["completion"]["extensions"]),
    )
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_options = ["Dates", "Date", "Fecha"]
    assigned_options = ["Assigned", "Asignado"]
    completed_options = ["Completed", "Completado"]
    athlete_options = ["Athlete", "Name", "Player", "Atleta"]

    date_col = next((col for col in date_options if col in df.columns), None)
    assigned_col = next((col for col in assigned_options if col in df.columns), None)
    completed_col = next((col for col in completed_options if col in df.columns), None)
    athlete_col = next((col for col in athlete_options if col in df.columns), None)
    if not date_col or not assigned_col or not completed_col:
        missing_map: dict[str, list[str]] = {}
        if not date_col:
            missing_map["fecha"] = date_options
        if not assigned_col:
            missing_map["asignado"] = assigned_options
        if not completed_col:
            missing_map["completado"] = completed_options
        raise ValueError(_missing_columns_message("Completion Report", df, missing_map))
    df["Date"] = pd.to_datetime(df[date_col], errors="coerce")
    df["Assigned"] = pd.to_numeric(df[assigned_col], errors="coerce")
    df["Completed"] = pd.to_numeric(df[completed_col], errors="coerce")
    if athlete_col:
        df["Athlete"] = df[athlete_col].astype(str).str.strip().str.title()
    df = _require_valid_dates(df, "Completion Report", "Date", date_col)
    _require_numeric_content(df, "Completion Report", "Assigned", "Assigned/Asignado")
    _require_numeric_content(df, "Completion Report", "Completed", "Completed/Completado")
    df["Pct"] = (df["Completed"] / df["Assigned"].where(df["Assigned"] > 0)) * 100
    valid_df = df.dropna(subset=["Pct"]).copy()
    if valid_df.empty:
        raise ValueError(
            "Completion Report: no se pudo calcular el porcentaje porque 'Assigned' es 0 o invalido en todas las filas."
        )
    return valid_df


def parse_rep_load_report(file) -> pd.DataFrame:
    _ensure_supported_extension(
        file,
        str(UPLOAD_CONTRACTS["rep_load"]["label"]),
        tuple(UPLOAD_CONTRACTS["rep_load"]["extensions"]),
    )
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_options = ["Date", "Dates", "Fecha"]
    reps_assigned_options = ["Rep Count (Assigned)", "Assigned Reps", "Reps Assigned"]
    reps_completed_options = ["Rep Count (Completed)", "Completed Reps", "Reps Completed"]
    load_options = ["Load (Completed)", "Load Completed", "Load", "Weight"]
    athlete_options = ["Athlete", "Name", "Player", "Atleta"]
    exercise_options = ["Exercise Name", "Exercise", "Ejercicio"]
    rename_map = {}
    if date_col := next((col for col in date_options if col in df.columns), None):
        rename_map[date_col] = "Date"
    if reps_assigned_col := next(
        (col for col in reps_assigned_options if col in df.columns),
        None,
    ):
        rename_map[reps_assigned_col] = "Reps_Assigned"
    if reps_completed_col := next(
        (col for col in reps_completed_options if col in df.columns),
        None,
    ):
        rename_map[reps_completed_col] = "Reps_Completed"
    if load_col := next((col for col in load_options if col in df.columns), None):
        rename_map[load_col] = "Load_kg"
    if athlete_col := next((col for col in athlete_options if col in df.columns), None):
        rename_map[athlete_col] = "Athlete"
    if exercise_col := next((col for col in exercise_options if col in df.columns), None):
        rename_map[exercise_col] = "Exercise"

    df = df.rename(columns=rename_map)
    if "Date" not in df.columns:
        raise ValueError(
            _missing_columns_message(
                "Rep/Load Report",
                df,
                {"fecha": date_options},
            )
        )

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=False, errors="coerce")
    if "Load_kg" in df.columns:
        df["Load_kg"] = pd.to_numeric(df["Load_kg"].astype(str).str.replace("--", ""), errors="coerce")
    if "Reps_Completed" in df.columns:
        df["Reps_Completed"] = pd.to_numeric(df["Reps_Completed"].astype(str).str.replace("--", ""), errors="coerce")
    if "Athlete" in df.columns:
        df["Athlete"] = df["Athlete"].astype(str).str.strip().str.title()
    df = _require_valid_dates(df, "Rep/Load Report", "Date", "Date")
    _require_any_numeric_content(
        df,
        "Rep/Load Report",
        {
            "Reps_Completed": "repeticiones completadas",
            "Load_kg": "carga completada",
        },
    )
    return df


def _split_tag_tokens(value) -> list[str]:
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [token.strip() for token in _TAG_TOKEN_RE.split(text) if token.strip()]


def _classify_raw_tag(value) -> tuple[str, str, bool, bool]:
    tokens = _split_tag_tokens(value)
    if not tokens:
        return "untagged", "untagged", False, True

    for token in tokens:
        if TAG_CATEGORY_MAP.get(token) == "invalid":
            return "invalid", token, True, False

    for token in tokens:
        category = TAG_CATEGORY_MAP.get(token)
        if category:
            return category, token, False, False

    return "untagged", tokens[0], False, True


def _first_positive(series: pd.Series, fallback: pd.Series) -> pd.Series:
    if series is None:
        return fallback
    if fallback is None:
        return series
    return series.where(series.notna() & (series > 0), fallback)


def prepare_raw_workouts_df(raw_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if raw_df is None:
        return None

    df = raw_df.copy()
    column_aliases = {
        "Assigned Date": ["Date", "Workout Date", "Fecha"],
        "Athlete": ["Name", "Player", "Athlete Name", "Atleta"],
        "Tags": ["Tag", "Labels"],
        "Exercise": ["Exercise Name", "Movement", "Ejercicio"],
        "Sets": ["Set Count", "Completed Sets", "Sets Completed"],
        "Duration_s": [
            "Duration (s)",
            "Duration",
            "Seconds",
            "Time (s)",
            "Time",
            "Hold Time (s)",
            "Hold Time",
        ],
    }
    for target_col, options in column_aliases.items():
        if target_col in df.columns:
            continue
        source_col = next((option for option in options if option in df.columns), None)
        if source_col:
            df[target_col] = df[source_col]

    if df.empty:
        for column in [
            "Date",
            "Category",
            "stimulus_category",
            "Volume_Load",
            "Volume_Load_legacy",
            "Volume_Load_kg",
            "Contacts",
            "Exposures",
            "is_invalid",
            "is_untagged",
        ]:
            if column not in df.columns:
                df[column] = pd.Series(dtype=object if column in {"Category", "stimulus_category"} else "float64")
        if "is_invalid" in df.columns:
            df["is_invalid"] = df["is_invalid"].astype(bool)
        if "is_untagged" in df.columns:
            df["is_untagged"] = df["is_untagged"].astype(bool)
        return df

    if "Assigned Date" in df.columns:
        df["Assigned Date"] = pd.to_datetime(df["Assigned Date"], errors="coerce")
    elif "Date" in df.columns:
        df["Assigned Date"] = pd.to_datetime(df["Date"], errors="coerce")
    else:
        df["Assigned Date"] = pd.NaT
    df["Date"] = df["Assigned Date"]

    for column in ["Result", "Reps", "Sets", "Duration_s"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "Athlete" in df.columns:
        df["Athlete"] = (
            df["Athlete"]
            .where(df["Athlete"].notna(), "")
            .astype(str)
            .str.strip()
            .str.title()
            .replace("", pd.NA)
        )
    if "Exercise" in df.columns:
        df["Exercise"] = (
            df["Exercise"]
            .where(df["Exercise"].notna(), "")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
        )
    if "Tags" in df.columns:
        df["Tags"] = (
            df["Tags"]
            .where(df["Tags"].notna(), "")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
        )

    tag_info = (
        df["Tags"].apply(_classify_raw_tag)
        if "Tags" in df.columns
        else pd.Series([("untagged", "untagged", False, True)] * len(df), index=df.index)
    )
    classified = pd.DataFrame(
        list(tag_info),
        index=df.index,
        columns=["stimulus_category", "Category", "is_invalid", "is_untagged"],
    )
    for column in classified.columns:
        df[column] = classified[column]

    result = pd.to_numeric(df.get("Result", pd.Series(index=df.index, dtype="float64")), errors="coerce")
    reps = pd.to_numeric(df.get("Reps", pd.Series(index=df.index, dtype="float64")), errors="coerce")
    sets = pd.to_numeric(df.get("Sets", pd.Series(index=df.index, dtype="float64")), errors="coerce")
    duration_s = pd.to_numeric(df.get("Duration_s", pd.Series(index=df.index, dtype="float64")), errors="coerce")

    df["Volume_Load_legacy"] = result * reps
    # Backwards-compatible alias while downstream modules still expect Volume_Load.
    df["Volume_Load"] = df["Volume_Load_legacy"]

    df["Volume_Load_kg"] = pd.Series(index=df.index, dtype="float64")
    df["Contacts"] = pd.Series(index=df.index, dtype="float64")
    df["Exposures"] = pd.Series(index=df.index, dtype="float64")

    strength_mask = df["stimulus_category"].eq("strength_loaded")
    valid_strength = strength_mask & result.gt(0) & reps.gt(0)
    df.loc[valid_strength, "Volume_Load_kg"] = (result.loc[valid_strength] * reps.loc[valid_strength]).round(3)

    contacts_mask = df["stimulus_category"].isin(["plyo_jump", "landing_mechanics"]) & reps.gt(0)
    df.loc[contacts_mask, "Contacts"] = reps.loc[contacts_mask]

    dlo_mask = df["stimulus_category"].eq("olympic_derivatives") & reps.gt(0)
    # DLO se monitorea por exposicion tecnica, no por tonelaje acumulado.
    df.loc[dlo_mask, "Exposures"] = reps.loc[dlo_mask]

    iso_mask = df["stimulus_category"].eq("iso")
    df.loc[iso_mask, "Exposures"] = _first_positive(duration_s, sets).loc[iso_mask]

    core_mask = df["stimulus_category"].eq("core_stability")
    df.loc[core_mask, "Exposures"] = _first_positive(sets, reps).loc[core_mask]

    mobility_mask = df["stimulus_category"].eq("mobility_prehab")
    df.loc[mobility_mask, "Exposures"] = _first_positive(sets, reps).loc[mobility_mask]

    df["is_invalid"] = df["is_invalid"].astype(bool)
    df["is_untagged"] = df["is_untagged"].astype(bool)
    return df


def summarize_raw_workouts_quality(raw_df: pd.DataFrame | None) -> pd.DataFrame:
    prepared = prepare_raw_workouts_df(raw_df)
    if prepared is None or prepared.empty:
        return pd.DataFrame(columns=["Detalle", "Filas", "Contexto"])

    def _format_dates(values: pd.Series) -> str:
        dates = pd.to_datetime(values, errors="coerce").dropna().dt.strftime("%Y-%m-%d").unique().tolist()
        return ", ".join(dates[:4]) if dates else "-"

    def _format_exercises(values: pd.Series) -> str:
        exercises = values.dropna().astype(str).str.strip()
        exercises = [value for value in exercises.unique().tolist() if value]
        return ", ".join(exercises[:4]) if exercises else "-"

    issues: list[dict[str, object]] = []

    invalid_rows = prepared[prepared["is_invalid"]]
    if not invalid_rows.empty:
        issues.append(
            {
                "Detalle": 'Tag invalido ("ju")',
                "Filas": int(len(invalid_rows)),
                "Contexto": f"Fechas: {_format_dates(invalid_rows['Assigned Date'])}",
            }
        )

    untagged_rows = prepared[prepared["is_untagged"]]
    if not untagged_rows.empty:
        issues.append(
            {
                "Detalle": "Filas sin tag clasificado",
                "Filas": int(len(untagged_rows)),
                "Contexto": f"Ejercicios: {_format_exercises(untagged_rows.get('Exercise', pd.Series(dtype=object)))}",
            }
        )

    zero_result_rows = prepared[
        prepared["stimulus_category"].eq("strength_loaded")
        & pd.to_numeric(prepared.get("Result", pd.Series(index=prepared.index, dtype="float64")), errors="coerce").eq(0)
    ]
    if not zero_result_rows.empty:
        issues.append(
            {
                "Detalle": "Result = 0 en strength_loaded",
                "Filas": int(len(zero_result_rows)),
                "Contexto": f"Fechas: {_format_dates(zero_result_rows['Assigned Date'])}",
            }
        )

    zero_reps_rows = prepared[
        pd.to_numeric(prepared.get("Reps", pd.Series(index=prepared.index, dtype="float64")), errors="coerce").eq(0)
    ]
    if not zero_reps_rows.empty:
        issues.append(
            {
                "Detalle": "Reps = 0",
                "Filas": int(len(zero_reps_rows)),
                "Contexto": f"Fechas: {_format_dates(zero_reps_rows['Assigned Date'])}",
            }
        )

    return pd.DataFrame(issues, columns=["Detalle", "Filas", "Contexto"])


def parse_raw_workouts(file) -> pd.DataFrame:
    """Robust raw workout parser that tolerates column variants."""
    _ensure_supported_extension(
        file,
        str(UPLOAD_CONTRACTS["raw_workouts"]["label"]),
        tuple(UPLOAD_CONTRACTS["raw_workouts"]["extensions"]),
    )
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_options = ["Assigned Date", "Date", "Workout Date", "Fecha"]
    athlete_options = ["Athlete", "Name", "Player", "Athlete Name", "Atleta"]
    result_options = ["Result", "Load", "Weight", "Carga"]
    reps_options = ["Reps", "Rep Count", "Completed Reps"]
    tags_options = ["Tags", "Tag", "Labels"]
    exercise_options = ["Exercise", "Exercise Name", "Movement", "Ejercicio"]
    sets_options = ["Sets", "Set Count", "Completed Sets", "Sets Completed"]
    duration_options = [
        "Duration_s",
        "Duration (s)",
        "Duration",
        "Seconds",
        "Time (s)",
        "Time",
        "Hold Time (s)",
        "Hold Time",
    ]
    date_col = next((col for col in date_options if col in df.columns), None)
    athlete_col = next((col for col in athlete_options if col in df.columns), None)
    result_col = next((col for col in result_options if col in df.columns), None)
    reps_col = next((col for col in reps_options if col in df.columns), None)
    tags_col = next((col for col in tags_options if col in df.columns), None)
    exercise_col = next((col for col in exercise_options if col in df.columns), None)
    sets_col = next((col for col in sets_options if col in df.columns), None)
    duration_col = next((col for col in duration_options if col in df.columns), None)
    if not date_col or not result_col or not reps_col:
        missing_map: dict[str, list[str]] = {}
        if not date_col:
            missing_map["fecha"] = date_options
        if not result_col:
            missing_map["resultado/carga"] = result_options
        if not reps_col:
            missing_map["repeticiones"] = reps_options
        raise ValueError(_missing_columns_message("Raw Data Report - Workouts", df, missing_map))

    rename_map = {date_col: "Assigned Date", result_col: "Result", reps_col: "Reps"}
    if athlete_col:
        rename_map[athlete_col] = "Athlete"
    if tags_col:
        rename_map[tags_col] = "Tags"
    if exercise_col:
        rename_map[exercise_col] = "Exercise"
    if sets_col:
        rename_map[sets_col] = "Sets"
    if duration_col:
        rename_map[duration_col] = "Duration_s"

    df = df.rename(columns=rename_map)
    df["Assigned Date"] = pd.to_datetime(df["Assigned Date"], errors="coerce")
    df["Result"] = pd.to_numeric(df["Result"], errors="coerce")
    df["Reps"] = pd.to_numeric(df["Reps"], errors="coerce")
    if "Sets" in df.columns:
        df["Sets"] = pd.to_numeric(df["Sets"], errors="coerce")
    if "Duration_s" in df.columns:
        df["Duration_s"] = pd.to_numeric(df["Duration_s"], errors="coerce")
    if "Athlete" in df.columns:
        df["Athlete"] = df["Athlete"].astype(str).str.strip().str.title()
    df = _require_valid_dates(df, "Raw Data Report - Workouts", "Assigned Date", "Assigned Date")
    _require_any_numeric_content(
        df,
        "Raw Data Report - Workouts",
        {
            "Result": "resultado/carga",
            "Reps": "repeticiones",
            "Sets": "sets",
            "Duration_s": "duracion",
        },
    )
    return prepare_raw_workouts_df(df)


def parse_maxes_health(file) -> pd.DataFrame:
    """Robust parser for TeamBuildr maxes exports."""
    _ensure_supported_extension(
        file,
        str(UPLOAD_CONTRACTS["maxes"]["label"]),
        tuple(UPLOAD_CONTRACTS["maxes"]["extensions"]),
    )
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_options = ["Added Date", "Date", "Fecha"]
    value_options = ["Max Value", "Value", "Peso", "Weight"]
    athlete_options = ["Athlete", "Name", "Player", "Atleta"]
    first_name_options = ["First Name", "Nombre"]
    last_name_options = ["Last Name", "Apellido"]
    exercise_options = ["Exercise Name", "Exercise", "Ejercicio"]
    date_col = next((col for col in date_options if col in df.columns), None)
    value_col = next((col for col in value_options if col in df.columns), None)
    athlete_col = next((col for col in athlete_options if col in df.columns), None)
    first_name_col = next((col for col in first_name_options if col in df.columns), None)
    last_name_col = next((col for col in last_name_options if col in df.columns), None)
    exercise_col = next((col for col in exercise_options if col in df.columns), None)
    if not date_col or not value_col:
        missing_map: dict[str, list[str]] = {}
        if not date_col:
            missing_map["fecha"] = date_options
        if not value_col:
            missing_map["valor maximo"] = value_options
        raise ValueError(_missing_columns_message("Raw Data Report - Maxes", df, missing_map))

    df["Added Date"] = pd.to_datetime(df[date_col], errors="coerce")
    df["Max Value"] = pd.to_numeric(df[value_col], errors="coerce")
    if athlete_col:
        df["Athlete"] = df[athlete_col].astype(str).str.strip().str.title()
    elif first_name_col and last_name_col:
        df["Athlete"] = (
            df[first_name_col].astype(str).str.strip()
            + " "
            + df[last_name_col].astype(str).str.strip()
        ).str.strip().str.title()
    else:
        df["Athlete"] = "Sin atleta"
    if exercise_col:
        df["Exercise Name"] = df[exercise_col]
    df = _require_valid_dates(df, "Raw Data Report - Maxes", "Added Date", date_col)
    _require_numeric_content(df, "Raw Data Report - Maxes", "Max Value", "valor maximo")
    return df


def _read_forceplate_xlsx(file_bytes: bytes) -> dict[str, list[float]]:
    """Read transposed force plate export rows as metric -> reps."""
    with zipfile.ZipFile(BytesIO(file_bytes)) as workbook:
        namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        strings = []
        try:
            with workbook.open("xl/sharedStrings.xml") as file:
                ss_tree = ET.parse(file)
                strings = [
                    "".join(t.text or "" for t in si.findall(f".//{{{namespace}}}t"))
                    for si in ss_tree.findall(f".//{{{namespace}}}si")
                ]
        except KeyError:
            strings = []

        with workbook.open("xl/worksheets/sheet1.xml") as file:
            tree = ET.parse(file)
            raw_rows = []
            for row in tree.findall(f".//{{{namespace}}}row"):
                cells = []
                for cell in row.findall(f"{{{namespace}}}c"):
                    cell_type = cell.get("t", "")
                    value_el = cell.find(f"{{{namespace}}}v")
                    if value_el is None:
                        cells.append(None)
                    elif cell_type == "s":
                        index = int(value_el.text)
                        cells.append(strings[index] if index < len(strings) else None)
                    else:
                        try:
                            cells.append(float(value_el.text))
                        except Exception:
                            cells.append(value_el.text)
                raw_rows.append(cells)

    result: dict[str, list[float]] = {}
    for row in raw_rows[1:]:
        if not row or not row[0]:
            continue
        metric = str(row[0]).strip()
        numbers = []
        for value in row[1:]:
            if value is None or value == "":
                continue
            try:
                numbers.append(float(value))
            except Exception:
                continue
        if numbers:
            result[metric] = numbers
    return result


def _extract_best(values: list[float], agg: str) -> float | None:
    if not values:
        return None
    if agg == "max":
        return round(max(values), 3)
    if agg == "min":
        return round(min(values), 3)
    return round(sum(values) / len(values), 3)


def parse_forceplate_file(
    file_bytes: bytes,
    test_type: str,
    filename: str | None = None,
) -> dict[str, object]:
    """Parse one force plate file and return mapped KPIs."""
    _ensure_supported_extension(
        filename,
        str(UPLOAD_CONTRACTS["forceplate"]["label"]),
        tuple(UPLOAD_CONTRACTS["forceplate"]["extensions"]),
    )
    try:
        raw = _read_forceplate_xlsx(file_bytes)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(
            "El archivo de evaluacion debe ser un .xlsx valido exportado desde la plataforma de fuerza."
        ) from exc
    metric_map = TEST_MAPS.get(test_type, {})
    result: dict[str, object] = {"test_type": test_type}
    for metric_name, (col_name, agg) in metric_map.items():
        if metric_name in raw:
            result[col_name] = _extract_best(raw[metric_name], agg)
            result[f"{col_name}_reps"] = raw[metric_name]
    return result


def parse_jump_eval(file) -> pd.DataFrame:
    """Compatibility parser for standard tabular evaluation files."""
    filename = file.name.lower() if hasattr(file, "name") else ""
    if filename.endswith(".csv"):
        _ensure_supported_extension(file, "Evaluaciones tabulares", ("csv",))
        df = _read_csv_with_fallback(file)
        raw_date_series = df.get("Date", df.get("Fecha", pd.Series(dtype=object)))
    else:
        _ensure_supported_extension(file, "Evaluaciones tabulares", ("xlsx", "xls"))
        df = pd.read_excel(file)
        raw_date_series = df.get("Date", df.get("Fecha", pd.Series(dtype=object)))
    df.columns = [col.strip() for col in df.columns]
    df["Date"] = pd.to_datetime(
        df.get("Date", df.get("Fecha", pd.Timestamp.today())),
        dayfirst=True,
        errors="coerce",
    )
    for column in ["CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "IMTP_N"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = _require_valid_dates(
        df.assign(__source_date=raw_date_series),
        "Evaluaciones tabulares",
        "Date",
        "__source_date",
    )
    return df
