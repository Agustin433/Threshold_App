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

TAG_CATEGORIES = {
    "Empuje Horizontal": "Push H",
    "Empuje Vertical": "Push V",
    "Traccion Horizontal": "Pull H",
    "Traccion Vertical": "Pull V",
    "Dominante de Rodilla": "Dom. Rodilla",
    "Dominante de Rodilla/Stance_Split": "Dom. Rodilla",
    "Dominante de Cadera": "Dom. Cadera",
    "DLO": "DLO",
    "Jump_Plyo": "Plyo/Saltos",
    "Jump_Ballistic": "Balistico",
    "Accessories MMSS": "Accesorios MMSS",
    "Accessories MMII/Ham_Curl": "Accesorios MMII",
    "Neck": "Cuello/Trapecio",
}

_CMJ_MAP = {
    "Height Jump (cm)": ("CMJ_cm", "max"),
    "RSI": ("CMJ_RSI", "max"),
    "Concentric Time (ms)": ("CMJ_conc_ms", "min"),
    "Braking Time (ms)": ("CMJ_brake_ms", "min"),
    "Contraction Time (ms)": ("CMJ_contraction_ms", "min"),
    "Propulsive Max Force (N)": ("CMJ_peak_force_N", "max"),
    "Maximum propulsive power (w)": ("CMJ_peak_power_W", "max"),
    "Propuslive Asymmetry Max Force (%)": ("CMJ_asym_pct", "mean"),
    "Braking Asymmetry Max Force (%)": ("CMJ_brake_asym_pct", "mean"),
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
    **{col: col.lower() for col in RAW_EVALUATION_COLUMNS},
}
SUPABASE_EVALUATIONS_TABLE = "evaluations"


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


def parse_xlsx_questionnaire(file_bytes: bytes, mode: str = "rpe") -> pd.DataFrame:
    """Parse TeamBuildr questionnaire report exports."""
    rows = _read_xlsx_rows(file_bytes)
    records = []
    current_athlete = None

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
            continue

        if not current_athlete or not is_date:
            continue

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

    return pd.DataFrame(records)


def parse_completion_report(file) -> pd.DataFrame:
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_col = next((col for col in ["Dates", "Date", "Fecha"] if col in df.columns), None)
    assigned_col = next((col for col in ["Assigned", "Asignado"] if col in df.columns), None)
    completed_col = next((col for col in ["Completed", "Completado"] if col in df.columns), None)
    if not date_col or not assigned_col or not completed_col:
        raise ValueError("El Completion Report no tiene las columnas esperadas.")
    df["Date"] = pd.to_datetime(df[date_col], errors="coerce")
    df["Assigned"] = pd.to_numeric(df[assigned_col], errors="coerce")
    df["Completed"] = pd.to_numeric(df[completed_col], errors="coerce")
    df["Pct"] = df["Completed"] / df["Assigned"] * 100
    return df.dropna(subset=["Date"])


def parse_rep_load_report(file) -> pd.DataFrame:
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    rename_map = {}
    if date_col := next((col for col in ["Date", "Dates", "Fecha"] if col in df.columns), None):
        rename_map[date_col] = "Date"
    if reps_assigned_col := next(
        (col for col in ["Rep Count (Assigned)", "Assigned Reps", "Reps Assigned"] if col in df.columns),
        None,
    ):
        rename_map[reps_assigned_col] = "Reps_Assigned"
    if reps_completed_col := next(
        (col for col in ["Rep Count (Completed)", "Completed Reps", "Reps Completed"] if col in df.columns),
        None,
    ):
        rename_map[reps_completed_col] = "Reps_Completed"
    if load_col := next((col for col in ["Load (Completed)", "Load Completed", "Load", "Weight"] if col in df.columns), None):
        rename_map[load_col] = "Load_kg"
    if athlete_col := next((col for col in ["Athlete", "Name", "Player", "Atleta"] if col in df.columns), None):
        rename_map[athlete_col] = "Athlete"
    if exercise_col := next((col for col in ["Exercise Name", "Exercise", "Ejercicio"] if col in df.columns), None):
        rename_map[exercise_col] = "Exercise"

    df = df.rename(columns=rename_map)
    if "Date" not in df.columns:
        raise ValueError("El Rep/Load Report no tiene una columna de fecha reconocible.")

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=False, errors="coerce")
    if "Load_kg" in df.columns:
        df["Load_kg"] = pd.to_numeric(df["Load_kg"].astype(str).str.replace("--", ""), errors="coerce")
    if "Reps_Completed" in df.columns:
        df["Reps_Completed"] = pd.to_numeric(df["Reps_Completed"].astype(str).str.replace("--", ""), errors="coerce")
    if "Athlete" in df.columns:
        df["Athlete"] = df["Athlete"].astype(str).str.strip().str.title()
    return df.dropna(subset=["Date"])


