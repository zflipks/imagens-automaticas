from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image

import gerar_imagens as renderer
import phase3_visual_validation as phase3


class Phase3VisualValidationTests(unittest.TestCase):
    def test_existing_evaluation_has_no_text_classification_errors(self) -> None:
        path = (
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-phase3"
            / "geometry-evaluation.json"
        )
        if not path.exists():
            self.skipTest("Phase 3 evaluation report unavailable")
        report = json.loads(path.read_text(encoding="utf-8"))
        metrics = report["metrics"]
        self.assertEqual(metrics["sample_count"], 20)
        self.assertEqual(metrics["true_positive"], 2)
        self.assertEqual(metrics["false_positive"], 0)
        self.assertEqual(metrics["false_negative"], 0)
        decisions = {item["name"]: item["predicted_text"] for item in report["samples"]}
        self.assertTrue(decisions["phase1-bomdia"])
        self.assertTrue(decisions["phase1-aniversario"])

    def test_geometry_detector_finds_both_difficult_text_regions(self) -> None:
        detector = phase3.TypographyRegionDetector()
        root = (
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-pilot"
            / "backgrounds"
        )
        if not root.exists():
            self.skipTest("Phase 1 staging fixtures unavailable")
        for category in ("bomdia", "aniversario"):
            with Image.open(root / f"{category}.jpg") as image:
                decision = detector.analyze(image)
            self.assertTrue(decision.has_text_region, category)

    def test_clean_photo_set_has_no_combined_false_positives(self) -> None:
        path = (
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-phase3"
            / "geometry-evaluation.json"
        )
        if not path.exists():
            self.skipTest("Phase 3 evaluation report unavailable")
        report = json.loads(path.read_text(encoding="utf-8"))
        clean = [item for item in report["samples"] if not item["expected_text"]]
        self.assertEqual(len(clean), 18)
        self.assertFalse(any(item["predicted_text"] for item in clean))

    def test_duplicate_moon_scene_is_flagged(self) -> None:
        path = (
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-phase2"
            / "backgrounds"
            / "03-boanoite-13b46ee3032ea302.jpg"
        )
        if not path.exists():
            self.skipTest("Phase 2 moon fixture unavailable")
        with Image.open(path) as image:
            quality = phase3.assess_visual_quality(
                image, "a quiet bedroom window framing the moon and soft night clouds"
            )
        self.assertTrue(
            any(issue.startswith("possible_duplicate_moons:") for issue in quality.issues)
        )

    def test_human_scene_requires_anatomy_review(self) -> None:
        image = Image.new("RGB", (1024, 1024), "gray")
        quality = phase3.assess_visual_quality(
            image, "adult friends sharing a picnic in a garden"
        )
        self.assertTrue(quality.anatomy_review_required)


if __name__ == "__main__":
    unittest.main()
