from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

import ai_background_pipeline as pipeline
import phase4_visual_validation as phase4
import phase7_background_library as phase7
import phase8_production_integration as phase8


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, detections=None):
        self.detections = list(detections or [])

    def detect(self, _image):
        return list(self.detections)


def make_photo(path: Path) -> Path:
    image = Image.new("RGB", (1024, 1024), (120, 170, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 720, 420, 980), fill=(80, 120, 70))
    image.save(path, "PNG")
    return path


def receipt() -> phase7.ValidationReceipt:
    return phase7.ValidationReceipt(
        "test", False, "approved", "approved",
        "2027-01-01T00:00:00+00:00", "evidence"
    )


class Phase8ProductionIntegrationTests(unittest.TestCase):
    def test_approved_registration_requires_validation_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            with self.assertRaises(ValueError):
                library.add_file(
                    make_photo(root / "photo.png"), "bomdia", "morning",
                    date(2027, 1, 1), "test", "approved"
                )

    def test_validator_registers_clean_photo_with_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record, evidence = phase8.validate_and_register(
                library, make_photo(root / "clean.png"), "bomdia", "morning",
                date(2027, 1, 1), "local", "morning coffee and flowers",
                FakeOcr(),
            )
            self.assertEqual(record.approval_status, "approved")
            self.assertIsNotNone(record.validation_receipt)
            self.assertEqual(evidence["phase5"]["decision"], "approved")

    def test_confirmed_text_cannot_be_registered_as_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record, _evidence = phase8.validate_and_register(
                library, make_photo(root / "text.png"), "bomdia", "morning",
                date(2027, 1, 1), "local", "morning coffee and flowers",
                FakeOcr([pipeline.OcrDetection("GOOD MORNING", 98.0)]),
            )
            self.assertEqual(record.approval_status, "rejected")
            self.assertFalse(
                library.eligible(record, date(2027, 1, 10), "bomdia", "x", 0)
            )

    def test_unpromoted_interruption_releases_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = library.add_file(
                make_photo(root / "photo.png"), "bomdia", "morning",
                date(2027, 1, 1), "test", "approved",
                validation_receipt=receipt(),
            )
            library.save_atomic()
            library.reserve("run", date(2027, 1, 9), "bomdia", [record])
            library.save_atomic()
            journal = root / "journal.json"
            phase8.create_reserved_journal(
                journal, "batch", {"bomdia": "run"}, {"bomdia": [("phrase", 0)]}
            )
            result = phase8.recover_promotion_confirmation(library, journal, None)
            self.assertEqual(result, "unpromoted_reservations_released")
            self.assertEqual(library.reservations, [])
            self.assertEqual(record.usages, [])

    def test_promoted_interruption_confirms_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = library.add_file(
                make_photo(root / "photo.png"), "bomdia", "morning",
                date(2027, 1, 1), "test", "approved",
                validation_receipt=receipt(),
            )
            library.save_atomic()
            library.reserve("run", date(2027, 1, 9), "bomdia", [record])
            library.save_atomic()
            journal = root / "journal.json"
            catalog = {"batch_id": "batch", "complete": True}
            phase8.create_reserved_journal(
                journal, "batch", {"bomdia": "run"}, {"bomdia": [("phrase", 0)]}
            )
            phase8.mark_catalog_promoted(journal, catalog)
            self.assertEqual(
                phase8.recover_promotion_confirmation(library, journal, catalog),
                "promoted_usage_confirmed",
            )
            self.assertEqual(len(record.usages), 1)
            self.assertEqual(
                phase8.recover_promotion_confirmation(library, journal, catalog),
                "already_confirmed",
            )
            self.assertEqual(len(record.usages), 1)

    def test_cleanup_preserves_promoted_and_removes_abandoned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            library.reservations = [
                phase7.Reservation("abandoned", "2027-01-09", "bomdia", [], old),
                phase7.Reservation("promoted", "2027-01-09", "amor", [], old),
            ]
            journal = root / "journal.json"
            value = phase8.PromotionJournal(
                "batch", {"amor": "promoted"}, {"amor": []}, "promoted",
                "digest", datetime.now(timezone.utc).isoformat(),
            )
            phase8.write_journal_atomic(journal, value)
            removed = phase8.cleanup_reservations_safely(
                library, [journal], datetime.now(timezone.utc)
            )
            self.assertEqual(removed, ["abandoned"])
            self.assertEqual([item.run_id for item in library.reservations], ["promoted"])

    def test_real_local_candidate_categories_are_valid(self) -> None:
        report = (
            phase8.renderer.REPO_ROOT / ".generation-staging"
            / "ai-background-phase5" / "phase5-evaluation.json"
        )
        if not report.exists():
            self.skipTest("Phase 5 local evaluation fixtures unavailable")
        candidates = phase8.local_approved_candidates(10)
        self.assertEqual(len(candidates), 10)
        self.assertTrue(all(path.exists() for _category, path in candidates))
        self.assertTrue(all(category in phase8.renderer.CATEGORY_STYLES for category, _ in candidates))

    def test_initial_stock_cost_contains_all_scenarios_without_consumption(self) -> None:
        costs = phase8.initial_stock_cost()
        self.assertEqual(set(costs), {"ideal", "realistic", "conservative"})
        self.assertTrue(all(row["approved_backgrounds"] == 640 for row in costs.values()))


if __name__ == "__main__":
    unittest.main()
