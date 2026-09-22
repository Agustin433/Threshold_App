"""Ingesta semanal de exports de TeamBuildr al store local de Threshold S&C.

No pasa por la interfaz de Streamlit: llama directo a los mismos parsers de
`modules.data_loader` y a `local_store.save_dataset`, asi que el resultado es
identico a cargar los mismos archivos a mano desde la app.

Identifica cada CSV por sus COLUMNAS, no por nombre de archivo, porque
TeamBuildr/el navegador les pone nombres inconsistentes semana a semana
("Teambuildr Raw Data Report.csv", "...csv1.csv", "...csv2.csv", etc.).

Uso:
    python scripts/weekly_ingest.py "<carpeta con los CSV de esta semana>" [--week-start YYYY-MM-DD]

--week-start es la fecha que representa el rango exportado en el Completion
Report (por defecto, el viernes mas reciente). Se usa para poder acumular
historial semana a semana de cumplimiento, ya que ese reporte no trae fecha
por fila.
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from modules import data_loader as dl  # noqa: E402
import local_store as ls  # noqa: E402


class UploadLike(io.BytesIO):
    """Envoltorio minimo para que los parsers de data_loader (pensados para
    UploadedFile de Streamlit) acepten un archivo local por path."""

    def __init__(self, path: Path):
        super().__init__(path.read_bytes())
        self.name = path.name


def _sniff_columns(path: Path) -> list[str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, errors="strict") as fh:
                header = fh.readline()
            return [c.strip().strip('"') for c in header.strip().split(",")]
        except UnicodeDecodeError:
            continue
    with path.open("r", encoding="latin-1", errors="replace") as fh:
        header = fh.readline()
    return [c.strip().strip('"') for c in header.strip().split(",")]


def _classify(columns: list[str]) -> str | None:
    cols = set(columns)
    if {"Question ID", "Response ID", "Result", "Timestamp Complete"}.issubset(cols):
        return "questionnaire_raw"
    if {"Max Value", "Exercise Id"}.issubset(cols):
        return "maxes"
    if {"Set Number", "WorkoutId"}.issubset(cols):
        return "raw_workouts"
    if {"Assigned", "Completed", "Percent"}.issubset(cols):
        return "completion"
    return None


def _most_recent_completed_monday(today: date | None = None) -> date:
    """Lunes de la ultima semana CERRADA (no la semana en curso).

    Si hoy es viernes 2026-09-04 (weekday=4), la ultima semana cerrada es
    lunes 2026-08-24 a domingo 2026-08-30. Esto tiene que coincidir siempre
    con el --week-start que use weekly_decision_report.py, asi que ambos
    scripts comparten esta misma funcion en espiritu: "lunes" es la unica
    convencion valida para --week-start en todo este pipeline.
    """
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def ingest(export_dir: Path, week_start: date) -> dict[str, dict]:
    results: dict[str, dict] = {}
    csv_files = sorted(export_dir.glob("*.csv"))
    if not csv_files:
        raise SystemExit(f"No hay archivos .csv en {export_dir}")

    found: dict[str, Path] = {}
    for path in csv_files:
        try:
            columns = _sniff_columns(path)
        except Exception as exc:  # pragma: no cover - solo IO raro
            results[path.name] = {"status": "error", "detail": f"no se pudo leer encabezado: {exc}"}
            continue
        kind = _classify(columns)
        if kind is None:
            results[path.name] = {"status": "skipped", "detail": "columnas no reconocidas, se ignora"}
            continue
        if kind in found:
            results[path.name] = {
                "status": "skipped",
                "detail": f"ya se uso '{found[kind].name}' para '{kind}'; se ignora este duplicado",
            }
            continue
        found[kind] = path

    if "questionnaire_raw" in found:
        path = found["questionnaire_raw"]
        try:
            rpe_df, wellness_df = dl.parse_questionnaire_raw_csv(UploadLike(path))
            ls.save_dataset("rpe_df", rpe_df)
            ls.save_dataset("wellness_df", wellness_df)
            results[path.name] = {
                "status": "ok",
                "detail": f"{len(rpe_df)} sesiones de RPE, {len(wellness_df)} dia(s)-atleta de wellness",
            }
        except Exception as exc:
            results[path.name] = {"status": "error", "detail": str(exc)}

    if "raw_workouts" in found:
        path = found["raw_workouts"]
        try:
            df = dl.parse_raw_workouts(UploadLike(path))
            ls.save_dataset("raw_df", df)
            results[path.name] = {"status": "ok", "detail": f"{len(df)} filas de workouts"}
        except Exception as exc:
            results[path.name] = {"status": "error", "detail": str(exc)}

    if "maxes" in found:
        path = found["maxes"]
        try:
            df = dl.parse_maxes_health(UploadLike(path))
            ls.save_dataset("maxes_df", df)
            results[path.name] = {"status": "ok", "detail": f"{len(df)} maximos"}
        except Exception as exc:
            results[path.name] = {"status": "error", "detail": str(exc)}

    if "completion" in found:
        path = found["completion"]
        try:
            df = dl.parse_completion_report(UploadLike(path))
            df["Date"] = pd.Timestamp(week_start)
            ls.save_dataset("completion_df", df)
            results[path.name] = {
                "status": "ok",
                "detail": f"{len(df)} atleta(s), etiquetado semana {week_start.isoformat()}",
            }
        except Exception as exc:
            results[path.name] = {"status": "error", "detail": str(exc)}

    for kind_label in ("questionnaire_raw", "raw_workouts", "maxes", "completion"):
        if kind_label not in found:
            results[f"<falta: {kind_label}>"] = {
                "status": "missing",
                "detail": "no se encontro ningun CSV de este tipo en la carpeta",
            }

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export_dir", help="Carpeta con los CSV exportados de TeamBuildr esta semana")
    parser.add_argument(
        "--week-start",
        help=(
            "LUNES (YYYY-MM-DD) de la semana exportada en Completion Report. "
            "Tiene que ser el mismo lunes que se le pase despues a weekly_decision_report.py. "
            "Por defecto, el lunes de la ultima semana cerrada."
        ),
    )
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    week_start = date.fromisoformat(args.week_start) if args.week_start else _most_recent_completed_monday()

    results = ingest(export_dir, week_start)

    print(f"Ingesta semanal - carpeta: {export_dir}")
    print(f"Semana (Completion Report): {week_start.isoformat()}")
    print("-" * 60)
    ok = err = 0
    for name, info in results.items():
        status = info["status"]
        marker = {"ok": "OK", "error": "ERROR", "skipped": "SKIP", "missing": "FALTA"}.get(status, status.upper())
        print(f"[{marker}] {name}: {info['detail']}")
        if status == "ok":
            ok += 1
        elif status == "error":
            err += 1

    print("-" * 60)
    print(f"{ok} dataset(s) cargados correctamente, {err} error(es).")
    if err:
        sys.exit(1)


if __name__ == "__main__":
    main()
