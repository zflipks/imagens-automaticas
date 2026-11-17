from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase4_visual_validation as phase4
import phase5_approval_optimization as phase5


class FakeOcr:
    def __init__(self, detections=None):
        self.detections = list(detections or [])

    def detect(self, _image):
        return list(self.detections)


class Phase5ApprovalOptimizationTests(unittest.TestCase):
    def test_confirmed_text_remains_rejected(self) -> None:
        result = phase5.validate_background_optimized(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            FakeOcr([pipeline.OcrDetection("GOOD MORNING", 98.0)]),
            "bomdia",
            "morning coffee and flowers",
        )
        self.assertEqual(result.decision, phase4.Decision.REJECTED)

    def test_known_duplicate_remains_rejected(self) -> None:
        image = Image.new("RGB", (1024, 1024), (120, 170, 100))
        result = phase5.validate_background_optimized(
            image,
            FakeOcr(),
            "bomdia",
            "morning coffee and flowers",
            {pipeline.image_fingerprint(image)},
        )
        self.assertEqual(result.decision, phase4.Decision.REJECTED)
        self.assertIn("duplicate_fingerprint", result.reasons)

    def test_anatomy_risk_is_recorded_without_automatic_quarantine(self) -> None:
        result = phase5.validate_background_optimized(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            FakeOcr(),
            "amor",
            "romantic couple with roses",
        )
        self.assertEqual(result.decision, phase4.Decision.APPROVED)
        self.assertIn("anatomy_unverified", result.recorded_risks)

    def test_controlled_watermark_shape_is_not_approved(self) -> None:
        watermark = dict(
            (name, image) for name, image, _expected in phase4.controlled_fixtures()
        )["watermark"]
        result = phase5.validate_background_optimized(
            watermark,
            FakeOcr(),
            "bomdia",
            "morning coffee and flowers",
        )
        self.assertEqual(result.decision, phase4.Decision.QUARANTINE)
        self.assertIn("possible_watermark_or_signature", result.recorded_risks)

    def test_invalid_reserve_file_is_skipped_and_history_is_respected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "broken.jpg"
            invalid.write_bytes(b"not an image")
            valid = root / "valid.jpg"
            Image.new("RGB", (1024, 1024), "green").save(valid, "JPEG")
            repeated = phase5.ReserveEntry("repeat", "bomdia", "fp-old", valid)
            broken = phase5.ReserveEntry("broken", "bomdia", "fp-broken", invalid)
            fresh = phase5.ReserveEntry("fresh", "bomdia", "fp-new", valid)
            selected = phase5.choose_reserve(
                [repeated, broken, fresh], "bomdia", {"fp-old"}
            )
            self.assertEqual(selected, fresh)

    def test_incomplete_daily_batch_preserves_previous_catalog(self) -> None:
        previous = {"generated_at": "valid", "bomdia": ["old.jpg"]}
        selected, preserved = phase5.preserve_catalog_on_incomplete_batch(
            previous, {"bomdia"}, {"bomdia", "boatarde"}
        )
        self.assertIs(selected, previous)
        self.assertTrue(preserved)

    def test_complete_batch_can_advance_to_staging(self) -> None:
        _selected, preserved = phase5.preserve_catalog_on_incomplete_batch(
            {"old": True}, set(renderer.CATEGORY_STYLES), set(renderer.CATEGORY_STYLES)
        )
        self.assertFalse(preserved)

    def test_prompts_explicitly_avoid_high_risk_text_sources(self) -> None:
        plan = pipeline.build_prompt_plan("natal", renderer.date(2026, 12, 20), 0)
        lowered = plan.prompt.casefold()
        for phrase in ("signatures", "packaging", "clocks", "plain unmarked"):
            self.assertIn(phrase, lowered)

    def test_cost_estimate_never_authorizes_paid_usage(self) -> None:
        estimate = phase5.cost_estimate(0.9)
        self.assertTrue(estimate["paid_plan_not_authorized"])
        self.assertEqual(estimate["free_candidates_per_day_floor"], 57)


if __name__ == "__main__":
    unittest.main()
