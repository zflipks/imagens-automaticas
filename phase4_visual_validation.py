from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
from phase3_visual_validation import TypographyRegionDetector, assess_visual_quality


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class ValidationDecision:
    decision: Decision
    reasons: tuple[str, ...]
    elapsed_seconds: float
    evidence: dict[str, object]


@dataclass(frozen=True)
class LegibilityResult:
    decision: Decision
    changed_pixel_ratio: float
    median_luminance_delta: float
    strong_contrast_ratio: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateResult:
    name: str
    decision: Decision
    background: ValidationDecision
    legibility: LegibilityResult | None


class OcrLike(Protocol):
    def detect(self, image: Image.Image) -> list[pipeline.OcrDetection]: ...


HUMAN_TERMS = {
    "hand", "hands", "person", "people", "friend", "friends", "couple",
    "runner", "family", "face", "woman", "man", "child", "children",
}
IMPOSSIBLE_OBJECT_TERMS = {
    "clock", "cutlery", "bicycle", "vehicle", "instrument", "furniture",
}
CATEGORY_TERMS: dict[str, set[str]] = {
    "bomdia": {"dawn", "sunrise", "morning", "coffee", "breakfast", "flowers"},
    "boatarde": {"afternoon", "tea", "garden", "sunlight", "terrace"},
    "boanoite": {"night", "moon", "stars", "lantern", "blue hour"},
    "aniversario": {"party", "cake", "balloons", "gifts", "celebration"},
    "anonovo": {"fireworks", "new year", "celebration", "midnight"},
    "fe": {"cross", "prayer", "spiritual", "light", "church"},
    "gratidao": {"gratitude", "peaceful", "sunlight", "nature"},
    "amizade": {"friends", "friendship", "picnic", "companionship"},
    "amor": {"love", "romantic", "couple", "roses", "hearts"},
    "motivacao": {"runner", "mountain", "path", "achievement", "sunrise"},
    "felizsemana": {"week", "planner", "flowers", "morning", "workspace"},
    "bomfimdesemana": {"weekend", "leisure", "hammock", "picnic", "beach"},
    "natal": {"christmas", "tree", "ornaments", "gifts", "snow"},
    "pascoa": {"easter", "eggs", "bunny", "spring", "basket"},
    "bomsabado": {"saturday", "breakfast", "garden", "leisure"},
    "felizdomingo": {"sunday", "family", "brunch", "peaceful", "church"},
}


def _text_evidence(
    image: Image.Image, ocr: OcrLike
) -> tuple[bool, bool, dict[str, object]]:
    detections = tuple(ocr.detect(image))
    geometry = TypographyRegionDetector().analyze(image)
    strong = [item for item in detections if pipeline.significant_text_detection(item)]
    support = [
        item for item in detections
        if len("".join(c for c in item.text if c.isalnum())) >= 2
        and item.confidence >= 50
    ]
    f = geometry.features
    geometry_band = (
        f.row_concentration >= 0.34
        and f.peak_band_density >= 0.34
        and f.peak_band_span >= 0.97
    )
    direct_phrase = any(
        " " in item.text.strip()
        and len("".join(c for c in item.text if c.isalpha())) >= 6
        and item.confidence >= 80
        for item in detections
    )
    corroborated = (
        bool(strong)
        or len(support) >= 4
        or max((item.confidence for item in detections), default=0.0) >= 90
    )
    rejected = (
        direct_phrase
        or (geometry_band and corroborated)
        or (geometry.has_text_region and len(strong) >= 2)
    )
    uncertain = (
        not rejected
        and (
            geometry.has_text_region
            or geometry_band
            or len(strong) >= 1
            or len(support) >= 3
        )
    )
    evidence = {
        "geometry_score": geometry.score,
        "geometry_reasons": geometry.reasons,
        "geometry_band": geometry_band,
        "ocr_count": len(detections),
        "ocr_support_count": len(support),
        "ocr_strong_count": len(strong),
        "ocr_max_confidence": round(
            max((item.confidence for item in detections), default=0.0), 2
        ),
        "ocr_text": [item.text for item in detections],
    }
    return rejected, uncertain, evidence


