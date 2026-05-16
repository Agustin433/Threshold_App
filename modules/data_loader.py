"""Shared file parsers for TeamBuildr and force plate exports."""

from __future__ import annotations

import base64
import html
import os
from io import BytesIO
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from modules.evaluation_registry import get_evaluation_spec, get_storage_mapping
from modules.involution_parser import parse_involution_summary_excel

_DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}$"
)
_SESSION_NOTE_LABELS = {
    "athlete": "Athlete",
    "date recorded": "Date",
    "assigned exercise": "Assigned_Exercise",
    "date assigned": "Date_Assigned",
    "opt-out type": "Opt_Out_Type",
    "opt out type": "Opt_Out_Type",
    "explanation": "Explanation_Text",
}
SESSION_NOTE_COLUMNS = [
    "Date",
    "Athlete",
    "Date_Assigned",
    "Assigned_Exercise",
    "Opt_Out_Type",
    "Reason_Category",
    "Replacement_Exercise",
    "Explanation_Text",
    "Source",
    "Source_Page",
    "Raw_Text",
]

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
_SPRINT_DISTANCE_RE = re.compile(r"\b\d+\s*m\b|\d+m", re.IGNORECASE)

EXERCISE_KEYWORDS = {
    "olympic_derivatives": [
        "clean",
        "snatch",
        "hang",
        "jerk",
        "high pull",
        "power clean",
        "hang power",
        "hang high",
        "landmine push jerk",
        "split jerk",
    ],
    "sprint_cod": [
        "sprint",
        "spinning",
        "strides",
        "stride",
        "acceleration",
        "accel",
        "cod",
        "cone drill",
        "cone 5m",
        "figure 8",
        "banded resisted sprint",
        "knee down",
        "falling start",
        "10m +",
        "20m +",
        "30m +",
    ],
    "iso": [
        "iso-hold",
        "iso hold",
        "isometric",
        "iso-catch",
        "iso catch",
        "-hold",
        "hold",
    ],
    "landing_mechanics": [
        "drop catch",
        "catch",
        "landing",
    ],
    "plyo_jump": [
        "jump",
        "broad jump",
        "rope jump",
        "box jump",
        "drop jump",
        "rebound",
        "plyo",
        "ballistic",
        "split squat jump",
        "hop",
        "bound",
    ],
    "core_stability": [
        "deadbug",
        "pallof",
        "plank",
        "anti-rotation",
        "bird dog",
        "hollow",
        "core",
        "rotation",
    ],
    "mobility_prehab": [
        "stretch",
        "mobility",
        "wall drill",
        "wall lean",
        "bar hang",
        "hang",
        "piston",
        "corrective",
        "pigeon",
        "hip stretch",
        "thoracic",
        "prayer",
    ],
    "strength_loaded": [
        "pull-up",
        "chin-up",
        "pull up",
        "chin up",
        "row",
        "press",
        "squat",
        "deadlift",
        "rdl",
        "lunge",
        "step-up",
        "step up",
        "curl",
        "extension",
        "raise",
        "thrust",
        "hinge",
        "nordic",
        "eccentric",
        "bulgarian",
        "goblet",
        "bench",
        "military",
        "overhead",
    ],
}

KEYWORD_PRIORITY_ORDER = [
    "olympic_derivatives",
    "sprint_cod",
    "iso",
    "landing_mechanics",
    "plyo_jump",
    "core_stability",
    "mobility_prehab",
    "strength_loaded",
]

CATEGORY_SPECIFICITY_ORDER = {
    "iso": 0,
    "olympic_derivatives": 1,
    "sprint_cod": 2,
    "landing_mechanics": 3,
    "plyo_jump": 4,
    "core_stability": 5,
    "mobility_prehab": 6,
    "strength_loaded": 7,
    "untagged": 98,
    "invalid": 99,
}

CATEGORY_DISPLAY_LABELS = {
    "strength_loaded": "Strength / loaded",
    "olympic_derivatives": "Olympic derivatives",
    "plyo_jump": "Plyo / jump",
    "landing_mechanics": "Landing mechanics",
    "iso": "Isometric",
    "core_stability": "Core / stability",
    "mobility_prehab": "Mobility / prehab",
    "sprint_cod": "Sprint / COD",
    "untagged": "Untagged",
    "invalid": "Invalid",
}

_TAG_CATEGORY_LOOKUP = {str(tag).strip().lower(): category for tag, category in TAG_CATEGORY_MAP.items()}

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

