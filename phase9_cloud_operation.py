from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase4_visual_validation as phase4
import phase6_production_simulation as phase6
import phase7_background_library as phase7
import phase8_production_integration as phase8

STAGING_ROOT = renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase9"
DEFAULT_STATE_ROOT = STAGING_ROOT / "state"
DEFAULT_MAX_CALLS = 57
DEFAULT_MAX_NEURONS = 9_849.6


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class BudgetLedger:
    max_calls: int
    max_neurons: float
    projected_calls: int = 0
    projected_neurons: float = 0.0
    observed_neurons: float = 0.0

    def reserve_candidate(self) -> None:
        next_calls = self.projected_calls + 1
        next_neurons = self.projected_neurons + phase6.NEURONS_PER_CANDIDATE
        if next_calls > self.max_calls or next_neurons > self.max_neurons:
            raise BudgetExhausted("daily_generation_budget_exhausted")
        self.projected_calls = next_calls
        self.projected_neurons = next_neurons


class CleanSimulatedOcr:
    name = "simulated-clean-ocr"

    def available(self) -> bool:
        return True

    def detect(self, _image: Image.Image) -> list[pipeline.OcrDetection]:
        return []


def cloudflare_secret_status() -> dict[str, bool]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    return {
        "account_id_available": bool(account_id),
        "account_id_format_valid": bool(re.fullmatch(r"[0-9a-fA-F]{32}", account_id)),
        "api_token_available": bool(os.getenv("CLOUDFLARE_API_TOKEN")),
    }


def _simulated_background(path: Path, category: str, slot: int, day: date) -> Path:
    seed = int(hashlib.sha256(f"{day}|{category}|{slot}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    top = tuple(rng.randint(175, 225) for _ in range(3))
    bottom = tuple(rng.randint(135, 185) for _ in range(3))
    gradient = Image.new("RGB", (1, 1024))
    gradient.putdata([
        tuple(round(top[channel] * (1 - y / 1023) + bottom[channel] * (y / 1023)) for channel in range(3))
        for y in range(1024)
    ])
    image = gradient.resize((1024, 1024))
    draw = ImageDraw.Draw(image)
    for index in range(5):
        x = rng.randint(40, 900)
        y = rng.randint(60, 430)
        radius = rng.randint(35, 135)
        color = tuple(min(235, value + rng.randint(15, 65)) for value in top)
        draw.ellipse((x, y, x + radius, y + radius), fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=90)
    return path


def _messages_and_styles(category: str, day: date) -> list[tuple[str, int]]:
    messages = renderer.load_messages()[category]
    styles = list(renderer.CATEGORY_STYLE_ORDER[category])
    selected = renderer.choose_messages(messages, [], category, day, styles)
    result = list(zip(selected, styles))
    if len(result) != 10 or len(set(selected)) != 10 or len(set(styles)) != 10:
        raise RuntimeError("invalid_phrase_or_style_assignment")
    return result


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(renderer.REPO_ROOT))
    except ValueError:
        return str(path)


def run_isolated_batch(
    reference_date: date,
    categories: list[str],
    state_root: Path = DEFAULT_STATE_ROOT,
    staging_root: Path = STAGING_ROOT,
    max_calls: int = DEFAULT_MAX_CALLS,
    max_neurons: float = DEFAULT_MAX_NEURONS,
    use_tesseract: bool = False,
    fail_after_render: bool = False,
) -> dict[str, object]:
    unknown = set(categories) - set(renderer.CATEGORY_STYLES)
    if unknown:
        raise ValueError(f"unknown_categories:{sorted(unknown)}")
    state_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    library_path = state_root / "background-library.json"
    library = phase7.BackgroundLibrary.load(library_path)
    ledger = BudgetLedger(max_calls, max_neurons)
    ocr = pipeline.TesseractOcr() if use_tesseract else CleanSimulatedOcr()
    if not ocr.available():
        raise RuntimeError("tesseract_not_available")
    batch_id = f"phase9-{reference_date.isoformat()}"
    journal_path = state_root / "journals" / f"{batch_id}.json"
    run_ids: dict[str, str] = {}
    journal_assignments: dict[str, list[tuple[str, int]]] = {}
    catalog_categories: dict[str, list[dict[str, object]]] = {}
    rendered_root = staging_root / batch_id / "rendered"

    try:
        for category in categories:
            assignments = _messages_and_styles(category, reference_date)
            selection = library.select(category, reference_date, assignments, batch_id)
            selected = list(selection.records)
            while len(selected) < 10:
                ledger.reserve_candidate()
                slot = len(selected)
                candidate_path = state_root / "backgrounds" / category / f"{batch_id}-{slot + 1:02d}.jpg"
                _simulated_background(candidate_path, category, slot, reference_date)
                record, _evidence = phase8.validate_and_register(
                    library, candidate_path, category, "simulated-cloud-test",
                    reference_date, "phase9-simulated-source",
                    pipeline.CATEGORY_SCENES[category][slot % len(pipeline.CATEGORY_SCENES[category])],
                    ocr, {"simulated": True, "neurons_observed": 0.0},
                )
                if record.approval_status != phase4.Decision.APPROVED.value:
                    continue
                if record.image_id in {item.image_id for item in selected}:
                    continue
                selected.append(record)
            if len({record.image_id for record in selected}) != 10:
                raise RuntimeError("background_identity_not_unique")
            run_id = f"{batch_id}-{category}"
            library.reserve(run_id, reference_date, category, selected)
            run_ids[category] = run_id
            journal_assignments[category] = assignments
            category_rows = []
            for slot, (record, (message, style_id)) in enumerate(zip(selected, assignments), start=1):
                with Image.open(record.file_path) as source:
                    background = source.convert("RGB")
                artwork, legibility = phase4.render_and_validate(
                    background, category, message, style_id, style_id,
                    f"{batch_id}:{category}:{slot}",
                )
                if legibility.decision != phase4.Decision.APPROVED.value:
                    raise RuntimeError(f"rendered_phrase_not_legible:{category}:{slot}:{legibility.reasons}")
                target = rendered_root / category / f"{slot:02d}.jpg"
                target.parent.mkdir(parents=True, exist_ok=True)
                artwork.convert("RGB").save(target, "JPEG", quality=92)
                category_rows.append({
                    "slot": slot, "image_id": record.image_id, "phrase": message,
                    "style_id": style_id, "file": _display_path(target),
                })
            catalog_categories[category] = category_rows

        library.save_atomic()
        phase8.create_reserved_journal(journal_path, batch_id, run_ids, journal_assignments)
        catalog = {
            "batch_id": batch_id, "reference_date": reference_date.isoformat(),
            "isolated": True, "categories": catalog_categories,
        }
        catalog_path = staging_root / batch_id / "catalog.json"
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = catalog_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, catalog_path)
        phase8.mark_catalog_promoted(journal_path, catalog)
        if fail_after_render:
            raise RuntimeError("injected_failure_after_isolated_promotion")
        phase8.recover_promotion_confirmation(library, journal_path, catalog)
        return {
            "status": "confirmed", "batch_id": batch_id,
            "categories": len(categories), "artworks": sum(map(len, catalog_categories.values())),
            "projected_calls": ledger.projected_calls,
            "projected_neurons_if_real": round(ledger.projected_neurons, 1),
            "observed_neurons": ledger.observed_neurons,
            "catalog": _display_path(catalog_path),
            "state_library": str(library_path),
            "secrets": cloudflare_secret_status(),
        }
    except Exception:
        if library_path.exists():
            recovery_library = phase7.BackgroundLibrary.load(library_path)
            journal = phase8.load_journal(journal_path)
            if journal and journal.status == "reserved":
                phase8.recover_promotion_confirmation(recovery_library, journal_path, None)
        raise


