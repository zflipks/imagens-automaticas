from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Callable, Iterable, Protocol

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

import gerar_imagens as renderer

MODEL = "@cf/black-forest-labs/flux-1-schnell"
MODEL_STEPS = 4
OBSERVED_NEURONS_PER_CANDIDATE = 172.8
FREE_NEURONS_PER_DAY = 10_000.0
DEFAULT_DAILY_CALL_LIMIT = 15
PILOT_ROOT = renderer.REPO_ROOT / ".generation-staging" / "ai-background-phase2"
LEDGER_FILE = PILOT_ROOT / "budget-ledger.json"
HISTORY_FILE = PILOT_ROOT / "background-history.json"
REPORT_FILE = PILOT_ROOT / "phase2-report.json"
BACKGROUNDS_DIR = PILOT_ROOT / "backgrounds"
RENDERED_DIR = PILOT_ROOT / "rendered"
REJECTED_DIR = PILOT_ROOT / "rejected"
MOSAICS_DIR = PILOT_ROOT / "mosaics"

NO_TEXT_CLAUSE = (
    "The scene must contain absolutely no written language or typography: no words, letters, "
    "numbers, captions, greeting cards, banners, signs, labels, logos, watermarks, signatures, "
    "packaging text, screens, clocks, posters or branded objects. Use only plain unmarked cups, "
    "boxes and surfaces; avoid storefronts, books, stationery, product packaging and decorative "
    "objects that resemble glyphs. Keep the overlay area simple, softly focused and unobstructed."
)

CATEGORY_SCENES: dict[str, tuple[str, ...]] = {
    "bomdia": (
        "a steaming ceramic coffee cup beside wildflowers overlooking a misty valley at dawn",
        "a sunlit breakfast table on a garden veranda with fruit, flowers and soft morning haze",
        "dew-covered daisies beside a quiet lake as the first sunlight crosses distant hills",
        "a rustic window ledge with coffee and blossoms facing a bright countryside sunrise",
    ),
    "boatarde": (
        "an elegant tea setting in a luminous afternoon garden",
        "golden sunlight crossing a field of daisies and a shaded wooden bench",
        "a peaceful terrace with iced tea, citrus and colorful flowers",
        "warm late-afternoon light through trees beside a calm country path",
    ),
    "boanoite": (
        "a moonlit lake beneath a clear starry sky and delicate lantern glow",
        "a cozy porch at blue hour with candles and a peaceful distant landscape",
        "a quiet bedroom window framing the moon and soft night clouds",
        "a tranquil garden path illuminated by warm lanterns under the stars",
    ),
    "aniversario": (
        "a joyful party table with a decorated cake, balloons, confetti and wrapped gifts",
        "an elegant garden celebration with pastel balloons, flowers and festive lights",
        "a colorful cake close-up surrounded by candles, ribbons and presents",
        "a sophisticated indoor celebration with bokeh lights, balloons and gift boxes",
    ),
    "anonovo": (
        "golden fireworks reflected over a waterfront skyline at midnight",
        "elegant champagne glasses with sparklers and warm celebration lights",
        "a festive rooftop scene with gold confetti and distant fireworks",
        "bright sparklers against luxurious black and gold party decorations",
    ),
    "fe": (
        "a simple wooden cross on a hill beneath radiant sunbeams and peaceful clouds",
        "a single unmarked candle beside a cross silhouette near a sunlit window",
        "a quiet country chapel surrounded by soft morning light and wildflowers",
        "an open devotional setting with a cross silhouette and heavenly light over mountains",
    ),
    "gratidao": (
        "a small bouquet resting in warm sunrise light over a peaceful landscape",
        "an abundant garden table with flowers, fruit and gentle golden light",
        "a quiet empty bench overlooking a vast sunlit valley",
        "simple wildflowers in a glass vase beside a bright window and calm countryside",
    ),
    "amizade": (
        "two plain coffee cups beside matching flowers on a cheerful garden table",
        "a pair of empty chairs facing a warm sunset over a peaceful lake",
        "two bicycles resting beside a bright beach path at sunset",
        "a simple picnic for two with flowers and warm sunlight, no people visible",
    ),
    "amor": (
        "two rose bouquets forming a subtle heart composition at golden sunset",
        "two intertwined ribbons beside red roses and candlelight",
        "an elegant romantic dinner setting with roses and soft warm bokeh",
        "two flowering trees leaning toward each other in evening light",
    ),
    "motivacao": (
        "a clear mountain summit path as sunrise breaks through clouds",
        "an open coastal road leading toward dramatic morning light",
        "a winding trail leading toward luminous mountains and a wide sky",
        "a high ridge overlooking a vast valley beneath an open luminous sky",
    ),
    "felizsemana": (
        "a bright planner-free worktable with coffee, flowers and morning sunlight",
        "a fresh garden path opening toward a sunny landscape",
        "colorful flowers and coffee arranged by a window at the start of a new day",
        "a clean welcoming desk with a plant and warm daylight, all surfaces blank",
    ),
    "bomfimdesemana": (
        "a relaxing tropical beach with a hammock and turquoise water",
        "a quiet cabin terrace with coffee overlooking green mountains",
        "a sunny picnic beside a lake surrounded by peaceful nature",
        "a restful garden lounge with flowers and soft weekend sunlight",
    ),
    "natal": (
        "a decorated evergreen tree with wrapped gifts, warm lights and snow outside",
        "a cozy fireplace scene with ornaments, candles, garlands and blank gift boxes",
        "a snowy window beside red and gold ornaments and glowing festive lights",
        "an elegant holiday dining room with an evergreen centerpiece and warm bokeh",
    ),
    "pascoa": (
        "a spring garden arrangement with decorated eggs, flowers and a small rabbit",
        "a rustic basket of pastel eggs among blossoms in gentle morning light",
        "a peaceful cross at sunrise surrounded by spring flowers",
        "an elegant Easter table with eggs, greenery and soft natural light",
    ),
    "bomsabado": (
        "a relaxed breakfast with coffee and flowers on a sunny garden patio",
        "a hammock beneath trees beside a peaceful lake in morning light",
        "a colorful weekend market bouquet on a rustic table",
        "a calm garden bench surrounded by flowers and warm sunlight",
    ),
    "felizdomingo": (
        "a peaceful breakfast table in a bright empty garden",
        "sunbeams over a serene countryside chapel and flowering meadow",
        "a tranquil lake at sunrise with flowers in the foreground",
        "a welcoming outdoor table beneath soft golden light, no people visible",
    ),
}

