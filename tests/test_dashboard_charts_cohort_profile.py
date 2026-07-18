"""Regression + gap coverage for threading `profile_df` through the chart-prep
layer (`_prepare_jump_df` -> `_prepare_frame` -> chart_quadrant_dri_sj/rsi_sj).

Context: app.py's Profile/Team views already recompute cohort-aware z-scores
via `shared_calc_zscores(latest_jdf, profile_df=...)` before handing the frame
to the quadrant charts. Today that survives only because `_prepare_frame`'s
existing shortcut (`{"SJ_Z", "CMJ_Z"}.issubset(df.columns)`) returns the frame
as-is whenever those columns are already present -- it never re-derives them.
None of `_prepare_jump_df`, `_prepare_frame`, `chart_quadrant_dri_sj` or
`chart_quadrant_rsi_sj` currently accept a `profile_df` parameter at all, so
any caller that needs cohort-aware z-scores recomputed *inside* this layer
(i.e. when the shortcut does not apply) has no way to ask for it.
"""

from __future__ import annotations

import unittest

import plotly.graph_objects as go

from charts.dashboard_charts import _prepare_frame, chart_quadrant_dri_sj, chart_quadrant_rsi_sj
from modules.jump_analysis import _prepare_jump_df

from tests.test_jump_analysis_cohort_zscore import _build_two_cohort_frames, _expected_z

MINIMAL_THEME = {
    "colors": {
        "navy": "#0D3C5E",
        "muted": "#708C9F",
        "gray": "#708C9F",
        "green": "#4FC97E",
        "yellow": "#E8C84A",
        "orange": "#C88759",
        "red": "#D94F4F",
        "card": "#FFFFFF",
        "steel": "#4A9FD4",
        "white": "#FFFFFF",
    },
    "layout": {},
    "grid": "",
    "grid_soft": "",
    "reference_line": "",
    "legend": {},
}


class PrepareJumpDfAcceptsProfileDfTest(unittest.TestCase):
    """Case 1 (plan): expected to fail today with TypeError; passes after the fix."""

    def test_prepare_jump_df_accepts_profile_df_and_uses_cohort(self):
        jump_df, profile_df = _build_two_cohort_frames()
        result = _prepare_jump_df(jump_df.copy(), profile_df=profile_df)

        handball_sj = [30, 32, 34]
        expected_ana = _expected_z(handball_sj, 30)
        actual_ana = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        self.assertAlmostEqual(actual_ana, expected_ana, places=2)


class PrepareFrameShortcutRegressionTest(unittest.TestCase):
    """Case 2 (plan): today's actual safe path -- no `profile_df` kwarg involved
    at all, matching how app.py really calls these functions today. Expected
    to pass both before and after the fix (the shortcut itself never changes).
    """

    def test_prepare_frame_shortcut_preserves_precomputed_cohort_zscore(self):
        jump_df, profile_df = _build_two_cohort_frames()
        # Simulate what app.py already does before reaching the chart: compute
        # cohort-aware z-scores up front via calc_zscores(profile_df=...).
        from modules.jump_analysis import calc_zscores

        precomputed = calc_zscores(jump_df.copy(), profile_df=profile_df)
        handball_sj = [30, 32, 34]
        expected_ana = _expected_z(handball_sj, 30)
        precomputed_ana = precomputed.loc[precomputed["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        self.assertAlmostEqual(precomputed_ana, expected_ana, places=2)

        # _prepare_frame is called exactly like app.py -> chart_quadrant_dri_sj
        # calls it today: no profile_df kwarg at all.
        result = _prepare_frame(precomputed.copy())

        actual_ana = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        self.assertAlmostEqual(actual_ana, expected_ana, places=2)
        # The shortcut must return the frame untouched, not recomputed.
        self.assertTrue(result.equals(precomputed))


class PrepareFrameWithoutShortcutTest(unittest.TestCase):
    """Case 3 (plan): the actual latent-bug scenario -- a frame without
    precomputed SJ_Z/CMJ_Z falls through to `_prepare_jump_df`. Expected to
    fail today with TypeError; passes after the fix with cohort-aware values.
    """

    def test_prepare_frame_without_shortcut_uses_cohort_when_profile_df_passed(self):
        jump_df, profile_df = _build_two_cohort_frames()
        self.assertFalse({"SJ_Z", "CMJ_Z"}.issubset(jump_df.columns))

        result = _prepare_frame(jump_df.copy(), profile_df=profile_df)

        handball_sj = [30, 32, 34]
        expected_ana = _expected_z(handball_sj, 30)
        actual_ana = result.loc[result["Athlete"] == "Ana Lopez", "SJ_Z"].iloc[0]
        self.assertAlmostEqual(actual_ana, expected_ana, places=2)


class ChartQuadrantAcceptsProfileDfTest(unittest.TestCase):
    """Case 4 (plan): smoke test on both quadrant chart functions. Expected to
    fail today with TypeError for both; passes after the fix (returns a
    go.Figure either way, even if the data ends up in the "no data" branch).
    """

    def test_chart_quadrant_dri_sj_and_rsi_sj_accept_profile_df(self):
        jump_df, profile_df = _build_two_cohort_frames()

        fig_dri = chart_quadrant_dri_sj(jump_df.copy(), theme=MINIMAL_THEME, profile_df=profile_df)
        fig_rsi = chart_quadrant_rsi_sj(jump_df.copy(), theme=MINIMAL_THEME, profile_df=profile_df)

        self.assertIsInstance(fig_dri, go.Figure)
        self.assertIsInstance(fig_rsi, go.Figure)


if __name__ == "__main__":
    unittest.main()