def _build_force_time_metric_map(storage_mapping: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {
        "Force Max (N)": (storage_mapping["force_max_n"], "max"),
        "Force Avg (N)": (storage_mapping["force_avg_n"], "mean"),
        "RFD at 50 (N/s)": (storage_mapping["rfd_50_n_s"], "max"),
        "RFD at 100 (N/s)": (storage_mapping["rfd_100_n_s"], "max"),
        "RFD at 150 (N/s)": (storage_mapping["rfd_150_n_s"], "max"),
        "RFD at 250 (N/s)": (storage_mapping["rfd_250_n_s"], "max"),
        "Force At 50 (N)": (storage_mapping["force_50_n"], "max"),
        "Force At 100 (N)": (storage_mapping["force_100_n"], "max"),
        "Force At 150 (N)": (storage_mapping["force_150_n"], "max"),
        "Force At 200 (N)": (storage_mapping["force_200_n"], "max"),
        "Force At 250 (N)": (storage_mapping["force_250_n"], "max"),
        "Asimmetry (%)": (storage_mapping["asymmetry_pct"], "mean"),
        "Asymmetry (%)": (storage_mapping["asymmetry_pct"], "mean"),
        "Pre-tension (N)": (storage_mapping["pre_tension_n"], "mean"),
        "Time Max Force (s)": (storage_mapping["time_to_peak_s"], "mean"),
        "Time Pull (s)": (storage_mapping["time_pull_s"], "mean"),
        "Force Left Max (N)": (storage_mapping["force_left_max_n"], "max"),
        "Force Right Max (N)": (storage_mapping["force_right_max_n"], "max"),
    }


_IMTP_SPEC = get_evaluation_spec("imtp") or {}
_IMTP_STORAGE_MAPPING = get_storage_mapping("imtp")
_IMTP_LEGACY_STORAGE_ALIASES: dict[str, str] = dict(_IMTP_SPEC.get("legacy_storage_aliases", {}))
_ISO_PUSH_HAMSTRING_STORAGE_MAPPING = get_storage_mapping("iso_push_hamstring")
_FORCE_TIME_TEST_TYPE_TO_TEST_ID = {
    "IMTP": "imtp",
    "ISO_PUSH_HAMSTRING": "iso_push_hamstring",
}

_IMTP_MAP = _build_force_time_metric_map(_IMTP_STORAGE_MAPPING)
_ISO_PUSH_HAMSTRING_MAP = _build_force_time_metric_map(_ISO_PUSH_HAMSTRING_STORAGE_MAPPING)

TEST_MAPS = {
    "CMJ": _CMJ_MAP,
    "SJ": _SJ_MAP,
    "DJ": _DJ_MAP,
    "IMTP": _IMTP_MAP,
    "ISO_PUSH_HAMSTRING": _ISO_PUSH_HAMSTRING_MAP,
}
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
    **{col: col.lower() for col in _IMTP_LEGACY_STORAGE_ALIASES},
}
SUPABASE_EVALUATIONS_TABLE = "evaluations"

UPLOAD_CONTRACTS: dict[str, dict[str, object]] = {
    "questionnaire_raw": {
        "label": "Questionnaire Raw CSV",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Questionnaire Raw Export (.csv)",
        "examples": ("questionnaire_raw.csv", "questionnaire-report-raw.csv"),
    },
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
        "label": "Rep/Load Report (legacy opcional)",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Rep/Load Report (.csv) - legacy opcional",
        "examples": ("rep_load.csv",),
    },
    "raw_workouts": {
        "label": "Raw Data Report - Workouts",
        "extensions": ("csv",),
        "expected_format": "TeamBuildr Raw Data Report - Workouts (.csv) - fuente oficial para carga externa",
        "examples": ("raw_workouts.csv",),
    },
    "session_notes": {
        "label": "Opt-outs / Session Notes",
        "extensions": ("pdf",),
        "expected_format": "TeamBuildr Opt-Outs / Session Notes PDF (.pdf)",
        "examples": ("opt_outs.pdf", "session_notes.pdf"),
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
        "examples": ("cmj.xlsx", "sj.xlsx", "dj.xlsx", "imtp.xlsx", "iso_push_hamstring.xlsx"),
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
    sleep = _safe_float(sueno)
    stress = _safe_float(estres)
    pain = _safe_float(dolor)
    if sleep is None and stress is None and pain is None:
        return None

    # Higher score should represent better wellness: sleep contributes positively,
    # while stress and pain are inverted on the observed 0-10 TeamBuildr scale.
    score = 0.0
    if sleep is not None:
        score += max(0.0, min(10.0, sleep))
    if stress is not None:
        score += max(0.0, 10.0 - max(0.0, min(10.0, stress)))
    if pain is not None:
        score += max(0.0, 10.0 - max(0.0, min(10.0, pain)))
    return score


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


def _match_columns_case_insensitive(
    columns: pd.Index | list[str],
    expected: list[str],
) -> dict[str, str] | None:
    lookup = {str(column).strip().lower(): str(column) for column in columns}
    resolved: dict[str, str] = {}
    for column_name in expected:
        matched = lookup.get(column_name.strip().lower())
        if matched is None:
            return None
        resolved[column_name] = matched
    return resolved


def _clean_numeric_text(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "--": pd.NA})
    )


def _parse_completion_percent_series(series: pd.Series) -> pd.Series:
    cleaned = (
        _clean_numeric_text(series)
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _is_completion_aggregate_row(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    return normalized in {"average", "avg", "total"}


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


QUESTIONNAIRE_RAW_ID_MAP: dict[int, str] = {
    103496: "RPE",
    103497: "Duration_min",
    103219: "Sueno_hs",
    103227: "Estres",
    103498: "Dolor",
}


def _read_binary_content(file_or_buffer) -> bytes:
    if isinstance(file_or_buffer, (str, os.PathLike, Path)):
        return Path(file_or_buffer).read_bytes()

    if hasattr(file_or_buffer, "getvalue"):
        raw_bytes = file_or_buffer.getvalue()
    elif hasattr(file_or_buffer, "read"):
        raw_bytes = file_or_buffer.read()
        if hasattr(file_or_buffer, "seek"):
            file_or_buffer.seek(0)
    else:
        raise ValueError("No se pudo leer el archivo de cuestionarios raw.")

    if isinstance(raw_bytes, str):
        return raw_bytes.encode("utf-8", errors="replace")
    if raw_bytes is None:
        raise ValueError("El archivo de cuestionarios raw esta vacio.")
    return raw_bytes


def _clean_pdf_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u00a0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _decode_pdf_literal(raw: bytes) -> str:
    payload = raw[1:-1]
    text = payload.decode("latin-1", errors="ignore")
    text = (
        text.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\n")
        .replace(r"\t", "\t")
    )
    return text


def _extract_text_from_pdf_stream(stream_bytes: bytes) -> str:
    parts: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\)])*\)", stream_bytes, flags=re.S):
        text = _decode_pdf_literal(match.group(0))
        if text.strip():
            parts.append(text.strip())
    for match in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>", stream_bytes):
        hex_text = re.sub(rb"\s+", b"", match.group(1))
        try:
            decoded = bytes.fromhex(hex_text.decode("ascii")).decode("utf-16-be", errors="ignore")
        except Exception:
            continue
        if decoded.strip():
            parts.append(decoded.strip())
    return "\n".join(parts)