LIGHTING = (
    "soft diffused natural light",
    "warm golden-hour backlight",
    "bright airy daylight",
    "cinematic side lighting with gentle contrast",
    "subtle volumetric light through atmospheric haze",
)
COMPOSITIONS = (
    "wide environmental composition with the main subject in the left third and clean space on the right",
    "editorial medium shot with the subject in the right third and calm space on the left",
    "low-angle foreground detail with an uncluttered sky in the upper half",
    "balanced diagonal composition with a quiet central area for a later overlay",
    "layered depth with foreground details and broad soft negative space near the top",
    "slightly elevated viewpoint with visual weight near the lower corners and an open middle",
)
PALETTES = (
    "warm amber, cream and natural green palette",
    "fresh pastel palette with restrained saturation",
    "rich cinematic colors with realistic skin and materials",
    "clean blue and gold palette",
    "earthy neutral palette with one vivid accent color",
)
LENSES = (
    "35mm documentary photography",
    "50mm natural perspective photography",
    "85mm shallow-depth editorial photography",
    "24mm environmental photography with realistic proportions",
)


@dataclass(frozen=True)
class PromptPlan:
    category: str
    variant_key: str
    scene: str
    lighting: str
    composition: str
    palette: str
    lens: str
    prompt: str


@dataclass(frozen=True)
class OcrDetection:
    text: str
    confidence: float
    box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class ValidationResult:
    approved: bool
    reasons: tuple[str, ...]
    detections: tuple[OcrDetection, ...]
    fingerprint: str
    brightness: float
    saturation: float


