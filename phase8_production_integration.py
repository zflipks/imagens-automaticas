from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase3_visual_validation as phase3
import phase4_visual_validation as phase4
import phase5_approval_optimization as phase5
import phase6_production_simulation as phase6
import phase7_background_library as phase7

PHASE8_ROOT = renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase8"


@dataclass
class PromotionJournal:
    batch_id: str
    run_ids: dict[str, str]
    assignments: dict[str, list[tuple[str, int]]]
    status: str
    catalog_digest: str | None
    updated_at: str


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_and_register(
    library: phase7.BackgroundLibrary,
    path: Path,
    category: str,
    theme: str,
    generated_at: date,
    origin: str,
    scene: str,
    ocr: pipeline.OcrEngine,
    metadata: dict[str, object] | None = None,
) -> tuple[phase7.BackgroundRecord, dict[str, object]]:
    valid, invalid_reason = phase7._valid_image_file(path)
    if not valid:
        raise ValueError(invalid_reason)
    with Image.open(path) as source:
        image = source.convert("RGB")
    geometry = phase3.TypographyRegionDetector().analyze(image)
    phase4_result = phase4.validate_background_three_state(
        image, ocr, category, scene
    )
    phase5_result = phase5.validate_background_optimized(
        image, ocr, category, scene
    )
    final_decision = phase5_result.decision
    evidence = {
        "phase3": {
            "detector": phase3.TypographyRegionDetector.name,
            "text_region": geometry.has_text_region,
            "score": geometry.score,
            "reasons": geometry.reasons,
        },
        "phase4": {
            "decision": phase4_result.decision.value,
            "reasons": phase4_result.reasons,
        },
        "phase5": {
            "decision": phase5_result.decision.value,
            "reasons": phase5_result.reasons,
            "risks": phase5_result.recorded_risks,
        },
    }
    receipt = phase7.ValidationReceipt(
        phase3_detector=phase3.TypographyRegionDetector.name,
        phase3_text_region=geometry.has_text_region,
        phase4_decision=phase4_result.decision.value,
        phase5_decision=phase5_result.decision.value,
        validated_at=datetime.now(timezone.utc).isoformat(),
        evidence_digest=_json_digest(evidence),
    )
    record = library.add_file(
        path,
        category,
        theme,
        generated_at,
        origin,
        approval_status=final_decision.value,
        metadata={**(metadata or {}), "validation_evidence": evidence},
        validation_receipt=receipt,
    )
    return record, evidence


