from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import shutil
import time
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

REPO_ROOT = Path(__file__).resolve().parent
IMAGES_DIR = REPO_ROOT / "imagens"
PREVIEWS_DIR = REPO_ROOT / "previews"
MESSAGES_FILE = REPO_ROOT / ".github" / "workflows" / "frases.json"
HISTORY_FILE = REPO_ROOT / ".github" / "generation-history.json"
CREDITS_FILE = REPO_ROOT / "image-credits.json"
INDEX_FILE = REPO_ROOT / "index.json"
ATTRIBUTIONS_FILE = REPO_ROOT / "ATTRIBUTIONS.md"
RESERVE_FILE = REPO_ROOT / ".github" / "background-reserve.json"
LOCAL_RESERVE_DIR = REPO_ROOT / ".github" / "background-reserve-files"
STAGING_DIR = REPO_ROOT / ".generation-staging"
CHECKPOINT_FILE = STAGING_DIR / "checkpoint.json"
BACKUP_DIR = REPO_ROOT / ".generation-backup"
TRANSACTION_FILE = REPO_ROOT / ".generation-transaction.json"
RAW_BASE_URL = "https://raw.githubusercontent.com/zflipks/imagens-automaticas/main"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
OPENVERSE_TOKEN_API = "https://api.openverse.org/v1/auth_tokens/token/"
IMAGE_SIZE = (1080, 1080)
IMAGES_PER_CATEGORY = 10
STYLE_COUNT = 10
DOWNLOAD_ATTEMPTS = 2
OPENVERSE_PAGES = 3
OPENVERSE_PAGE_SIZE = 20
MAX_RETRY_AFTER_SECONDS = 60
RESERVE_LIMIT = 500
HISTORY_ASSET_LIMIT = 500
HISTORY_ART_LIMIT = 0
ALLOWED_LICENSES = {"cc0", "pdm", "by"}

GLOBAL_REJECTED_METADATA = {
    "advertisement", "advertising", "banner", "book cover", "brochure", "catalog",
    "document", "flyer", "instructions", "label", "logo", "magazine", "manual",
    "newspaper", "packaging", "poster", "product", "scan", "screenshot", "sign",
    "signboard", "text", "typography", "watermark",
}
CATEGORY_REJECTED_METADATA = {
    "fe": {"army", "car", "military", "soldier", "truck", "vehicle", "weapon"},
    "natal": {"craft template", "instruction", "manual", "tutorial"},
    "pascoa": {"brand", "candy store", "packaging", "supermarket"},
    "aniversario": {"funeral", "memorial"},
    "amor": {"anatomy", "medical", "surgery"},
}
CATEGORY_REQUIRED_EVIDENCE = {
    "fe": {"blessing", "church", "cross", "faith", "heaven", "light", "peace", "prayer", "religion", "serene", "spiritual"},
    "natal": {"christmas", "holiday", "nativity", "noel", "ornament", "wreath"},
    "pascoa": {"bunny", "cross", "easter", "egg", "paschal", "rabbit", "resurrection", "spring"},
    "aniversario": {"balloon", "birthday", "cake", "celebration", "confetti", "gift", "party"},
    "amor": {"candle", "couple", "heart", "love", "romance", "romantic", "rose", "wedding"},
}


class OpenverseAccessError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


CATEGORY_STYLES = {
    "bomdia": {
        "title": "Bom Dia",
        "accent": ("#FFB000", "#FF5C93", "#FFF08A"),
        "themes": [
            ("coffee", "café da manhã"),
            ("sunrise", "amanhecer"),
            ("peony", "flores românticas"),
            ("goldfinch", "pássaros"),
            ("sunflower", "jardins floridos"),
        ],
    },
    "boatarde": {
        "title": "Boa Tarde",
        "accent": ("#FF8A3D", "#FFCF5C", "#FF6B91"),
        "themes": [
            ("daisy", "jardim ensolarado"),
            ("tulip", "flores"),
            ("sunset", "luz dourada"),
            ("tea", "chá"),
            ("sunshine", "paisagem ensolarada"),
        ],
    },
    "boanoite": {
        "title": "Boa Noite",
        "accent": ("#D9C2FF", "#FFD36B", "#8AA8FF"),
        "themes": [
            ("moon", "lua"),
            ("stars", "estrelas"),
            ("porch", "varanda aconchegante"),
            ("nightscape", "céu noturno"),
            ("candle", "iluminação suave"),
        ],
    },
    "aniversario": {
        "title": "Feliz Aniversário",
        "accent": ("#FF5FA2", "#FFD45C", "#EFA8FF"),
        "themes": [
            ("cake", "bolo"),
            ("balloons", "balões"),
            ("gift", "presentes"),
            ("bouquet", "flores"),
            ("birthday", "comemoração"),
        ],
    },
    "anonovo": {
        "title": "Feliz Ano Novo",
        "accent": ("#FFD447", "#FFF2A6", "#FF9F43"),
        "themes": [
            ("fireworks", "fogos"),
            ("glitter", "brilho dourado"),
            ("champagne", "festa"),
            ("party", "luzes de festa"),
            ("sparkler", "renovação"),
        ],
    },
    "fe": {
        "title": "Mensagens de Fé",
        "accent": ("#FFD56A", "#F6F0D0", "#8FC7FF"),
        "themes": [("prayer", "oração"), ("church", "fé"), ("sunbeam", "céu iluminado"), ("peaceful nature", "natureza serena"), ("cross", "símbolo de fé")],
    },
    "gratidao": {
        "title": "Gratidão",
        "accent": ("#F7B955", "#FF8FA3", "#B6D77A"),
        "themes": [("gratitude", "gratidão"), ("flowers", "flores"), ("sunrise", "amanhecer"), ("happy people", "felicidade"), ("peaceful landscape", "paisagem acolhedora")],
    },
    "amizade": {
        "title": "Amizade",
        "accent": ("#FFB35C", "#FF7FA8", "#79C8E8"),
        "themes": [("friends", "amigos"), ("friendship", "amizade"), ("hug", "abraço"), ("people together", "união"), ("friends laughing", "alegria entre amigos")],
    },
    "amor": {
        "title": "Amor",
        "accent": ("#E93B6F", "#FF8CAC", "#F4C36A"),
        "themes": [("red roses", "rosas vermelhas"), ("couple sunset", "casal ao pôr do sol"), ("heart", "coração"), ("romantic candles", "velas românticas"), ("love gift", "presente de amor")],
    },
    "motivacao": {
        "title": "Motivação",
        "accent": ("#FFB52E", "#6EC5FF", "#FF6D6D"),
        "themes": [("mountain summit", "conquista"), ("hiking trail", "caminho"), ("sunrise", "amanhecer"), ("runner", "superação"), ("inspiring landscape", "paisagem inspiradora")],
    },
    "felizsemana": {
        "title": "Feliz Semana",
        "accent": ("#FFD15A", "#FF8CB5", "#80CFA9"),
        "themes": [("morning coffee", "café"), ("sunrise", "novo começo"), ("flowers", "flores"), ("bright landscape", "paisagem alegre"), ("garden", "jardim")],
    },
    "bomfimdesemana": {
        "title": "Bom Fim de Semana",
        "accent": ("#5FC8E8", "#FFB45C", "#86C982"),
        "themes": [("beach", "praia"), ("relaxing nature", "natureza"), ("travel", "viagem"), ("coffee break", "descanso com café"), ("peaceful garden", "jardim relaxante")],
    },
    "natal": {
        "title": "Feliz Natal",
        "accent": ("#D93B4D", "#E5C45B", "#2E9B65"),
        "themes": [("christmas tree", "árvore de Natal"), ("christmas gifts", "presentes"), ("christmas lights", "luzes natalinas"), ("christmas wreath", "guirlanda"), ("christmas star", "estrela de Natal")],
    },
    "pascoa": {
        "title": "Feliz Páscoa",
        "accent": ("#F4B5D4", "#F3D06B", "#9BCB7A"),
        "themes": [("easter eggs", "ovos decorados"), ("easter bunny", "coelho"), ("spring flowers", "flores"), ("resurrection cross", "símbolo religioso"), ("easter basket", "cesta de Páscoa")],
    },
    "bomsabado": {
        "title": "Bom Sábado",
        "accent": ("#FFC85A", "#F58FB1", "#79C99E"),
        "themes": [("breakfast coffee", "café da manhã"), ("flowers", "flores"), ("garden", "jardim"), ("relaxing nature", "descanso"), ("weekend leisure", "lazer")],
    },
    "felizdomingo": {
        "title": "Feliz Domingo",
        "accent": ("#FFD76B", "#9CCBFF", "#F28FA8"),
        "themes": [("sunday sunrise", "amanhecer"), ("flowers", "flores"), ("family together", "família"), ("peaceful nature", "paz"), ("blessing", "bênçãos")],
    },
}

TITLE_FONT_CANDIDATES = (
    REPO_ROOT / "fonts" / "Pacifico-Regular.ttf",
    REPO_ROOT / "Pacifico-Regular.ttf",
    Path("C:/Windows/Fonts/segoesc.ttf"),
)
SERIF_FONT_CANDIDATES = (
    REPO_ROOT / "fonts" / "DejaVuSerif.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    Path("C:/Windows/Fonts/georgia.ttf"),
)
SERIF_BOLD_FONT_CANDIDATES = (
    REPO_ROOT / "fonts" / "DejaVuSerif-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    Path("C:/Windows/Fonts/georgiab.ttf"),
)
SERIF_ITALIC_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
    Path("C:/Windows/Fonts/georgiai.ttf"),
)
SANS_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/calibri.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)
SANS_BOLD_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/calibrib.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)
SANS_CONDENSED_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"),
    Path("C:/Windows/Fonts/impact.ttf"),
)
HAND_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/segoepr.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
)
MONO_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("C:/Windows/Fonts/consola.ttf"),
)

