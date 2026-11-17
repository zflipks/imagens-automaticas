from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase4_visual_validation as phase4
from phase3_visual_validation import assess_visual_quality, evaluation_dataset


@dataclass(frozen=True)
class OptimizedDecision:
    decision: phase4.Decision
    reasons: tuple[str, ...]
    recorded_risks: tuple[str, ...]
    evidence: dict[str, object]
    elapsed_seconds: float


@dataclass(frozen=True)
class ReserveEntry:
    name: str
    category: str
    fingerprint: str
    path: Path


def validate_file(path: Path) -> tuple[bool, str | None]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width < 512 or image.height < 512:
                return False, "invalid_dimensions"
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                return False, "invalid_format"
    except (OSError, ValueError):
        return False, "invalid_image_file"
    return True, None


def validate_background_optimized(
    image: Image.Image,
    ocr: phase4.OcrLike,
    category: str,
    scene: str,
    known_fingerprints: set[str] | None = None,
) -> OptimizedDecision:
    started = time.perf_counter()
    confirmed_text, _phase4_uncertain, evidence = phase4._text_evidence(image, ocr)
    quality = assess_visual_quality(image, scene)
    reasons: list[str] = []
    risks: list[str] = []

    fingerprint = pipeline.image_fingerprint(image)
    if confirmed_text:
        reasons.append("confirmed_background_text")
    if fingerprint in (known_fingerprints or set()):
        reasons.append("duplicate_fingerprint")
    if any(issue.startswith("possible_duplicate_moons:") for issue in quality.issues):
        reasons.append("probable_duplicate_moons")

    score = float(evidence["geometry_score"])
    geometry_reasons = tuple(str(item) for item in evidence["geometry_reasons"])
    strong = int(evidence["ocr_strong_count"])
    support = int(evidence["ocr_support_count"])
    likely_structural_mark = (
        not confirmed_text
        and score >= 1.18
        and any(reason.startswith("horizontal_edge_band:") for reason in geometry_reasons)
        and any(reason.startswith("edge_concentration:") for reason in geometry_reasons)
    )
    corroborated_ambiguity = (
        not confirmed_text
        and score >= 0.78
        and (strong >= 1 or support >= 3)
    )
    if likely_structural_mark:
        risks.append("possible_watermark_or_signature")
    if corroborated_ambiguity:
        risks.append("possible_background_text")

    scene_lower = scene.casefold()
    if any(term in scene_lower for term in phase4.HUMAN_TERMS):
        risks.append("anatomy_unverified")
    if any(term in scene_lower for term in phase4.IMPOSSIBLE_OBJECT_TERMS):
        risks.append("object_geometry_unverified")
    if quality.contrast_risk:
        risks.append("busy_overlay_region_requires_post_render_check")

    if reasons:
        decision = phase4.Decision.REJECTED
    elif "possible_watermark_or_signature" in risks or "possible_background_text" in risks:
        decision = phase4.Decision.QUARANTINE
    else:
        decision = phase4.Decision.APPROVED

    evidence.update({
        "fingerprint": fingerprint,
        "visual_quality": asdict(quality),
        "policy": "phase5-optimized",
    })
    return OptimizedDecision(
        decision,
        tuple(reasons or (["all_essential_background_gates_passed"] if decision == phase4.Decision.APPROVED else [])),
        tuple(risks),
        evidence,
        round(time.perf_counter() - started, 4),
    )


def choose_reserve(
    entries: Iterable[ReserveEntry],
    category: str,
    recent_fingerprints: set[str],
) -> ReserveEntry | None:
    for entry in entries:
        if entry.category != category:
            continue
        if entry.fingerprint in recent_fingerprints:
            continue
        valid, _reason = validate_file(entry.path)
        if valid:
            return entry
    return None


def preserve_catalog_on_incomplete_batch(
    previous_catalog: dict[str, object],
    completed_categories: set[str],
    required_categories: set[str],
) -> tuple[dict[str, object], bool]:
    if completed_categories != required_categories:
        return previous_catalog, True
    return {"status": "staged-complete", "categories": sorted(required_categories)}, False


def _phase4_rows() -> dict[str, dict[str, object]]:
    path = (
        renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase4"
        / "phase4-evaluation.json"
    )
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {row["name"]: row for row in report["existing"]["samples"]}


