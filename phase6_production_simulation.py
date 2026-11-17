from __future__ import annotations

import argparse
import calendar
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase5_approval_optimization as phase5

BACKGROUNDS_PER_CATEGORY = 10
NEURONS_PER_CANDIDATE = 172.8
FREE_NEURONS_PER_DAY = 10_000.0
USD_PER_1000_NEURONS = 0.011
WORKERS_PAID_BASE_USD = 5.0
USD_BRL_PTAX = 5.7851

SCENARIOS = {
    "ideal": {"approval_rate": 0.90, "safety_margin": 1.05},
    "realistic": {"approval_rate": 0.60, "safety_margin": 1.10},
    "conservative": {"approval_rate": 0.45, "safety_margin": 1.20},
}


@dataclass(frozen=True)
class SimulatedArtwork:
    category: str
    slot: int
    phrase_id: str
    style_id: int
    background_fingerprint: str
    candidate_attempts: int


@dataclass(frozen=True)
class DayEstimate:
    day: str
    categories: int
    artworks: int
    candidates: int
    neurons: float
    free_limit_exceeded: bool
    overage_neurons: float


def simulate_category(
    category: str,
    outcomes: Iterable[str] | None = None,
    recent_fingerprints: set[str] | None = None,
) -> tuple[list[SimulatedArtwork], int]:
    if category not in renderer.CATEGORY_STYLES:
        raise ValueError(f"unknown category: {category}")
    outcome_queue = iter(outcomes or ())
    recent = set(recent_fingerprints or set())
    used: set[str] = set()
    artworks: list[SimulatedArtwork] = []
    attempts_total = 0
    for slot, style_id in enumerate(renderer.CATEGORY_STYLE_ORDER[category], start=1):
        slot_attempts = 0
        while True:
            slot_attempts += 1
            attempts_total += 1
            fingerprint = f"{category}-slot-{slot}-attempt-{slot_attempts}"
            outcome = next(outcome_queue, "approved")
            if outcome not in {"approved", "rejected", "quarantine", "invalid"}:
                raise ValueError(f"unsupported outcome: {outcome}")
            if outcome != "approved":
                continue
            if fingerprint in used or fingerprint in recent:
                continue
            used.add(fingerprint)
            artworks.append(
                SimulatedArtwork(
                    category=category,
                    slot=slot,
                    phrase_id=f"{category}-phrase-{slot}",
                    style_id=style_id,
                    background_fingerprint=fingerprint,
                    candidate_attempts=slot_attempts,
                )
            )
            break
    validate_category_invariant(artworks)
    return artworks, attempts_total


def validate_category_invariant(artworks: list[SimulatedArtwork]) -> None:
    if len(artworks) != BACKGROUNDS_PER_CATEGORY:
        raise RuntimeError("category_batch_must_have_ten_artworks")
    if len({item.phrase_id for item in artworks}) != BACKGROUNDS_PER_CATEGORY:
        raise RuntimeError("phrases_must_be_unique")
    if len({item.style_id for item in artworks}) != BACKGROUNDS_PER_CATEGORY:
        raise RuntimeError("styles_must_be_unique")
    if len({item.background_fingerprint for item in artworks}) != BACKGROUNDS_PER_CATEGORY:
        raise RuntimeError("backgrounds_must_be_unique")


def simulate_complete_batch(
    categories: list[str],
    failure_category: str | None = None,
) -> dict[str, object]:
    previous_catalog = {"generated_at": "last-valid", "status": "published"}
    completed: set[str] = set()
    batches: dict[str, list[dict[str, object]]] = {}
    for category in categories:
        if category == failure_category:
            break
        outcomes = (
            ["rejected", "approved", "quarantine", "approved"]
            if category == categories[0]
            else None
        )
        artworks, _attempts = simulate_category(category, outcomes)
        batches[category] = [asdict(item) for item in artworks]
        completed.add(category)
    selected_catalog, preserved = phase5.preserve_catalog_on_incomplete_batch(
        previous_catalog, completed, set(categories)
    )
    return {
        "required_categories": categories,
        "completed_categories": sorted(completed),
        "artworks": sum(len(items) for items in batches.values()),
        "all_category_invariants_passed": all(
            len({item["background_fingerprint"] for item in items}) == 10
            and len({item["phrase_id"] for item in items}) == 10
            and len({item["style_id"] for item in items}) == 10
            for items in batches.values()
        ),
        "previous_catalog_preserved": preserved,
        "selected_catalog": selected_catalog,
    }


def candidate_count(artworks: int, scenario: dict[str, float]) -> int:
    raw = artworks / scenario["approval_rate"]
    return math.ceil(raw * scenario["safety_margin"])


def estimate_day(reference_date: date, scenario: dict[str, float]) -> DayEstimate:
    categories = renderer.active_categories(reference_date)
    artworks = len(categories) * BACKGROUNDS_PER_CATEGORY
    candidates = candidate_count(artworks, scenario)
    neurons = candidates * NEURONS_PER_CANDIDATE
    overage = max(0.0, neurons - FREE_NEURONS_PER_DAY)
    return DayEstimate(
        day=reference_date.isoformat(),
        categories=len(categories),
        artworks=artworks,
        candidates=candidates,
        neurons=round(neurons, 1),
        free_limit_exceeded=neurons > FREE_NEURONS_PER_DAY,
        overage_neurons=round(overage, 1),
    )


