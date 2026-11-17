from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image

import ai_background_pipeline as pipeline
import gerar_imagens as renderer
import phase4_visual_validation as phase4
import phase6_production_simulation as phase6

LIBRARY_VERSION = 2
MIN_COMPLETE_DAYS = 7
DEFAULT_MAX_USES_30_DAYS = 4
NEAR_DUPLICATE_DISTANCE = 14
DEFAULT_LIBRARY_ROOT = (
    renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase7"
)
DEFAULT_LIBRARY_FILE = DEFAULT_LIBRARY_ROOT / "background-library.json"


class LibraryConflict(RuntimeError):
    pass


class InsufficientBackgrounds(RuntimeError):
    pass


@dataclass
class Usage:
    day: str
    category: str
    phrase_id: str
    style_id: int
    batch_id: str


@dataclass
class ValidationReceipt:
    phase3_detector: str
    phase3_text_region: bool
    phase4_decision: str
    phase5_decision: str
    validated_at: str
    evidence_digest: str


@dataclass
class BackgroundRecord:
    image_id: str
    category: str
    theme: str
    file_path: str
    sha256: str
    perceptual_hash: str
    generated_at: str
    origin: str
    approval_status: str = phase4.Decision.QUARANTINE.value
    metadata: dict[str, object] = field(default_factory=dict)
    usages: list[Usage] = field(default_factory=list)
    validation_receipt: ValidationReceipt | None = None


@dataclass
class Reservation:
    run_id: str
    day: str
    category: str
    image_ids: list[str]
    created_at: str


@dataclass
class Selection:
    records: list[BackgroundRecord]
    new_required: int
    seed: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def visual_hash(image: Image.Image) -> str:
    """Composite perceptual signature: 256-bit dHash plus coarse RGB layout."""
    rgb = image.convert("RGB")
    gray = rgb.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data())
    gradient_bits = []
    for row in range(16):
        start = row * 17
        gradient_bits.extend(
            "1" if pixels[start + column] > pixels[start + column + 1] else "0"
            for column in range(16)
        )
    layout = rgb.resize((4, 4), Image.Resampling.BOX)
    color_bits = []
    for red, green, blue in layout.get_flattened_data():
        for value in (red, green, blue):
            color_bits.extend(f"{value >> 4:04b}")
    bits = "".join(gradient_bits + color_bits)
    return f"{int(bits, 2):0{len(bits) // 4}x}"


def visual_hash_file(path: Path) -> str:
    with Image.open(path) as image:
        return visual_hash(image)


def hash_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def stable_image_id(sha256: str, perceptual_hash: str) -> str:
    return hashlib.sha256(f"{sha256}:{perceptual_hash}".encode()).hexdigest()[:24]


