from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from modules.evaluation_registry import get_evaluation_spec, get_storage_mapping

NORMALIZED_TO_SUMMARY = {
    "force_max_n": "peak_force_n",
    "force_avg_n": "avg_force_n",
    "time_to_peak_s": "time_to_peak_s",
    "time_pull_s": "time_pull_s",
    "pre_tension_n": "pre_tension_n",
    "force_left_max_n": "left_force_n",
    "force_right_max_n": "right_force_n",
    "asymmetry_pct": "absolute_asymmetry_pct",
    "force_50_n": "force_50_n",
    "force_100_n": "force_100_n",
    "force_150_n": "force_150_n",
    "force_200_n": "force_200_n",
    "force_250_n": "force_250_n",
    "rfd_50_n_s": "rfd_50_n_s",
    "rfd_100_n_s": "rfd_100_n_s",
    "rfd_150_n_s": "rfd_150_n_s",
    "rfd_250_n_s": "rfd_250_n_s",
}


def _to_mapping(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            converted = value.to_dict()
            return dict(converted) if isinstance(converted, Mapping) else {}
        except Exception:
            return {}
    return {}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _coerce_number(value: object) -> int | float | None:
    if _is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else float(value)
    try:
        numeric = float(str(value).strip())
    except Exception:
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _resolve_spec(spec: dict[str, object] | None, test_id: str) -> dict[str, object]:
    if isinstance(spec, Mapping):
        return dict(spec)
    return get_evaluation_spec(test_id) or {}


def _nested_metrics(source: dict[str, object]) -> dict[str, object]:
    metrics = source.get("metrics")
    if isinstance(metrics, Mapping):
        return dict(metrics)
    if hasattr(metrics, "to_dict"):
        try:
            converted = metrics.to_dict()
            return dict(converted) if isinstance(converted, Mapping) else {}
        except Exception:
            return {}
    return {}


def _pick_metric_value(
    source: dict[str, object],
    nested_metrics: dict[str, object],
    normalized_field: str,
    storage_mapping: dict[str, str],
    legacy_storage_aliases: dict[str, str],
) -> int | float | None:
    candidates = []
    if normalized_field in nested_metrics:
        candidates.append(nested_metrics.get(normalized_field))
    if normalized_field in source:
        candidates.append(source.get(normalized_field))

    storage_field = storage_mapping.get(normalized_field)
    if storage_field:
        candidates.append(source.get(storage_field))
        for legacy_field, canonical_field in legacy_storage_aliases.items():
            if canonical_field == storage_field:
                candidates.append(source.get(legacy_field))

    for candidate in candidates:
        numeric = _coerce_number(candidate)
        if numeric is not None:
            return numeric
    return None


def _pct_of_peak(value: int | float | None, peak_force_n: int | float | None) -> float | None:
    numeric_value = _coerce_number(value)
    peak = _coerce_number(peak_force_n)
    if numeric_value is None or peak is None or peak <= 0:
        return None
    return (float(numeric_value) / float(peak)) * 100.0


def _asymmetry_direction(
    left_force_n: int | float | None,
    right_force_n: int | float | None,
) -> tuple[str | None, str | None, int | float | None]:
    left = _coerce_number(left_force_n)
    right = _coerce_number(right_force_n)
    if left is None or right is None:
        return None, None, None
    if float(left) == float(right):
        return None, None, 0
    if float(left) > float(right):
        return "left", "right", _coerce_number(float(left) - float(right))
    return "right", "left", _coerce_number(float(right) - float(left))


def _basis_from_summary(summary: dict[str, object]) -> str:
    present_values = [
        summary.get("peak_force_n"),
        summary.get("avg_force_n"),
        summary.get("time_to_peak_s"),
        summary.get("time_pull_s"),
        summary.get("pre_tension_n"),
        summary.get("left_force_n"),
        summary.get("right_force_n"),
        summary.get("force_50_n"),
        summary.get("force_100_n"),
        summary.get("force_150_n"),
        summary.get("force_200_n"),
        summary.get("force_250_n"),
        summary.get("rfd_50_n_s"),
        summary.get("rfd_100_n_s"),
        summary.get("rfd_150_n_s"),
        summary.get("rfd_250_n_s"),
    ]
    has_any_data = any(_coerce_number(value) is not None for value in present_values)
    if not has_any_data:
        return "missing"
    if (
        _coerce_number(summary.get("peak_force_n")) is not None
        and bool(summary.get("has_valid_force_time"))
        and bool(summary.get("has_valid_asymmetry"))
    ):
        return "valid"
    return "partial"


def _format_number(value: object, *, digits: int = 0, unit: str = "") -> str:
    numeric = _coerce_number(value)
    if numeric is None:
        return "Sin dato"
    rendered = f"{float(numeric):.{digits}f}"
    if digits == 0:
        rendered = rendered.split(".")[0]
    return f"{rendered} {unit}".strip()


def _format_pct(value: object, *, digits: int = 1) -> str:
    numeric = _coerce_number(value)
    if numeric is None:
        return "Sin dato"
    return f"{float(numeric):.{digits}f}%"


def summarize_force_time_test(
    row_or_record: object,
    spec: dict[str, object] | None = None,
    test_id: str = "imtp",
) -> dict[str, object]:
    source = _to_mapping(row_or_record)
    resolved_test_id = str(source.get("test_id") or test_id or "").strip().lower() or "imtp"
    resolved_spec = _resolve_spec(spec, resolved_test_id)
    storage_mapping = dict(resolved_spec.get("storage_mapping", {})) if resolved_spec.get("storage_mapping") else {}
    if not storage_mapping:
        storage_mapping = get_storage_mapping(resolved_test_id)
    legacy_storage_aliases = (
        dict(resolved_spec.get("legacy_storage_aliases", {}))
        if resolved_spec.get("legacy_storage_aliases")
        else {}
    )
    nested_metrics = _nested_metrics(source)

    summary: dict[str, object] = {
        "test_id": resolved_test_id,
        "display_name": resolved_spec.get("display_name", resolved_test_id.upper()),
    }

    for normalized_field, summary_field in NORMALIZED_TO_SUMMARY.items():
        summary[summary_field] = _pick_metric_value(
            source,
            nested_metrics,
            normalized_field,
            storage_mapping,
            legacy_storage_aliases,
        )

    asymmetry_pct = _coerce_number(summary.get("absolute_asymmetry_pct"))
    summary["absolute_asymmetry_pct"] = abs(float(asymmetry_pct)) if asymmetry_pct is not None else None

    stronger_side, weaker_side, side_difference_n = _asymmetry_direction(
        summary.get("left_force_n"),
        summary.get("right_force_n"),
    )
    summary["stronger_side"] = stronger_side
    summary["weaker_side"] = weaker_side
    summary["side_difference_n"] = side_difference_n

    peak_force_n = summary.get("peak_force_n")
    summary["force_100_pct_peak"] = _pct_of_peak(summary.get("force_100_n"), peak_force_n)
    summary["force_200_pct_peak"] = _pct_of_peak(summary.get("force_200_n"), peak_force_n)
    summary["force_250_pct_peak"] = _pct_of_peak(summary.get("force_250_n"), peak_force_n)

    summary["has_valid_force_time"] = bool(
        _coerce_number(summary.get("peak_force_n")) is not None
        and any(
            _coerce_number(summary.get(field)) is not None
            for field in ("force_50_n", "force_100_n", "force_150_n", "force_200_n", "force_250_n")
        )
    )
    summary["has_valid_rfd"] = any(
        _coerce_number(summary.get(field)) is not None
        for field in ("rfd_50_n_s", "rfd_100_n_s", "rfd_150_n_s", "rfd_250_n_s")
    )
    summary["has_valid_asymmetry"] = bool(
        _coerce_number(summary.get("left_force_n")) is not None
        and _coerce_number(summary.get("right_force_n")) is not None
        and _coerce_number(summary.get("absolute_asymmetry_pct")) is not None
    )
    summary["basis"] = _basis_from_summary(summary)

    return summary


def get_force_time_points(summary: Mapping[str, object]) -> list[dict[str, object]]:
    source = _to_mapping(summary)
    return [
        {"label": "50 ms", "time_ms": 50, "value_n": _coerce_number(source.get("force_50_n"))},
        {"label": "100 ms", "time_ms": 100, "value_n": _coerce_number(source.get("force_100_n"))},
        {"label": "150 ms", "time_ms": 150, "value_n": _coerce_number(source.get("force_150_n"))},
        {"label": "200 ms", "time_ms": 200, "value_n": _coerce_number(source.get("force_200_n"))},
        {"label": "250 ms", "time_ms": 250, "value_n": _coerce_number(source.get("force_250_n"))},
        {"label": "Peak", "time_ms": None, "value_n": _coerce_number(source.get("peak_force_n"))},
    ]


def get_rfd_points(summary: Mapping[str, object]) -> list[dict[str, object]]:
    source = _to_mapping(summary)
    return [
        {"label": "RFD 50", "time_ms": 50, "value_n_s": _coerce_number(source.get("rfd_50_n_s"))},
        {"label": "RFD 100", "time_ms": 100, "value_n_s": _coerce_number(source.get("rfd_100_n_s"))},
        {"label": "RFD 150", "time_ms": 150, "value_n_s": _coerce_number(source.get("rfd_150_n_s"))},
        {"label": "RFD 250", "time_ms": 250, "value_n_s": _coerce_number(source.get("rfd_250_n_s"))},
    ]


def get_asymmetry_summary(summary: Mapping[str, object]) -> dict[str, object]:
    source = _to_mapping(summary)
    asymmetry_pct = _coerce_number(source.get("absolute_asymmetry_pct"))
    result = {
        "left_force_n": _coerce_number(source.get("left_force_n")),
        "right_force_n": _coerce_number(source.get("right_force_n")),
        "absolute_asymmetry_pct": asymmetry_pct,
        "stronger_side": source.get("stronger_side"),
        "weaker_side": source.get("weaker_side"),
        "side_difference_n": _coerce_number(source.get("side_difference_n")),
        "interpretation": "",
    }

    if asymmetry_pct is None:
        result["interpretation"] = "Sin datos suficientes para interpretar asimetria."
        return result
    if float(asymmetry_pct) < 10.0:
        result["interpretation"] = "Diferencia lateral baja/contextual."
        return result
    if float(asymmetry_pct) <= 20.0:
        result["interpretation"] = "Diferencia lateral moderada. Revisar tendencia y contexto."
        return result
    result["interpretation"] = (
        "Diferencia lateral relevante. Revisar junto con dolor, historial, fatiga y carga reciente."
    )
    return result


def _compose_asymmetry_text(source: Mapping[str, object]) -> str:
    asymmetry = get_asymmetry_summary(source)
    if asymmetry["absolute_asymmetry_pct"] is None:
        return str(asymmetry["interpretation"])
    return (
        f"Izquierda {_format_number(asymmetry['left_force_n'], digits=0, unit='N')} vs derecha "
        f"{_format_number(asymmetry['right_force_n'], digits=0, unit='N')}. "
        f"{asymmetry['interpretation']}"
    )


def interpret_imtp_force_time(summary: Mapping[str, object]) -> dict[str, object]:
    source = _to_mapping(summary)
    basis = str(source.get("basis") or "missing")

    peak_force = _coerce_number(source.get("peak_force_n"))
    if peak_force is None:
        peak_force_text = "Sin dato suficiente de Peak Force para describir la produccion maxima en la posicion de IMTP."
    else:
        peak_force_text = (
            f"Peak Force de {_format_number(peak_force, digits=0, unit='N')}: "
            "describe la produccion maxima de fuerza isometrica en la posicion de IMTP."
        )

    if source.get("has_valid_force_time"):
        pct_100 = _format_pct(source.get("force_100_pct_peak"))
        pct_200 = _format_pct(source.get("force_200_pct_peak"))
        pct_250 = _format_pct(source.get("force_250_pct_peak"))
        force_time_text = (
            "El perfil de fuerza por puntos exportados a 50, 100, 150, 200 y 250 ms describe "
            "como expresa fuerza en ventanas tempranas e intermedias antes del pico. "
            f"En esta medicion, Force@100 = {pct_100}, Force@200 = {pct_200} y Force@250 = {pct_250} del pico."
        )
    else:
        force_time_text = (
            "Faltan puntos suficientes del perfil de fuerza exportado para describir con claridad "
            "la expresion temporal de fuerza antes del pico."
        )

    if source.get("has_valid_rfd"):
        rfd_text = (
            "La RFD describe la tasa de desarrollo de fuerza en las ventanas exportadas de 50, 100, 150 y 250 ms. "
            "Sin TE o umbral de confiabilidad propio, conviene interpretarla con cautela y como apoyo descriptivo."
        )
    else:
        rfd_text = (
            "No hay suficientes puntos de RFD para una lectura completa. Cuando se utilice, la RFD debe "
            "interpretarse con cautela si no hay TE o umbral de confiabilidad propio."
        )

    asymmetry_text = _compose_asymmetry_text(source)

    decision_note = (
        "Usar esta lectura como descripcion del perfil IMTP y combinarla con tendencia, contexto del test "
        "y estado del atleta. No tomar decisiones fuertes basadas solo en RFD cuando no hay TE disponible."
    )

    return {
        "title": "IMTP force-time",
        "peak_force_text": peak_force_text,
        "force_time_text": force_time_text,
        "rfd_text": rfd_text,
        "asymmetry_text": asymmetry_text,
        "decision_note": decision_note,
        "basis": basis,
    }


def interpret_hamstring_force_time(summary: Mapping[str, object]) -> dict[str, object]:
    source = _to_mapping(summary)
    basis = str(source.get("basis") or "missing")

    peak_force = _coerce_number(source.get("peak_force_n"))
    if peak_force is None:
        peak_force_text = (
            "Sin dato suficiente de Peak Force para describir la capacidad isometrica especifica "
            "de la cadena posterior y los flexores de rodilla en esta posicion."
        )
    else:
        peak_force_text = (
            f"Peak Force de {_format_number(peak_force, digits=0, unit='N')}: "
            "describe la capacidad isometrica especifica de la cadena posterior y los flexores "
            "de rodilla en esta posicion de ISO Push bilateral."
        )

    if source.get("has_valid_force_time"):
        pct_100 = _format_pct(source.get("force_100_pct_peak"))
        pct_200 = _format_pct(source.get("force_200_pct_peak"))
        pct_250 = _format_pct(source.get("force_250_pct_peak"))
        force_time_text = (
            "El perfil de fuerza por puntos exportados a 50, 100, 150, 200 y 250 ms describe "
            "la expresion local de fuerza en ventanas tempranas e intermedias antes del pico. "
            f"En esta medicion, Force@100 = {pct_100}, Force@200 = {pct_200} y Force@250 = {pct_250} del pico."
        )
    else:
        force_time_text = (
            "Faltan puntos suficientes del perfil de fuerza exportado para describir con claridad "
            "la expresion local de fuerza antes del pico."
        )

    if source.get("has_valid_rfd"):
        rfd_text = (
            "La RFD describe la tasa de desarrollo de fuerza en las ventanas exportadas de 50, 100, 150 y 250 ms. "
            "Sin TE especifico de este test, conviene interpretarla con cautela y como apoyo descriptivo."
        )
    else:
        rfd_text = (
            "No hay suficientes puntos de RFD para una lectura completa. Cuando se utilice, la RFD debe "
            "interpretarse con cautela si no hay TE especifico de este test."
        )

    decision_note = (
        "Usar esta lectura como descripcion complementaria de la capacidad isometrica local y combinarla "
        "con tendencia, contexto del test y otras evaluaciones. No tomar decisiones fuertes basadas solo "
        "en RFD cuando no hay TE disponible."
    )

    return {
        "title": "ISO Push Hip-Hamstring Bilateral force-time",
        "peak_force_text": peak_force_text,
        "force_time_text": force_time_text,
        "rfd_text": rfd_text,
        "asymmetry_text": _compose_asymmetry_text(source),
        "decision_note": decision_note,
        "basis": basis,
    }