def _extract_pdf_text_pages_fallback(raw_bytes: bytes) -> list[tuple[int, str]]:
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", raw_bytes, flags=re.S):
        stream = match.group(1).strip(b"\r\n")
        prefix = raw_bytes[max(0, match.start() - 300):match.start()]
        if b"ASCII85Decode" in prefix:
            try:
                ascii_stream = stream.strip()
                if ascii_stream.startswith(b"<~") and ascii_stream.endswith(b"~>"):
                    stream = base64.a85decode(ascii_stream, adobe=True)
                else:
                    stream = base64.a85decode(ascii_stream.removesuffix(b"~>"))
            except Exception:
                pass
        if b"FlateDecode" in prefix:
            try:
                stream = zlib.decompress(stream)
            except Exception:
                pass
        text = _extract_text_from_pdf_stream(stream)
        if text.strip():
            chunks.append(text)
    return [(1, "\n".join(chunks))] if chunks else []


def _extract_pdf_text_pages(file_or_buffer) -> list[tuple[int, str]]:
    raw_bytes = _read_binary_content(file_or_buffer)
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw_bytes))
        pages = [
            (idx, _clean_pdf_text(page.extract_text() or ""))
            for idx, page in enumerate(reader.pages, start=1)
        ]
        if any(text for _, text in pages):
            return pages
    except Exception:
        pass
    return _extract_pdf_text_pages_fallback(raw_bytes)


def _session_note_date(value: object) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    return pd.Timestamp(parsed).normalize()


def _is_session_note_date(value: object) -> bool:
    text = _clean_pdf_text(value)
    if not text:
        return False
    if _DATE_RE.match(text):
        return True
    parsed = pd.to_datetime(text, errors="coerce")
    return bool(pd.notna(parsed))


def _normalize_session_note_label(value: object) -> str | None:
    clean = _clean_pdf_text(value).strip(":").lower()
    clean = clean.replace("opt out", "opt-out")
    return _SESSION_NOTE_LABELS.get(clean)


def classify_session_note_reason(opt_out_type: object = "", explanation: object = "") -> str:
    text = f"{opt_out_type or ''} {explanation or ''}".lower()
    if re.search(r"\b(pain|sore|injur|hurt|ache|dolor|molest|lesion)\b", text):
        return "injury_or_pain"
    if re.search(r"\b(equipment|equipamiento|rack|machine|barbell|dumbbell|kettlebell|band|no db|no equipment)\b", text):
        return "lack_of_equipment"
    if re.search(r"\b(load|weight|lighter|heavier|reps?|sets?|volume|intensity|reduced|modified load|carga)\b", text):
        return "modified_load"
    if re.search(r"\b(absent|absence|missed|skipped|not completed|did not complete|no exercises completed|ausente|falta)\b", text):
        return "absence_or_not_completed"
    if re.search(r"\b(instead|substitut|swap|swapped|replaced|changed|change|technical|tecnica|tecnico)\b", text):
        return "technical_change"
    return "other"