def validate_background_three_state(
    image: Image.Image,
    ocr: OcrLike,
    category: str,
    scene: str,
    known_fingerprints: set[str] | None = None,
) -> ValidationDecision:
    started = time.perf_counter()
    rejected_text, uncertain_text, evidence = _text_evidence(image, ocr)
    quality = assess_visual_quality(image, scene)
    reasons: list[str] = []
    quarantine: list[str] = []

    if rejected_text:
        reasons.append("confirmed_background_text")
    elif uncertain_text:
        quarantine.append("possible_background_text")

    fingerprint = pipeline.image_fingerprint(image)
    if fingerprint in (known_fingerprints or set()):
        reasons.append("duplicate_fingerprint")

    if any(issue.startswith("possible_duplicate_moons:") for issue in quality.issues):
        reasons.append("probable_duplicate_moons")

    scene_terms = set(scene.casefold().replace(",", " ").split())
    if scene_terms & HUMAN_TERMS:
        quarantine.append("human_anatomy_not_reliably_verifiable_locally")
    if scene_terms & IMPOSSIBLE_OBJECT_TERMS:
        quarantine.append("object_geometry_not_reliably_verifiable_locally")

    category_vocabulary = CATEGORY_TERMS.get(category, set())
    if scene.strip() and category_vocabulary and not any(
        term in scene.casefold() for term in category_vocabulary
    ):
        quarantine.append("category_compatibility_unconfirmed")

    if quality.contrast_risk:
        quarantine.append("background_overlay_region_busy")

    if reasons:
        decision = Decision.REJECTED
        final_reasons = reasons
    elif quarantine:
        decision = Decision.QUARANTINE
        final_reasons = quarantine
    else:
        decision = Decision.APPROVED
        final_reasons = ["all_background_gates_passed"]

    evidence.update(
        {
            "fingerprint": fingerprint,
            "visual_quality": asdict(quality),
            "category": category,
            "scene": scene,
        }
    )
    return ValidationDecision(
        decision=decision,
        reasons=tuple(final_reasons),
        elapsed_seconds=round(time.perf_counter() - started, 4),
        evidence=evidence,
    )


def validate_rendered_legibility(
    rendered: Image.Image,
    baseline_without_message: Image.Image,
) -> LegibilityResult:
    actual = rendered.convert("RGB")
    baseline = baseline_without_message.convert("RGB")
    if actual.size != baseline.size:
        return LegibilityResult(
            Decision.REJECTED, 0.0, 0.0, 0.0, ("render_size_mismatch",)
        )

    diff = ImageChops.difference(actual, baseline).convert("L")
    diff_values = list(diff.get_flattened_data())
    changed = [index for index, value in enumerate(diff_values) if value >= 10]
    changed_ratio = len(changed) / max(1, len(diff_values))
    if changed_ratio < 0.0005:
        return LegibilityResult(
            Decision.REJECTED,
            round(changed_ratio, 6),
            0.0,
            0.0,
            ("message_not_visibly_rendered",),
        )

    actual_luma = list(actual.convert("L").get_flattened_data())
    local_background = list(
        baseline.convert("L").filter(ImageFilter.GaussianBlur(7)).get_flattened_data()
    )
    deltas = sorted(abs(actual_luma[index] - local_background[index]) for index in changed)
    median_delta = float(deltas[len(deltas) // 2])
    strong_ratio = sum(delta >= 35 for delta in deltas) / len(deltas)

    if median_delta >= 28 and strong_ratio >= 0.35:
        decision = Decision.APPROVED
        reasons = ("post_render_contrast_passed",)
    elif median_delta < 12 or strong_ratio < 0.12:
        decision = Decision.REJECTED
        reasons = ("post_render_text_illegible",)
    else:
        decision = Decision.QUARANTINE
        reasons = ("post_render_legibility_uncertain",)
    return LegibilityResult(
        decision,
        round(changed_ratio, 6),
        round(median_delta, 2),
        round(strong_ratio, 4),
        reasons,
    )


def render_and_validate(
    background: Image.Image,
    category: str,
    message: str,
    style_id: int,
    palette_id: int,
    seed: str,
) -> tuple[Image.Image, LegibilityResult]:
    prepared = ImageOps.fit(
        background.convert("RGB"), renderer.IMAGE_SIZE, Image.Resampling.LANCZOS
    ).convert("RGBA")
    rendered = renderer.render_artwork(
        prepared, category, message, style_id, palette_id, seed
    )
    # A single neutral glyph keeps every approved style code path valid while
    # producing a minimal message layer for differential legibility measurement.
    baseline = renderer.render_artwork(
        prepared, category, "a", style_id, palette_id, seed
    )
    return rendered, validate_rendered_legibility(rendered, baseline)


def select_first_safe_candidate(
    candidates: Iterable[tuple[str, Image.Image, str]],
    ocr: OcrLike,
    category: str,
    message: str,
    style_id: int,
    palette_id: int,
    previous_valid: Image.Image | None = None,
) -> tuple[Image.Image | None, list[CandidateResult], bool]:
    results: list[CandidateResult] = []
    for name, image, scene in candidates:
        background_decision = validate_background_three_state(
            image, ocr, category, scene
        )
        if background_decision.decision != Decision.APPROVED:
            results.append(
                CandidateResult(name, background_decision.decision, background_decision, None)
            )
            continue
        rendered, legibility = render_and_validate(
            image, category, message, style_id, palette_id, name
        )
        final_decision = legibility.decision
        results.append(
            CandidateResult(name, final_decision, background_decision, legibility)
        )
        if final_decision == Decision.APPROVED:
            return rendered, results, False
    return previous_valid, results, previous_valid is not None


def controlled_fixtures() -> list[tuple[str, Image.Image, bool]]:
    base = Image.new("RGB", (1024, 1024), (128, 164, 105))
    fixtures: list[tuple[str, Image.Image, bool]] = [("clean", base, False)]
    font = ImageFont.load_default(size=64)
    cases = {
        "words": ("GOOD MORNING", (100, 130)),
        "watermark": ("stockphoto", (520, 900)),
        "signature": ("Jane 2026", (650, 780)),
        "sign": ("STOP 24H", (340, 390)),
        "packaging": ("COFFEE PREMIUM", (220, 590)),
    }
    for name, (text, position) in cases.items():
        image = base.copy()
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (position[0] - 12, position[1] - 12, position[0] + 520, position[1] + 90),
            fill=(238, 232, 210),
        )
        draw.text(position, text, font=font, fill=(20, 20, 20))
        fixtures.append((name, image, True))
    return fixtures


def evaluate_controlled() -> dict[str, object]:
    ocr = pipeline.TesseractOcr()
    if not ocr.available():
        raise RuntimeError("Tesseract unavailable")
    rows: list[dict[str, object]] = []
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "quarantine": 0}
    for name, image, expected_text in controlled_fixtures():
        result = validate_background_three_state(
            image, ocr, "bomdia", "morning coffee and flowers"
        )
        predicted = result.decision == Decision.REJECTED
        if result.decision == Decision.QUARANTINE:
            counts["quarantine"] += 1
        elif expected_text and predicted:
            counts["tp"] += 1
        elif expected_text:
            counts["fn"] += 1
        elif predicted:
            counts["fp"] += 1
        else:
            counts["tn"] += 1
        rows.append(
            {
                "name": name,
                "expected_text": expected_text,
                "decision": result.decision.value,
                "reasons": result.reasons,
                "elapsed_seconds": result.elapsed_seconds,
                "evidence": result.evidence,
            }
        )
    return {"samples": rows, "metrics": counts}