STYLE_NAMES = (
    "Aconchegante",
    "Natureza limpa",
    "Floral romântico",
    "Fotográfico editorial",
    "Elegante dourado",
    "Manuscrito afetivo",
    "Chamativo pop",
    "Ilustrado colorido",
    "Fé delicada",
    "Motivacional moderno",
)

REMOTE_FONT_URLS = {
    "great_vibes": "https://raw.githubusercontent.com/google/fonts/main/ofl/greatvibes/GreatVibes-Regular.ttf",
    "caveat": "https://raw.githubusercontent.com/google/fonts/main/ofl/caveat/Caveat%5Bwght%5D.ttf",
    "playfair": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
}
REMOTE_FONT_FALLBACKS = {
    "great_vibes": TITLE_FONT_CANDIDATES,
    "caveat": HAND_FONT_CANDIDATES,
    "playfair": SERIF_FONT_CANDIDATES,
}
_REMOTE_FONT_BYTES: dict[str, bytes] = {}

# Cada tema aparece duas vezes no lote; os dez estilos continuam únicos.
CATEGORY_STYLE_ORDER = {
    "bomdia": [0, 1, 2, 3, 8, 5, 9, 4, 6, 7],
    "boatarde": [1, 2, 4, 0, 8, 7, 3, 9, 5, 6],
    "boanoite": [4, 1, 0, 3, 8, 5, 9, 6, 2, 7],
    "aniversario": [7, 6, 5, 2, 8, 4, 9, 0, 3, 1],
    "anonovo": [6, 4, 0, 7, 9, 3, 8, 5, 1, 2],
    "fe": [8, 1, 4, 0, 3, 5, 9, 2, 7, 6],
    "gratidao": [2, 1, 0, 4, 5, 7, 3, 8, 9, 6],
    "amizade": [7, 3, 5, 2, 6, 1, 0, 4, 9, 8],
    "amor": [2, 5, 4, 3, 6, 0, 7, 1, 8, 9],
    "motivacao": [9, 1, 3, 6, 4, 0, 5, 7, 8, 2],
    "felizsemana": [0, 1, 2, 9, 7, 5, 3, 4, 8, 6],
    "bomfimdesemana": [1, 0, 3, 5, 7, 2, 4, 9, 8, 6],
    "natal": [4, 7, 6, 0, 8, 2, 5, 3, 9, 1],
    "pascoa": [2, 7, 8, 1, 4, 5, 0, 3, 6, 9],
    "bomsabado": [0, 2, 1, 5, 7, 3, 4, 9, 8, 6],
    "felizdomingo": [8, 1, 2, 0, 4, 5, 3, 7, 9, 6],
}

SECOND_CYCLE_QUERIES = {
    "bomdia": {"coffee": "latte", "sunrise": "dawn", "peony": "blossom", "goldfinch": "robin", "sunflower": "garden"},
    "boatarde": {"daisy": "garden", "tulip": "flower", "sunset": "sunlight", "tea": "teacup", "sunshine": "landscape"},
    "boanoite": {"moon": "moonlight", "stars": "night sky", "porch": "cozy home", "nightscape": "city night", "candle": "lantern"},
    "aniversario": {"cake": "birthday cake", "balloons": "party balloons", "gift": "wrapped gift", "bouquet": "peony", "birthday": "birthday party"},
    "anonovo": {"fireworks": "firework", "glitter": "gold sparkle", "champagne": "celebration toast", "party": "party lights", "sparkler": "sparklers"},
    "fe": {"prayer": "praying hands", "church": "church interior", "sunbeam": "heavenly light", "peaceful nature": "serene nature", "cross": "christian cross"},
    "gratidao": {"gratitude": "thankful", "flowers": "flower garden", "sunrise": "dawn", "happy people": "joy", "peaceful landscape": "serene landscape"},
    "amizade": {"friends": "best friends", "friendship": "friendship hug", "hug": "friends hugging", "people together": "community", "friends laughing": "happy friends"},
    "amor": {"red roses": "red rose bouquet", "couple sunset": "romantic couple", "heart": "love heart", "romantic candles": "candlelight romance", "love gift": "romantic gift"},
    "motivacao": {"mountain summit": "mountain peak", "hiking trail": "mountain path", "sunrise": "dawn", "runner": "running athlete", "inspiring landscape": "epic landscape"},
    "felizsemana": {"morning coffee": "coffee cup", "sunrise": "dawn", "flowers": "bright flowers", "bright landscape": "sunny landscape", "garden": "flower garden"},
    "bomfimdesemana": {"beach": "tropical beach", "relaxing nature": "peaceful nature", "travel": "weekend travel", "coffee break": "coffee leisure", "peaceful garden": "quiet garden"},
    "natal": {"christmas tree": "decorated christmas tree", "christmas gifts": "wrapped christmas gifts", "christmas lights": "holiday lights", "christmas wreath": "holiday wreath", "christmas star": "christmas decoration"},
    "pascoa": {"easter eggs": "decorated easter eggs", "easter bunny": "rabbit easter", "spring flowers": "spring blossom", "resurrection cross": "easter cross", "easter basket": "easter decoration"},
    "bomsabado": {"breakfast coffee": "weekend breakfast", "flowers": "bright flowers", "garden": "flower garden", "relaxing nature": "peaceful nature", "weekend leisure": "relaxing weekend nature"},
    "felizdomingo": {"sunday sunrise": "dawn", "flowers": "bright flowers", "family together": "happy family", "peaceful nature": "serene nature", "blessing": "prayer"},
}

THEME_FALLBACK_QUERIES = {
    category: list(dict.fromkeys(
        [query for query, _label in config["themes"]]
        + list(SECOND_CYCLE_QUERIES[category].values())
    ))
    for category, config in CATEGORY_STYLES.items()
}

DAILY_CATEGORIES = (
    "bomdia", "boatarde", "boanoite", "aniversario", "fe", "gratidao",
    "amizade", "amor", "motivacao", "felizsemana", "bomfimdesemana",
)
SEASONAL_CATEGORIES = ("anonovo", "natal", "pascoa")
WEEKEND_CATEGORIES = {5: "bomsabado", 6: "felizdomingo"}

_RESERVE_POOL: list[dict[str, object]] = []
_DISCOVERED_RESERVE: dict[str, dict[str, object]] = {}
_BLOCKED_FINGERPRINTS: set[str] = set()

FAITH_TERMS = ("deus", "fé", "bênção", "abenç", "divina", "proteção", "senhor")
MOTIVATION_TERMS = ("esperança", "coragem", "confiança", "sonho", "recome", "acredite", "força")
EMPHASIS_TERMS = {
    "deus": (255, 215, 92), "fé": (255, 224, 116), "amor": (255, 102, 165),
    "gratidão": (255, 205, 90), "esperança": (117, 236, 190),
    "coragem": (255, 177, 76), "bênçãos": (255, 222, 125),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera lotes temáticos do BomDiaWhats.")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=datetime.now().astimezone().date(),
        help="Data de referência no formato AAAA-MM-DD.",
    )
    parser.add_argument(
        "--initialize-all",
        action="store_true",
        help="Gera lote inicial das 16 categorias, inclusive sazonais e de fim de semana.",
    )
    return parser.parse_args()


