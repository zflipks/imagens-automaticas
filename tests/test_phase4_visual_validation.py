from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase4_visual_validation as phase4


class FakeOcr:
    def __init__(self, detections=None):
        self.detections = list(detections or [])

    def detect(self, _image):
        return list(self.detections)


class Phase4VisualValidationTests(unittest.TestCase):
    def test_decision_contract_has_three_states(self) -> None:
        self.assertEqual(
            {item.value for item in phase4.Decision},
            {"approved", "rejected", "quarantine"},
        )

    def test_confirmed_text_is_rejected(self) -> None:
        ocr = FakeOcr([
            pipeline.OcrDetection("GOOD MORNING", 96.0, (100, 100, 400, 80))
        ])
        result = phase4.validate_background_three_state(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            ocr,
            "bomdia",
            "morning coffee and flowers",
        )
        self.assertEqual(result.decision, phase4.Decision.REJECTED)
        self.assertIn("confirmed_background_text", result.reasons)

    def test_ambiguous_text_is_quarantined(self) -> None:
        ocr = FakeOcr([
            pipeline.OcrDetection("mark", 72.0, (100, 100, 100, 40))
        ])
        result = phase4.validate_background_three_state(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            ocr,
            "bomdia",
            "morning coffee and flowers",
        )
        self.assertEqual(result.decision, phase4.Decision.QUARANTINE)
        self.assertIn("possible_background_text", result.reasons)

    def test_clean_compatible_background_is_approved(self) -> None:
        result = phase4.validate_background_three_state(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            FakeOcr(),
            "bomdia",
            "morning coffee and flowers",
        )
        self.assertEqual(result.decision, phase4.Decision.APPROVED)

    def test_duplicate_is_rejected(self) -> None:
        image = Image.new("RGB", (1024, 1024), (120, 170, 100))
        result = phase4.validate_background_three_state(
            image,
            FakeOcr(),
            "bomdia",
            "morning coffee and flowers",
            {pipeline.image_fingerprint(image)},
        )
        self.assertEqual(result.decision, phase4.Decision.REJECTED)
        self.assertIn("duplicate_fingerprint", result.reasons)

    def test_human_anatomy_is_not_falsely_claimed_as_solved(self) -> None:
        result = phase4.validate_background_three_state(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            FakeOcr(),
            "amor",
            "romantic couple with roses",
        )
        self.assertEqual(result.decision, phase4.Decision.QUARANTINE)
        self.assertIn(
            "human_anatomy_not_reliably_verifiable_locally", result.reasons
        )

    def test_all_sixteen_categories_have_compatibility_vocabulary(self) -> None:
        self.assertEqual(
            set(phase4.CATEGORY_TERMS), set(renderer.CATEGORY_STYLES)
        )

    def test_post_render_contrast_approves_legible_text(self) -> None:
        baseline = Image.new("RGB", (400, 200), "white")
        rendered = baseline.copy()
        ImageDraw.Draw(rendered).rectangle((40, 60, 360, 130), fill="black")
        result = phase4.validate_rendered_legibility(rendered, baseline)
        self.assertEqual(result.decision, phase4.Decision.APPROVED)

    def test_post_render_contrast_rejects_invisible_message(self) -> None:
        image = Image.new("RGB", (400, 200), "white")
        result = phase4.validate_rendered_legibility(image, image.copy())
        self.assertEqual(result.decision, phase4.Decision.REJECTED)
        self.assertIn("message_not_visibly_rendered", result.reasons)

    def test_quarantine_skips_candidate_and_preserves_last_valid(self) -> None:
        old = Image.new("RGB", (1080, 1080), "navy")
        candidate = Image.new("RGB", (1024, 1024), (120, 170, 100))
        selected, results, preserved = phase4.select_first_safe_candidate(
            [("human", candidate, "romantic couple with roses")],
            FakeOcr(),
            "amor",
            "Que o amor ilumine o seu dia.",
            0,
            0,
            previous_valid=old,
        )
        self.assertIs(selected, old)
        self.assertTrue(preserved)
        self.assertEqual(results[0].decision, phase4.Decision.QUARANTINE)

    def test_object_geometry_limit_routes_to_quarantine(self) -> None:
        result = phase4.validate_background_three_state(
            Image.new("RGB", (1024, 1024), (120, 170, 100)),
            FakeOcr(),
            "bomdia",
            "morning coffee beside a clock",
        )
        self.assertEqual(result.decision, phase4.Decision.QUARANTINE)
        self.assertIn(
            "object_geometry_not_reliably_verifiable_locally", result.reasons
        )


if __name__ == "__main__":
    unittest.main()