def parse_raw_workouts(file) -> pd.DataFrame:
    """Robust raw workout parser that tolerates column variants."""
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_col = next((col for col in ["Assigned Date", "Date", "Workout Date", "Fecha"] if col in df.columns), None)
    athlete_col = next((col for col in ["Athlete", "Name", "Player", "Athlete Name", "Atleta"] if col in df.columns), None)
    result_col = next((col for col in ["Result", "Load", "Weight", "Carga"] if col in df.columns), None)
    reps_col = next((col for col in ["Reps", "Rep Count", "Completed Reps"] if col in df.columns), None)
    tags_col = next((col for col in ["Tags", "Tag", "Labels"] if col in df.columns), None)
    if not date_col or not result_col or not reps_col:
        raise ValueError("El Raw Data Report no tiene las columnas minimas esperadas.")

    rename_map = {date_col: "Assigned Date", result_col: "Result", reps_col: "Reps"}
    if athlete_col:
        rename_map[athlete_col] = "Athlete"
    if tags_col:
        rename_map[tags_col] = "Tags"

    df = df.rename(columns=rename_map)
    df["Assigned Date"] = pd.to_datetime(df["Assigned Date"], errors="coerce")
    df["Result"] = pd.to_numeric(df["Result"], errors="coerce")
    df["Reps"] = pd.to_numeric(df["Reps"], errors="coerce")
    df["Volume_Load"] = df["Result"] * df["Reps"]
    if "Athlete" in df.columns:
        df["Athlete"] = df["Athlete"].astype(str).str.strip().str.title()
    tag_series = df["Tags"] if "Tags" in df.columns else pd.Series(index=df.index, dtype=object)
    df["Category"] = tag_series.map(TAG_CATEGORIES).fillna("Sin categoria")
    return df.dropna(subset=["Assigned Date"])


def parse_maxes_health(file) -> pd.DataFrame:
    """Robust parser for TeamBuildr maxes exports."""
    df = _read_csv_with_fallback(file)
    df.columns = [col.strip().strip('"') for col in df.columns]
    date_col = next((col for col in ["Added Date", "Date", "Fecha"] if col in df.columns), None)
    value_col = next((col for col in ["Max Value", "Value", "Peso", "Weight"] if col in df.columns), None)
    athlete_col = next((col for col in ["Athlete", "Name", "Player", "Atleta"] if col in df.columns), None)
    first_name_col = next((col for col in ["First Name", "Nombre"] if col in df.columns), None)
    last_name_col = next((col for col in ["Last Name", "Apellido"] if col in df.columns), None)
    exercise_col = next((col for col in ["Exercise Name", "Exercise", "Ejercicio"] if col in df.columns), None)
    if not date_col or not value_col:
        raise ValueError("El reporte de maximos no tiene fecha o valor maximo reconocible.")

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


def parse_forceplate_file(file_bytes: bytes, test_type: str) -> dict[str, object]:
    """Parse one force plate file and return mapped KPIs."""
    raw = _read_forceplate_xlsx(file_bytes)
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
        df = _read_csv_with_fallback(file)
    else:
        df = pd.read_excel(file)
    df.columns = [col.strip() for col in df.columns]
    df["Date"] = pd.to_datetime(
        df.get("Date", df.get("Fecha", pd.Timestamp.today())),
        dayfirst=True,
        errors="coerce",
    )
    for column in ["CMJ_cm", "SJ_cm", "DJ_cm", "DJ_tc_ms", "IMTP_N"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df