@dataclass
class GeneratedCandidate:
    image: Image.Image
    category: str
    prompt_plan: PromptPlan
    generation_seconds: float
    neurons_observed: float | None
    request_id: str | None
    resolution: str
    model: str = MODEL
    steps: int = MODEL_STEPS


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def detect(self, image: Image.Image) -> list[OcrDetection]: ...


class BackgroundSource(Protocol):
    def generate(self, category: str, plan: PromptPlan) -> GeneratedCandidate: ...


def windows_environment(name: str) -> tuple[str, str]:
    value = os.getenv(name, "").strip()
    if value:
        return value, "process"
    if platform.system() != "Windows":
        return "", "absent"
    try:
        import winreg

        locations = (
            (winreg.HKEY_CURRENT_USER, r"Environment", "user"),
            (winreg.HKEY_CURRENT_USER, r"Volatile Environment", "user-volatile"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                "machine",
            ),
        )
        for hive, key_path, scope in locations:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    candidate, _kind = winreg.QueryValueEx(key, name)
                candidate = str(candidate).strip()
                if candidate:
                    return candidate, scope
            except (FileNotFoundError, PermissionError):
                continue
    except (ImportError, OSError):
        pass
    return "", "absent"


def build_prompt_plan(category: str, reference_date: date, attempt: int) -> PromptPlan:
    if category not in CATEGORY_SCENES:
        raise KeyError(f"Unknown category: {category}")
    rng = random.Random(f"ai-background:{category}:{reference_date.isoformat()}:{attempt}")
    scene = CATEGORY_SCENES[category][attempt % len(CATEGORY_SCENES[category])]
    lighting = LIGHTING[rng.randrange(len(LIGHTING))]
    composition = COMPOSITIONS[rng.randrange(len(COMPOSITIONS))]
    palette = PALETTES[rng.randrange(len(PALETTES))]
    lens = LENSES[rng.randrange(len(LENSES))]
    variant_key = hashlib.sha256(
        f"{category}|{scene}|{lighting}|{composition}|{palette}|{lens}".encode("utf-8")
    ).hexdigest()[:16]
    prompt = (
        f"Square 1:1 photorealistic background image. Scene: {scene}. "
        f"Lighting: {lighting}. Composition: {composition}. Color direction: {palette}. "
        f"Camera language: {lens}. Realistic materials, natural detail, polished editorial quality. "
        "Reserve visually calm negative space so a separate renderer can add a Portuguese greeting later. "
        + NO_TEXT_CLAUSE
    )
    return PromptPlan(category, variant_key, scene, lighting, composition, palette, lens, prompt)