def write_journal_atomic(path: Path, journal: PromotionJournal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(asdict(journal), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_journal(path: Path) -> PromotionJournal | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["assignments"] = {
        category: [tuple(item) for item in assignments]
        for category, assignments in payload["assignments"].items()
    }
    return PromotionJournal(**payload)


def create_reserved_journal(
    path: Path,
    batch_id: str,
    run_ids: dict[str, str],
    assignments: dict[str, list[tuple[str, int]]],
) -> PromotionJournal:
    journal = PromotionJournal(
        batch_id,
        run_ids,
        assignments,
        "reserved",
        None,
        datetime.now(timezone.utc).isoformat(),
    )
    write_journal_atomic(path, journal)
    return journal


def mark_catalog_promoted(
    path: Path, catalog: dict[str, object]
) -> PromotionJournal:
    journal = load_journal(path)
    if journal is None or journal.status != "reserved":
        raise phase7.LibraryConflict("promotion_journal_not_reserved")
    journal.status = "promoted"
    journal.catalog_digest = _json_digest(catalog)
    journal.updated_at = datetime.now(timezone.utc).isoformat()
    write_journal_atomic(path, journal)
    return journal


def recover_promotion_confirmation(
    library: phase7.BackgroundLibrary,
    journal_path: Path,
    current_catalog: dict[str, object] | None,
) -> str:
    journal = load_journal(journal_path)
    if journal is None:
        return "nothing_to_recover"
    if journal.status == "confirmed":
        return "already_confirmed"
    if journal.status == "reserved":
        for run_id in journal.run_ids.values():
            library.release(run_id)
        library.save_atomic()
        journal.status = "rolled_back"
        journal.updated_at = datetime.now(timezone.utc).isoformat()
        write_journal_atomic(journal_path, journal)
        return "unpromoted_reservations_released"
    if journal.status == "rolled_back":
        return "already_rolled_back"
    if journal.status != "promoted":
        raise phase7.LibraryConflict("unknown_promotion_journal_status")
    if current_catalog is None or _json_digest(current_catalog) != journal.catalog_digest:
        raise phase7.LibraryConflict("promoted_catalog_digest_mismatch")
    for category, run_id in journal.run_ids.items():
        library.confirm(
            run_id, journal.assignments[category], journal.batch_id
        )
    library.save_atomic()
    journal.status = "confirmed"
    journal.updated_at = datetime.now(timezone.utc).isoformat()
    write_journal_atomic(journal_path, journal)
    return "promoted_usage_confirmed"


def cleanup_reservations_safely(
    library: phase7.BackgroundLibrary,
    journal_paths: list[Path],
    now: datetime,
    max_age: timedelta = timedelta(hours=6),
) -> list[str]:
    protected: set[str] = set()
    for path in journal_paths:
        journal = load_journal(path)
        if journal and journal.status == "promoted":
            protected.update(journal.run_ids.values())
    return library.cleanup_abandoned_reservations(now, max_age, protected)


def local_approved_candidates(limit: int = 10) -> list[tuple[str, Path]]:
    report_path = (
        renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase5"
        / "phase5-evaluation.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [
        row for row in report["existing_comparison"]["samples"]
        if row["phase5_decision"] == phase4.Decision.APPROVED.value
    ]
    candidates: list[tuple[str, Path]] = []
    for row in rows[:limit]:
        parts = str(row["name"]).split("-")
        category = parts[1] if parts[0] == "phase1" else parts[2]
        candidates.append((category, renderer.REPO_ROOT / str(row["file"])))
    return candidates


def assemble_local_artworks(
    output_root: Path = PHASE8_ROOT,
    limit: int = 10,
) -> dict[str, object]:
    candidates = local_approved_candidates(limit)
    if len(candidates) < limit:
        raise RuntimeError("not_enough_locally_approved_photos")
    output_root.mkdir(parents=True, exist_ok=True)
    rendered_dir = output_root / "rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    library_path = output_root / "audit-library.json"
    library = phase7.BackgroundLibrary(library_path)
    ocr = pipeline.TesseractOcr()
    messages = renderer.load_messages()
    rows: list[dict[str, object]] = []
    used_messages: set[str] = set()
    rendered_images: list[tuple[str, Image.Image]] = []

    for index, (category, path) in enumerate(candidates):
        scene = pipeline.CATEGORY_SCENES.get(category, ("photographic background",))[0]
        record, evidence = validate_and_register(
            library,
            path,
            category,
            "local audit",
            date(2026, 11, 17),
            "existing-local-file",
            scene,
            ocr,
        )
        if record.approval_status != phase4.Decision.APPROVED.value:
            rows.append({
                "category": category,
                "file": str(path.relative_to(renderer.REPO_ROOT)),
                "decision": record.approval_status,
                "evidence": evidence,
            })
            continue
        style_id = index % renderer.STYLE_COUNT
        message = next(
            value for value in messages[category] if value not in used_messages
        )
        used_messages.add(message)
        with Image.open(path) as source:
            background = source.convert("RGB")
        rendered, legibility = phase4.render_and_validate(
            background,
            category,
            message,
            style_id,
            style_id,
            f"phase8:{category}:{index}",
        )
        target = rendered_dir / f"{index + 1:02d}-{category}-style-{style_id}.jpg"
        rendered.convert("RGB").save(target, "JPEG", quality=92)
        rendered_images.append((category, rendered.convert("RGB")))
        rows.append({
            "category": category,
            "file": str(path.relative_to(renderer.REPO_ROOT)),
            "image_id": record.image_id,
            "style_id": style_id,
            "message": message,
            "rendered_file": str(target.relative_to(renderer.REPO_ROOT)),
            "background_decision": record.approval_status,
            "post_render_legibility": asdict(legibility),
            "evidence": evidence,
        })

    library.save_atomic()
    mosaic_path = output_root / "local-artworks-mosaic.jpg"
    _make_mosaic(rendered_images, mosaic_path)
    file_sizes = [path.stat().st_size for _category, path in candidates]
    return {
        "requested": limit,
        "registered_approved": sum(
            row.get("background_decision") == phase4.Decision.APPROVED.value
            for row in rows
        ),
        "rendered": len(rendered_images),
        "unique_background_ids": len({
            row["image_id"] for row in rows if "image_id" in row
        }),
        "unique_messages": len({
            row["message"] for row in rows if "message" in row
        }),
        "styles_used": sorted({
            row["style_id"] for row in rows if "style_id" in row
        }),
        "average_local_background_bytes": round(sum(file_sizes) / len(file_sizes)),
        "estimated_640_background_bytes": round(
            sum(file_sizes) / len(file_sizes) * 640
        ),
        "mosaic": str(mosaic_path.relative_to(renderer.REPO_ROOT)),
        "rows": rows,
    }


def _make_mosaic(items: list[tuple[str, Image.Image]], path: Path) -> None:
    thumb_size = 320
    columns = 5
    rows = max(1, (len(items) + columns - 1) // columns)
    canvas = Image.new("RGB", (columns * thumb_size, rows * thumb_size), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (category, image) in enumerate(items):
        thumb = ImageOps.fit(image, (thumb_size, thumb_size), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_size
        y = (index // columns) * thumb_size
        canvas.paste(thumb, (x, y))
        draw.rectangle((x, y, x + 150, y + 28), fill=(0, 0, 0))
        draw.text((x + 7, y + 6), category, fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "JPEG", quality=90)


def initial_stock_cost() -> dict[str, object]:
    scenarios = {}
    for name, config in phase6.SCENARIOS.items():
        calls = phase6.candidate_count(640, config)
        neurons = calls * phase6.NEURONS_PER_CANDIDATE
        overage = max(0.0, neurons - phase6.FREE_NEURONS_PER_DAY)
        usd = phase6.WORKERS_PAID_BASE_USD + (
            overage / 1000 * phase6.USD_PER_1000_NEURONS
        )
        scenarios[name] = {
            "approved_backgrounds": 640,
            "candidate_calls": calls,
            "neurons": round(neurons, 1),
            "one_day_cost_usd": round(usd, 2),
            "one_day_cost_brl": round(usd * phase6.USD_BRL_PTAX, 2),
            "note": "One-day formation; spreading across days uses more free allocation.",
        }
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report", type=Path, default=PHASE8_ROOT / "phase8-audit.json"
    )
    args = parser.parse_args()
    local = assemble_local_artworks()
    report = {
        "local_integration": local,
        "initial_640_stock_cost": initial_stock_cost(),
        "storage": {
            "recommended": "Git LFS plus versioned JSON on an operational branch",
            "github_actions_artifact_is_not_durable_primary_storage": True,
            "estimated_640_background_bytes": local["estimated_640_background_bytes"],
        },
        "neurons_consumed": 0,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "rendered": local["rendered"],
        "approved": local["registered_approved"],
        "unique": local["unique_background_ids"],
        "estimated_640_mb": round(
            local["estimated_640_background_bytes"] / 1024 / 1024, 2
        ),
        "neurons_consumed": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