class BackgroundLibrary:
    def __init__(
        self,
        path: Path = DEFAULT_LIBRARY_FILE,
        records: Iterable[BackgroundRecord] | None = None,
        reservations: Iterable[Reservation] | None = None,
        revision: int = 0,
    ):
        self.path = path
        self.records = {record.image_id: record for record in (records or [])}
        self.reservations = list(reservations or [])
        self.revision = revision
        self.loaded_revision = revision

    @classmethod
    def load(cls, path: Path = DEFAULT_LIBRARY_FILE) -> "BackgroundLibrary":
        if not path.exists():
            return cls(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_version = int(payload.get("version", 0))
        if source_version not in {1, LIBRARY_VERSION}:
            raise RuntimeError("unsupported_background_library_version")
        records = []
        migrated_ids: dict[str, str] = {}
        for raw in payload.get("records", []):
            data = dict(raw)
            data["usages"] = [Usage(**usage) for usage in data.get("usages", [])]
            receipt = data.get("validation_receipt")
            data["validation_receipt"] = (
                ValidationReceipt(**receipt) if isinstance(receipt, dict) else None
            )
            if source_version == 1:
                old_id = str(data["image_id"])
                file_path = Path(str(data["file_path"]))
                if file_path.exists():
                    data["perceptual_hash"] = visual_hash_file(file_path)
                    data["image_id"] = stable_image_id(
                        str(data["sha256"]), str(data["perceptual_hash"])
                    )
                migrated_ids[old_id] = str(data["image_id"])
            records.append(BackgroundRecord(**data))
        reservations = []
        for item in payload.get("reservations", []):
            reservation = dict(item)
            reservation["image_ids"] = [
                migrated_ids.get(str(image_id), str(image_id))
                for image_id in reservation.get("image_ids", [])
            ]
            reservations.append(Reservation(**reservation))
        return cls(path, records, reservations, int(payload.get("revision", 0)))

    def snapshot(self) -> dict[str, object]:
        return {
            "version": LIBRARY_VERSION,
            "revision": self.revision,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "records": [asdict(record) for record in self.records.values()],
            "reservations": [asdict(item) for item in self.reservations],
        }

    def save_atomic(self) -> None:
        if self.path.exists():
            disk = json.loads(self.path.read_text(encoding="utf-8"))
            if int(disk.get("revision", 0)) != self.loaded_revision:
                raise LibraryConflict("library_revision_changed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.revision = self.loaded_revision + 1
        temporary = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        self.loaded_revision = self.revision

    def add_file(
        self,
        path: Path,
        category: str,
        theme: str,
        generated_at: date,
        origin: str,
        approval_status: str = phase4.Decision.QUARANTINE.value,
        metadata: dict[str, object] | None = None,
        validation_receipt: ValidationReceipt | None = None,
    ) -> BackgroundRecord:
        valid, reason = _valid_image_file(path)
        if not valid:
            raise ValueError(reason)
        if approval_status == phase4.Decision.APPROVED.value:
            if validation_receipt is None:
                raise ValueError("approved_background_requires_validation_receipt")
            if validation_receipt.phase5_decision != phase4.Decision.APPROVED.value:
                raise ValueError("validation_receipt_does_not_approve")
        digest = sha256_file(path)
        perceptual = visual_hash_file(path)
        duplicate = self.find_duplicate(digest, perceptual)
        if duplicate:
            return duplicate
        record = BackgroundRecord(
            image_id=stable_image_id(digest, perceptual),
            category=category,
            theme=theme,
            file_path=str(path),
            sha256=digest,
            perceptual_hash=perceptual,
            generated_at=generated_at.isoformat(),
            origin=origin,
            approval_status=approval_status,
            metadata=dict(metadata or {}),
            validation_receipt=validation_receipt,
        )
        self.records[record.image_id] = record
        return record

    def find_duplicate(
        self, digest: str, perceptual_hash: str
    ) -> BackgroundRecord | None:
        for record in self.records.values():
            if record.sha256 == digest:
                return record
            if hash_distance(record.perceptual_hash, perceptual_hash) <= NEAR_DUPLICATE_DISTANCE:
                return record
        return None

    def eligible(
        self,
        record: BackgroundRecord,
        reference_date: date,
        category: str,
        phrase_id: str,
        style_id: int,
        max_uses_30_days: int = DEFAULT_MAX_USES_30_DAYS,
        excluded_ids: set[str] | None = None,
    ) -> bool:
        if record.image_id in (excluded_ids or set()):
            return False
        if record.category != category:
            return False
        if record.approval_status != phase4.Decision.APPROVED.value:
            return False
        valid, _reason = _valid_image_file(Path(record.file_path))
        if not valid:
            return False
        recent = [
            usage for usage in record.usages
            if reference_date - timedelta(days=29)
            <= date.fromisoformat(usage.day)
            <= reference_date
        ]
        if len(recent) >= max_uses_30_days:
            return False
        if record.usages:
            last_day = max(date.fromisoformat(usage.day) for usage in record.usages)
            if (reference_date - last_day).days < MIN_COMPLETE_DAYS + 1:
                return False
        if any(
            usage.phrase_id == phrase_id
            for usage in record.usages
        ):
            return False
        if any(
            reservation.day == reference_date.isoformat()
            and record.image_id in reservation.image_ids
            for reservation in self.reservations
        ):
            return False
        return True

    def select(
        self,
        category: str,
        reference_date: date,
        assignments: list[tuple[str, int]],
        batch_id: str,
        max_uses_30_days: int = DEFAULT_MAX_USES_30_DAYS,
        excluded_ids: set[str] | None = None,
    ) -> Selection:
        seed = hashlib.sha256(
            f"{batch_id}|{reference_date}|{category}|{self.revision}".encode()
        ).hexdigest()
        rng = random.Random(seed)
        candidates = list(self.records.values())
        rng.shuffle(candidates)
        selected: list[BackgroundRecord] = []
        used_styles: dict[str, set[int]] = {
            record.image_id: {usage.style_id for usage in record.usages}
            for record in candidates
        }
        for phrase_id, style_id in assignments:
            eligible = [
                record for record in candidates
                if record not in selected
                and self.eligible(
                    record,
                    reference_date,
                    category,
                    phrase_id,
                    style_id,
                    max_uses_30_days,
                    excluded_ids,
                )
            ]
            if not eligible:
                break
            eligible.sort(
                key=lambda record: (
                    style_id in used_styles[record.image_id],
                    len(record.usages),
                    record.image_id,
                )
            )
            selected.append(eligible[0])
        return Selection(selected, len(assignments) - len(selected), seed)

    def reserve(self, run_id: str, reference_date: date, category: str, records: list[BackgroundRecord]) -> None:
        if any(item.run_id == run_id for item in self.reservations):
            raise LibraryConflict("run_id_already_reserved")
        same_day = {
            image_id
            for item in self.reservations
            if item.day == reference_date.isoformat()
            for image_id in item.image_ids
        }
        ids = [record.image_id for record in records]
        if same_day.intersection(ids):
            raise LibraryConflict("background_already_reserved_same_day")
        self.reservations.append(
            Reservation(
                run_id,
                reference_date.isoformat(),
                category,
                ids,
                datetime.now(timezone.utc).isoformat(),
            )
        )

    def confirm(
        self,
        run_id: str,
        assignments: list[tuple[str, int]],
        batch_id: str,
    ) -> None:
        reservation = next(
            (item for item in self.reservations if item.run_id == run_id), None
        )
        if reservation is None:
            already_confirmed = [
                usage
                for record in self.records.values()
                for usage in record.usages
                if usage.batch_id == batch_id
            ]
            if len(already_confirmed) == len(assignments):
                return
            raise LibraryConflict("reservation_not_found")
        if len(reservation.image_ids) != len(assignments):
            raise LibraryConflict("reservation_assignment_mismatch")
        for image_id, (phrase_id, style_id) in zip(
            reservation.image_ids, assignments
        ):
            record = self.records[image_id]
            if not any(usage.batch_id == batch_id for usage in record.usages):
                record.usages.append(
                    Usage(
                        reservation.day,
                        reservation.category,
                        phrase_id,
                        style_id,
                        batch_id,
                    )
                )
        self.reservations.remove(reservation)

    def release(self, run_id: str) -> None:
        self.reservations = [
            item for item in self.reservations if item.run_id != run_id
        ]

    def cleanup_abandoned_reservations(
        self,
        now: datetime,
        max_age: timedelta,
        promoted_run_ids: set[str] | None = None,
    ) -> list[str]:
        promoted = promoted_run_ids or set()
        removed: list[str] = []
        retained: list[Reservation] = []
        for reservation in self.reservations:
            created = datetime.fromisoformat(reservation.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if reservation.run_id not in promoted and now - created > max_age:
                removed.append(reservation.run_id)
            else:
                retained.append(reservation)
        self.reservations = retained
        return removed


def _valid_image_file(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, "missing_file"
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width < 512 or image.height < 512:
                return False, "invalid_dimensions"
    except (OSError, ValueError):
        return False, "invalid_image"
    return True, None


def assignments_for_category(category: str, day_key: str) -> list[tuple[str, int]]:
    styles = list(renderer.CATEGORY_STYLE_ORDER[category])
    rng = random.Random(
        hashlib.sha256(f"{day_key}|{category}|assignments".encode()).hexdigest()
    )
    rng.shuffle(styles)
    return [
        (f"{category}-phrase-{day_key}-{index}", style)
        for index, style in enumerate(styles, start=1)
    ]


def prepare_category_batch(
    library: BackgroundLibrary,
    category: str,
    reference_date: date,
    batch_id: str,
    run_id: str,
    generate_candidate,
    max_new_calls: int,
    max_uses_30_days: int = DEFAULT_MAX_USES_30_DAYS,
    excluded_ids: set[str] | None = None,
) -> tuple[list[BackgroundRecord], list[tuple[str, int]], int]:
    assignments = assignments_for_category(category, reference_date.isoformat())
    selection = library.select(
        category,
        reference_date,
        assignments,
        batch_id,
        max_uses_30_days,
        excluded_ids,
    )
    selected = list(selection.records)
    calls = 0
    while len(selected) < len(assignments) and calls < max_new_calls:
        calls += 1
        try:
            candidate = generate_candidate(category, len(selected), calls)
        except Exception as error:
            raise InsufficientBackgrounds("background_source_failed") from error
        if candidate is None:
            continue
        if candidate.approval_status != phase4.Decision.APPROVED.value:
            continue
        if candidate.validation_receipt is None:
            continue
        if candidate.image_id in {item.image_id for item in selected}:
            continue
        if candidate.image_id in (excluded_ids or set()):
            continue
        selected.append(candidate)
    if len(selected) != 10:
        raise InsufficientBackgrounds(
            f"category_incomplete:{category}:{len(selected)}/10"
        )
    if len({record.image_id for record in selected}) != 10:
        raise InsufficientBackgrounds("category_backgrounds_not_unique")
    library.reserve(run_id, reference_date, category, selected)
    return selected, assignments, calls


@dataclass
class SimRecord:
    image_id: str
    category: str
    usages: list[tuple[date, str, int]] = field(default_factory=list)


def _sim_eligible(
    record: SimRecord,
    day: date,
    phrase: str,
    max_uses: int,
    used_today: set[str],
) -> bool:
    if record.image_id in used_today:
        return False
    recent = [usage for usage in record.usages if day - timedelta(days=29) <= usage[0] <= day]
    if len(recent) >= max_uses:
        return False
    if record.usages and (day - max(usage[0] for usage in record.usages)).days < 8:
        return False
    if any(usage[1] == phrase for usage in record.usages):
        return False
    return True


def simulate_90_days(
    start: date,
    strategy_uses: int,
    approval_rate: float,
    safety_margin: float,
    initially_stocked: bool,
) -> dict[str, object]:
    library: dict[str, list[SimRecord]] = {
        category: [] for category in renderer.CATEGORY_STYLES
    }
    sequence = 0
    if initially_stocked:
        for category in renderer.CATEGORY_STYLES:
            for _ in range(40):
                sequence += 1
                library[category].append(SimRecord(f"stock-{sequence}", category))

    daily_rows: list[dict[str, object]] = []
    total_artworks = total_new = total_reused = total_calls = 0

    def create_new(category: str, count: int, day: date, day_used: set[str]) -> int:
        nonlocal sequence
        for slot in range(count):
            sequence += 1
            record = SimRecord(f"generated-{sequence}", category)
            phrase = f"{category}-{day.isoformat()}-new-{slot}"
            style = slot % 10
            record.usages.append((day, phrase, style))
            library[category].append(record)
            day_used.add(record.image_id)
        return count

    initial_day = start - timedelta(days=1)
    initial_new = 0
    if not initially_stocked:
        for category in renderer.CATEGORY_STYLES:
            initial_new += create_new(category, 10, initial_day, set())
    initial_calls = (
        math.ceil(initial_new / approval_rate * safety_margin)
        if initial_new else 0
    )
    if initial_new:
        daily_rows.append(_financial_day(initial_day, 160, initial_new, 0, initial_calls))

    for offset in range(90):
        day = start + timedelta(days=offset)
        categories = renderer.active_categories(day)
        used_today: set[str] = set()
        day_new = day_reused = 0
        for category in categories:
            assignments = assignments_for_category(category, day.isoformat())
            selected: list[SimRecord] = []
            if strategy_uses > 1:
                candidates = list(library[category])
                random.Random(
                    hashlib.sha256(f"{day}|{category}|simulation".encode()).hexdigest()
                ).shuffle(candidates)
                for phrase, style in assignments:
                    eligible = [
                        item for item in candidates
                        if item not in selected
                        and _sim_eligible(item, day, phrase, strategy_uses, used_today)
                    ]
                    if not eligible:
                        break
                    eligible.sort(
                        key=lambda item: (
                            style in {usage[2] for usage in item.usages},
                            len(item.usages),
                            item.image_id,
                        )
                    )
                    record = eligible[0]
                    record.usages.append((day, phrase, style))
                    selected.append(record)
                    used_today.add(record.image_id)
            day_reused += len(selected)
            day_new += create_new(
                category, 10 - len(selected), day, used_today
            )
        calls = (
            math.ceil(day_new / approval_rate * safety_margin)
            if day_new else 0
        )
        artworks = len(categories) * 10
        daily_rows.append(_financial_day(day, artworks, day_new, day_reused, calls))
        total_artworks += artworks
        total_new += day_new
        total_reused += day_reused
        total_calls += calls

    if initial_new:
        total_artworks += 160
        total_new += initial_new
        total_calls += initial_calls

    months: dict[str, list[dict[str, object]]] = {}
    for row in daily_rows:
        months.setdefault(row["day"][:7], []).append(row)
    monthly = []
    total_cost_usd = 0.0
    for month, rows in sorted(months.items()):
        overage = sum(float(row["overage_neurons"]) for row in rows)
        paid = overage > 0
        cost = (
            phase6.WORKERS_PAID_BASE_USD
            + overage / 1000 * phase6.USD_PER_1000_NEURONS
            if paid else 0.0
        )
        total_cost_usd += cost
        monthly.append({
            "month": month,
            "artworks": sum(int(row["artworks"]) for row in rows),
            "new_backgrounds": sum(int(row["new_backgrounds"]) for row in rows),
            "reused_backgrounds": sum(int(row["reused_backgrounds"]) for row in rows),
            "calls": sum(int(row["calls"]) for row in rows),
            "neurons": round(sum(float(row["neurons"]) for row in rows), 1),
            "free_neurons_used": round(sum(float(row["free_neurons_used"]) for row in rows), 1),
            "overage_neurons": round(overage, 1),
            "cost_usd": round(cost, 2),
            "cost_brl": round(cost * phase6.USD_BRL_PTAX, 2),
        })
    return {
        "initially_stocked": initially_stocked,
        "max_uses_30_days": strategy_uses,
        "approval_rate": approval_rate,
        "artworks": total_artworks,
        "new_backgrounds": total_new,
        "reused_backgrounds": total_reused,
        "cloudflare_calls": total_calls,
        "neurons": round(total_calls * phase6.NEURONS_PER_CANDIDATE, 1),
        "months": monthly,
        "cost_usd": round(total_cost_usd, 2),
        "cost_brl": round(total_cost_usd * phase6.USD_BRL_PTAX, 2),
    }


def _financial_day(
    day: date,
    artworks: int,
    new_backgrounds: int,
    reused_backgrounds: int,
    calls: int,
) -> dict[str, object]:
    neurons = calls * phase6.NEURONS_PER_CANDIDATE
    free_used = min(neurons, phase6.FREE_NEURONS_PER_DAY)
    return {
        "day": day.isoformat(),
        "artworks": artworks,
        "new_backgrounds": new_backgrounds,
        "reused_backgrounds": reused_backgrounds,
        "calls": calls,
        "neurons": round(neurons, 1),
        "free_neurons_used": round(free_used, 1),
        "overage_neurons": round(max(0.0, neurons - free_used), 1),
    }


def build_simulation_report(start: date) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for initially_stocked in (False, True):
        for strategy in (1, 3, 4):
            for scenario_name, config in phase6.SCENARIOS.items():
                result = simulate_90_days(
                    start,
                    strategy,
                    config["approval_rate"],
                    config["safety_margin"],
                    initially_stocked,
                )
                result["strategy"] = {
                    1: "A_no_reuse",
                    3: "B_up_to_3_uses",
                    4: "C_up_to_4_uses",
                }[strategy]
                result["scenario"] = scenario_name
                results.append(result)
    baseline = {
        (item["initially_stocked"], item["scenario"]): item
        for item in results if item["max_uses_30_days"] == 1
    }
    for item in results:
        reference = baseline[(item["initially_stocked"], item["scenario"])]
        item["savings_vs_no_reuse_percent"] = round(
            (1 - item["cost_usd"] / max(0.0001, reference["cost_usd"])) * 100,
            2,
        )
        item["new_background_reduction_percent"] = round(
            (1 - item["new_backgrounds"] / max(1, reference["new_backgrounds"])) * 100,
            2,
        )
    return {
        "start": start.isoformat(),
        "days": 90,
        "rules": {
            "unique_backgrounds_per_category_day": 10,
            "min_complete_days_between_uses": MIN_COMPLETE_DAYS,
            "strategies": [1, 3, 4],
            "identity": "sha256 plus 256-bit perceptual hash",
            "near_duplicate_hamming_distance": NEAR_DUPLICATE_DISTANCE,
        },
        "pricing": {
            "free_neurons_daily": phase6.FREE_NEURONS_PER_DAY,
            "usd_per_1000_overage": phase6.USD_PER_1000_NEURONS,
            "paid_base_usd_per_calendar_month": phase6.WORKERS_PAID_BASE_USD,
            "usd_brl_ptax": phase6.USD_BRL_PTAX,
            "taxes_storage_and_actions_not_included": True,
        },
        "results": results,
        "neurons_consumed_by_simulation": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=date(2027, 1, 1))
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_LIBRARY_ROOT / "phase7-simulation.json",
    )
    args = parser.parse_args()
    report = build_simulation_report(args.start)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = [
        {
            "stocked": item["initially_stocked"],
            "strategy": item["strategy"],
            "scenario": item["scenario"],
            "new": item["new_backgrounds"],
            "reused": item["reused_backgrounds"],
            "cost_brl": item["cost_brl"],
            "savings": item["savings_vs_no_reuse_percent"],
        }
        for item in report["results"]
    ]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