def evaluate_existing() -> dict[str, object]:
    ocr = pipeline.TesseractOcr()
    if not ocr.available():
        raise RuntimeError("Tesseract unavailable")
    old_rows = _phase4_rows()
    phase2_report_path = (
        renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase2"
        / "phase2-report.json"
    )
    scenes: dict[str, str] = {}
    if phase2_report_path.exists():
        payload = json.loads(phase2_report_path.read_text(encoding="utf-8"))
        scenes = {
            Path(str(item.get("background_file") or item.get("file") or "")).name:
            str(item.get("scene") or "")
            for item in payload.get("candidates", [])
        }

    rows: list[dict[str, object]] = []
    metrics = {"approved": 0, "rejected": 0, "quarantine": 0, "false_negative": 0}
    reason_audit: dict[str, int] = {}
    for name, path, expected_text in evaluation_dataset():
        if not path.exists():
            continue
        category = name.split("-", 2)[1]
        with Image.open(path) as source:
            result = validate_background_optimized(
                source.convert("RGB"), ocr, category, scenes.get(path.name, "")
            )
        metrics[result.decision.value] += 1
        if expected_text and result.decision == phase4.Decision.APPROVED:
            metrics["false_negative"] += 1
        previous = old_rows.get(name, {})
        for reason in previous.get("reasons", []):
            reason_audit[str(reason)] = reason_audit.get(str(reason), 0) + 1
        rows.append({
            "name": name,
            "file": str(path.relative_to(renderer.REPO_ROOT)),
            "expected_text": expected_text,
            "phase4_decision": previous.get("decision"),
            "phase4_reasons": previous.get("reasons", []),
            "phase5_decision": result.decision.value,
            "phase5_reasons": result.reasons,
            "recorded_risks": result.recorded_risks,
            "elapsed_seconds": result.elapsed_seconds,
        })
    return {"samples": rows, "metrics": metrics, "phase4_reason_audit": reason_audit}


def cost_estimate(approval_rate: float) -> dict[str, object]:
    neurons = pipeline.OBSERVED_NEURONS_PER_CANDIDATE
    free_daily = pipeline.FREE_NEURONS_PER_DAY
    usd_per_1000 = 0.011
    paid_base_usd = 5.0
    brl_per_usd_assumption = 5.50
    scenarios: list[dict[str, object]] = []
    for artwork_target in (110, 160):
        for strategy, backgrounds_needed in (
            ("unique_background_per_artwork", artwork_target),
            ("one_background_across_ten_styles", math.ceil(artwork_target / 10)),
        ):
            calls = math.ceil(backgrounds_needed / max(approval_rate, 0.01))
            daily_neurons = calls * neurons
            daily_overage = max(0.0, daily_neurons - free_daily)
            monthly_usd = (
                0.0 if daily_overage == 0
                else paid_base_usd + daily_overage / 1000 * usd_per_1000 * 30
            )
            scenarios.append({
                "strategy": strategy,
                "artworks_target": artwork_target,
                "approved_backgrounds_needed": backgrounds_needed,
                "candidate_calls": calls,
                "daily_neurons": round(daily_neurons, 1),
                "daily_free_limit_exceeded": daily_neurons > free_daily,
                "estimated_monthly_usd": round(monthly_usd, 2),
                "estimated_monthly_brl_at_5_50": round(
                    monthly_usd * brl_per_usd_assumption, 2
                ),
                "within_brl_50": monthly_usd * brl_per_usd_assumption <= 50,
            })
    return {
        "approval_rate_used": round(approval_rate, 4),
        "observed_neurons_per_candidate": neurons,
        "free_candidates_per_day_floor": math.floor(free_daily / neurons),
        "pricing_assumptions": {
            "free_neurons_per_day": free_daily,
            "usd_per_1000_neurons_above_free": usd_per_1000,
            "workers_paid_base_usd_per_month": paid_base_usd,
            "brl_per_usd": brl_per_usd_assumption,
        },
        "scenarios": scenarios,
        "paid_plan_not_authorized": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase5"
        / "phase5-evaluation.json",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    existing = evaluate_existing()
    phase2 = [row for row in existing["samples"] if row["name"].startswith("phase2-")]
    approved = sum(row["phase5_decision"] == "approved" for row in phase2)
    approval_rate = approved / max(1, len(phase2))
    report = {
        "existing_comparison": existing,
        "cost_estimate": cost_estimate(approval_rate),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "neurons_consumed": 0,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "metrics": existing["metrics"],
        "phase2_approval_rate": round(approval_rate, 4),
        "elapsed_seconds": report["elapsed_seconds"],
        "neurons_consumed": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