def estimate_month(year: int, month: int, scenario: dict[str, float]) -> dict[str, object]:
    days = [
        estimate_day(date(year, month, day), scenario)
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    total_overage = sum(day.overage_neurons for day in days)
    paid_required = total_overage > 0
    monthly_usd = (
        WORKERS_PAID_BASE_USD + total_overage / 1000 * USD_PER_1000_NEURONS
        if paid_required else 0.0
    )
    return {
        "year": year,
        "month": month,
        "artworks": sum(day.artworks for day in days),
        "candidates": sum(day.candidates for day in days),
        "neurons": round(sum(day.neurons for day in days), 1),
        "days_exceeding_free": sum(day.free_limit_exceeded for day in days),
        "overage_neurons": round(total_overage, 1),
        "paid_plan_required": paid_required,
        "cost_usd": round(monthly_usd, 2),
        "cost_brl_ptax": round(monthly_usd * USD_BRL_PTAX, 2),
        "seasonal_category_days": sum(
            max(0, day.categories - (12 if date(year, month, int(day.day[-2:])).weekday() >= 5 else 11))
            for day in days
        ),
    }


def estimate_profile(artworks: int, scenario: dict[str, float]) -> dict[str, object]:
    candidates = candidate_count(artworks, scenario)
    neurons = candidates * NEURONS_PER_CANDIDATE
    overage = max(0.0, neurons - FREE_NEURONS_PER_DAY)
    daily_ai_usd = overage / 1000 * USD_PER_1000_NEURONS
    return {
        "artworks": artworks,
        "categories": artworks // 10,
        "candidates": candidates,
        "neurons": round(neurons, 1),
        "free_limit_exceeded": neurons > FREE_NEURONS_PER_DAY,
        "overage_neurons": round(overage, 1),
        "daily_ai_overage_usd": round(daily_ai_usd, 4),
        "daily_ai_overage_brl": round(daily_ai_usd * USD_BRL_PTAX, 2),
    }


def build_report(year: int) -> dict[str, object]:
    profiles = {
        "weekday": 110,
        "saturday": 120,
        "sunday": 120,
        "initial_full": 160,
        "one_seasonal_weekday": 120,
        "one_seasonal_weekend": 130,
        "two_seasonals_weekday": 130,
        "two_seasonals_weekend": 140,
    }
    scenarios: dict[str, object] = {}
    for name, config in SCENARIOS.items():
        months = [estimate_month(year, month, config) for month in range(1, 13)]
        scenarios[name] = {
            "assumptions": config,
            "profiles": {
                profile: estimate_profile(artworks, config)
                for profile, artworks in profiles.items()
            },
            "months": months,
            "annual": {
                "artworks": sum(month["artworks"] for month in months),
                "candidates": sum(month["candidates"] for month in months),
                "neurons": round(sum(month["neurons"] for month in months), 1),
                "cost_usd": round(sum(month["cost_usd"] for month in months), 2),
                "cost_brl_ptax": round(
                    sum(month["cost_brl_ptax"] for month in months), 2
                ),
            },
        }

    weekday = date(2027, 2, 1)
    saturday = date(2027, 2, 6)
    sunday = date(2027, 2, 7)
    simulations = {
        "weekday": simulate_complete_batch(renderer.active_categories(weekday)),
        "saturday": simulate_complete_batch(renderer.active_categories(saturday)),
        "sunday": simulate_complete_batch(renderer.active_categories(sunday)),
        "initial_full": simulate_complete_batch(
            renderer.active_categories(weekday, initialize_all=True)
        ),
        "incomplete_preserves_previous": simulate_complete_batch(
            renderer.active_categories(weekday), failure_category="amor"
        ),
    }
    return {
        "rule": {
            "artworks_per_category": 10,
            "unique_phrases_per_category": 10,
            "unique_styles_per_category": 10,
            "unique_backgrounds_per_category": 10,
            "background_reuse_within_category_batch_allowed": False,
        },
        "observed": {
            "neurons_per_candidate_1024_4_steps": NEURONS_PER_CANDIDATE,
            "phase5_approval_rate": 0.60,
            "free_neurons_per_day": FREE_NEURONS_PER_DAY,
        },
        "pricing": {
            "workers_paid_base_usd_month": WORKERS_PAID_BASE_USD,
            "usd_per_1000_overage_neurons": USD_PER_1000_NEURONS,
            "usd_brl_ptax_sale_2026_11_17": USD_BRL_PTAX,
            "paid_plan_not_authorized": True,
        },
        "simulations": simulations,
        "scenarios": scenarios,
        "neurons_consumed_by_simulation": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument(
        "--report",
        type=Path,
        default=renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase6"
        / "phase6-simulation.json",
    )
    args = parser.parse_args()
    report = build_report(args.year)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        name: data["profiles"]["weekday"]
        for name, data in report["scenarios"].items()
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
