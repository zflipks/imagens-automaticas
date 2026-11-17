from __future__ import annotations

import unittest
from datetime import date

import gerar_imagens as renderer
import phase6_production_simulation as phase6


class Phase6ProductionSimulationTests(unittest.TestCase):
    def test_official_category_rule_is_enforced(self) -> None:
        for category in renderer.CATEGORY_STYLES:
            artworks, _attempts = phase6.simulate_category(category)
            self.assertEqual(len(artworks), 10)
            self.assertEqual(len({item.phrase_id for item in artworks}), 10)
            self.assertEqual(len({item.style_id for item in artworks}), 10)
            self.assertEqual(len({item.background_fingerprint for item in artworks}), 10)

    def test_rejections_and_quarantine_generate_new_candidates(self) -> None:
        artworks, attempts = phase6.simulate_category(
            "bomdia", ["rejected", "quarantine", "approved"]
        )
        self.assertEqual(len(artworks), 10)
        self.assertEqual(attempts, 12)
        self.assertEqual(artworks[0].candidate_attempts, 3)

    def test_recent_background_cannot_be_reused(self) -> None:
        recent = {"bomdia-slot-1-attempt-1"}
        artworks, attempts = phase6.simulate_category(
            "bomdia", recent_fingerprints=recent
        )
        self.assertNotIn(
            "bomdia-slot-1-attempt-1",
            {item.background_fingerprint for item in artworks},
        )
        self.assertEqual(attempts, 11)

    def test_weekday_weekend_and_initial_sizes(self) -> None:
        weekday = phase6.simulate_complete_batch(
            renderer.active_categories(date(2027, 2, 1))
        )
        saturday = phase6.simulate_complete_batch(
            renderer.active_categories(date(2027, 2, 6))
        )
        sunday = phase6.simulate_complete_batch(
            renderer.active_categories(date(2027, 2, 7))
        )
        initial = phase6.simulate_complete_batch(
            renderer.active_categories(date(2027, 2, 1), initialize_all=True)
        )
        self.assertEqual(weekday["artworks"], 110)
        self.assertEqual(saturday["artworks"], 120)
        self.assertEqual(sunday["artworks"], 120)
        self.assertEqual(initial["artworks"], 160)
        for batch in (weekday, saturday, sunday, initial):
            self.assertTrue(batch["all_category_invariants_passed"])

    def test_incomplete_batch_preserves_previous_catalog(self) -> None:
        result = phase6.simulate_complete_batch(
            renderer.active_categories(date(2027, 2, 1)),
            failure_category="amor",
        )
        self.assertTrue(result["previous_catalog_preserved"])
        self.assertEqual(result["selected_catalog"]["generated_at"], "last-valid")

    def test_seasonal_category_adds_ten_unique_artworks(self) -> None:
        normal = len(renderer.active_categories(date(2027, 11, 24)))
        christmas = len(renderer.active_categories(date(2027, 11, 25)))
        self.assertEqual(christmas, normal + 1)
        estimate = phase6.estimate_day(
            date(2027, 11, 25), phase6.SCENARIOS["realistic"]
        )
        self.assertEqual(estimate.artworks, christmas * 10)

    def test_realistic_free_tier_is_insufficient_for_weekday(self) -> None:
        estimate = phase6.estimate_profile(110, phase6.SCENARIOS["realistic"])
        self.assertTrue(estimate["free_limit_exceeded"])
        self.assertEqual(estimate["candidates"], 202)

    def test_simulation_never_consumes_neurons(self) -> None:
        report = phase6.build_report(2027)
        self.assertEqual(report["neurons_consumed_by_simulation"], 0)
        self.assertFalse(
            report["rule"]["background_reuse_within_category_batch_allowed"]
        )

    def test_all_phase_modules_remain_importable(self) -> None:
        import ai_background_pipeline
        import phase3_visual_validation
        import phase4_visual_validation
        import phase5_approval_optimization

        self.assertIsNotNone(ai_background_pipeline.MODEL)
        self.assertIsNotNone(phase3_visual_validation.TypographyRegionDetector)
        self.assertIsNotNone(phase4_visual_validation.Decision)
        self.assertIsNotNone(phase5_approval_optimization.OptimizedDecision)


if __name__ == "__main__":
    unittest.main()
