from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import phase7_background_library as phase7
import phase8_production_integration as phase8
import phase9_cloud_operation as phase9


class Phase9CloudOperationTests(unittest.TestCase):
    def test_budget_blocks_before_paid_consumption(self) -> None:
        ledger = phase9.BudgetLedger(max_calls=1, max_neurons=172.8)
        ledger.reserve_candidate()
        with self.assertRaises(phase9.BudgetExhausted):
            ledger.reserve_candidate()

    def test_secret_status_exposes_only_booleans(self) -> None:
        with patch.dict("os.environ", {
            "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
            "CLOUDFLARE_API_TOKEN": "test-placeholder-not-a-secret",
        }, clear=False):
            status = phase9.cloudflare_secret_status()
        self.assertEqual(status, {
            "account_id_available": True,
            "account_id_format_valid": True,
            "api_token_available": True,
        })
        self.assertNotIn("test-placeholder-not-a-secret", repr(status))

    def test_paid_base_is_recurring_even_without_overage(self) -> None:
        rows = phase9.recurring_paid_cost([1000.0, 0.0, 0.0], True)
        self.assertEqual([row["cost_usd"] for row in rows], [5.01, 5.0, 5.0])
        free = phase9.recurring_paid_cost([0.0], False)
        self.assertEqual(free[0]["cost_usd"], 0.0)

    def test_gradual_160_stock_plan_stays_below_free_daily_limit(self) -> None:
        plan = phase9.gradual_stock_plan()
        self.assertEqual(plan["target_approved"], 160)
        self.assertTrue(plan["within_free_daily_neurons"])
        self.assertGreaterEqual(plan["estimated_days"], 5)

    def test_isolated_batch_uses_ten_unique_photos_phrases_and_styles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = phase9.run_isolated_batch(
                date(2027, 1, 4), ["bomdia"],
                root / "state", root / "staging",
                max_calls=10, max_neurons=1728.0,
            )
            self.assertEqual(result["status"], "confirmed")
            self.assertEqual(result["artworks"], 10)
            self.assertEqual(result["observed_neurons"], 0.0)
            catalog = json.loads(Path(result["catalog"]).read_text(encoding="utf-8"))
            rows = catalog["categories"]["bomdia"]
            self.assertEqual(len({row["image_id"] for row in rows}), 10)
            self.assertEqual(len({row["phrase"] for row in rows}), 10)
            self.assertEqual(len({row["style_id"] for row in rows}), 10)
            library = phase7.BackgroundLibrary.load(root / "state" / "background-library.json")
            self.assertEqual(sum(len(record.usages) for record in library.records.values()), 10)
            self.assertTrue(all(record.validation_receipt for record in library.records.values()))

    def test_failure_after_promotion_is_recoverable_without_duplicate_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            staging = root / "staging"
            with self.assertRaisesRegex(RuntimeError, "injected_failure"):
                phase9.run_isolated_batch(
                    date(2027, 1, 4), ["bomdia"], state, staging,
                    max_calls=10, max_neurons=1728.0, fail_after_render=True,
                )
            library = phase7.BackgroundLibrary.load(state / "background-library.json")
            self.assertEqual(sum(len(record.usages) for record in library.records.values()), 0)
            journal_path = state / "journals" / "phase9-2027-01-04.json"
            catalog_path = staging / "phase9-2027-01-04" / "catalog.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(
                phase8.recover_promotion_confirmation(library, journal_path, catalog),
                "promoted_usage_confirmed",
            )
            self.assertEqual(sum(len(record.usages) for record in library.records.values()), 10)
            self.assertEqual(
                phase8.recover_promotion_confirmation(library, journal_path, catalog),
                "already_confirmed",
            )

    def test_incomplete_budget_never_creates_promoted_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(phase9.BudgetExhausted):
                phase9.run_isolated_batch(
                    date(2027, 1, 4), ["bomdia"],
                    root / "state", root / "staging",
                    max_calls=5, max_neurons=864.0,
                )
            self.assertFalse((root / "staging" / "phase9-2027-01-04" / "catalog.json").exists())


if __name__ == "__main__":
    unittest.main()