def easter_date(year: int) -> date:
    """Calcula a Páscoa pelo algoritmo gregoriano de Meeus/Jones/Butcher."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def seasonal_category_is_active(category: str, reference_date: date) -> bool:
    if category == "anonovo":
        return (reference_date.month == 12 and reference_date.day >= 15) or (
            reference_date.month == 1 and reference_date.day <= 10
        )
    if category == "natal":
        return (reference_date.month == 11 and reference_date.day >= 25) or (
            reference_date.month == 12 and reference_date.day <= 26
        )
    if category == "pascoa":
        delta = (reference_date - easter_date(reference_date.year)).days
        return -30 <= delta <= 7
    return False


def active_categories(reference_date: date, initialize_all: bool = False) -> list[str]:
    if initialize_all:
        return list(CATEGORY_STYLES)
    active = list(DAILY_CATEGORIES)
    weekend = WEEKEND_CATEGORIES.get(reference_date.weekday())
    if weekend:
        active.append(weekend)
    active.extend(
        category for category in SEASONAL_CATEGORIES
        if seasonal_category_is_active(category, reference_date)
    )
    return active


def find_font(candidates: Iterable[Path]) -> Path | None:
    return next((path for path in candidates if path.exists()), None)


def load_font(candidates: Iterable[Path], size: int):
    path = find_font(candidates)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def load_named_font(name: str, size: int):
    """Carrega uma fonte OFL oficial em memória, com fallback local seguro."""
    try:
        if name not in _REMOTE_FONT_BYTES:
            response = requests.get(REMOTE_FONT_URLS[name], timeout=(10, 35))
            response.raise_for_status()
            _REMOTE_FONT_BYTES[name] = response.content
        return ImageFont.truetype(BytesIO(_REMOTE_FONT_BYTES[name]), size)
    except (requests.RequestException, OSError, KeyError):
        return load_font(REMOTE_FONT_FALLBACKS.get(name, SERIF_FONT_CANDIDATES), size)


def validate_font_environment() -> None:
    """Falha cedo se o ambiente não reproduzir as famílias usadas pelos dez estilos."""
    required_local = {
        "title": TITLE_FONT_CANDIDATES,
        "serif": SERIF_FONT_CANDIDATES,
        "serif_bold": SERIF_BOLD_FONT_CANDIDATES,
        "serif_italic": SERIF_ITALIC_FONT_CANDIDATES,
        "sans": SANS_FONT_CANDIDATES,
        "sans_bold": SANS_BOLD_FONT_CANDIDATES,
        "sans_condensed": SANS_CONDENSED_FONT_CANDIDATES,
        "hand": HAND_FONT_CANDIDATES,
        "mono": MONO_FONT_CANDIDATES,
    }
    missing = [name for name, candidates in required_local.items() if find_font(candidates) is None]
    if missing:
        raise RuntimeError("Fontes locais necessárias ausentes: " + ", ".join(missing))

    for name in REMOTE_FONT_URLS:
        font = load_named_font(name, 48)
        if name not in _REMOTE_FONT_BYTES:
            raise RuntimeError(
                f"Fonte OFL {name} indisponível; a geração usaria fallback e alteraria o visual."
            )
        if not isinstance(font, ImageFont.FreeTypeFont):
            raise RuntimeError(f"Fonte OFL inválida: {name}")

    print("Fontes aprovadas disponíveis: locais e OFL remotas carregadas sem fallback.")


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def expand_message_spec(spec: object, category: str) -> list[str]:
    if isinstance(spec, list):
        values = spec
    elif isinstance(spec, dict):
        values = list(spec.get("base", []))
        combinations = spec.get("combinations", {})
        starts = combinations.get("starts", [])
        endings = combinations.get("endings", [])
        values.extend(
            f"{start.rstrip()} {ending.lstrip()}"
            for start, ending in itertools.product(starts, endings)
        )
    else:
        raise ValueError(f"Formato inválido de frases em {category}.")

    unique = list(dict.fromkeys(
        value.strip() for value in values if isinstance(value, str) and value.strip()
    ))
    if len(unique) < 100:
        raise ValueError(f"{category} precisa oferecer ao menos 100 frases; encontrou {len(unique)}.")
    return unique


def load_messages() -> dict[str, list[str]]:
    with MESSAGES_FILE.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        category: expand_message_spec(raw.get(category), category)
        for category in CATEGORY_STYLES
    }


def load_history() -> dict[str, object]:
    if not HISTORY_FILE.exists():
        return {"version": 2, "categories": {}}
    with HISTORY_FILE.open(encoding="utf-8") as handle:
        history = json.load(handle)
    history.setdefault("version", 2)
    history.setdefault("categories", {})
    return history


def choose_messages(
    available: list[str], recent: list[str], category: str, reference_date: date,
    style_ids: list[int],
) -> list[str]:
    rng = random.Random(f"messages:{category}:{reference_date.isoformat()}")
    recent_set = set(recent)
    fresh = [message for message in available if message not in recent_set]
    reused = [message for message in available if message in recent_set]
    rng.shuffle(fresh)
    rng.shuffle(reused)
    pool = fresh + reused
    selected: list[str] = []
    for style_id in style_ids:
        required = FAITH_TERMS if style_id == 8 else MOTIVATION_TERMS if style_id == 9 else ()
        candidate = next((text for text in pool if text not in selected and (not required or any(term in text.casefold() for term in required))), None)
        if candidate is None:
            candidate = next((text for text in pool if text not in selected), None)
        if candidate is None:
            raise RuntimeError(f"Não foi possível selecionar frases únicas para {category}.")
        selected.append(candidate)
    return selected


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join((*current, word))
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_lines: int, start: int):
    for size in range(start, 31, -2):
        font = load_font(SERIF_BOLD_FONT_CANDIDATES, size)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = load_font(SERIF_BOLD_FONT_CANDIDATES, 30)
    return font, wrap_text(draw, text, font, max_width)


def configure_openverse_auth(session: requests.Session) -> bool:
    """Autentica quando os segredos existem; nunca registra nem persiste credenciais."""
    client_id = os.getenv("OPENVERSE_CLIENT_ID", "").strip()
    client_secret = os.getenv("OPENVERSE_CLIENT_SECRET", "").strip()
    if bool(client_id) != bool(client_secret):
        raise RuntimeError(
            "Defina OPENVERSE_CLIENT_ID e OPENVERSE_CLIENT_SECRET em conjunto."
        )
    if not client_id:
        return False
    response = session.post(
        OPENVERSE_TOKEN_API,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=(10, 30),
    )
    response.raise_for_status()
    token = str(response.json().get("access_token", "")).strip()
    if not token:
        raise RuntimeError("Openverse não retornou access_token.")
    session.headers["Authorization"] = f"Bearer {token}"
    return True


def openverse_search(
    session: requests.Session,
    theme_query: str,
    rng: random.Random,
    page: int,
) -> list[dict[str, object]]:
    params = {
        "q": theme_query,
        "license": "cc0,pdm,by",
        "license_type": "commercial",
        "category": "photograph",
        "excluded_source": "bio_diversity",
        "mature": "false",
        "page_size": OPENVERSE_PAGE_SIZE,
        "page": page,
    }
    response = session.get(OPENVERSE_API, params=params, timeout=(10, 25))
    if response.status_code == 401:
        raise OpenverseAccessError(
            401,
            "Openverse rejeitou as credenciais. Verifique os segredos antes de tentar novamente.",
        )
    if response.status_code == 403:
        cloudflare = "cloudflare" in response.text.casefold() or "just a moment" in response.text.casefold()
        reason = "desafio Cloudflare" if cloudflare else "acesso proibido"
        raise OpenverseAccessError(
            403,
            f"Openverse respondeu 403 ({reason}); a execução não tentará contornar o bloqueio.",
        )
    if response.status_code == 429:
        raw_retry = response.headers.get("Retry-After", "0")
        try:
            retry_after = min(max(int(raw_retry), 0), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            retry_after = 0
        raise OpenverseAccessError(
            429,
            f"Limite do Openverse atingido; Retry-After={raw_retry!r}.",
            retry_after,
        )
    response.raise_for_status()
    results = response.json().get("results", [])
    query_tokens = {
        token for token in theme_query.casefold().replace("-", " ").split()
        if len(token) >= 3 and token not in {"and", "with", "the"}
    }
    filtered: list[dict[str, object]] = []
    for item in results:
        license_code = str(item.get("license", "")).lower()
        title = str(item.get("title") or "").casefold()
        tags = {
            str(tag.get("name") or "").strip().casefold()
            for tag in item.get("tags", [])
        }
        metadata_text = " ".join((title, *tags))
        matches_theme = any(token in metadata_text for token in query_tokens)
        beverage_query = bool(query_tokens & {"latte", "espresso", "cappuccino", "coffee", "tea", "teacup"})
        beverage_ok = not beverage_query or any(
            term in metadata_text
            for term in {"coffee", "latte", "espresso", "cappuccino", "cafe", "barista", "tea", "teacup"}
        )
        if (
            license_code in ALLOWED_LICENSES
            and item.get("url")
            and matches_theme
            and beverage_ok
            and not any(term in metadata_text for term in GLOBAL_REJECTED_METADATA)
        ):
            filtered.append(item)
    rng.shuffle(filtered)
    priority = {"cc0": 0, "pdm": 1, "by": 2}
    filtered.sort(key=lambda item: priority.get(str(item.get("license", "")).lower(), 9))
    return filtered


def metadata_theme_is_suitable(
    item: dict[str, object], category: str, query: str
) -> tuple[bool, list[str]]:
    title = str(item.get("title") or "").casefold()
    tags = {
        str(tag.get("name") or "").strip().casefold()
        for tag in item.get("tags", [])
        if isinstance(tag, dict)
    }
    text = " ".join((title, query.casefold(), *tags))
    rejected = GLOBAL_REJECTED_METADATA | CATEGORY_REJECTED_METADATA.get(category, set())
    if any(term in text for term in rejected):
        return False, []
    required = CATEGORY_REQUIRED_EVIDENCE.get(category)
    evidence = sorted(term for term in (required or set()) if term in text)
    if required and not evidence:
        return False, []
    return True, evidence


def load_local_reserve_image(metadata: dict[str, object]) -> Image.Image:
    relative = str(metadata.get("local_file") or "")
    if not relative:
        raise FileNotFoundError("Entrada não possui arquivo de reserva local.")
    path = (REPO_ROOT / relative).resolve()
    reserve_root = LOCAL_RESERVE_DIR.resolve()
    if reserve_root not in path.parents:
        raise ValueError(f"Caminho de reserva fora da área permitida: {relative}")
    expected_hash = str(metadata.get("file_sha256") or "")
    content = path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(f"Hash divergente na reserva local: {relative}")
    image = Image.open(BytesIO(content))
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB")


def metadata_from_item(
    item: dict[str, object], category: str, theme_label: str, query: str
) -> dict[str, object]:
    license_code = str(item.get("license", "")).lower()
    creator = str(item.get("creator") or "Autor não informado")
    title = str(item.get("title") or "Sem título")
    source_url = item.get("foreign_landing_url") or item.get("source_url")
    license_url = item.get("license_url")
    attribution = item.get("attribution") or f"{title} — {creator}"
    _suitable, evidence = metadata_theme_is_suitable(item, category, query)
    return {
        "asset_id": str(item.get("id") or item.get("asset_id")),
        "category": category,
        "theme": theme_label,
        "search_terms": query,
        "title": title,
        "creator": creator,
        "creator_url": item.get("creator_url"),
        "license": license_code,
        "license_version": item.get("license_version"),
        "license_url": license_url,
        "source": item.get("source"),
        "provider": item.get("provider"),
        "source_url": source_url,
        "download_url": item.get("url") or item.get("download_url"),
        "attribution": attribution,
        "attribution_required": license_code == "by",
        "share_credit": (
            f"Foto: {title}, por {creator} — {license_code.upper()}. "
            f"Fonte: {source_url}; licença: {license_url}"
            if license_code == "by" else None
        ),
        "openverse_detail_url": item.get("detail_url") or item.get("openverse_detail_url"),
        "local_file": item.get("local_file"),
        "file_sha256": item.get("file_sha256"),
        "thematic_evidence": evidence,
        "visual_review_status": item.get("visual_review_status", "pending"),
    }


def load_reserve() -> list[dict[str, object]]:
    if not RESERVE_FILE.exists():
        return []
    with RESERVE_FILE.open(encoding="utf-8") as handle:
        value = json.load(handle)
    entries = value.get("entries", []) if isinstance(value, dict) else []
    return [
        entry for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("license", "")).lower() in ALLOWED_LICENSES
        and (entry.get("local_file") or entry.get("download_url"))
        and entry.get("asset_id")
    ]


def download_image(session: requests.Session, url: str) -> Image.Image:
    response = session.get(url, timeout=(15, 60), allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and not content_type.casefold().startswith("image/"):
        raise ValueError(f"Conteúdo remoto não é imagem: {content_type}")
    image = Image.open(BytesIO(response.content))
    image.load()
    image = ImageOps.exif_transpose(image).convert("RGB")
    if min(image.size) < 500:
        raise ValueError(f"Imagem pequena demais: {image.size}")
    return image


def image_is_suitable(image: Image.Image, category: str) -> bool:
    sample = image.resize((64, 64), Image.Resampling.BILINEAR)
    brightness = sum(ImageStat.Stat(sample.convert("L")).mean)
    saturation = ImageStat.Stat(sample.convert("HSV")).mean[1]
    minimums = {
        "bomdia": (52, 16),
        "boatarde": (45, 12),
        "boanoite": (20, 8),
        "aniversario": (42, 12),
        "anonovo": (30, 10),
        "fe": (38, 8),
        "gratidao": (45, 12),
        "amizade": (42, 10),
        "amor": (35, 12),
        "motivacao": (38, 10),
        "felizsemana": (45, 12),
        "bomfimdesemana": (42, 10),
        "natal": (28, 10),
        "pascoa": (42, 12),
        "bomsabado": (45, 12),
        "felizdomingo": (45, 10),
    }
    minimum_brightness, minimum_saturation = minimums[category]
    return brightness >= minimum_brightness and saturation >= minimum_saturation


def image_fingerprint(image: Image.Image) -> str:
    sample = image.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
    values = list(sample.getdata())
    average = sum(values) / len(values)
    bits = bytes(1 if value >= average else 0 for value in values)
    return hashlib.sha256(bits).hexdigest()


def try_candidates(
    session: requests.Session,
    candidates: Iterable[dict[str, object]],
    category: str,
    theme_label: str,
    query: str,
    blocked_ids: set[str],
) -> tuple[Image.Image, dict[str, object]] | None:
    global _DISCOVERED_RESERVE, _BLOCKED_FINGERPRINTS
    last_error: Exception | None = None
    for item in candidates:
        metadata = metadata_from_item(item, category, theme_label, query)
        asset_id = str(metadata["asset_id"])
        if asset_id in blocked_ids:
            continue
        thematic_ok, evidence = metadata_theme_is_suitable(item, category, query)
        if not thematic_ok:
            print(f"  rejeitado {category}/{asset_id}: metadados sem evidência temática suficiente")
            continue
        metadata["thematic_evidence"] = evidence
        if str(metadata.get("license")) == "by" and (
            not item.get("creator") or not metadata.get("license_url") or not metadata.get("source_url")
        ):
            print(f"  rejeitado {category}/{asset_id}: atribuição CC BY incompleta")
            continue
        if len(_DISCOVERED_RESERVE) < RESERVE_LIMIT:
            _DISCOVERED_RESERVE.setdefault(asset_id, metadata)
        try:
            if metadata.get("local_file"):
                image = load_local_reserve_image(metadata)
                metadata["background_origin"] = "local-reserve"
            else:
                image = download_image(session, str(metadata["download_url"]))
                metadata["background_origin"] = "openverse"
            if not image_is_suitable(image, category):
                raise ValueError(f"Fundo escuro ou pouco vibrante para {category}")
            fingerprint = image_fingerprint(image)
            if fingerprint in _BLOCKED_FINGERPRINTS:
                raise ValueError("Conteúdo fotográfico repetido detectado")
            metadata["content_fingerprint"] = fingerprint
            _DISCOVERED_RESERVE.pop(asset_id, None)
            return image, metadata
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = error
            continue
    if last_error:
        print(f"  aviso: candidatos rejeitados para {query}: {last_error}")
    return None


def fetch_thematic_background(
    session: requests.Session,
    category: str,
    slot: int,
    reference_date: date,
    blocked_ids: set[str],
) -> tuple[Image.Image, dict[str, object]]:
    themes = CATEGORY_STYLES[category]["themes"]
    primary_query, theme_label = themes[(slot - 1) % len(themes)]
    if category == "bomdia" and primary_query == "coffee" and slot <= len(themes):
        primary_query = "espresso"
    elif slot > len(themes):
        primary_query = SECOND_CYCLE_QUERIES[category].get(primary_query, primary_query)
        theme_label = f"{theme_label} — variação"

    rng = random.Random(f"background:{category}:{slot}:{reference_date.isoformat()}")
    queries = list(dict.fromkeys((primary_query, *THEME_FALLBACK_QUERIES[category])))
    api_errors: list[str] = []
    api_blocked = False
    for query in queries:
        if api_blocked:
            break
        for page in range(1, OPENVERSE_PAGES + 1):
            if api_blocked:
                break
            for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
                try:
                    candidates = openverse_search(session, query, rng, page)
                    for candidate in candidates[:12]:
                        metadata = metadata_from_item(candidate, category, theme_label, query)
                        candidate_id = str(metadata["asset_id"])
                        if candidate_id not in blocked_ids and len(_DISCOVERED_RESERVE) < RESERVE_LIMIT:
                            _DISCOVERED_RESERVE.setdefault(candidate_id, metadata)
                    result = try_candidates(
                        session, candidates, category, theme_label, query, blocked_ids
                    )
                    if result:
                        return result
                    break
                except OpenverseAccessError as error:
                    api_errors.append(f"{query}/p{page}/t{attempt}: HTTP {error.status_code}: {error}")
                    if error.status_code == 429 and attempt < DOWNLOAD_ATTEMPTS:
                        wait_seconds = error.retry_after or min(attempt * 5, MAX_RETRY_AFTER_SECONDS)
                        print(f"  Openverse 429; aguardando {wait_seconds}s antes da última tentativa")
                        time.sleep(wait_seconds)
                        continue
                    api_blocked = True
                    print(f"  Openverse indisponível para este lote: {error}")
                    break
                except (requests.RequestException, ValueError) as error:
                    api_errors.append(f"{query}/p{page}/t{attempt}: {error}")
                    if attempt < DOWNLOAD_ATTEMPTS:
                        time.sleep(min(attempt * 2, 8))

    reserve_candidates = [
        item for item in _RESERVE_POOL
        if item.get("category") == category
        and str(item.get("asset_id")) not in blocked_ids
        and item.get("visual_review_status") == "approved"
    ]
    rng.shuffle(reserve_candidates)
    reserve_candidates.sort(key=lambda item: 0 if item.get("local_file") else 1)
    reserve_result = try_candidates(
        session, reserve_candidates, category, f"{theme_label} — reserva", primary_query, blocked_ids
    )
    if reserve_result:
        print(f"  reserva local utilizada: {reserve_result[1].get('local_file')}")
        return reserve_result

    summary = "; ".join(api_errors[-5:]) or "nenhum candidato adequado encontrado"
    raise RuntimeError(
        f"Não foi possível obter fundo inédito para {category}/{theme_label}. {summary}"
    )


def prepare_background(image: Image.Image, category: str, variant: int) -> Image.Image:
    image = ImageOps.fit(image, IMAGE_SIZE, method=Image.Resampling.LANCZOS)
    saturation = 1.38 if category in {"bomdia", "boatarde", "aniversario"} else 1.25
    image = ImageEnhance.Color(image).enhance(saturation)
    image = ImageEnhance.Contrast(image).enhance(1.08)
    image = ImageEnhance.Brightness(image).enhance(
        1.14 if category == "bomdia" else 1.08 if category in {"boatarde", "aniversario"} else 1.02
    )
    tint_colors = {
        "bomdia": (255, 201, 92),
        "boatarde": (255, 149, 79),
        "boanoite": (77, 82, 180),
        "aniversario": (255, 102, 171),
        "anonovo": (255, 191, 45),
        "fe": (246, 218, 145),
        "gratidao": (255, 184, 112),
        "amizade": (255, 144, 174),
        "amor": (225, 70, 105),
        "motivacao": (255, 171, 64),
        "felizsemana": (255, 202, 96),
        "bomfimdesemana": (93, 190, 210),
        "natal": (185, 45, 64),
        "pascoa": (244, 176, 207),
        "bomsabado": (255, 196, 91),
        "felizdomingo": (255, 209, 112),
    }
    tint = Image.new("RGB", IMAGE_SIZE, tint_colors[category])
    image = Image.blend(image, tint, 0.07 if category != "boanoite" else 0.11)
    if variant % 2:
        image = image.filter(ImageFilter.GaussianBlur(0.25))
    return image.convert("RGBA")


def linear_gradient(
    size: tuple[int, int],
    start: tuple[int, int, int, int],
    end: tuple[int, int, int, int],
    vertical: bool = True,
) -> Image.Image:
    strip_size = (1, size[1]) if vertical else (size[0], 1)
    strip = Image.new("RGBA", strip_size)
    pixels = strip.load()
    extent = max(1, (size[1] if vertical else size[0]) - 1)
    for position in range(extent + 1):
        ratio = position / extent
        color = tuple(round(start[i] * (1 - ratio) + end[i] * ratio) for i in range(4))
        if vertical:
            pixels[0, position] = color
        else:
            pixels[position, 0] = color
    return strip.resize(size)


def draw_flower(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int], alpha: int = 210) -> None:
    petal = (*color, alpha)
    for angle in range(0, 360, 60):
        radians = math.radians(angle)
        px = x + int(math.cos(radians) * size * 0.65)
        py = y + int(math.sin(radians) * size * 0.65)
        draw.ellipse((px - size // 2, py - size // 3, px + size // 2, py + size // 3), fill=petal)
    draw.ellipse((x - size // 3, y - size // 3, x + size // 3, y + size // 3), fill=(255, 220, 72, alpha))


def draw_heart(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, color: tuple[int, int, int], alpha: int = 150) -> None:
    points = []
    for step in range(101):
        t = 2 * math.pi * step / 100
        px = 16 * math.sin(t) ** 3
        py = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((x + px * size / 32, y - py * size / 32))
    draw.polygon(points, fill=(*color, alpha))


def add_ornaments(layer: Image.Image, category: str, accent: tuple[int, int, int], seed: str) -> None:
    draw = ImageDraw.Draw(layer)
    rng = random.Random(seed)
    flower_colors = [(255, 104, 160), (255, 190, 65), (255, 245, 245), (210, 104, 255)]
    if category in {"bomdia", "boatarde", "aniversario"}:
        corners = [(68, 80), (1010, 90), (75, 990), (1005, 980)]
        for index, (x, y) in enumerate(corners):
            draw_flower(draw, x, y, rng.randint(22, 35), flower_colors[index], 185)
        for _ in range(6):
            draw_heart(draw, rng.randint(70, 1010), rng.randint(70, 1010), rng.randint(16, 27), accent, 85)
    for _ in range(26):
        x, y = rng.randint(35, 1045), rng.randint(35, 1045)
        radius = rng.choice((2, 3, 4, 6))
        draw.regular_polygon((x, y, radius), 4, rotation=45, fill=(*accent, rng.randint(100, 220)))


def text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    align: str,
    shadow: tuple[int, int, int, int] = (45, 20, 20, 220),
    gap: int = 15,
) -> None:
    left, top, right, bottom = box
    heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
    total = sum(heights) + gap * max(0, len(lines) - 1)
    y = top + max(0, (bottom - top - total) / 2)
    for line, height in zip(lines, heights):
        width = draw.textbbox((0, 0), line, font=font)[2]
        x = left if align == "left" else right - width if align == "right" else (left + right - width) / 2
        draw.text((x + 4, y + 5), line, font=font, fill=shadow, stroke_width=3, stroke_fill=shadow)
        draw.text((x, y), line, font=font, fill=fill, stroke_width=2, stroke_fill=(75, 35, 35, 210))
        y += height + gap


def title_font_for(draw: ImageDraw.ImageDraw, title: str, max_width: int = 900):
    for size in range(142, 79, -4):
        font = load_font(TITLE_FONT_CANDIDATES, size)
        if draw.textbbox((0, 0), title, font=font)[2] <= max_width:
            return font
    return load_font(TITLE_FONT_CANDIDATES, 78)


def draw_title(draw: ImageDraw.ImageDraw, title: str, xy: tuple[int, int], font, fill: tuple[int, int, int], anchor: str = "mm") -> None:
    glow = tuple(min(255, channel + 65) for channel in fill)
    draw.text(xy, title, font=font, fill=(*glow, 150), anchor=anchor, stroke_width=12, stroke_fill=(255, 255, 255, 90))
    draw.text((xy[0] + 5, xy[1] + 7), title, font=font, fill=(70, 20, 25, 220), anchor=anchor, stroke_width=6, stroke_fill=(255, 255, 255, 190))
    draw.text(xy, title, font=font, fill=(*fill, 255), anchor=anchor, stroke_width=3, stroke_fill=(255, 255, 255, 245))


def fit_with_candidates(
    draw: ImageDraw.ImageDraw,
    text: str,
    candidates: Iterable[Path],
    max_width: int,
    max_lines: int,
    start_size: int,
):
    for size in range(start_size, 27, -2):
        font = load_font(candidates, size)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = load_font(candidates, 26)
    return font, wrap_text(draw, text, font, max_width)


def fit_title_with_candidates(
    draw: ImageDraw.ImageDraw,
    title: str,
    candidates: Iterable[Path],
    start_size: int,
    max_width: int,
):
    for size in range(start_size, 55, -3):
        font = load_font(candidates, size)
        if draw.textbbox((0, 0), title, font=font)[2] <= max_width:
            return font
    return load_font(candidates, 54)


def localized_gradient(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    maximum_alpha: int,
    vertical: bool = True,
) -> Image.Image:
    left, top, right, bottom = box
    gradient = linear_gradient(
        (right - left, bottom - top),
        (*color, 0),
        (*color, maximum_alpha),
        vertical=vertical,
    )
    layer = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
    layer.alpha_composite(gradient, (left, top))
    return Image.alpha_composite(canvas, layer)


def draw_soft_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill: tuple[int, int, int, int],
    anchor: str = "la",
    stroke: int = 2,
    stroke_fill: tuple[int, int, int, int] = (25, 20, 25, 190),
) -> None:
    draw.text(
        (xy[0] + 3, xy[1] + 4),
        text,
        font=font,
        fill=(0, 0, 0, 125),
        anchor=anchor,
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 105),
    )
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        anchor=anchor,
        stroke_width=stroke,
        stroke_fill=stroke_fill,
    )


def draw_glowing_text(canvas: Image.Image, xy: tuple[int, int], text: str, font, fill: tuple[int, int, int], anchor: str = "mm", glow: tuple[int, int, int] | None = None) -> None:
    mask = Image.new("L", IMAGE_SIZE, 0)
    md = ImageDraw.Draw(mask)
    md.text(xy, text, font=font, fill=255, anchor=anchor, stroke_width=2)
    glow_layer = Image.new("RGBA", IMAGE_SIZE, (*((glow or fill)), 0))
    glow_layer.putalpha(mask.filter(ImageFilter.GaussianBlur(12)).point(lambda value: min(170, value)))
    canvas.alpha_composite(glow_layer)
    draw = ImageDraw.Draw(canvas)
    draw.text((xy[0] + 3, xy[1] + 5), text, font=font, fill=(0, 0, 0, 150), anchor=anchor)
    draw.text(xy, text, font=font, fill=(*fill, 255), anchor=anchor, stroke_width=2, stroke_fill=(255, 255, 255, 95))


def draw_gradient_text(canvas: Image.Image, xy: tuple[int, int], text: str, font, top: tuple[int, int, int], bottom: tuple[int, int, int], anchor: str = "mm") -> None:
    mask = Image.new("L", IMAGE_SIZE, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255, anchor=anchor, stroke_width=1)
    gradient = linear_gradient(IMAGE_SIZE, (*top, 255), (*bottom, 255))
    shadow = mask.filter(ImageFilter.GaussianBlur(9))
    shadow_layer = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
    shadow_layer.putalpha(shadow.point(lambda value: min(145, value)))
    canvas.alpha_composite(shadow_layer)
    canvas.alpha_composite(Image.composite(gradient, Image.new("RGBA", IMAGE_SIZE), mask))


def emphasized_word(message: str) -> str | None:
    for word in message.split():
        clean = word.casefold().strip(".,!?:;—–()\"'")
        if clean in EMPHASIS_TERMS:
            return word.strip(".,!?:;—–()\"'")
    return None


def draw_semantic_message(draw: ImageDraw.ImageDraw, message: str, box: tuple[int, int, int, int], font, emphasis_font, fill: tuple[int, int, int, int], align: str = "center") -> None:
    left, top, right, bottom = box
    lines = wrap_text(draw, message, font, right - left)
    line_height = max(draw.textbbox((0, 0), "Ágj", font=font)[3], draw.textbbox((0, 0), "Ágj", font=emphasis_font)[3]) + 14
    y = top + max(0, ((bottom - top) - line_height * len(lines)) / 2)
    for line in lines:
        tokens = line.split()
        widths = [draw.textlength(token + (" " if i < len(tokens) - 1 else ""), font=emphasis_font if token.casefold().strip(".,!?:;—–()\"'") in EMPHASIS_TERMS else font) for i, token in enumerate(tokens)]
        total = sum(widths)
        x = left if align == "left" else right - total if align == "right" else (left + right - total) / 2
        for token, width in zip(tokens, widths):
            clean = token.casefold().strip(".,!?:;—–()\"'")
            active_font = emphasis_font if clean in EMPHASIS_TERMS else font
            color = (*EMPHASIS_TERMS.get(clean, fill[:3]), 255)
            draw.text((x + 3, y + 4), token, font=active_font, fill=(0, 0, 0, 150), stroke_width=2, stroke_fill=(0, 0, 0, 110))
            draw.text((x, y), token, font=active_font, fill=color, stroke_width=1, stroke_fill=(45, 25, 35, 155))
            x += width
        y += line_height


def render_artwork(
    background: Image.Image,
    category: str,
    message: str,
    style_id: int,
    palette_id: int,
    seed: str,
) -> Image.Image:
    style = CATEGORY_STYLES[category]
    title = str(style["title"])
    accents = [hex_rgb(value) for value in style["accent"]]
    accent = accents[palette_id % len(accents)]
    rng = random.Random(seed)
    canvas = background.copy()
    draw = ImageDraw.Draw(canvas)

    if style_id == 0:  # Aconchegante
        canvas = localized_gradient(canvas, (0, 420, 1080, 1080), (92, 42, 24), 175)
        warm = Image.new("RGBA", IMAGE_SIZE, (255, 170, 76, 32))
        canvas = Image.alpha_composite(canvas, warm)
        draw = ImageDraw.Draw(canvas)
        title_font = load_named_font("great_vibes", 146 if len(title) < 14 else 116)
        draw_gradient_text(canvas, (80, 155), title, title_font, (255, 250, 205), (226, 164, 60), anchor="la")
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("caveat", 57)
        emphasis_font = load_named_font("caveat", 70)
        draw_semantic_message(draw, message, (85, 620, 855, 990), body_font, emphasis_font, (255, 250, 235, 255), "left")
        for offset in (0, 28, 56):
            draw.arc((850 + offset // 2, 700 - offset, 990 - offset // 2, 880 - offset), 200, 335, fill=(255, 230, 180, 155), width=4)

    elif style_id == 1:  # Natureza limpa
        canvas = localized_gradient(canvas, (0, 0, 1080, 1080), (18, 54, 35), 132)
        draw = ImageDraw.Draw(canvas)
        title_font = load_named_font("playfair", 105 if len(title) < 14 else 88)
        draw_soft_text(draw, (72, 100), title, title_font, (255, 255, 245, 255), stroke=1)
        draw.line((72, 225, 410, 225), fill=(*accent, 220), width=4)
        body_font, lines = fit_with_candidates(draw, message, SERIF_FONT_CANDIDATES, 620, 6, 49)
        text_block(draw, lines, body_font, (72, 590, 700, 980), (255, 255, 248, 255), "left", gap=18)

    elif style_id == 2:  # Floral romântico — texto integrado, rosa luminoso
        canvas = localized_gradient(canvas, (0, 430, 1080, 1080), (78, 18, 43), 145)
        canvas = Image.alpha_composite(canvas, Image.new("RGBA", IMAGE_SIZE, (255, 188, 215, 28)))
        draw = ImageDraw.Draw(canvas)
        title_font = load_named_font("great_vibes", 156 if len(title) < 14 else 128)
        draw_glowing_text(canvas, (540, 170), title, title_font, (255, 92, 166), glow=(255, 78, 157))
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("caveat", 55)
        emphasis_font = load_named_font("caveat", 67)
        draw_semantic_message(draw, message, (155, 610, 925, 965), body_font, emphasis_font, (255, 247, 245, 255))

    elif style_id == 3:  # Fotográfico editorial
        canvas = localized_gradient(canvas, (0, 550, 1080, 1080), (0, 0, 0), 165)
        draw = ImageDraw.Draw(canvas)
        title_font = fit_title_with_candidates(draw, title.upper(), SANS_BOLD_FONT_CANDIDATES, 94, 860)
        draw_soft_text(draw, (540, 790), title.upper(), title_font, (255, 255, 255, 255), anchor="mm", stroke=1)
        body_font, lines = fit_with_candidates(draw, message, SANS_FONT_CANDIDATES, 820, 4, 43)
        text_block(draw, lines, body_font, (130, 860, 950, 1015), (255, 255, 255, 255), "center", gap=10)
        draw.rectangle((60, 60, 74, 350), fill=(*accent, 240))
        draw.text((95, 68), STYLE_NAMES[style_id].upper(), font=load_font(SANS_BOLD_FONT_CANDIDATES, 22), fill=(255, 255, 255, 210))

    elif style_id == 4:  # Elegante dourado
        canvas = localized_gradient(canvas, (0, 0, 1080, 1080), (20, 15, 30), 125)
        frame = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        gold = (242, 204, 105)
        fd.rounded_rectangle((50, 50, 1030, 1030), radius=18, outline=(*gold, 235), width=4)
        fd.rounded_rectangle((72, 72, 1008, 1008), radius=14, outline=(255, 255, 255, 125), width=2)
        for x, y in ((72, 72), (1008, 72), (72, 1008), (1008, 1008)):
            fd.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(*gold, 230))
        canvas = Image.alpha_composite(canvas, frame)
        draw = ImageDraw.Draw(canvas)
        title_font = load_named_font("great_vibes", 142 if len(title) < 14 else 112)
        draw_gradient_text(canvas, (540, 185), title, title_font, (255, 250, 205), (195, 132, 35))
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("playfair", 49)
        emphasis_font = load_named_font("playfair", 61)
        draw_semantic_message(draw, message, (180, 520, 900, 910), body_font, emphasis_font, (255, 252, 235, 255))
        draw.line((350, 325, 730, 325), fill=(*gold, 220), width=3)

    elif style_id == 5:  # Manuscrito afetivo — caligrafia diretamente na foto
        canvas = localized_gradient(canvas, (0, 360, 1080, 1080), (72, 28, 45), 145)
        decor = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        dd = ImageDraw.Draw(decor)
        for x, y in ((105, 155), (950, 910), (890, 130)):
            draw_heart(dd, x, y, 24, (255, 120, 160), 95)
        canvas = Image.alpha_composite(canvas, decor)
        title_font = load_named_font("great_vibes", 148 if len(title) < 14 else 118)
        draw_glowing_text(canvas, (540, 175), title, title_font, (255, 239, 213), glow=(255, 180, 125))
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("caveat", 58)
        emphasis_font = load_named_font("caveat", 72)
        draw_semantic_message(draw, message, (135, 600, 945, 965), body_font, emphasis_font, (255, 250, 232, 255))

    elif style_id == 6:  # Chamativo pop — título enorme e luz, sem faixa
        canvas = localized_gradient(canvas, (0, 510, 1080, 1080), (45, 17, 56), 175)
        canvas = Image.alpha_composite(canvas, Image.new("RGBA", IMAGE_SIZE, (*accent, 28)))
        draw = ImageDraw.Draw(canvas)
        title_font = fit_title_with_candidates(draw, title.upper(), SANS_CONDENSED_FONT_CANDIDATES, 154, 950)
        draw.text((545, 170), title.upper(), font=title_font, fill=(0, 0, 0, 145), anchor="mm", stroke_width=12, stroke_fill=(*accent, 80))
        draw.text((535, 158), title.upper(), font=title_font, fill=(*accent, 255), anchor="mm", stroke_width=4, stroke_fill=(255, 255, 255, 235))
        body_font = load_font(SANS_BOLD_FONT_CANDIDATES, 51)
        emphasis_font = load_font(SANS_CONDENSED_FONT_CANDIDATES, 67)
        draw_semantic_message(draw, message, (115, 680, 965, 1015), body_font, emphasis_font, (255, 255, 255, 255))

    elif style_id == 7:  # Ilustrado colorido — ornamentos leves, sem tarjas
        canvas = localized_gradient(canvas, (0, 430, 1080, 1080), (33, 26, 62), 150)
        art = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        ad = ImageDraw.Draw(art)
        blobs = [(255, 109, 170), (255, 203, 74), (132, 201, 255), (185, 126, 255)]
        for x, y, color in ((75, 85, blobs[0]), (1000, 100, blobs[1]), (90, 995, blobs[2]), (990, 970, blobs[3])):
            draw_flower(ad, x, y, 30, color, 175)
        canvas = Image.alpha_composite(canvas, art)
        title_font = load_named_font("great_vibes", 150 if len(title) < 14 else 120)
        draw_gradient_text(canvas, (540, 165), title, title_font, (255, 245, 145), (255, 84, 164))
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("caveat", 57)
        emphasis_font = load_named_font("caveat", 70)
        draw_semantic_message(draw, message, (150, 610, 930, 965), body_font, emphasis_font, (255, 255, 255, 255))

    elif style_id == 8:  # Fé delicada
        canvas = Image.alpha_composite(canvas, Image.new("RGBA", IMAGE_SIZE, (255, 245, 210, 45)))
        rays = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        rd = ImageDraw.Draw(rays)
        for angle in range(-70, 71, 14):
            radians = math.radians(angle)
            rd.polygon([(540, 60), (540 + math.sin(radians - 0.04) * 850, 60 + math.cos(radians - 0.04) * 850), (540 + math.sin(radians + 0.04) * 850, 60 + math.cos(radians + 0.04) * 850)], fill=(255, 230, 145, 28))
        canvas = Image.alpha_composite(canvas, rays)
        draw = ImageDraw.Draw(canvas)
        title_font = load_named_font("great_vibes", 142 if len(title) < 14 else 112)
        draw_glowing_text(canvas, (540, 175), title, title_font, (255, 246, 211), glow=(255, 214, 105))
        draw = ImageDraw.Draw(canvas)
        body_font = load_named_font("playfair", 51)
        emphasis_font = load_named_font("playfair", 64)
        draw_semantic_message(draw, message, (180, 550, 900, 945), body_font, emphasis_font, (255, 255, 245, 255))
        draw.line((510, 365, 570, 365), fill=(255, 225, 125, 225), width=5)
        draw.line((540, 335, 540, 410), fill=(255, 225, 125, 225), width=5)

    else:  # Motivacional moderno
        canvas = localized_gradient(canvas, (0, 0, 1080, 1080), (20, 24, 45), 145, vertical=False)
        draw = ImageDraw.Draw(canvas)
        words = message.rstrip(".!?").split()
        meaningful = emphasized_word(message)
        lead = (meaningful or next((word for word in words if len(word) >= 7), words[0])).upper()
        remainder = message
        small_title = fit_title_with_candidates(draw, title.upper(), SANS_BOLD_FONT_CANDIDATES, 58, 860)
        draw.text((75, 80), title.upper(), font=small_title, fill=(*accent, 255))
        lead_font = fit_title_with_candidates(draw, lead, SANS_CONDENSED_FONT_CANDIDATES, 122, 900)
        draw.text((75, 270), lead, font=lead_font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(20, 20, 30, 210))
        draw.rectangle((75, 420, 430, 433), fill=(*accent, 245))
        body_font, lines = fit_with_candidates(draw, remainder, SANS_BOLD_FONT_CANDIDATES, 720, 6, 50)
        text_block(draw, lines, body_font, (75, 500, 795, 930), (255, 255, 255, 255), "left")
        draw.text((75, 980), "ACREDITE • SIGA • COMPARTILHE", font=load_font(SANS_FONT_CANDIDATES, 25), fill=(*accent, 230))

    draw = ImageDraw.Draw(canvas)
    signature_font = load_font(SANS_FONT_CANDIDATES, 20)
    draw.text(
        (1022, 1045),
        "BomDiaWhats",
        font=signature_font,
        fill=(255, 255, 255, 215),
        anchor="rs",
        stroke_width=1,
        stroke_fill=(35, 25, 35, 165),
    )
    return canvas.convert("RGB")


def image_path(category: str, slot: int, images_root: Path = IMAGES_DIR) -> Path:
    return images_root / category / f"{category}_{slot}.jpg"


def save_artwork(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.jpg")
    image.save(temporary, "JPEG", quality=91, optimize=True, progressive=True, subsampling="4:2:0")
    temporary.replace(destination)


def artwork_signature(category: str, message: str, asset_id: str, layout: int, palette: int) -> str:
    raw = f"{category}|{message}|{asset_id}|{layout}|{palette}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def build_catalog(generated_at: str, images_root: Path = IMAGES_DIR) -> dict[str, object]:
    catalog: dict[str, object] = {"generated_at": generated_at}
    for category in CATEGORY_STYLES:
        catalog[category] = [
            f"{RAW_BASE_URL}/imagens/{category}/{category}_{slot}.jpg?v={file_version(image_path(category, slot, images_root))}"
            for slot in range(1, IMAGES_PER_CATEGORY + 1)
        ]
    return catalog


def make_category_mosaic(
    category: str,
    style_ids: list[int],
    images_root: Path = IMAGES_DIR,
    previews_root: Path = PREVIEWS_DIR,
) -> None:
    thumb_size = 324
    margin = 24
    label_height = 52
    canvas = Image.new("RGB", (margin * 4 + thumb_size * 3, margin * 5 + (thumb_size + label_height) * 4), "#F7F1E7")
    draw = ImageDraw.Draw(canvas)
    label_font = load_font(SERIF_BOLD_FONT_CANDIDATES, 24)
    for index in range(IMAGES_PER_CATEGORY):
        row, column = divmod(index, 3)
        image = Image.open(image_path(category, index + 1, images_root)).convert("RGB")
        image.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
        x = margin + column * (thumb_size + margin)
        y = margin + row * (thumb_size + label_height + margin)
        canvas.paste(image, (x, y))
        label = f"{index + 1}. {STYLE_NAMES[style_ids[index]]}"
        label_box = draw.textbbox((0, 0), label, font=label_font)
        label_width = label_box[2] - label_box[0]
        draw.text((x + (thumb_size - label_width) / 2, y + thumb_size + 10), label, font=label_font, fill="#49382B")
    previews_root.mkdir(parents=True, exist_ok=True)
    canvas.save(previews_root / f"mosaico-{category}.jpg", "JPEG", quality=91, optimize=True)


def merge_recent(new_values: list[str], previous: list[str], limit: int) -> list[str]:
    merged = list(dict.fromkeys((*new_values, *previous)))
    return merged if limit <= 0 else merged[:limit]


def write_attributions(path: Path, credits: dict[str, object]) -> None:
    lines = [
        "# Créditos fotográficos do lote atual",
        "",
        "As obras CC BY exigem atribuição. Ao compartilhar uma arte, envie também o crédito correspondente.",
        "",
    ]
    categories = credits.get("categories", {})
    for category, entries in categories.items():
        lines.extend((f"## {CATEGORY_STYLES[category]['title']}", ""))
        for entry in entries:
            if entry.get("attribution_required"):
                lines.append(f"- {entry['file']}: {entry['share_credit']}")
        if lines[-1] != "":
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def validate_staged_batch(
    images_root: Path,
    catalog: dict[str, object],
    credits: dict[str, object],
    history: dict[str, object],
) -> None:
    all_assets: list[str] = []
    all_signatures: list[str] = []
    for category in CATEGORY_STYLES:
        urls = catalog.get(category)
        entries = credits.get("categories", {}).get(category, [])
        if not isinstance(urls, list) or len(urls) != IMAGES_PER_CATEGORY:
            raise RuntimeError(f"Catálogo incompleto para {category}.")
        if len(entries) != IMAGES_PER_CATEGORY:
            raise RuntimeError(f"Créditos incompletos para {category}.")
        if len({entry["style_id"] for entry in entries}) != STYLE_COUNT:
            raise RuntimeError(f"Estilos incompletos para {category}.")
        for slot in range(1, IMAGES_PER_CATEGORY + 1):
            path = image_path(category, slot, images_root)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.size != IMAGE_SIZE or image.format != "JPEG":
                    raise RuntimeError(f"Imagem inválida: {path}")
        all_assets.extend(str(entry["asset_id"]) for entry in entries)
        all_signatures.extend(str(entry["art_signature"]) for entry in entries)
    if len(set(all_assets)) != len(all_assets):
        raise RuntimeError("O lote contém fundos repetidos.")
    if len(set(all_signatures)) != len(all_signatures):
        raise RuntimeError("O lote contém artes repetidas.")
    if history.get("last_generation") is None:
        raise RuntimeError("Histórico sem data de geração.")


def recover_interrupted_transaction() -> None:
    if not TRANSACTION_FILE.exists():
        return
    state = json.loads(TRANSACTION_FILE.read_text(encoding="utf-8"))
    if state.get("status") == "promoted":
        TRANSACTION_FILE.unlink(missing_ok=True)
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
        return
    existing = set(state.get("existing", []))
    for name in state.get("targets", []):
        target = REPO_ROOT / name
        backup = BACKUP_DIR / name
        if backup.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.replace(target)
        elif name not in existing and target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()
    TRANSACTION_FILE.unlink(missing_ok=True)
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    shutil.rmtree(BACKUP_DIR, ignore_errors=True)


def promote_staged_batch() -> None:
    targets = [
        "imagens", "previews", "index.json", "image-credits.json",
        "ATTRIBUTIONS.md", ".github/generation-history.json",
        ".github/background-reserve.json", ".github/background-reserve-files",
    ]
    shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    BACKUP_DIR.mkdir(parents=True)
    existing = [name for name in targets if (REPO_ROOT / name).exists()]
    write_json_atomic(TRANSACTION_FILE, {"status": "promoting", "targets": targets, "existing": existing})
    try:
        for name in targets:
            staged = STAGING_DIR / name
            if not staged.exists():
                raise RuntimeError(f"Saída ausente no staging: {name}")
        for name in existing:
            target = REPO_ROOT / name
            backup = BACKUP_DIR / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.replace(backup)
        for name in targets:
            target = REPO_ROOT / name
            staged = STAGING_DIR / name
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(target)
        write_json_atomic(TRANSACTION_FILE, {"status": "promoted", "targets": targets, "existing": existing})
    except Exception:
        recover_interrupted_transaction()
        raise
    TRANSACTION_FILE.unlink(missing_ok=True)
    shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    shutil.rmtree(STAGING_DIR, ignore_errors=True)


def load_generation_checkpoint(
    reference_date: date, categories: list[str]
) -> dict[str, object] | None:
    if not CHECKPOINT_FILE.exists():
        return None
    try:
        checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        checkpoint.get("version") != 1
        or checkpoint.get("reference_date") != reference_date.isoformat()
        or checkpoint.get("categories") != categories
    ):
        return None
    return checkpoint


def save_generation_checkpoint(
    reference_date: date,
    categories: list[str],
    completed_categories: list[str],
    generated_at: str,
    credits: dict[str, object],
    next_history: dict[str, object],
    style_assignments: dict[str, list[int]],
    blocked_assets: set[str],
) -> None:
    write_json_atomic(
        CHECKPOINT_FILE,
        {
            "version": 1,
            "reference_date": reference_date.isoformat(),
            "categories": categories,
            "completed_categories": completed_categories,
            "generated_at": generated_at,
            "credits": credits,
            "next_history": next_history,
            "style_assignments": style_assignments,
            "blocked_assets": sorted(blocked_assets),
            "blocked_fingerprints": sorted(_BLOCKED_FINGERPRINTS),
            "discovered_reserve": _DISCOVERED_RESERVE,
        },
    )


def generate(reference_date: date, initialize_all: bool = False) -> None:
    global _RESERVE_POOL, _DISCOVERED_RESERVE, _BLOCKED_FINGERPRINTS
    recover_interrupted_transaction()
    categories_to_generate = active_categories(reference_date, initialize_all)
    checkpoint = load_generation_checkpoint(reference_date, categories_to_generate)
    staging_images = STAGING_DIR / "imagens"
    staging_previews = STAGING_DIR / "previews"
    if checkpoint is None:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        if IMAGES_DIR.exists():
            shutil.copytree(IMAGES_DIR, staging_images, dirs_exist_ok=True)
        else:
            staging_images.mkdir(parents=True)
        if PREVIEWS_DIR.exists():
            shutil.copytree(PREVIEWS_DIR, staging_previews, dirs_exist_ok=True)
        staged_reserve = STAGING_DIR / ".github" / "background-reserve-files"
        if LOCAL_RESERVE_DIR.exists():
            shutil.copytree(LOCAL_RESERVE_DIR, staged_reserve, dirs_exist_ok=True)
        else:
            staged_reserve.mkdir(parents=True, exist_ok=True)
    else:
        print(
            "Retomando staging validado por checkpoint: "
            f"{len(checkpoint.get('completed_categories', []))} categorias completas."
        )

    _RESERVE_POOL = load_reserve()
    _DISCOVERED_RESERVE = {}
    _BLOCKED_FINGERPRINTS = set()
    messages = load_messages()
    history = load_history()
    previous_categories = history.get("categories", {})
    if not isinstance(previous_categories, dict):
        previous_categories = {}

    previous_credits: dict[str, object] = {}
    if CREDITS_FILE.exists():
        with CREDITS_FILE.open(encoding="utf-8") as handle:
            loaded_credits = json.load(handle)
        previous_credits = loaded_credits.get("categories", {})

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
    session.headers["User-Agent"] = "BomDiaWhats thematic image generator/6.0 (zflipks)"
    authenticated = configure_openverse_auth(session)
    print("Openverse: " + ("autenticado" if authenticated else "acesso anônimo"))

    blocked_assets: set[str] = set()
    for entry in previous_categories.values():
        if isinstance(entry, dict):
            blocked_assets.update(str(value) for value in entry.get("recent_asset_ids", []))
            _BLOCKED_FINGERPRINTS.update(
                str(value) for value in entry.get("recent_content_fingerprints", [])
            )

    next_history = json.loads(json.dumps(history))
    next_history["version"] = 3
    next_history["last_generation"] = reference_date.isoformat()
    next_history.setdefault("categories", {})
    next_history["generated_categories"] = categories_to_generate

    style_assignments: dict[str, list[int]] = {}
    completed_categories: list[str] = []
    credits: dict[str, object] = {
        "generated_at": generated_at,
        "source": "Openverse API — preferência CC0/PDM, aceitando CC BY com atribuição",
        "license_notice": (
            "Openverse indexa metadados e não garante direitos de imagem, marcas, propriedade "
            "ou exatidão da licença. A página de origem deve ser preservada para auditoria."
        ),
        "categories": dict(previous_credits) if isinstance(previous_credits, dict) else {},
    }
    if checkpoint is not None:
        generated_at = str(checkpoint["generated_at"])
        credits = checkpoint["credits"]
        next_history = checkpoint["next_history"]
        style_assignments = {
            str(key): [int(value) for value in values]
            for key, values in checkpoint.get("style_assignments", {}).items()
        }
        completed_categories = [
            str(value) for value in checkpoint.get("completed_categories", [])
        ]
        blocked_assets.update(
            str(value) for value in checkpoint.get("blocked_assets", [])
        )
        _BLOCKED_FINGERPRINTS.update(
            str(value) for value in checkpoint.get("blocked_fingerprints", [])
        )
        _DISCOVERED_RESERVE = {
            str(key): value
            for key, value in checkpoint.get("discovered_reserve", {}).items()
        }

    print(
        f"Lote {reference_date.isoformat()}: {len(categories_to_generate)} categorias, "
        f"{len(categories_to_generate) * IMAGES_PER_CATEGORY} imagens"
    )
    for category in categories_to_generate:
        if category in completed_categories:
            print(f"{category}: reutilizando categoria completa do checkpoint")
            continue
        previous = previous_categories.get(category, {})
        if not isinstance(previous, dict):
            previous = {}
        rng = random.Random(f"styles:{category}:{reference_date.isoformat()}")
        style_ids = CATEGORY_STYLE_ORDER[category].copy()
        if rng.randrange(2):
            style_ids[0:5], style_ids[5:10] = style_ids[5:10], style_ids[0:5]
        selected = choose_messages(
            messages[category],
            [str(value) for value in previous.get("recent_messages", [])],
            category,
            reference_date,
            style_ids,
        )
        palettes = [rng.randrange(3) for _ in range(IMAGES_PER_CATEGORY)]
        style_assignments[category] = style_ids

        asset_ids: list[str] = []
        signatures: list[str] = []
        category_credits: list[dict[str, object]] = []
        recent_signatures = set(str(value) for value in previous.get("recent_art_signatures", []))

        print(f"{category}: gerando {IMAGES_PER_CATEGORY} cartões temáticos")
        for slot, message in enumerate(selected, 1):
            background, metadata = fetch_thematic_background(
                session, category, slot, reference_date, blocked_assets
            )
            asset_id = str(metadata["asset_id"])
            style_id = style_ids[slot - 1]
            palette_id = palettes[slot - 1]
            signature = artwork_signature(category, message, asset_id, style_id, palette_id)
            if signature in recent_signatures:
                raise RuntimeError(f"Assinatura completa repetida em {category}, slot {slot}.")

            artwork = render_artwork(
                prepare_background(background, category, style_id),
                category,
                message,
                style_id,
                palette_id,
                signature,
            )
            destination = image_path(category, slot, staging_images)
            save_artwork(artwork, destination)
            blocked_assets.add(asset_id)
            _BLOCKED_FINGERPRINTS.add(str(metadata["content_fingerprint"]))
            asset_ids.append(asset_id)
            signatures.append(signature)
            category_credits.append({
                "slot": slot,
                "file": f"imagens/{category}/{category}_{slot}.jpg",
                "message": message,
                "style_id": style_id + 1,
                "style": STYLE_NAMES[style_id],
                "palette": palette_id + 1,
                "art_signature": signature,
                **metadata,
            })
            print(
                f"  criado: imagens/{category}/{category}_{slot}.jpg — "
                f"{metadata['theme']} — {STYLE_NAMES[style_id]}"
            )

        next_history["categories"][category] = {
            "recent_messages": merge_recent(
                selected, [str(v) for v in previous.get("recent_messages", [])], 300
            ),
            "recent_asset_ids": merge_recent(
                asset_ids, [str(v) for v in previous.get("recent_asset_ids", [])], HISTORY_ASSET_LIMIT
            ),
            "recent_art_signatures": merge_recent(
                signatures, [str(v) for v in previous.get("recent_art_signatures", [])], HISTORY_ART_LIMIT
            ),
            "recent_content_fingerprints": merge_recent(
                [str(entry["content_fingerprint"]) for entry in category_credits],
                [str(v) for v in previous.get("recent_content_fingerprints", [])],
                HISTORY_ASSET_LIMIT,
            ),
        }
        credits["categories"][category] = category_credits
        completed_categories.append(category)
        save_generation_checkpoint(
            reference_date,
            categories_to_generate,
            completed_categories,
            generated_at,
            credits,
            next_history,
            style_assignments,
            blocked_assets,
        )
        print(f"{category}: checkpoint salvo após 10 imagens válidas")

    catalog = build_catalog(generated_at, staging_images)
    reserve_by_id = {
        str(entry["asset_id"]): entry
        for entry in (*_RESERVE_POOL, *_DISCOVERED_RESERVE.values())
        if str(entry.get("asset_id")) not in blocked_assets
    }
    reserve = {
        "version": 2,
        "updated_at": generated_at,
        "notice": "Reserva temática licenciada; cada URL é revalidada antes do uso.",
        "entries": list(reserve_by_id.values())[:RESERVE_LIMIT],
    }

    mosaic_categories = tuple(CATEGORY_STYLES)
    for category in mosaic_categories:
        if category in style_assignments:
            make_category_mosaic(
                category, style_assignments[category], staging_images, staging_previews
            )

    write_json_atomic(STAGING_DIR / "index.json", catalog)
    write_json_atomic(STAGING_DIR / "image-credits.json", credits)
    write_json_atomic(STAGING_DIR / ".github" / "generation-history.json", next_history)
    write_json_atomic(STAGING_DIR / ".github" / "background-reserve.json", reserve)
    write_attributions(STAGING_DIR / "ATTRIBUTIONS.md", credits)
    validate_staged_batch(staging_images, catalog, credits, next_history)
    promote_staged_batch()
    total = len(categories_to_generate) * IMAGES_PER_CATEGORY
    print(
        f"Concluído: {total} imagens de {len(categories_to_generate)} categorias "
        "validadas e promovidas atomicamente."
    )

def main() -> None:
    args = parse_args()
    generate(args.date, args.initialize_all)


if __name__ == "__main__":
    main()
