"""Verifica que los tres PDF traigan sus graficos como IMAGENES (kaleido).

Para cada reporte (profesional, atleta, cliente) genera el PDF real con datos
de prueba y compara las imagenes de grafico embebidas con las esperadas:

- profesional: carga + ACWR EWMA, wellness score, sueno/estres/dolor y
  distribucion del bloque (4);
- atleta: carga semanal + cronica y wellness score (2);
- cliente: sesiones por semana y wellness score (2).

Los graficos se reconocen por su ancho en pixeles (lienzo de impresion x
escala), asi no se confunden con las imagenes de marca. Usa `pdfimages -list`
(poppler) si esta instalado; si no, lee las imagenes con pypdf.

Uso:
    python scripts/check_pdf_charts.py [carpeta_salida]

Sale con codigo 1 si kaleido quedo desactivado o si algun reporte no trae
exactamente los graficos esperados.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from pypdf import PdfReader  # noqa: E402

from charts.report_charts import PRINT_CANVAS_WIDTH_PX, PRINT_SCALE  # noqa: E402
from modules import report_generator  # noqa: E402
from modules.app_clock import frozen_app_now  # noqa: E402
from test_reports_yellow_coverage import ATHLETE, NOW, full_charts_state  # noqa: E402

CHART_IMAGE_WIDTH_PX = PRINT_CANVAS_WIDTH_PX * PRINT_SCALE
AUDIENCES = ("profe", "atleta", "cliente")


def chart_image_widths_pdfimages(path: Path) -> list[int] | None:
    """Anchos de las imagenes segun `pdfimages -list` (None si no esta instalado)."""
    if shutil.which("pdfimages") is None:
        return None
    output = subprocess.run(["pdfimages", "-list", str(path)], capture_output=True, text=True, check=True).stdout
    widths: list[int] = []
    for line in output.splitlines()[2:]:  # encabezado + separador
        parts = line.split()
        if len(parts) > 4 and parts[2] == "image":
            widths.append(int(parts[3]))
    return widths


def chart_image_widths_pypdf(pdf: bytes) -> list[int]:
    widths: list[int] = []
    for page in PdfReader(BytesIO(pdf)).pages:
        for image in page.images:
            widths.append(int(image.image.width))
    return widths


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    chromium = report_generator.configure_system_chromium()
    print(f"Chromium del sistema: {chromium or 'no encontrado'}")

    failures: list[str] = []
    state = full_charts_state()
    for audience in AUDIENCES:
        with frozen_app_now(NOW):
            expected = sorted(report_generator.build_report_chart_figures(state, ATHLETE, audience))
            pdf = report_generator.generate_visual_report_pdf(state, ATHLETE, audience)
        if not pdf:
            failures.append(f"{audience}: no se genero el PDF")
            continue
        path = out_dir / f"threshold_check_{audience}.pdf"
        path.write_bytes(pdf)
        widths = chart_image_widths_pdfimages(path)
        source = "pdfimages"
        if widths is None:
            widths = chart_image_widths_pypdf(pdf)
            source = "pypdf"
        charts = sum(1 for width in widths if width == CHART_IMAGE_WIDTH_PX)
        wanted = list(report_generator.REPORT_CHART_SLUGS[audience])
        print(
            f"{audience}: {path.name} · imagenes ({source}): {len(widths)} · "
            f"graficos {CHART_IMAGE_WIDTH_PX}px: {charts} · esperados: {len(expected)} {expected}"
        )
        if sorted(wanted) != expected:
            failures.append(f"{audience}: el fixture no produjo todos los graficos ({expected} vs {sorted(wanted)})")
        if charts != len(expected):
            failures.append(f"{audience}: {charts} grafico(s) embebido(s), se esperaban {len(expected)}")

    disabled = report_generator.kaleido_disabled_reason()
    if disabled:
        failures.append(f"kaleido quedo desactivado: {disabled}")
    for failure in failures:
        print(f"::error::{failure}")
    if failures:
        return 1
    print("OK: los tres reportes traen sus graficos como imagenes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