class TesseractOcr:
    name = "tesseract-local"

    def __init__(self, executable: str | None = None, confidence_threshold: float = 35.0):
        configured = executable or os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
        if not configured and platform.system() == "Windows":
            common_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            if common_path.exists():
                configured = str(common_path)
        self.executable = configured
        self.confidence_threshold = confidence_threshold

    def available(self) -> bool:
        return bool(self.executable)

    def _detect_once(self, image: Image.Image, psm: int) -> list[OcrDetection]:
        buffer = BytesIO()
        image.save(buffer, "PNG")
        result = subprocess.run(
            [
                self.executable,
                "stdin",
                "stdout",
                "-l",
                "eng+por",
                "--psm",
                str(psm),
                "tsv",
            ],
            input=buffer.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=90,
        )
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Tesseract OCR failed: {error[:300]}")
        rows = csv.DictReader(
            StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"
        )
        detections: list[OcrDetection] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf") or -1)
            except ValueError:
                confidence = -1
            if confidence < self.confidence_threshold or not re.search(
                r"[A-Za-zÀ-ÿ0-9]", text
            ):
                continue
            box = tuple(int(row[key]) for key in ("left", "top", "width", "height"))
            detections.append(OcrDetection(text, confidence, box))
        return detections

    def detect(self, image: Image.Image) -> list[OcrDetection]:
        if not self.executable:
            raise RuntimeError(
                "Tesseract OCR is unavailable. Install it or set TESSERACT_CMD before generating."
            )
        rgb = image.convert("RGB")
        gray = ImageOps.autocontrast(image.convert("L"))
        threshold = gray.point(lambda value: 255 if value >= 165 else 0).convert("RGB")
        width, height = rgb.size
        top = rgb.crop((0, 0, width, max(1, height // 2))).resize(
            (width * 2, height), Image.Resampling.LANCZOS
        )
        top_gray = ImageOps.autocontrast(top.convert("L"))
        top_threshold = top_gray.point(
            lambda value: 255 if value >= 165 else 0
        ).convert("RGB")
        detections = [
            *self._detect_once(rgb, 6),
            *self._detect_once(rgb, 11),
            *self._detect_once(threshold, 6),
            *self._detect_once(top, 11),
            *self._detect_once(top_threshold, 11),
        ]
        unique: dict[tuple[str, tuple[int, int, int, int] | None], OcrDetection] = {}
        for detection in detections:
            key = (detection.text.casefold(), detection.box)
            previous = unique.get(key)
            if previous is None or detection.confidence > previous.confidence:
                unique[key] = detection
        return list(unique.values())


def image_fingerprint(image: Image.Image) -> str:
    sample = image.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
    pixels = list(sample.get_flattened_data())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if value >= average else "0" for value in pixels)
    return f"{int(bits, 2):064x}"


def significant_text_detection(detection: OcrDetection) -> bool:
    normalized = re.sub(r"[^A-Za-zÀ-ÿ0-9]+", "", detection.text)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]+", "", normalized)
    digits = re.sub(r"[^0-9]+", "", normalized)
    if len(digits) >= 2 and detection.confidence >= 70:
        return True
    if len(letters) >= 4 and detection.confidence >= 70:
        return True
    if len(letters) >= 6 and detection.confidence >= 55:
        return True
    return False


