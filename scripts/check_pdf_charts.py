"""Verifica que el PDF profesional traiga los graficos como IMAGENES (kaleido).

Sin Chrome, kaleido no renderiza y el PDF sale solo con el logo como imagen:
los graficos caen al respaldo dibujado a mano. Este script genera un PDF real
con datos de prueba, lo guarda y cuenta las imagenes embebidas.

Uso:
    python scripts/check_pdf_charts.py [salida.pdf] [--brand-images N]

Sale con codigo 1 si kaleido no genero ningun grafico, si quedo desactivado
o si el PDF no tiene mas imagenes que las de marca (icono + logotipo = 2).
"""

from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from pypdf import PdfReader  # noqa: E402

from modules import report_generator  # noqa: E402
from test_professional_pdf_report import _professional_state_with_force_time  # noqa: E402


def count_pdf_images(pdf: bytes) -> int:
    reader = PdfReader(BytesIO(pdf))
    return sum(len(page.images) for page in reader.pages)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="threshold_check.pdf")
    parser.add_argument("--brand-images", type=int, default=2)
    args = parser.parse_args()

    chromium = report_generator.configure_system_chromium()
    print(f"Chromium del sistema: {chromium or 'no encontrado'}")

    rendered: list[int] = []
    original = report_generator._plotly_figure_to_png_bytes

    def counting_render(*args, **kwargs):
        png = original(*args, **kwargs)
        if png:
            rendered.append(len(png))
        return png

    report_generator._plotly_figure_to_png_bytes = counting_render
    try:
        pdf = report_generator.generate_visual_report_pdf(
            _professional_state_with_force_time(), "Ana Lopez", "profe"
        )
    finally:
        report_generator._plotly_figure_to_png_bytes = original
    if not pdf:
        print("::error::No se genero el PDF")
        return 1
    Path(args.output).write_bytes(pdf)
    images = count_pdf_images(pdf)
    disabled = report_generator.kaleido_disabled_reason()
    print(
        f"PDF: {args.output} ({len(pdf)} bytes) · imagenes embebidas: {images} · "
        f"graficos generados por kaleido: {len(rendered)}"
    )
    if disabled:
        print(f"::error::kaleido quedo desactivado: {disabled}")
        return 1
    if not rendered:
        print("::error::kaleido no genero ningun grafico: el PDF usa solo el respaldo dibujado.")
        return 1
    if images <= args.brand_images:
        print(
            f"::error::El PDF tiene {images} imagen(es), las mismas que la marca "
            f"({args.brand_images}): los graficos no se embebieron como imagen."
        )
        return 1
    print("OK: los graficos salen como imagenes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
