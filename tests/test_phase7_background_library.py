from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

import gerar_imagens as renderer
import phase4_visual_validation as phase4
import phase7_background_library as phase7


def make_image(path: Path, color: tuple[int, int, int]) -> Path:
    image = Image.new("RGB", (1024, 1024), color)
    x = 80 + color[0] * 3
    ImageDraw.Draw(image).ellipse((x, 180, x + 220, 400), fill=(245, 235, 210))
    image.save(path, "PNG")
    return path


def approved_receipt() -> phase7.ValidationReceipt:
    return phase7.ValidationReceipt(
        "test-geometry", False, "approved", "approved",
        "2027-01-01T00:00:00+00:00", "test-evidence"
    )


def add_approved(library, *args, **kwargs):
    if len(args) < 6:
        kwargs.setdefault("approval_status", phase4.Decision.APPROVED.value)
    kwargs.setdefault("validation_receipt", approved_receipt())
    return library.add_file(*args, **kwargs)


class Phase7BackgroundLibraryTests(unittest.TestCase):
    def test_persistence_between_executions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "library.json"
            photo = make_image(root / "photo.png", (20, 100, 180))
            library = phase7.BackgroundLibrary(path)
            record = add_approved(library,
                photo, "bomdia", "amanhecer", date(2027, 1, 1), "cloudflare"
            )
            library.save_atomic()
            loaded = phase7.BackgroundLibrary.load(path)
            self.assertIn(record.image_id, loaded.records)
            self.assertEqual(loaded.records[record.image_id].origin, "cloudflare")

    def test_identical_and_near_identical_images_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = make_image(root / "first.png", (20, 100, 180))
            identical = root / "copy.png"
            identical.write_bytes(first.read_bytes())
            near = make_image(root / "near.png", (21, 101, 181))
            library = phase7.BackgroundLibrary(root / "library.json")
            one = add_approved(library, first, "bomdia", "a", date(2027, 1, 1), "test")
            two = add_approved(library, identical, "bomdia", "b", date(2027, 1, 1), "test")
            three = add_approved(library, near, "bomdia", "c", date(2027, 1, 1), "test")
            self.assertEqual(one.image_id, two.image_id)
            self.assertEqual(one.image_id, three.image_id)
            self.assertEqual(len(library.records), 1)

    def test_four_uses_maximum_in_moving_thirty_days(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = add_approved(library,
                make_image(root / "photo.png", (20, 100, 180)),
                "bomdia", "a", date(2026, 1, 1), "test"
            )
            for index, day in enumerate((1, 9, 17, 25)):
                record.usages.append(
                    phase7.Usage(
                        date(2027, 1, day).isoformat(), "bomdia",
                        f"phrase-{index}", index, f"batch-{index}"
                    )
                )
            self.assertFalse(
                library.eligible(record, date(2027, 1, 30), "bomdia", "new", 5)
            )
            self.assertTrue(
                library.eligible(record, date(2027, 2, 2), "bomdia", "new", 5)
            )

    def test_seven_complete_days_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = add_approved(library,
                make_image(root / "photo.png", (20, 100, 180)),
                "bomdia", "a", date(2026, 1, 1), "test"
            )
            record.usages.append(
                phase7.Usage("2027-01-01", "bomdia", "old", 0, "batch")
            )
            self.assertFalse(
                library.eligible(record, date(2027, 1, 8), "bomdia", "new", 1)
            )
            self.assertTrue(
                library.eligible(record, date(2027, 1, 9), "bomdia", "new", 1)
            )

    def test_reuses_require_different_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = add_approved(library,
                make_image(root / "photo.png", (20, 100, 180)),
                "bomdia", "a", date(2026, 1, 1), "test"
            )
            record.usages.extend([
                phase7.Usage("2027-01-01", "bomdia", "phrase-a", 0, "b1"),
                phase7.Usage("2027-01-09", "bomdia", "phrase-b", 1, "b2"),
            ])
            self.assertFalse(
                library.eligible(record, date(2027, 1, 17), "bomdia", "phrase-a", 2)
            )
            self.assertTrue(
                library.eligible(record, date(2027, 1, 17), "bomdia", "phrase-c", 2)
            )

    def test_same_background_cannot_be_reserved_by_two_categories_same_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = add_approved(library,
                make_image(root / "photo.png", (20, 100, 180)),
                "bomdia", "a", date(2026, 1, 1), "test"
            )
            library.reserve("run-a", date(2027, 1, 1), "bomdia", [record])
            with self.assertRaises(phase7.LibraryConflict):
                library.reserve("run-b", date(2027, 1, 1), "amor", [record])

    def test_rejected_quarantine_and_missing_files_are_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            records = []
            for index, status in enumerate(("rejected", "quarantine", "approved")):
                path = make_image(root / f"{index}.png", (index * 40 + 10, 90, 180))
                record = add_approved(library,
                    path, "bomdia", "a", date(2026, 1, 1), "test", status
                )
                records.append(record)
            Path(records[2].file_path).unlink()
            for record in records:
                self.assertFalse(
                    library.eligible(record, date(2027, 1, 10), "bomdia", "new", 1)
                )

    def test_simulation_does_not_mutate_persistent_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            library = phase7.BackgroundLibrary(path)
            library.save_atomic()
            before = path.read_bytes()
            phase7.build_simulation_report(date(2027, 1, 1))
            self.assertEqual(path.read_bytes(), before)

    def test_usage_is_recorded_only_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            record = add_approved(library,
                make_image(root / "photo.png", (20, 100, 180)),
                "bomdia", "a", date(2026, 1, 1), "test"
            )
            library.reserve("run", date(2027, 1, 9), "bomdia", [record])
            self.assertEqual(record.usages, [])
            library.confirm("run", [("new phrase", 2)], "batch")
            self.assertEqual(len(record.usages), 1)

    def test_revision_conflict_prevents_concurrent_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            original = phase7.BackgroundLibrary(path)
            original.save_atomic()
            first = phase7.BackgroundLibrary.load(path)
            second = phase7.BackgroundLibrary.load(path)
            first.save_atomic()
            with self.assertRaises(phase7.LibraryConflict):
                second.save_atomic()

    def test_end_to_end_selection_generates_only_missing_backgrounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = phase7.BackgroundLibrary(root / "library.json")
            for index in range(6):
                add_approved(library,
                    make_image(root / f"reuse-{index}.png", (10 + index * 20, 80, 160)),
                    "bomdia", "a", date(2026, 1, 1), "test"
                )
            calls = []

            def generate(category, slot, attempt):
                calls.append(attempt)
                return phase7.BackgroundRecord(
                    f"new-{attempt}", category, "generated", "simulated",
                    f"sha-{attempt}", f"{attempt:064x}", "2027-01-09",
                    "fake-cloudflare", phase4.Decision.APPROVED.value,
                    validation_receipt=approved_receipt(),
                )

            selected, assignments, generated_calls = phase7.prepare_category_batch(
                library, "bomdia", date(2027, 1, 9), "batch", "run",
                generate, 10
            )
            self.assertEqual(len(selected), 10)
            self.assertEqual(len({item.image_id for item in selected}), 10)
            self.assertEqual(len({style for _phrase, style in assignments}), 10)
            self.assertEqual(generated_calls, 4)

    def test_cloudflare_failure_and_budget_exhaustion_leave_batch_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = phase7.BackgroundLibrary(Path(directory) / "library.json")

            def failed(*_args):
                raise RuntimeError("cloudflare unavailable")

            with self.assertRaises(phase7.InsufficientBackgrounds):
                phase7.prepare_category_batch(
                    library, "bomdia", date(2027, 1, 9), "batch", "run",
                    failed, 3
                )
            self.assertEqual(library.reservations, [])

            with self.assertRaises(phase7.InsufficientBackgrounds):
                phase7.prepare_category_batch(
                    library, "bomdia", date(2027, 1, 9), "batch", "run2",
                    lambda *_args: None, 2
                )
            self.assertEqual(library.reservations, [])

    def test_ten_unique_backgrounds_phrases_and_styles(self) -> None:
        assignments = phase7.assignments_for_category("amor", "2027-01-01")
        self.assertEqual(len(assignments), 10)
        self.assertEqual(len({phrase for phrase, _style in assignments}), 10)
        self.assertEqual(len({style for _phrase, style in assignments}), 10)

    def test_moving_window_survives_month_boundary(self) -> None:
        record = phase7.SimRecord("id", "bomdia")
        record.usages = [
            (date(2027, 1, 10), "a", 0),
            (date(2027, 1, 18), "b", 1),
            (date(2027, 1, 26), "c", 2),
        ]
        self.assertFalse(
            phase7._sim_eligible(record, date(2027, 2, 3), "d", 3, set())
        )
        self.assertTrue(
            phase7._sim_eligible(record, date(2027, 2, 11), "d", 3, set())
        )

    def test_incomplete_flow_preserves_previous_catalog_contract(self) -> None:
        import phase5_approval_optimization as phase5

        previous = {"generated_at": "valid"}
        selected, preserved = phase5.preserve_catalog_on_incomplete_batch(
            previous, {"bomdia"}, {"bomdia", "amor"}
        )
        self.assertIs(selected, previous)
        self.assertTrue(preserved)


if __name__ == "__main__":
    unittest.main()