def evaluate_existing() -> dict[str, object]:
    from phase3_visual_validation import evaluation_dataset

    ocr = pipeline.TesseractOcr()
    if not ocr.available():
        raise RuntimeError("Tesseract unavailable")
    phase2_report = (
        renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase2"
        / "phase2-report.json"
    )
    scene_by_file: dict[str, str] = {}
    if phase2_report.exists():
        payload = json.loads(phase2_report.read_text(encoding="utf-8"))
        scene_by_file = {
            Path(str(item.get("background_file") or item.get("file") or "")).name:
            str(item.get("scene") or "")
            for item in payload.get("candidates", [])
        }
    rows: list[dict[str, object]] = []
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "quarantine": 0}
    for name, path, expected_text in evaluation_dataset():
        if not path.exists():
            continue
        category = name.split("-", 2)[1]
        with Image.open(path) as source:
            result = validate_background_three_state(
                source.convert("RGB"),
                ocr,
                category,
                scene_by_file.get(path.name, ""),
            )
        predicted = result.decision == Decision.REJECTED
        if expected_text and predicted:
            counts["tp"] += 1
        elif expected_text and result.decision == Decision.QUARANTINE:
            counts["quarantine"] += 1
        elif expected_text:
            counts["fn"] += 1
        elif predicted:
            counts["fp"] += 1
        elif result.decision == Decision.QUARANTINE:
            counts["quarantine"] += 1
        else:
            counts["tn"] += 1
        rows.append({
            "name": name,
            "file": str(path.relative_to(renderer.REPO_ROOT)),
            "expected_text": expected_text,
            "decision": result.decision.value,
            "reasons": result.reasons,
            "elapsed_seconds": result.elapsed_seconds,
        })
    return {"samples": rows, "metrics": counts}


def evaluate_ten_styles() -> dict[str, object]:
    path = (
        renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase2"
        / "backgrounds" / "01-bomdia-131e6402dc0e0b08.jpg"
    )
    if not path.exists():
        return {"samples": [], "metrics": {"missing_fixture": True}}
    with Image.open(path) as source:
        background = source.convert("RGB")
    rows: list[dict[str, object]] = []
    for style_id in range(renderer.STYLE_COUNT):
        _rendered, result = render_and_validate(
            background,
            "bomdia",
            "Que a esperança ilumine cada passo do seu dia.",
            style_id,
            style_id,
            f"phase4-style-{style_id}",
        )
        rows.append({"style_id": style_id, **asdict(result), "decision": result.decision.value})
    return {
        "samples": rows,
        "metrics": {
            "approved": sum(row["decision"] == Decision.APPROVED.value for row in rows),
            "rejected": sum(row["decision"] == Decision.REJECTED.value for row in rows),
            "quarantine": sum(row["decision"] == Decision.QUARANTINE.value for row in rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase4"
        / "phase4-evaluation.json",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    report = {
        "controlled": evaluate_controlled(),
        "existing": evaluate_existing(),
        "ten_styles": evaluate_ten_styles(),
        "limitations": [
            "Local heuristics cannot reliably prove correct human anatomy.",
            "Local heuristics cannot reliably identify every impossible object.",
            "Category compatibility uses declared scene metadata, not visual understanding.",
            "Quarantine is fail-safe and must trigger another candidate automatically.",
        ],
    }
    report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "controlled": report["controlled"]["metrics"],
        "existing": report["existing"]["metrics"],
        "ten_styles": report["ten_styles"]["metrics"],
        "elapsed_seconds": report["elapsed_seconds"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