def recurring_paid_cost(overage_neurons_by_month: list[float], subscription_active: bool) -> list[dict[str, float]]:
    rows = []
    for index, overage in enumerate(overage_neurons_by_month, start=1):
        base = phase6.WORKERS_PAID_BASE_USD if subscription_active else 0.0
        variable = max(0.0, overage) / 1000 * phase6.USD_PER_1000_NEURONS
        usd = base + variable
        rows.append({"month": index, "overage_neurons": overage, "cost_usd": round(usd, 2),
                     "cost_brl": round(usd * phase6.USD_BRL_PTAX, 2)})
    return rows


def gradual_stock_plan(target: int = 160, approval_rate: float = 0.60, daily_calls: int = 49) -> dict[str, object]:
    approved_per_day = math.floor(daily_calls * approval_rate)
    days = math.ceil(target / approved_per_day)
    return {
        "target_approved": target, "approval_rate": approval_rate,
        "candidate_calls_per_day": daily_calls,
        "projected_neurons_per_day": round(daily_calls * phase6.NEURONS_PER_CANDIDATE, 1),
        "approved_per_day": approved_per_day, "estimated_days": days,
        "within_free_daily_neurons": daily_calls * phase6.NEURONS_PER_CANDIDATE <= phase6.FREE_NEURONS_PER_DAY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--categories", default="bomdia")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--max-neurons", type=float, default=DEFAULT_MAX_NEURONS)
    parser.add_argument("--use-tesseract", action="store_true")
    parser.add_argument("--report", type=Path, default=STAGING_ROOT / "phase9-preparation-report.json")
    args = parser.parse_args()
    categories = [value.strip() for value in args.categories.split(",") if value.strip()]
    result = run_isolated_batch(
        args.date, categories, args.state_root, args.staging_root,
        args.max_calls, args.max_neurons, args.use_tesseract,
    )
    report = {
        "isolated_batch": result,
        "gradual_initial_stock_160": gradual_stock_plan(),
        "recurring_paid_subscription_example": recurring_paid_cost(
            [112755.2, 0.0, 0.0], subscription_active=True
        ),
        "free_mode_example": recurring_paid_cost(
            [0.0, 0.0, 0.0], subscription_active=False
        ),
        "cloudflare_calls_performed": 0,
        "neurons_consumed": 0.0,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
