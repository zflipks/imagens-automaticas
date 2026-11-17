from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image

import ai_background_pipeline as pipeline
import gerar_imagens as renderer


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, detections: list[list[pipeline.OcrDetection]] | None = None):
        self.detections = list(detections or [])
        self.calls = 0

    def available(self) -> bool:
        return True

    def detect(self, _image: Image.Image) -> list[pipeline.OcrDetection]:
        self.calls += 1
        return self.detections.pop(0) if self.detections else []


class FakeSource:
    def __init__(self, colors: list[tuple[int, int, int]] | None = None):
        self.colors = colors or [(150, 100, 60)]
        self.calls = 0

    def generate(
        self, category: str, plan: pipeline.PromptPlan
    ) -> pipeline.GeneratedCandidate:
        color = self.colors[self.calls % len(self.colors)]
        self.calls += 1
        return pipeline.GeneratedCandidate(
            image=Image.new("RGB", (1024, 1024), color),
            category=category,
            prompt_plan=plan,
            generation_seconds=1.25,
            neurons_observed=172.8,
            request_id=f"fake-{self.calls}",
            resolution="1024x1024",
        )


class Phase2PipelineTests(unittest.TestCase):
    def test_all_sixteen_categories_have_varied_safe_prompts(self) -> None:
        self.assertEqual(set(pipeline.CATEGORY_SCENES), set(renderer.CATEGORY_STYLES))
        for category in renderer.CATEGORY_STYLES:
            plans = [
                pipeline.build_prompt_plan(category, date(2026, 11, 17), attempt)
                for attempt in range(8)
            ]
            self.assertGreaterEqual(len({plan.scene for plan in plans}), 4, category)
            self.assertGreaterEqual(len({plan.composition for plan in plans}), 3, category)
            self.assertEqual(len({plan.variant_key for plan in plans}), len(plans), category)
            for plan in plans:
                lowered = plan.prompt.casefold()
                self.assertIn("photorealistic", lowered)
                self.assertIn("no words", lowered)
                self.assertIn("logos", lowered)

    def test_ocr_text_rejects_original_background(self) -> None:
        ocr = FakeOcr([[pipeline.OcrDetection("Happy Birthday", 92.0, (10, 10, 200, 40))]])
        result = pipeline.validate_background(
            Image.new("RGB", (1024, 1024), (180, 120, 90)), ocr
        )
        self.assertFalse(result.approved)
        self.assertIn("text_region_consensus", result.reasons[0])

    def test_short_ocr_fragments_do_not_reject_photographic_texture(self) -> None:
        ocr = FakeOcr([[
            pipeline.OcrDetection("E", 86.0),
            pipeline.OcrDetection("vmar", 52.0),
            pipeline.OcrDetection("Na", 62.0),
        ]])
        result = pipeline.validate_background(
            Image.new("RGB", (1024, 1024), (180, 120, 90)), ocr
        )
        self.assertTrue(result.approved)
        self.assertEqual(len(result.detections), 3)

    def test_combined_detector_on_phase1_pilot(self) -> None:
        ocr = pipeline.TesseractOcr()
        root = (
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-pilot"
            / "backgrounds"
        )
        if not ocr.available() or not root.exists():
            self.skipTest("Local OCR or phase 1 staging fixtures unavailable")
        expected = {
            "bomdia": False,
            "aniversario": False,
            "amor": True,
            "fe": True,
            "natal": True,
        }
        for category, approved in expected.items():
            with Image.open(root / f"{category}.jpg") as image:
                result = pipeline.validate_background(image.convert("RGB"), ocr)
            self.assertEqual(
                result.approved,
                approved,
                (category, result.detections, result.reasons),
            )

    def test_clean_background_is_approved_before_rendering(self) -> None:
        result = pipeline.validate_background(
            Image.new("RGB", (1024, 1024), (180, 120, 90)), FakeOcr()
        )
        self.assertTrue(result.approved)
        self.assertEqual(result.detections, ())

    def test_duplicate_fingerprint_is_rejected(self) -> None:
        image = Image.new("RGB", (1024, 1024), (180, 120, 90))
        fingerprint = pipeline.image_fingerprint(image)
        result = pipeline.validate_background(image, FakeOcr(), {fingerprint})
        self.assertFalse(result.approved)
        self.assertIn("duplicate_fingerprint", result.reasons)

    def test_budget_stops_before_paid_usage(self) -> None:
        ledger = pipeline.BudgetLedger(
            day="2026-11-17",
            daily_call_limit=15,
            free_neuron_limit=1000.0,
            reference_neurons_per_call=172.8,
            calls=5,
            neurons_observed=864.0,
        )
        with self.assertRaises(pipeline.BudgetExceeded):
            ledger.assert_can_call()

    def test_budget_counts_rejected_candidates(self) -> None:
        ledger = pipeline.BudgetLedger(day="2026-11-17")
        ledger.record("bomdia", 172.8, "rejected")
        self.assertEqual(ledger.calls, 1)
        self.assertEqual(ledger.neurons_observed, 172.8)

    def test_missing_ocr_blocks_before_source_call(self) -> None:
        class MissingOcr(FakeOcr):
            def available(self) -> bool:
                return False

        source = FakeSource()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "OCR backend unavailable"):
                pipeline.run_pilot(
                    source,
                    MissingOcr(),
                    ["bomdia"],
                    1,
                    date(2026, 11, 17),
                    root / "ledger.json",
                    root / "history.json",
                    root / "report.json",
                )
        self.assertEqual(source.calls, 0)

    def test_rejection_is_recorded_and_not_rendered(self) -> None:
        source = FakeSource()
        ocr = FakeOcr([[pipeline.OcrDetection("Good Morning", 95.0)]])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_dirs = (
                pipeline.BACKGROUNDS_DIR,
                pipeline.RENDERED_DIR,
                pipeline.REJECTED_DIR,
                pipeline.MOSAICS_DIR,
            )
            try:
                pipeline.BACKGROUNDS_DIR = root / "backgrounds"
                pipeline.RENDERED_DIR = root / "rendered"
                pipeline.REJECTED_DIR = root / "rejected"
                pipeline.MOSAICS_DIR = root / "mosaics"
                report = pipeline.run_pilot(
                    source,
                    ocr,
                    ["bomdia"],
                    1,
                    date(2026, 11, 18),
                    root / "ledger.json",
                    root / "history.json",
                    root / "report.json",
                )
            finally:
                (
                    pipeline.BACKGROUNDS_DIR,
                    pipeline.RENDERED_DIR,
                    pipeline.REJECTED_DIR,
                    pipeline.MOSAICS_DIR,
                ) = old_dirs
            self.assertEqual(report["summary"]["candidate_count"], 1)
            self.assertEqual(report["summary"]["rejected_count"], 1)
            self.assertEqual(report["summary"]["approved_count"], 0)
            self.assertEqual(source.calls, 1)
            self.assertTrue(any((root / "rejected").glob("*.jpg")))
            self.assertFalse((root / "rendered").exists())

    def test_approved_candidate_is_rendered_after_validation(self) -> None:
        source = FakeSource()
        ocr = FakeOcr()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_dirs = (
                pipeline.BACKGROUNDS_DIR,
                pipeline.RENDERED_DIR,
                pipeline.REJECTED_DIR,
                pipeline.MOSAICS_DIR,
            )
            try:
                pipeline.BACKGROUNDS_DIR = root / "backgrounds"
                pipeline.RENDERED_DIR = root / "rendered"
                pipeline.REJECTED_DIR = root / "rejected"
                pipeline.MOSAICS_DIR = root / "mosaics"
                report = pipeline.run_pilot(
                    source,
                    ocr,
                    ["amor"],
                    1,
                    date(2026, 11, 18),
                    root / "ledger.json",
                    root / "history.json",
                    root / "report.json",
                )
            finally:
                (
                    pipeline.BACKGROUNDS_DIR,
                    pipeline.RENDERED_DIR,
                    pipeline.REJECTED_DIR,
                    pipeline.MOSAICS_DIR,
                ) = old_dirs
            self.assertEqual(report["summary"]["approved_count"], 1)
            self.assertEqual(ocr.calls, 1)
            self.assertTrue(any((root / "backgrounds").glob("*.jpg")))
            self.assertTrue(any((root / "rendered").glob("*.jpg")))
            self.assertTrue((root / "mosaics" / "fundos-aprovados.jpg").exists())
            self.assertTrue((root / "mosaics" / "artes-renderizadas.jpg").exists())

    def test_prior_pilot_usage_is_imported_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = pipeline.BudgetLedger.load(path, date(1999, 1, 1), 15)
            self.assertEqual(ledger.calls, 0)
            self.assertGreaterEqual(ledger.neurons_observed, 0)

    def test_report_contains_no_prompt_added_text_before_render(self) -> None:
        plan = pipeline.build_prompt_plan("natal", date(2026, 12, 1), 0)
        forbidden = ("feliz natal", "bom dia", "happy birthday")
        for value in forbidden:
            self.assertNotIn(value, plan.prompt.casefold())


if __name__ == "__main__":
    unittest.main()
