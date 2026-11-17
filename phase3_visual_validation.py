from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

import gerar_imagens as renderer


@dataclass(frozen=True)
class GeometryFeatures:
    edge_density: float
    row_peak_ratio: float
    row_concentration: float
    peak_band_density: float
    peak_band_span: float
    chroma_peak_ratio: float
    chroma_concentration: float
    horizontal_transition_score: float
    score: float


@dataclass(frozen=True)
class GeometryDecision:
    has_text_region: bool
    score: float
    reasons: tuple[str, ...]
    features: GeometryFeatures
    elapsed_seconds: float


def _smooth(values: list[float], radius: int) -> list[float]:
    if not values:
        return []
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    smoothed: list[float] = []
    for index in range(len(values)):
        left = max(0, index - radius)
        right = min(len(values), index + radius + 1)
        smoothed.append((prefix[right] - prefix[left]) / (right - left))
    return smoothed


def _top_concentration(values: list[float], fraction: float = 0.18) -> float:
    total = sum(values)
    if total <= 0:
        return 0.0
    count = max(1, round(len(values) * fraction))
    return sum(sorted(values, reverse=True)[:count]) / total


@dataclass(frozen=True)
class VisualQualityAssessment:
    duplicate_bright_circles: int
    anatomy_review_required: bool
    overlay_luminance_stddev: float
    overlay_edge_density: float
    contrast_risk: bool
    issues: tuple[str, ...]


