"""Render de graficos para PDF: nunca puede colgar la exportacion.

kaleido (Chrome headless) se puede colgar sin lanzar error. Antes eso dejaba
la exportacion trabada; ahora cada render tiene tiempo limite y, tras un
cuelgue, el resto del reporte usa los graficos dibujados directo.
"""

from __future__ import annotations

import os
import threading
import time
import unittest

from modules import report_generator as rg


class _FakePio:
    """Imita plotly.io: to_image se cuelga, falla o devuelve PNG."""

    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0
        self.release = threading.Event()

        class _Defaults:
            mathjax = None

        self.defaults = _Defaults()

    def to_image(self, figure, **kwargs):
        self.calls += 1
        if self.mode == "hang":
            self.release.wait(30)  # simula Chrome esperando para siempre
            return b"tarde"
        if self.mode == "error":
            raise RuntimeError("kaleido roto")
        return b"\x89PNG-fake"


class RenderTimeoutTest(unittest.TestCase):
    def setUp(self):
        self._timeout = rg.KALEIDO_RENDER_TIMEOUT_S
        rg.KALEIDO_RENDER_TIMEOUT_S = 0.5
        rg._kaleido_state.update({"disabled_until": 0.0, "reason": None})

    def tearDown(self):
        rg.KALEIDO_RENDER_TIMEOUT_S = self._timeout
        rg._kaleido_state.update({"disabled_until": 0.0, "reason": None})

    def _render(self, pio):
        return rg._plotly_figure_to_png_bytes(pio, object(), width=400, height=300, scale=1)

    def test_hang_returns_none_within_timeout_and_disables_kaleido(self):
        pio = _FakePio("hang")
        started = time.monotonic()
        self.assertIsNone(self._render(pio))
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("tardo mas de", rg.kaleido_disabled_reason())

        # El resto del reporte no vuelve a esperar: fallback inmediato.
        started = time.monotonic()
        self.assertIsNone(self._render(pio))
        self.assertLess(time.monotonic() - started, 0.1)
        self.assertEqual(pio.calls, 1)
        pio.release.set()

    def test_cooldown_expires(self):
        pio = _FakePio("hang")
        self._render(pio)
        pio.release.set()
        rg._kaleido_state["disabled_until"] = time.monotonic() - 1
        self.assertIsNone(rg.kaleido_disabled_reason())
        ok = _FakePio("ok")
        self.assertEqual(self._render(ok), b"\x89PNG-fake")

    def test_error_returns_none_without_disabling(self):
        self.assertIsNone(self._render(_FakePio("error")))
        self.assertIsNone(rg.kaleido_disabled_reason())

    def test_success_returns_png_and_uses_local_mathjax(self):
        pio = _FakePio("ok")
        self.assertEqual(self._render(pio), b"\x89PNG-fake")
        self.assertTrue(pio.defaults.mathjax.startswith("file://"))
        self.assertTrue(pio.defaults.mathjax.endswith("empty_mathjax.js"))
        self.assertTrue(rg._EMPTY_MATHJAX_PATH.exists())

    def test_disabled_kaleido_skips_chrome_download(self):
        rg._disable_kaleido("prueba")
        called = []
        original = rg._get_kaleido_chrome_sync
        rg._get_kaleido_chrome_sync = lambda: called.append(1) or "/chrome"
        try:
            import plotly.graph_objects as go

            result = rg._plotly_figure_to_png_bytes(
                _FakePio("ok"), go.Figure(), width=400, height=300, scale=1
            )
            self.assertIsNone(result)
            source = open(rg.__file__, encoding="utf-8").read()
            self.assertIn("if kaleido_disabled_reason() is not None:\n        # Ya hubo un cuelgue", source)
        finally:
            rg._get_kaleido_chrome_sync = original
        self.assertEqual(called, [])


@unittest.skipUnless(os.environ.get("CI"), "render real solo en CI: en el sandbox local Chrome no funciona")
class RealRenderInCiTest(unittest.TestCase):
    """En GitHub Actions Chrome funciona: el render por el hilo con timeout
    tiene que devolver un PNG real (no caer al fallback)."""

    def test_real_plotly_render_through_timeout_wrapper(self):
        import plotly.graph_objects as go
        import plotly.io as pio

        rg._kaleido_state.update({"disabled_until": 0.0, "reason": None})
        png = rg._plotly_figure_to_png_bytes(
            pio, go.Figure(go.Scatter(y=[1, 3, 2])), width=400, height=300, scale=1
        )
        self.assertIsNotNone(png, rg.kaleido_disabled_reason())
        self.assertTrue(bytes(png).startswith(b"\x89PNG"))
        self.assertIsNone(rg.kaleido_disabled_reason())


if __name__ == "__main__":
    unittest.main()