def validate_background(
    image: Image.Image,
    ocr: OcrEngine,
    known_fingerprints: set[str] | None = None,
) -> ValidationResult:
    from phase3_visual_validation import TypographyRegionDetector

    detections = tuple(ocr.detect(image))
    reasons: list[str] = []
    geometry = TypographyRegionDetector().analyze(image)
    strong = [item for item in detections if significant_text_detection(item)]
    support = [
        item
        for item in detections
        if len("".join(character for character in item.text if character.isalnum())) >= 2
        and item.confidence >= 50
    ]
    features = geometry.features
    geometry_typography = (
        features.row_concentration >= 0.34
        and features.peak_band_density >= 0.34
        and features.peak_band_span >= 0.97
    )
    ocr_corroborated = (
        bool(strong)
        or len(support) >= 4
        or max((item.confidence for item in detections), default=0.0) >= 90
    )
    direct_phrase = any(
        " " in item.text.strip()
        and len("".join(character for character in item.text if character.isalpha())) >= 6
        and item.confidence >= 80
        for item in detections
    )
    if direct_phrase or (geometry_typography and ocr_corroborated):
        reasons.append(
            "text_region_consensus:"
            f"geometry_score={geometry.score:.3f},"
            f"support={len(support)},strong={len(strong)}"
        )
    sample = image.convert("RGB").resize((128, 128), Image.Resampling.LANCZOS)
    brightness = float(ImageStat.Stat(sample.convert("L")).mean[0])
    saturation = float(ImageStat.Stat(sample.convert("HSV").getchannel("S")).mean[0])
    if brightness < 35:
        reasons.append(f"too_dark:brightness={brightness:.1f}")
    if brightness > 245:
        reasons.append(f"too_bright:brightness={brightness:.1f}")
    if saturation < 12:
        reasons.append(f"low_saturation:saturation={saturation:.1f}")
    fingerprint = image_fingerprint(image)
    if fingerprint in (known_fingerprints or set()):
        reasons.append("duplicate_fingerprint")
    return ValidationResult(
        approved=not reasons,
        reasons=tuple(reasons),
        detections=detections,
        fingerprint=fingerprint,
        brightness=round(brightness, 2),
        saturation=round(saturation, 2),
    )


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetLedger:
    day: str
    daily_call_limit: int = DEFAULT_DAILY_CALL_LIMIT
    free_neuron_limit: float = FREE_NEURONS_PER_DAY
    reference_neurons_per_call: float = OBSERVED_NEURONS_PER_CANDIDATE
    calls: int = 0
    neurons_observed: float = 0.0
    events: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, today: date, daily_call_limit: int) -> "BudgetLedger":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("day") == today.isoformat():
                data["daily_call_limit"] = min(int(data.get("daily_call_limit", daily_call_limit)), daily_call_limit)
                return cls(**data)
        historical = observed_pilot_neurons_for_day(today)
        ledger = cls(day=today.isoformat(), daily_call_limit=daily_call_limit)
        if historical:
            ledger.neurons_observed = historical
            ledger.events.append({
                "kind": "imported_prior_pilot_usage",
                "neurons": historical,
                "source": ".generation-staging/ai-background-pilot/pilot-report.json",
            })
        return ledger

    def assert_can_call(self) -> None:
        if self.calls >= self.daily_call_limit:
            raise BudgetExceeded(f"Daily call limit reached: {self.calls}/{self.daily_call_limit}")
        projected = self.neurons_observed + self.reference_neurons_per_call
        if projected > self.free_neuron_limit:
            raise BudgetExceeded(
                f"Free Neuron guard reached: projected {projected:.1f} > {self.free_neuron_limit:.1f}"
            )

    def record(self, category: str, neurons: float | None, status: str) -> None:
        observed = neurons if neurons is not None else self.reference_neurons_per_call
        self.calls += 1
        self.neurons_observed += observed
        self.events.append({
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "category": category,
            "neurons": observed,
            "status": status,
        })

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp.json")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def observed_pilot_neurons_for_day(today: date) -> float:
    path = renderer.REPO_ROOT / ".generation-staging" / "ai-background-pilot" / "pilot-report.json"
    if not path.exists():
        return 0.0
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        created = str(report.get("created_at", ""))[:10]
        if created != today.isoformat():
            return 0.0
        return sum(
            float(item.get("neurons_observed") or 0)
            for item in report.get("generations", {}).values()
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0.0


class CloudflareFluxSource:
    def __init__(self, account_id: str, api_token: str):
        if len(account_id) != 32 or any(character not in "0123456789abcdefABCDEF" for character in account_id):
            raise ValueError("CLOUDFLARE_ACCOUNT_ID must be exactly 32 hexadecimal characters")
        if not api_token:
            raise ValueError("CLOUDFLARE_API_TOKEN is unavailable")
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "User-Agent": "imagens-automaticas isolated phase2 pilot/1.0",
        })

    def generate(self, category: str, plan: PromptPlan) -> GeneratedCandidate:
        started = time.perf_counter()
        response = self.session.post(
            f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{MODEL}",
            json={"prompt": plan.prompt, "steps": MODEL_STEPS},
            timeout=(20, 180),
        )
        elapsed = time.perf_counter() - started
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            payload = {}
        if not response.ok or not payload.get("success", False):
            errors = payload.get("errors", [])
            safe = [
                {"code": item.get("code"), "message": item.get("message")}
                for item in errors if isinstance(item, dict)
            ]
            raise RuntimeError(f"Cloudflare HTTP {response.status_code}: {safe}")
        encoded = payload.get("result", {}).get("image")
        if not encoded:
            raise RuntimeError("Cloudflare returned no image")
        image = Image.open(BytesIO(base64.b64decode(encoded, validate=True))).convert("RGB")
        image.load()
        headers = {key.lower(): value for key, value in response.headers.items()}
        neuron_value = next(
            (value for key, value in headers.items() if "neuron" in key or "usage" in key),
            None,
        )
        try:
            neurons = float(neuron_value) if neuron_value is not None else None
        except ValueError:
            neurons = None
        return GeneratedCandidate(
            image=image,
            category=category,
            prompt_plan=plan,
            generation_seconds=round(elapsed, 3),
            neurons_observed=neurons,
            request_id=response.headers.get("cf-ai-req-id") or response.headers.get("cf-ray"),
            resolution=f"{image.width}x{image.height}",
        )