def _connected_components(
    mask: list[int], width: int, height: int
) -> list[tuple[int, int, int, int, int]]:
    visited = bytearray(width * height)
    components: list[tuple[int, int, int, int, int]] = []
    for start, value in enumerate(mask):
        if not value or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        min_x = max_x = start % width
        min_y = max_y = start // width
        area = 0
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            area += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbor = ny * width + nx
                    if mask[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        components.append((min_x, min_y, max_x, max_y, area))
    return components


def assess_visual_quality(image: Image.Image, scene: str = "") -> VisualQualityAssessment:
    sample = ImageOps.fit(image.convert("RGB"), (256, 256), Image.Resampling.LANCZOS)
    gray = sample.convert("L")
    hsv = sample.convert("HSV")
    gray_values = list(gray.get_flattened_data())
    saturation_values = list(hsv.getchannel("S").get_flattened_data())
    mask = [
        1 if y < 170 and gray_values[y * 256 + x] >= 205
        and saturation_values[y * 256 + x] <= 90 else 0
        for y in range(256)
        for x in range(256)
    ]
    circle_count = 0
    for min_x, min_y, max_x, max_y, area in _connected_components(mask, 256, 256):
        box_width = max_x - min_x + 1
        box_height = max_y - min_y + 1
        if not (6 <= box_width <= 55 and 6 <= box_height <= 55):
            continue
        ratio = box_width / box_height
        fill = area / (box_width * box_height)
        if 0.65 <= ratio <= 1.45 and fill >= 0.42:
            circle_count += 1

    overlay = gray.crop((25, 55, 231, 230))
    overlay_stat = ImageStat.Stat(overlay)
    luminance_stddev = float(overlay_stat.stddev[0])
    overlay_edges = overlay.filter(ImageFilter.FIND_EDGES)
    edge_values = list(overlay_edges.get_flattened_data())
    edge_density = sum(value >= 40 for value in edge_values) / len(edge_values)
    contrast_risk = luminance_stddev >= 62 or edge_density >= 0.30
    scene_text = scene.casefold()
    anatomy_risk = any(
        term in scene_text
        for term in ("hand", "person", "people", "friend", "couple", "runner", "family")
    )
    issues: list[str] = []
    if circle_count >= 2 and "moon" in scene_text:
        issues.append(f"possible_duplicate_moons:{circle_count}")
    if anatomy_risk:
        issues.append("human_anatomy_review_required")
    if contrast_risk:
        issues.append(
            f"overlay_contrast_risk:stddev={luminance_stddev:.1f},edges={edge_density:.3f}"
        )
    return VisualQualityAssessment(
        duplicate_bright_circles=circle_count,
        anatomy_review_required=anatomy_risk,
        overlay_luminance_stddev=round(luminance_stddev, 2),
        overlay_edge_density=round(edge_density, 4),
        contrast_risk=contrast_risk,
        issues=tuple(issues),
    )


class TypographyRegionDetector:
    name = "pillow-typography-geometry"

    def analyze(self, image: Image.Image) -> GeometryDecision:
        started = time.perf_counter()
        sample = ImageOps.fit(image.convert("RGB"), (256, 256), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(sample.convert("L"))
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_pixels = list(edges.get_flattened_data())
        width, height = edges.size
        threshold = 34
        binary = [
            1 if value >= threshold and 3 < index // width < height - 4 else 0
            for index, value in enumerate(edge_pixels)
        ]
        row_counts = [
            sum(binary[row * width : (row + 1) * width]) / width
            for row in range(height)
        ]
        smooth_rows = _smooth(row_counts, 5)
        global_edge_density = sum(row_counts) / height
        peak_index = max(range(height), key=smooth_rows.__getitem__)
        peak_value = smooth_rows[peak_index]
        baseline = statistics.median(smooth_rows) or 0.0001
        band_top = max(0, peak_index - 8)
        band_bottom = min(height, peak_index + 9)
        band_rows = binary[band_top * width : band_bottom * width]
        band_height = band_bottom - band_top
        band_density = sum(band_rows) / max(1, width * band_height)
        covered_columns = 0
        for column in range(width):
            hits = sum(binary[row * width + column] for row in range(band_top, band_bottom))
            if hits >= 2:
                covered_columns += 1
        band_span = covered_columns / width

        saturation = sample.convert("HSV").getchannel("S")
        sat_pixels = list(saturation.get_flattened_data())
        chroma_rows = [
            sum(1 for value in sat_pixels[row * width : (row + 1) * width] if value >= 115)
            / width
            for row in range(height)
        ]
        smooth_chroma = _smooth(chroma_rows, 5)
        chroma_baseline = statistics.median(smooth_chroma) or 0.0001
        chroma_peak = max(smooth_chroma)

        transitions: list[float] = []
        for row in range(height):
            line = binary[row * width : (row + 1) * width]
            changes = sum(1 for left, right in zip(line, line[1:]) if left != right)
            transitions.append(changes / width)
        transition_smooth = _smooth(transitions, 5)
        transition_baseline = statistics.median(transition_smooth) or 0.0001
        transition_score = max(transition_smooth) / transition_baseline

        row_peak_ratio = peak_value / baseline
        row_concentration = _top_concentration(smooth_rows)
        chroma_peak_ratio = chroma_peak / chroma_baseline
        chroma_concentration = _top_concentration(smooth_chroma)

        score = (
            min(row_peak_ratio / 5.0, 1.5) * 0.22
            + min(row_concentration / 0.42, 1.5) * 0.18
            + min(band_density / 0.24, 1.5) * 0.16
            + min(band_span / 0.62, 1.5) * 0.14
            + min(chroma_peak_ratio / 5.0, 1.5) * 0.12
            + min(chroma_concentration / 0.48, 1.5) * 0.08
            + min(transition_score / 5.0, 1.5) * 0.10
        )
        reasons: list[str] = []
        if row_peak_ratio >= 4.0:
            reasons.append(f"horizontal_edge_band:{row_peak_ratio:.2f}")
        if row_concentration >= 0.34:
            reasons.append(f"edge_concentration:{row_concentration:.3f}")
        if band_density >= 0.16 and band_span >= 0.38:
            reasons.append(f"glyph_like_band:{band_density:.3f}/{band_span:.3f}")
        if chroma_peak_ratio >= 4.0 and chroma_concentration >= 0.32:
            reasons.append(f"chroma_band:{chroma_peak_ratio:.2f}/{chroma_concentration:.3f}")
        has_text = score >= 0.78 and len(reasons) >= 2
        features = GeometryFeatures(
            edge_density=round(global_edge_density, 4),
            row_peak_ratio=round(row_peak_ratio, 4),
            row_concentration=round(row_concentration, 4),
            peak_band_density=round(band_density, 4),
            peak_band_span=round(band_span, 4),
            chroma_peak_ratio=round(chroma_peak_ratio, 4),
            chroma_concentration=round(chroma_concentration, 4),
            horizontal_transition_score=round(transition_score, 4),
            score=round(score, 4),
        )
        return GeometryDecision(
            has_text_region=has_text,
            score=round(score, 4),
            reasons=tuple(reasons),
            features=features,
            elapsed_seconds=round(time.perf_counter() - started, 4),
        )


def evaluation_dataset() -> list[tuple[str, Path, bool]]:
    phase1 = (
        renderer.REPO_ROOT
        / ".generation-staging"
        / "ai-background-pilot"
        / "backgrounds"
    )
    phase2 = (
        renderer.REPO_ROOT
        / ".generation-staging"
        / "ai-background-phase2"
        / "backgrounds"
    )
    samples: list[tuple[str, Path, bool]] = []
    for category in ("bomdia", "aniversario", "amor", "fe", "natal"):
        samples.append(
            (
                f"phase1-{category}",
                phase1 / f"{category}.jpg",
                category in {"bomdia", "aniversario"},
            )
        )
    if phase2.exists():
        for path in sorted(phase2.glob("*.jpg")):
            samples.append((f"phase2-{path.stem}", path, False))
    return samples


def evaluate() -> dict[str, object]:
    from ai_background_pipeline import TesseractOcr, significant_text_detection

    detector = TypographyRegionDetector()
    ocr = TesseractOcr()
    phase2_report_path = (
        renderer.REPO_ROOT
        / ".generation-staging"
        / "ai-background-phase2"
        / "phase2-report.json"
    )
    scene_by_name: dict[str, str] = {}
    if phase2_report_path.exists():
        phase2_report = json.loads(phase2_report_path.read_text(encoding="utf-8"))
        scene_by_name = {
            Path(str(item.get("background_file") or item.get("file") or "")).name: str(
                item.get("scene") or ""
            )
            for item in phase2_report.get("candidates", [])
        }
    rows: list[dict[str, object]] = []
    true_positive = false_positive = true_negative = false_negative = 0
    for name, path, expected in evaluation_dataset():
        if not path.exists():
            continue
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            decision = detector.analyze(rgb)
            quality = assess_visual_quality(rgb, scene_by_name.get(path.name, ""))
            ocr_started = time.perf_counter()
            ocr_detections = ocr.detect(rgb)
            ocr_elapsed = time.perf_counter() - ocr_started
        ocr_strong = [
            item for item in ocr_detections
            if significant_text_detection(item)
        ]
        ocr_support = [
            item for item in ocr_detections
            if len("".join(character for character in item.text if character.isalnum())) >= 2
            and item.confidence >= 50
        ]
        features = decision.features
        geometry_typography = (
            features.row_concentration >= 0.34
            and features.peak_band_density >= 0.34
            and features.peak_band_span >= 0.97
        )
        ocr_corroborated = (
            bool(ocr_strong)
            or len(ocr_support) >= 4
            or max((item.confidence for item in ocr_detections), default=0.0) >= 90
        )
        predicted = geometry_typography and ocr_corroborated
        if expected and predicted:
            true_positive += 1
        elif expected:
            false_negative += 1
        elif predicted:
            false_positive += 1
        else:
            true_negative += 1
        rows.append(
            {
                "name": name,
                "file": str(path.relative_to(renderer.REPO_ROOT)),
                "expected_text": expected,
                "predicted_text": predicted,
                "geometry_predicted_text": decision.has_text_region,
                "geometry_typography_band": geometry_typography,
                "ocr_corroborated": ocr_corroborated,
                "decision": {
                    "score": decision.score,
                    "reasons": decision.reasons,
                    "elapsed_seconds": decision.elapsed_seconds,
                },
                "features": asdict(decision.features),
                "visual_quality": asdict(quality),
                "ocr": {
                    "raw_count": len(ocr_detections),
                    "support_count": len(ocr_support),
                    "strong_count": len(ocr_strong),
                    "max_confidence": round(
                        max((item.confidence for item in ocr_detections), default=0.0), 2
                    ),
                    "elapsed_seconds": round(ocr_elapsed, 4),
                },
            }
        )
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    accuracy = (true_positive + true_negative) / max(1, len(rows))
    return {
        "detector": detector.name,
        "samples": rows,
        "metrics": {
            "sample_count": len(rows),
            "true_positive": true_positive,
            "false_positive": false_positive,
            "true_negative": true_negative,
            "false_negative": false_negative,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "accuracy": round(accuracy, 4),
            "average_geometry_seconds": round(
                sum(row["decision"]["elapsed_seconds"] for row in rows) / max(1, len(rows)),
                4,
            ),
            "average_ocr_seconds": round(
                sum(row["ocr"]["elapsed_seconds"] for row in rows) / max(1, len(rows)),
                4,
            ),
            "average_total_seconds": round(
                sum(
                    row["decision"]["elapsed_seconds"] + row["ocr"]["elapsed_seconds"]
                    for row in rows
                ) / max(1, len(rows)),
                4,
            ),
            "duplicate_moon_flags": sum(
                any(
                    str(issue).startswith("possible_duplicate_moons:")
                    for issue in row["visual_quality"]["issues"]
                )
                for row in rows
            ),
            "anatomy_review_flags": sum(
                bool(row["visual_quality"]["anatomy_review_required"]) for row in rows
            ),
            "contrast_risk_flags": sum(
                bool(row["visual_quality"]["contrast_risk"]) for row in rows
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=(
            renderer.REPO_ROOT
            / ".generation-staging"
            / "ai-background-phase3"
            / "geometry-evaluation.json"
        ),
    )
    args = parser.parse_args()
    report = evaluate()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