def extract_replacement_exercise(explanation: object) -> object:
    text = _clean_pdf_text(explanation)
    if not text:
        return pd.NA
    patterns = [
        r"(?:^|[.;]\s*)(?P<replacement>[A-Z][A-Za-z0-9 /+\-()]{2,80}?)\s+(?:was\s+)?completed instead\b",
        r"\b(?:completed|did)\s+(?P<replacement>[A-Z][A-Za-z0-9 /+\-()]{2,80}?)\s+instead\b",
        r"\b(?:substituted|replaced|swapped)\s+(?:with|to|for)\s+(?P<replacement>[^.;\n]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        replacement = _clean_pdf_text(match.group("replacement")).strip(" .,-")
        if replacement:
            return replacement
    return pd.NA


def _session_note_row(raw_row: dict[str, object], *, source: str, source_page: int) -> dict[str, object] | None:
    raw_text = _clean_pdf_text(raw_row.get("Raw_Text") or " | ".join(str(value) for value in raw_row.values() if value))
    if not raw_text or "no exercises completed yet" in raw_text.lower():
        return None

    athlete = _clean_pdf_text(raw_row.get("Athlete"))
    assigned_exercise = _clean_pdf_text(raw_row.get("Assigned_Exercise"))
    opt_out_type = _clean_pdf_text(raw_row.get("Opt_Out_Type"))
    explanation = _clean_pdf_text(raw_row.get("Explanation_Text"))
    date_recorded = _session_note_date(raw_row.get("Date"))
    date_assigned = _session_note_date(raw_row.get("Date_Assigned"))

    if not athlete or pd.isna(date_recorded):
        return None
    if not any([assigned_exercise, opt_out_type, explanation]):
        return None

    return {
        "Date": date_recorded,
        "Athlete": athlete.title(),
        "Date_Assigned": date_assigned,
        "Assigned_Exercise": assigned_exercise or pd.NA,
        "Opt_Out_Type": opt_out_type or pd.NA,
        "Reason_Category": classify_session_note_reason(opt_out_type, explanation),
        "Replacement_Exercise": extract_replacement_exercise(explanation),
        "Explanation_Text": explanation or pd.NA,
        "Source": source,
        "Source_Page": int(source_page),
        "Raw_Text": raw_text,
    }


def _parse_labeled_session_notes(lines: list[str], *, source: str, source_page: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current: dict[str, object] = {}
    current_field: str | None = None

    def flush() -> None:
        nonlocal current, current_field
        row = _session_note_row(current, source=source, source_page=source_page)
        if row is not None:
            rows.append(row)
        current = {}
        current_field = None

    label_pattern = re.compile(
        r"^(Athlete|Date Recorded|Assigned Exercise|Date Assigned|Opt[- ]Out Type|Explanation)\s*:?\s*(.*)$",
        flags=re.IGNORECASE,
    )
    for line in lines:
        match = label_pattern.match(line)
        if match:
            field = _normalize_session_note_label(match.group(1))
            if field == "Athlete" and current:
                flush()
            current_field = field
            if field:
                current[field] = _clean_pdf_text(match.group(2))
            continue
        if current_field and current:
            previous = _clean_pdf_text(current.get(current_field))
            current[current_field] = _clean_pdf_text(f"{previous} {line}")
    if current:
        flush()
    return rows


def _parse_table_session_notes(lines: list[str], *, source: str, source_page: int) -> list[dict[str, object]]:
    skip_labels = {label.lower() for label in _SESSION_NOTE_LABELS}
    usable = [
        line for line in lines
        if line.lower().strip(":") not in skip_labels
        and not line.lower().startswith("page ")
    ]
    rows: list[dict[str, object]] = []
    idx = 0
    while idx < len(usable) - 2:
        athlete = usable[idx]
        if _is_session_note_date(athlete) or not _is_session_note_date(usable[idx + 1]):
            idx += 1
            continue

        assigned_date_idx = None
        for candidate_idx in range(idx + 2, min(idx + 8, len(usable))):
            if _is_session_note_date(usable[candidate_idx]):
                assigned_date_idx = candidate_idx
                break
        if assigned_date_idx is None or assigned_date_idx + 1 >= len(usable):
            idx += 1
            continue

        next_idx = len(usable)
        for candidate_idx in range(assigned_date_idx + 2, len(usable) - 1):
            if not _is_session_note_date(usable[candidate_idx]) and _is_session_note_date(usable[candidate_idx + 1]):
                next_idx = candidate_idx
                break

        raw_row = {
            "Athlete": athlete,
            "Date": usable[idx + 1],
            "Assigned_Exercise": " ".join(usable[idx + 2:assigned_date_idx]),
            "Date_Assigned": usable[assigned_date_idx],
            "Opt_Out_Type": usable[assigned_date_idx + 1],
            "Explanation_Text": " ".join(usable[assigned_date_idx + 2:next_idx]),
            "Raw_Text": " | ".join(usable[idx:next_idx]),
        }
        row = _session_note_row(raw_row, source=source, source_page=source_page)
        if row is not None:
            rows.append(row)
        idx = max(next_idx, idx + 1)
    return rows


def _normalize_session_notes_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SESSION_NOTE_COLUMNS)
    df = pd.DataFrame(rows)
    for column in SESSION_NOTE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df = df[SESSION_NOTE_COLUMNS].copy()
    for column in ["Date", "Date_Assigned"]:
        df[column] = pd.to_datetime(df[column], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Date", "Athlete"])
    text_cols = [
        "Athlete",
        "Assigned_Exercise",
        "Opt_Out_Type",
        "Reason_Category",
        "Replacement_Exercise",
        "Explanation_Text",
        "Source",
        "Raw_Text",
    ]
    for column in text_cols:
        df[column] = df[column].map(lambda value: pd.NA if value is None or pd.isna(value) or not _clean_pdf_text(value) else _clean_pdf_text(value))
    df["Athlete"] = df["Athlete"].astype(str).str.strip().str.title()
    df["Source_Page"] = pd.to_numeric(df["Source_Page"], errors="coerce").fillna(1).astype(int)
    dedupe_cols = ["Athlete", "Date", "Date_Assigned", "Assigned_Exercise", "Opt_Out_Type", "Explanation_Text"]
    existing = [column for column in dedupe_cols if column in df.columns]
    if existing:
        df = df.drop_duplicates(subset=existing, keep="last")
    return df.sort_values(["Date", "Athlete"], ascending=[False, True]).reset_index(drop=True)


def parse_session_notes_pdf(file) -> pd.DataFrame:
    contract = UPLOAD_CONTRACTS["session_notes"]
    _ensure_supported_extension(
        file,
        str(contract["label"]),
        tuple(contract["extensions"]),
    )
    source = _resolve_filename(file) or "TeamBuildr session notes PDF"
    pages = _extract_pdf_text_pages(file)
    rows: list[dict[str, object]] = []
    for page_number, text in pages:
        lines = [
            _clean_pdf_text(line)
            for line in str(text or "").splitlines()
            if _clean_pdf_text(line)
        ]
        if not lines:
            continue
        rows.extend(_parse_labeled_session_notes(lines, source=source, source_page=page_number))
        rows.extend(_parse_table_session_notes(lines, source=source, source_page=page_number))
    result = _normalize_session_notes_df(rows)
    if result.empty:
        raise ValueError(
            "Opt-outs / Session Notes: no se detectaron filas reales de opt-out en el PDF. "
            "Verifica que el reporte incluya registros y no solo bloques 'No Exercises Completed Yet'."
        )
    return result


def _first_valid(series: pd.Series):
    valid = series.dropna()
    return valid.iloc[0] if not valid.empty else pd.NA


def parse_questionnaire_raw_csv(filepath_or_buffer) -> tuple[pd.DataFrame, pd.DataFrame]:
    contract = UPLOAD_CONTRACTS["questionnaire_raw"]
    _ensure_supported_extension(
        filepath_or_buffer,
        str(contract["label"]),
        tuple(contract["extensions"]),
    )

    raw_bytes = _read_binary_content(filepath_or_buffer)
    first_error = None
    dataframe = None
    for encoding, encoding_errors in (("utf-8", "replace"), ("latin-1", "replace")):
        try:
            dataframe = pd.read_csv(
                BytesIO(raw_bytes),
                encoding=encoding,
                encoding_errors=encoding_errors,
            )
            break
        except Exception as exc:
            if first_error is None:
                first_error = exc

    if dataframe is None:
        raise ValueError(
            "Questionnaire Raw CSV: no se pudo leer el archivo como CSV valido."
        ) from first_error

    dataframe.columns = [str(col).strip() for col in dataframe.columns]
    required_columns = {
        "nombre": ["First Name"],
        "apellido": ["Last Name"],
        "workout_id": ["Assigned Workout ID"],
        "pregunta_id": ["Question ID"],
        "resultado": ["Result"],
        "timestamp": ["Timestamp Complete"],
    }
    missing_map = {
        label: options
        for label, options in required_columns.items()
        if not any(option in dataframe.columns for option in options)
    }
    if missing_map:
        raise ValueError(_missing_columns_message("Questionnaire Raw CSV", dataframe, missing_map))

    first_name = dataframe["First Name"].fillna("").astype(str).map(lambda value: html.unescape(value).strip())
    last_name = dataframe["Last Name"].fillna("").astype(str).map(lambda value: html.unescape(value).strip())
    athlete = (first_name + " " + last_name).str.replace(r"\s+", " ", regex=True).str.strip()
    dataframe["Athlete"] = athlete.mask(athlete.eq(""), pd.NA)

    complete_ts = pd.to_numeric(dataframe["Timestamp Complete"], errors="coerce")
    dataframe["Date"] = pd.to_datetime(complete_ts, unit="s", errors="coerce").dt.normalize()
    dataframe["Question_ID"] = pd.to_numeric(dataframe["Question ID"], errors="coerce").astype("Int64")
    dataframe["Mapped_Field"] = dataframe["Question_ID"].map(QUESTIONNAIRE_RAW_ID_MAP)

    assigned_workout = dataframe["Assigned Workout ID"].astype(str).str.strip()
    assigned_workout = assigned_workout.mask(assigned_workout.isin({"", "nan", "None"}), pd.NA)
    if "Response ID" in dataframe.columns:
        response_id = dataframe["Response ID"].astype(str).str.strip()
        response_id = response_id.mask(response_id.isin({"", "nan", "None"}), pd.NA)
        assigned_workout = assigned_workout.fillna(response_id)
    fallback_ids = pd.Series(range(len(dataframe)), index=dataframe.index).map(lambda idx: f"row-{idx}")
    dataframe["Workout_Key"] = assigned_workout.fillna(fallback_ids)

    result_text = dataframe["Result"].fillna("").astype(str).map(lambda value: html.unescape(value).strip())
    dataframe["Result_num"] = pd.to_numeric(result_text.str.replace(",", ".", regex=False), errors="coerce")

    filtered = dataframe[
        dataframe["Athlete"].notna()
        & dataframe["Date"].notna()
        & dataframe["Mapped_Field"].notna()
    ].copy()

    if filtered.empty:
        raise ValueError(
            "Questionnaire Raw CSV: no se detectaron filas validas con Athlete, Date y Question ID reconocido."
        )

    pivot_df = (
        filtered.pivot_table(
            index=["Athlete", "Date", "Workout_Key"],
            columns="Mapped_Field",
            values="Result_num",
            aggfunc="first",
        )
        .reset_index()
    )
    pivot_df.columns.name = None

    rpe_columns = ["RPE", "Duration_min"]
    present_rpe_columns = [column for column in rpe_columns if column in pivot_df.columns]
    has_rpe_content = any(
        column in pivot_df.columns and pivot_df[column].notna().any()
        for column in rpe_columns
    )
    if not has_rpe_content:
        raise ValueError(
            "Questionnaire Raw CSV: no se detectaron respuestas validas de RPE/Time "
            "(Question IDs 103496 y 103497)."
        )

    rpe_sessions = pivot_df[pivot_df[present_rpe_columns].notna().any(axis=1)].copy()
    for column in rpe_columns:
        if column not in rpe_sessions.columns:
            rpe_sessions[column] = pd.NA
    rpe_df = (
        rpe_sessions.groupby(["Date", "Athlete"], as_index=False)
        .agg({"RPE": "mean", "Duration_min": "mean"})
        .sort_values(["Date", "Athlete"])
        .reset_index(drop=True)
    )
    valid_srpe_mask = (
        rpe_df["RPE"].notna()
        & rpe_df["Duration_min"].notna()
        & (rpe_df["RPE"] > 0)
        & (rpe_df["Duration_min"] > 0)
    )
    rpe_df["sRPE"] = pd.NA
    rpe_df.loc[valid_srpe_mask, "sRPE"] = (
        rpe_df.loc[valid_srpe_mask, "RPE"] * rpe_df.loc[valid_srpe_mask, "Duration_min"]
    )
    rpe_df = rpe_df[["Date", "Athlete", "RPE", "Duration_min", "sRPE"]]
    for column in ["RPE", "Duration_min", "sRPE"]:
        rpe_df[column] = pd.to_numeric(rpe_df[column], errors="coerce")
    if rpe_df.empty:
        raise ValueError(
            "Questionnaire Raw CSV: no se pudieron construir filas validas para rpe_df."
        )
    rpe_df.attrs["source_session_count"] = int(len(rpe_sessions))

    wellness_columns = ["Sueno_hs", "Estres", "Dolor"]
    present_wellness_columns = [column for column in wellness_columns if column in pivot_df.columns]
    wellness_df = pd.DataFrame(columns=["Date", "Athlete", "Sueno_hs", "Estres", "Dolor", "Wellness_Score"])
    if present_wellness_columns:
        wellness_sessions = pivot_df[pivot_df[present_wellness_columns].notna().any(axis=1)].copy()
        if not wellness_sessions.empty:
            agg_map = {column: _first_valid for column in present_wellness_columns}
            wellness_df = (
                wellness_sessions.groupby(["Date", "Athlete"], as_index=False)
                .agg(agg_map)
                .sort_values(["Date", "Athlete"])
                .reset_index(drop=True)
            )
            for column in wellness_columns:
                if column not in wellness_df.columns:
                    wellness_df[column] = pd.NA
            valid_wellness_mask = wellness_df[wellness_columns].notna().all(axis=1)
            wellness_df["Wellness_Score"] = pd.NA
            wellness_df.loc[valid_wellness_mask, "Wellness_Score"] = wellness_df.loc[
                valid_wellness_mask, wellness_columns
            ].apply(
                lambda row: _wellness_score(row.get("Sueno_hs"), row.get("Estres"), row.get("Dolor")),
                axis=1,
            )
            for column in wellness_columns + ["Wellness_Score"]:
                wellness_df[column] = pd.to_numeric(wellness_df[column], errors="coerce")
            wellness_df = wellness_df[["Date", "Athlete", "Sueno_hs", "Estres", "Dolor", "Wellness_Score"]]
    wellness_session_count = 0
    if present_wellness_columns:
        wellness_session_count = int(
            len(pivot_df[pivot_df[present_wellness_columns].notna().any(axis=1)])
        )
    wellness_df.attrs["source_session_count"] = wellness_session_count

    return rpe_df, wellness_df


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
    percent_options = ["Percent", "Pct", "Percentage", "Porcentaje"]

    date_col = next((col for col in date_options if col in df.columns), None)
    assigned_col = next((col for col in assigned_options if col in df.columns), None)
    completed_col = next((col for col in completed_options if col in df.columns), None)
    athlete_col = next((col for col in athlete_options if col in df.columns), None)
    percent_col = next((col for col in percent_options if col in df.columns), None)
    summary_columns = _match_columns_case_insensitive(
        df.columns,
        ["Athlete", "Assigned", "Completed", "Percent"],
    )

    if date_col is None and summary_columns is not None:
        result = df.rename(
            columns={
                summary_columns["Athlete"]: "Athlete",
                summary_columns["Assigned"]: "Assigned",
                summary_columns["Completed"]: "Completed",
                summary_columns["Percent"]: "Percent",
            }
        ).copy()
        result["Athlete"] = result["Athlete"].astype(str).str.strip()
        result = result[~result["Athlete"].map(_is_completion_aggregate_row)]
        result["Athlete"] = result["Athlete"].str.title()
        result["Assigned"] = pd.to_numeric(_clean_numeric_text(result["Assigned"]), errors="coerce")
        result["Completed"] = pd.to_numeric(_clean_numeric_text(result["Completed"]), errors="coerce")
        result["Pct"] = _parse_completion_percent_series(result["Percent"])
        missing_pct = result["Pct"].isna()
        computed_pct = (result["Completed"] / result["Assigned"].where(result["Assigned"] > 0)) * 100.0
        result.loc[missing_pct, "Pct"] = computed_pct.loc[missing_pct]
        result["Date"] = pd.NaT
        result["completion_scope"] = "uploaded_period_total"
        result["source_type"] = "completion_report_summary"
        result = result[result["Athlete"].notna() & result["Athlete"].ne("")]
        if result.empty:
            raise ValueError(
                "Completion Report: el archivo no contiene atletas reales luego de filtrar filas agregadas."
            )
        _require_numeric_content(result, "Completion Report", "Assigned", "Assigned/Asignado")
        _require_numeric_content(result, "Completion Report", "Completed", "Completed/Completado")
        return result.reset_index(drop=True)

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
    if percent_col and percent_col in df.columns:
        parsed_pct = _parse_completion_percent_series(df[percent_col])
        df["Pct"] = parsed_pct
    df = _require_valid_dates(df, "Completion Report", "Date", date_col)
    _require_numeric_content(df, "Completion Report", "Assigned", "Assigned/Asignado")
    _require_numeric_content(df, "Completion Report", "Completed", "Completed/Completado")
    computed_pct = (df["Completed"] / df["Assigned"].where(df["Assigned"] > 0)) * 100
    if "Pct" in df.columns:
        df["Pct"] = df["Pct"].fillna(computed_pct)
    else:
        df["Pct"] = computed_pct
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


def _tag_category(token: str) -> str | None:
    return _TAG_CATEGORY_LOOKUP.get(str(token).strip().lower())


def _choose_specific_category(categories: list[str]) -> str:
    if not categories:
        return "untagged"
    return min(categories, key=lambda category: CATEGORY_SPECIFICITY_ORDER.get(category, 97))


def _infer_exercise_category(exercise_name: str) -> str:
    exercise_text = str(exercise_name or "").strip().lower()
    if not exercise_text:
        return "untagged"

    for category in KEYWORD_PRIORITY_ORDER:
        for keyword in EXERCISE_KEYWORDS[category]:
            if keyword.lower() in exercise_text:
                return category
    return "untagged"


def classify_exercise(tag: str, exercise_name: str) -> str:
    cleaned_tag = str(tag or "").strip()
    if cleaned_tag:
        direct_category = _tag_category(cleaned_tag)
        if direct_category:
            return direct_category

        if "/" in cleaned_tag:
            token_categories = [_tag_category(token) for token in _split_tag_tokens(cleaned_tag)]
            token_categories = [category for category in token_categories if category]
            if token_categories:
                return _choose_specific_category(token_categories)

        token_categories = [_tag_category(token) for token in _split_tag_tokens(cleaned_tag)]
        token_categories = [category for category in token_categories if category]
        if token_categories:
            return _choose_specific_category(token_categories)

    return _infer_exercise_category(exercise_name)


def _resolve_stimulus_metadata(tag, exercise_name) -> tuple[str, str, bool, bool]:
    cleaned_tag = "" if pd.isna(tag) else str(tag).strip()
    category = classify_exercise(cleaned_tag, exercise_name)
    is_invalid = category == "invalid"
    is_untagged = category == "untagged"

    tokens = _split_tag_tokens(cleaned_tag)
    if tokens:
        matched_tokens = [token for token in tokens if _tag_category(token) == category]
        if matched_tokens:
            category_label = matched_tokens[0]
        elif is_invalid:
            category_label = tokens[0]
        else:
            category_label = CATEGORY_DISPLAY_LABELS.get(category, category)
    else:
        category_label = CATEGORY_DISPLAY_LABELS.get(category, category)

    return category, category_label, is_invalid, is_untagged


def _first_positive(series: pd.Series, fallback: pd.Series) -> pd.Series:
    if series is None:
        return fallback
    if fallback is None:
        return series
    return series.where(series.notna() & (series > 0), fallback)


PREPARED_RAW_WORKOUT_FLAG = "threshold_prepared_raw_workouts"
PREPARED_RAW_WORKOUT_COLUMNS = {
    "Assigned Date",
    "Date",
    "Category",
    "stimulus_category",
    "Volume_Load",
    "Volume_Load_legacy",
    "Volume_Load_kg",
    "Contacts",
    "Exposures",
    "Distance_m",
    "is_invalid",
    "is_untagged",
}


def is_prepared_raw_workouts_df(raw_df: pd.DataFrame | None) -> bool:
    if raw_df is None:
        return False
    if bool(getattr(raw_df, "attrs", {}).get(PREPARED_RAW_WORKOUT_FLAG)):
        return True
    return PREPARED_RAW_WORKOUT_COLUMNS.issubset(raw_df.columns)


def _mark_prepared_raw_workouts_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is not None:
        df.attrs[PREPARED_RAW_WORKOUT_FLAG] = True
    return df


def prepare_raw_workouts_df(raw_df: pd.DataFrame | None) -> pd.DataFrame | None:
    if raw_df is None:
        return None
    if is_prepared_raw_workouts_df(raw_df):
        return _mark_prepared_raw_workouts_df(raw_df.copy())

    df = raw_df.copy()
    column_aliases = {
        "Assigned Date": ["Date", "Workout Date", "Fecha"],
        "Athlete": ["Name", "Player", "Athlete Name", "Atleta"],
        "Tags": ["Tag", "Labels"],
        "Exercise": ["Exercise Name", "Movement", "Ejercicio"],
        "Exercise Name": ["Exercise", "Movement", "Ejercicio"],
        "Set Number": ["Set #", "Set No", "Set No.", "SetNumber"],
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
            "Distance_m",
            "is_invalid",
            "is_untagged",
        ]:
            if column not in df.columns:
                df[column] = pd.Series(dtype=object if column in {"Category", "stimulus_category"} else "float64")
        if "is_invalid" in df.columns:
            df["is_invalid"] = df["is_invalid"].astype(bool)
        if "is_untagged" in df.columns:
            df["is_untagged"] = df["is_untagged"].astype(bool)
        return _mark_prepared_raw_workouts_df(df)

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
    if "Exercise Name" in df.columns:
        df["Exercise Name"] = (
            df["Exercise Name"]
            .where(df["Exercise Name"].notna(), "")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
        )
    if "Exercise" in df.columns and "Exercise Name" not in df.columns:
        df["Exercise Name"] = df["Exercise"]
    elif "Exercise Name" in df.columns and "Exercise" not in df.columns:
        df["Exercise"] = df["Exercise Name"]
    if "Set Number" in df.columns:
        df["Set Number"] = pd.to_numeric(df["Set Number"], errors="coerce")
    if "Tags" in df.columns:
        df["Tags"] = (
            df["Tags"]
            .where(df["Tags"].notna(), "")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
        )

    tag_series = df["Tags"] if "Tags" in df.columns else pd.Series("", index=df.index, dtype=object)
    exercise_series = (
        df["Exercise Name"]
        if "Exercise Name" in df.columns
        else df.get("Exercise", pd.Series("", index=df.index, dtype=object))
    )
    tag_info = pd.Series(
        [
            _resolve_stimulus_metadata(tag_value, exercise_value)
            for tag_value, exercise_value in zip(tag_series.tolist(), exercise_series.tolist())
        ],
        index=df.index,
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
    df["Distance_m"] = pd.Series(index=df.index, dtype="float64")

    strength_mask = df["stimulus_category"].eq("strength_loaded")
    valid_strength = strength_mask & result.gt(0) & reps.gt(0)
    df.loc[valid_strength, "Volume_Load_kg"] = (result.loc[valid_strength] * reps.loc[valid_strength]).round(3)

    contacts_mask = df["stimulus_category"].isin(["plyo_jump", "landing_mechanics"]) & reps.gt(0)
    df.loc[contacts_mask, "Contacts"] = reps.loc[contacts_mask]

    dlo_mask = df["stimulus_category"].eq("olympic_derivatives") & reps.gt(0)
    # DLO se monitorea por exposicion tecnica, no por tonelaje acumulado.
    df.loc[dlo_mask, "Exposures"] = reps.loc[dlo_mask]

    sprint_mask = df["stimulus_category"].eq("sprint_cod")
    valid_sprint = sprint_mask & reps.gt(0)
    df.loc[valid_sprint, "Exposures"] = reps.loc[valid_sprint]
    exercise_name_series = (
        df["Exercise Name"].fillna("").astype(str)
        if "Exercise Name" in df.columns
        else pd.Series("", index=df.index, dtype=object)
    )
    sprint_distance_mask = valid_sprint & result.gt(0) & exercise_name_series.str.contains(_SPRINT_DISTANCE_RE)
    df.loc[sprint_distance_mask, "Distance_m"] = (
        result.loc[sprint_distance_mask] * reps.loc[sprint_distance_mask]
    ).round(3)

    iso_mask = df["stimulus_category"].eq("iso")
    df.loc[iso_mask, "Exposures"] = _first_positive(duration_s, sets).loc[iso_mask]

    core_mask = df["stimulus_category"].eq("core_stability")
    df.loc[core_mask, "Exposures"] = _first_positive(sets, reps).loc[core_mask]

    mobility_mask = df["stimulus_category"].eq("mobility_prehab")
    df.loc[mobility_mask, "Exposures"] = _first_positive(sets, reps).loc[mobility_mask]

    df["is_invalid"] = df["is_invalid"].astype(bool)
    df["is_untagged"] = df["is_untagged"].astype(bool)
    return _mark_prepared_raw_workouts_df(df)


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


def _is_missing_evaluation_value(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalize_legacy_imtp_rfd_aliases_record(record: dict[str, object]) -> dict[str, object]:
    result = dict(record)
    for legacy_field, canonical_field in _IMTP_LEGACY_STORAGE_ALIASES.items():
        if not _is_missing_evaluation_value(result.get(canonical_field)):
            continue
        legacy_value = result.get(legacy_field)
        if _is_missing_evaluation_value(legacy_value):
            continue
        result[canonical_field] = legacy_value
    return result


def _normalize_legacy_imtp_rfd_aliases_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()

    result = df.copy()
    for legacy_field, canonical_field in _IMTP_LEGACY_STORAGE_ALIASES.items():
        if legacy_field not in result.columns:
            continue
        if canonical_field not in result.columns:
            result[canonical_field] = pd.Series([None] * len(result), index=result.index, dtype=object)

        legacy_values = pd.to_numeric(result[legacy_field], errors="coerce")
        canonical_values = pd.to_numeric(result[canonical_field], errors="coerce")
        fill_mask = canonical_values.isna() & legacy_values.notna()
        if fill_mask.any():
            result.loc[fill_mask, canonical_field] = legacy_values.loc[fill_mask]
    return result


def _parse_involution_force_time_forceplate(file_bytes: bytes, test_id: str) -> dict[str, object]:
    parsed = parse_involution_summary_excel(file_bytes, test_id=test_id)
    storage_mapping = get_storage_mapping(test_id)
    result: dict[str, object] = {"test_type": str(test_id or "").strip().upper()}
    for normalized_field, storage_field in storage_mapping.items():
        value = parsed["metrics"].get(normalized_field)
        if value is None:
            continue
        result[storage_field] = value
        result[f"{storage_field}_reps"] = [value]
    return result


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
    resolved_test_type = str(test_type or "").strip().upper()
    force_time_test_id = _FORCE_TIME_TEST_TYPE_TO_TEST_ID.get(resolved_test_type)
    if force_time_test_id:
        try:
            return _parse_involution_force_time_forceplate(file_bytes, force_time_test_id)
        except (ValueError, InvalidFileException, OSError, zipfile.BadZipFile):
            pass
    try:
        raw = _read_forceplate_xlsx(file_bytes)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(
            "El archivo de evaluacion debe ser un .xlsx valido exportado desde la plataforma de fuerza."
        ) from exc
    metric_map = TEST_MAPS.get(resolved_test_type, TEST_MAPS.get(test_type, {}))
    result: dict[str, object] = {"test_type": resolved_test_type or test_type}
    for metric_name, (col_name, agg) in metric_map.items():
        if metric_name in raw:
            result[col_name] = _extract_best(raw[metric_name], agg)
            result[f"{col_name}_reps"] = raw[metric_name]
    return _normalize_legacy_imtp_rfd_aliases_record(result)


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
    return _normalize_legacy_imtp_rfd_aliases_frame(df)