def load_isolated_history(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "fingerprints": [], "variant_keys": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("version", 1)
    data.setdefault("fingerprints", [])
    data.setdefault("variant_keys", [])
    return data


def save_isolated_history(path: Path, history: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_jpeg(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=92, optimize=True, progressive=True)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(renderer.REPO_ROOT))
    except ValueError:
        return str(path)


def make_mosaic(paths: Iterable[Path], destination: Path, label: str) -> None:
    paths = list(paths)
    if not paths:
        return
    tile = 320
    columns = min(4, len(paths))
    rows = (len(paths) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile, rows * (tile + 44)), "#202124")
    draw = ImageDraw.Draw(canvas)
    for index, path in enumerate(paths):
        with Image.open(path) as source:
            image = ImageOps.fit(source.convert("RGB"), (tile, tile), Image.Resampling.LANCZOS)
        x = index % columns * tile
        y = index // columns * (tile + 44)
        canvas.paste(image, (x, y))
        draw.text((x + 10, y + tile + 10), path.stem, fill="white")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "JPEG", quality=90, optimize=True)


def run_pilot(
    source: BackgroundSource,
    ocr: OcrEngine,
    categories: list[str],
    max_candidates: int,
    reference_date: date,
    ledger_path: Path = LEDGER_FILE,
    history_path: Path = HISTORY_FILE,
    report_path: Path = REPORT_FILE,
) -> dict[str, object]:
    if not ocr.available():
        raise RuntimeError("OCR backend unavailable; refusing to consume AI resources")
    if max_candidates < 1 or max_candidates > 15:
        raise ValueError("max_candidates must be between 1 and 15")
    unknown = set(categories) - set(CATEGORY_SCENES)
    if unknown:
        raise ValueError(f"Unknown categories: {sorted(unknown)}")

    ledger = BudgetLedger.load(ledger_path, reference_date, max_candidates)
    history = load_isolated_history(history_path)
    fingerprints = set(str(value) for value in history["fingerprints"])
    variants = set(str(value) for value in history["variant_keys"])
    messages = renderer.load_messages()
    report: dict[str, object] = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "isolated-phase2-pilot",
        "published": False,
        "model": MODEL,
        "steps": MODEL_STEPS,
        "ocr": ocr.name,
        "max_candidates": max_candidates,
        "candidates": [],
        "approved": [],
        "rejected": [],
        "failures": [],
    }
    approved_backgrounds: list[Path] = []
    rendered_artworks: list[Path] = []

    for attempt in range(max_candidates):
        category = categories[attempt % len(categories)]
        ledger.assert_can_call()
        plan = build_prompt_plan(category, reference_date, attempt)
        if plan.variant_key in variants:
            plan = build_prompt_plan(category, reference_date, attempt + max_candidates)
        try:
            candidate = source.generate(category, plan)
            ledger.record(category, candidate.neurons_observed, "generated")
            ledger.save(ledger_path)
            validation = validate_background(candidate.image, ocr, fingerprints)
            item = {
                "attempt": attempt + 1,
                "category": category,
                "model": candidate.model,
                "steps": candidate.steps,
                "resolution": candidate.resolution,
                "generation_seconds": candidate.generation_seconds,
                "neurons_observed": candidate.neurons_observed,
                "request_id": candidate.request_id,
                "variant_key": plan.variant_key,
                "scene": plan.scene,
                "lighting": plan.lighting,
                "composition": plan.composition,
                "palette": plan.palette,
                "validation": {
                    "approved": validation.approved,
                    "reasons": list(validation.reasons),
                    "detections": [asdict(value) for value in validation.detections],
                    "brightness": validation.brightness,
                    "saturation": validation.saturation,
                    "fingerprint": validation.fingerprint,
                },
            }
            report["candidates"].append(item)
            filename = f"{attempt + 1:02d}-{category}-{plan.variant_key}.jpg"
            if not validation.approved:
                rejected_path = REJECTED_DIR / filename
                save_jpeg(candidate.image, rejected_path)
                item["file"] = display_path(rejected_path)
                report["rejected"].append(item)
                continue

            background_path = BACKGROUNDS_DIR / filename
            save_jpeg(candidate.image, background_path)
            message_rng = random.Random(f"phase2-message:{category}:{reference_date}:{attempt}")
            message = messages[category][message_rng.randrange(len(messages[category]))]
            style_id = renderer.CATEGORY_STYLE_ORDER[category][attempt % renderer.STYLE_COUNT]
            signature = renderer.artwork_signature(
                category, message, f"cloudflare:{plan.variant_key}", style_id, attempt % 3
            )
            artwork = renderer.render_artwork(
                renderer.prepare_background(candidate.image, category, style_id),
                category,
                message,
                style_id,
                attempt % 3,
                signature,
            )
            rendered_path = RENDERED_DIR / filename
            renderer.save_artwork(artwork, rendered_path)
            item.update({
                "background_file": display_path(background_path),
                "rendered_file": display_path(rendered_path),
                "style_id": style_id + 1,
                "style": renderer.STYLE_NAMES[style_id],
            })
            report["approved"].append(item)
            approved_backgrounds.append(background_path)
            rendered_artworks.append(rendered_path)
            fingerprints.add(validation.fingerprint)
            variants.add(plan.variant_key)
        except BudgetExceeded:
            raise
        except Exception as error:
            report["failures"].append({
                "attempt": attempt + 1,
                "category": category,
                "type": type(error).__name__,
                "message": str(error),
            })

    history["fingerprints"] = sorted(fingerprints)[-1000:]
    history["variant_keys"] = sorted(variants)[-2000:]
    history["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_isolated_history(history_path, history)
    make_mosaic(approved_backgrounds, MOSAICS_DIR / "fundos-aprovados.jpg", "fundos")
    make_mosaic(rendered_artworks, MOSAICS_DIR / "artes-renderizadas.jpg", "artes")
    report["summary"] = {
        "candidate_count": len(report["candidates"]),
        "approved_count": len(report["approved"]),
        "rejected_count": len(report["rejected"]),
        "failure_count": len(report["failures"]),
        "approval_rate": round(
            len(report["approved"]) / max(1, len(report["candidates"])), 4
        ),
        "neurons_this_phase2_ledger": round(ledger.neurons_observed, 2),
        "calls_this_phase2_ledger": ledger.calls,
        "average_generation_seconds": round(
            sum(float(item["generation_seconds"]) for item in report["candidates"])
            / max(1, len(report["candidates"])),
            3,
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def revalidate_existing(
    ocr: OcrEngine,
    report_file: Path = REPORT_FILE,
    history_file: Path = HISTORY_FILE,
) -> dict[str, object]:
    if not ocr.available():
        raise RuntimeError("OCR backend unavailable; revalidation stopped")
    if not report_file.exists():
        raise FileNotFoundError(f"Pilot report not found: {report_file}")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    messages = renderer.load_messages()
    approved: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    approved_paths: list[Path] = []
    rendered_paths: list[Path] = []
    rejected_paths: list[Path] = []
    fingerprints: set[str] = set()
    variants: set[str] = set()

    for item in report.get("candidates", []):
        relative = item.get("background_file") or item.get("file")
        if not relative:
            continue
        source_path = Path(str(relative))
        if not source_path.is_absolute():
            source_path = renderer.REPO_ROOT / source_path
        with Image.open(source_path) as opened:
            image = opened.convert("RGB")
            image.load()
        previous_validation = item.get("validation", {})
        validation = validate_background(image, ocr, fingerprints)
        item["initial_validation"] = previous_validation
        item["validation"] = {
            "approved": validation.approved,
            "reasons": list(validation.reasons),
            "detections": [asdict(value) for value in validation.detections],
            "brightness": validation.brightness,
            "saturation": validation.saturation,
            "fingerprint": validation.fingerprint,
        }
        filename = source_path.name
        if not validation.approved:
            rejected_path = REJECTED_DIR / filename
            if source_path != rejected_path:
                save_jpeg(image, rejected_path)
            item["file"] = display_path(rejected_path)
            item.pop("background_file", None)
            item.pop("rendered_file", None)
            rejected.append(item)
            rejected_paths.append(rejected_path)
            continue

        background_path = BACKGROUNDS_DIR / filename
        if source_path != background_path:
            save_jpeg(image, background_path)
        category = str(item["category"])
        attempt = int(item["attempt"]) - 1
        message_rng = random.Random(
            f"phase2-message:{category}:{str(report.get('created_at', ''))[:10]}:{attempt}"
        )
        message = messages[category][message_rng.randrange(len(messages[category]))]
        style_id = renderer.CATEGORY_STYLE_ORDER[category][attempt % renderer.STYLE_COUNT]
        variant_key = str(item["variant_key"])
        signature = renderer.artwork_signature(
            category, message, f"cloudflare:{variant_key}", style_id, attempt % 3
        )
        artwork = renderer.render_artwork(
            renderer.prepare_background(image, category, style_id),
            category,
            message,
            style_id,
            attempt % 3,
            signature,
        )
        rendered_path = RENDERED_DIR / filename
        renderer.save_artwork(artwork, rendered_path)
        item.update({
            "background_file": display_path(background_path),
            "rendered_file": display_path(rendered_path),
            "style_id": style_id + 1,
            "style": renderer.STYLE_NAMES[style_id],
        })
        item.pop("file", None)
        approved.append(item)
        approved_paths.append(background_path)
        rendered_paths.append(rendered_path)
        fingerprints.add(validation.fingerprint)
        variants.add(variant_key)

    report["approved"] = approved
    report["rejected"] = rejected
    report["revalidated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = report.setdefault("summary", {})
    summary.update({
        "candidate_count": len(report.get("candidates", [])),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "approval_rate": round(len(approved) / max(1, len(report.get("candidates", []))), 4),
        "revalidation_used_no_ai_calls": True,
    })
    history = load_isolated_history(history_file)
    history["fingerprints"] = sorted(
        set(str(value) for value in history.get("fingerprints", [])) | fingerprints
    )[-1000:]
    history["variant_keys"] = sorted(
        set(str(value) for value in history.get("variant_keys", [])) | variants
    )[-2000:]
    history["updated_at"] = report["revalidated_at"]
    save_isolated_history(history_file, history)
    make_mosaic(approved_paths, MOSAICS_DIR / "fundos-aprovados.jpg", "fundos")
    make_mosaic(rendered_paths, MOSAICS_DIR / "artes-renderizadas.jpg", "artes")
    make_mosaic(rejected_paths, MOSAICS_DIR / "fundos-rejeitados.jpg", "rejeitados")
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Isolated Cloudflare AI background phase 2 pilot")
    parser.add_argument("--pilot", action="store_true", help="Run real isolated AI pilot")
    parser.add_argument(
        "--revalidate-existing",
        action="store_true",
        help="Re-run OCR and rendering locally without AI calls",
    )
    parser.add_argument("--max-candidates", type=int, default=15)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.revalidate_existing:
        report = revalidate_existing(TesseractOcr())
        print(json.dumps(report["summary"], ensure_ascii=False))
        return 0
    if not args.pilot:
        print("No AI calls made. Run unit tests first, then pass --pilot explicitly.")
        return 0
    account_id, account_scope = windows_environment("CLOUDFLARE_ACCOUNT_ID")
    token, token_scope = windows_environment("CLOUDFLARE_API_TOKEN")
    account_valid = len(account_id) == 32 and all(
        character in "0123456789abcdefABCDEF" for character in account_id
    )
    safe_status = {
        "account_available": bool(account_id),
        "account_scope": account_scope,
        "account_format_32_hex": account_valid,
        "token_available": bool(token),
        "token_scope": token_scope,
        "ocr_available": TesseractOcr().available(),
    }
    print(json.dumps(safe_status))
    if not account_valid or not token:
        raise RuntimeError("Cloudflare credentials unavailable or invalid; no API call made")
    categories = list(CATEGORY_SCENES)
    report = run_pilot(
        CloudflareFluxSource(account_id, token),
        TesseractOcr(),
        categories,
        args.max_candidates,
        args.date,
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
