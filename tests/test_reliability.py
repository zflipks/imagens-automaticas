from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PIL import Image

import gerar_imagens as generator


def candidate(asset_id: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "url": f"https://example.test/{asset_id}.jpg",
        "title": "Foto temática",
        "creator": "Fotógrafo",
        "license": "cc0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "foreign_landing_url": f"https://example.test/{asset_id}",
        "tags": [{"name": "coffee"}],
    }


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        generator._DISCOVERED_RESERVE = {}
        generator._RESERVE_POOL = []
        generator._BLOCKED_FINGERPRINTS = set()

    def test_openverse_search_uses_requested_page(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": [candidate("pagina-3")]}
        session = Mock()
        session.get.return_value = response
        results = generator.openverse_search(session, "coffee", generator.random.Random(1), 3)
        self.assertEqual(len(results), 1)
        self.assertEqual(session.get.call_args.kwargs["params"]["page"], 3)
        self.assertEqual(session.get.call_args.kwargs["params"]["page_size"], generator.OPENVERSE_PAGE_SIZE)

    @patch.object(generator, "image_is_suitable", return_value=True)
    @patch.object(generator, "download_image")
    def test_download_failure_tries_next_candidate(self, download, _suitable) -> None:
        download.side_effect = [
            requests.ConnectionError("indisponível"),
            Image.new("RGB", (1080, 1080), "white"),
        ]
        result = generator.try_candidates(
            Mock(), [candidate("a"), candidate("b")], "bomdia", "café", "coffee", set()
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[1]["asset_id"], "b")
        self.assertEqual(download.call_count, 2)

    @patch.object(generator.time, "sleep")
    @patch.object(generator, "openverse_search", side_effect=requests.ConnectionError("API fora"))
    @patch.object(generator, "try_candidates")
    def test_api_outage_uses_reserve(self, try_candidates, _search, _sleep) -> None:
        reserve = generator.metadata_from_item(candidate("reserva"), "bomdia", "café", "coffee")
        reserve["visual_review_status"] = "approved"
        generator._RESERVE_POOL = [reserve]
        sentinel = (Image.new("RGB", (1080, 1080)), reserve)
        try_candidates.side_effect = lambda _s, items, *_args: sentinel if list(items) else None
        with patch.object(generator, "OPENVERSE_PAGES", 1), patch.object(generator, "DOWNLOAD_ATTEMPTS", 1):
            result = generator.fetch_thematic_background(Mock(), "bomdia", 1, date(2026, 11, 22), set())
        self.assertEqual(result[1]["asset_id"], "reserva")

    def _batch(self, root: Path, duplicate: bool = False, missing: bool = False):
        images = root / "imagens"
        catalog = {"generated_at": "test"}
        credits = {"categories": {}}
        history = {"last_generation": "2026-11-22", "categories": {}}
        for category in generator.CATEGORY_STYLES:
            catalog[category] = [f"url-{i}" for i in range(10)]
            entries = []
            assets = []
            signatures = []
            for index in range(10):
                asset = "duplicado" if duplicate else f"{category}-{index}"
                signature = f"sig-{category}-{index}"
                path = images / category / f"{category}_{index + 1}.jpg"
                if not (missing and category == "anonovo" and index == 9):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1080, 1080), "white").save(path, "JPEG")
                entries.append({"style_id": index + 1, "asset_id": asset, "art_signature": signature})
                assets.append(asset)
                signatures.append(signature)
            credits["categories"][category] = entries
            history["categories"][category] = {
                "recent_asset_ids": assets,
                "recent_art_signatures": signatures,
            }
        return images, catalog, credits, history

    def test_incomplete_batch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self._batch(Path(directory), missing=True)
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                generator.validate_staged_batch(*args)

    def test_repeated_background_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self._batch(Path(directory), duplicate=True)
            with self.assertRaisesRegex(RuntimeError, "fundos repetidos"):
                generator.validate_staged_batch(*args)

    def test_promotion_preflight_preserves_previous_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            backup = root / "backup"
            transaction = root / "transaction.json"
            old_index = root / "index.json"
            old_index.write_text('{"old": true}', encoding="utf-8")
            staging.mkdir()
            with (
                patch.object(generator, "REPO_ROOT", root),
                patch.object(generator, "STAGING_DIR", staging),
                patch.object(generator, "BACKUP_DIR", backup),
                patch.object(generator, "TRANSACTION_FILE", transaction),
            ):
                with self.assertRaisesRegex(RuntimeError, "Saída ausente"):
                    generator.promote_staged_batch()
            self.assertEqual(json.loads(old_index.read_text(encoding="utf-8")), {"old": True})

    def test_category_contract_and_styles(self) -> None:
        legacy = ["bomdia", "boatarde", "boanoite", "aniversario", "anonovo"]
        self.assertEqual(list(generator.CATEGORY_STYLES)[:5], legacy)
        self.assertEqual(len(generator.CATEGORY_STYLES), 16)
        for category, styles in generator.CATEGORY_STYLE_ORDER.items():
            self.assertIn(category, generator.CATEGORY_STYLES)
            self.assertEqual(len(styles), 10)
            self.assertEqual(len(set(styles)), 10)

    def test_daily_weekend_and_initial_schedules(self) -> None:
        weekday = generator.active_categories(date(2026, 11, 18))
        saturday = generator.active_categories(date(2026, 11, 21))
        sunday = generator.active_categories(date(2026, 11, 22))
        initial = generator.active_categories(date(2026, 11, 18), initialize_all=True)
        self.assertEqual(len(weekday), 11)
        self.assertEqual(len(saturday), 12)
        self.assertEqual(len(sunday), 12)
        self.assertIn("bomsabado", saturday)
        self.assertNotIn("felizdomingo", saturday)
        self.assertIn("felizdomingo", sunday)
        self.assertNotIn("bomsabado", sunday)
        self.assertEqual(len(initial), 16)

    def test_seasonal_windows_and_easter(self) -> None:
        self.assertEqual(generator.easter_date(2027), date(2027, 3, 28))
        self.assertTrue(generator.seasonal_category_is_active("pascoa", date(2027, 3, 1)))
        self.assertFalse(generator.seasonal_category_is_active("pascoa", date(2027, 2, 1)))
        self.assertTrue(generator.seasonal_category_is_active("natal", date(2026, 12, 24)))
        self.assertFalse(generator.seasonal_category_is_active("natal", date(2026, 11, 24)))
        self.assertTrue(generator.seasonal_category_is_active("anonovo", date(2027, 1, 10)))
        self.assertFalse(generator.seasonal_category_is_active("anonovo", date(2027, 1, 11)))

    def test_phrase_banks_cover_all_categories(self) -> None:
        phrases = generator.load_messages()
        self.assertEqual(set(phrases), set(generator.CATEGORY_STYLES))
        for category, values in phrases.items():
            self.assertGreaterEqual(len(values), 100, category)
            self.assertEqual(len(values), len(set(values)), category)

    def test_openverse_anonymous_page_size_is_supported(self) -> None:
        self.assertLessEqual(generator.OPENVERSE_PAGE_SIZE, 20)

    def test_openverse_cloudflare_403_is_finite(self) -> None:
        response = Mock(status_code=403, text="<title>Just a moment...</title> Cloudflare")
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(generator.OpenverseAccessError, "Cloudflare"):
            generator.openverse_search(session, "coffee", generator.random.Random(1), 1)
        self.assertEqual(session.get.call_count, 1)

    @patch.object(generator.time, "sleep")
    @patch.object(
        generator,
        "openverse_search",
        side_effect=generator.OpenverseAccessError(403, "Cloudflare"),
    )
    def test_real_local_reserve_file_survives_api_outage(self, _search, _sleep) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reserve_root = root / ".github" / "background-reserve-files"
            photo = reserve_root / "bomdia" / "coffee.jpg"
            photo.parent.mkdir(parents=True)
            Image.new("RGB", (1200, 900), (210, 150, 70)).save(photo, "JPEG")
            digest = generator.hashlib.sha256(photo.read_bytes()).hexdigest()
            entry = candidate("reserva-local")
            entry.update(
                {
                    "category": "bomdia",
                    "theme": "café",
                    "search_terms": "coffee",
                    "local_file": ".github/background-reserve-files/bomdia/coffee.jpg",
                    "file_sha256": digest,
                    "visual_review_status": "approved",
                }
            )
            generator._RESERVE_POOL = [entry]
            with (
                patch.object(generator, "REPO_ROOT", root),
                patch.object(generator, "LOCAL_RESERVE_DIR", reserve_root),
                patch.object(generator, "OPENVERSE_PAGES", 1),
                patch.object(generator, "DOWNLOAD_ATTEMPTS", 1),
            ):
                image, metadata = generator.fetch_thematic_background(
                    Mock(), "bomdia", 1, date(2026, 11, 22), set()
                )
            self.assertEqual(image.size, (1200, 900))
            self.assertEqual(metadata["background_origin"], "local-reserve")

    def test_checkpoint_can_resume_completed_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_file = Path(directory) / "checkpoint.json"
            with patch.object(generator, "CHECKPOINT_FILE", checkpoint_file):
                generator.save_generation_checkpoint(
                    date(2026, 11, 22),
                    ["bomdia", "boatarde"],
                    ["bomdia"],
                    "2026-11-22T09:00:00Z",
                    {"categories": {"bomdia": []}},
                    {"categories": {"bomdia": {}}},
                    {"bomdia": list(range(10))},
                    {"asset-1"},
                )
                checkpoint = generator.load_generation_checkpoint(
                    date(2026, 11, 22), ["bomdia", "boatarde"]
                )
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint["completed_categories"], ["bomdia"])


if __name__ == "__main__":
    unittest.main()
