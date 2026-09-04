import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.schemas import BuyerIntent


PRICE_PATTERNS = (
    re.compile(r"(?:under|below|less than|upto|up to|max(?:imum)?)\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:or less|and below|budget)", re.IGNORECASE),
)
MIN_PRICE_PATTERN = re.compile(r"(?:above|over|more than|min(?:imum)?|at least)\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
QUANTITY_PATTERN = re.compile(r"\b([1-9][0-9]*)\s*(?:x\s*)?(?:pieces?|pcs?|items?|units?|pairs?)\b", re.IGNORECASE)
PRODUCT_QUANTITY_PATTERN = re.compile(r"\b(?:need|want|show me|get|buy)\s+([1-9][0-9]*)\s+(?!hours?\b|hrs?\b)", re.IGNORECASE)
BATTERY_PATTERN = re.compile(r"(?:at least|min(?:imum)?|over|more than)?\s*([0-9]{1,3})\s*(?:hours?|hrs?)\s*battery", re.IGNORECASE)

KNOWN_CATEGORIES = {
    "headphone": "headphones",
    "headphones": "headphones",
    "earphone": "headphones",
    "earphones": "headphones",
    "earbuds": "headphones",
    "shirt": "Apparel",
    "t-shirt": "Apparel",
    "tee": "Apparel",
    "tote": "Accessories",
    "bag": "Accessories",
    "phone": "phones",
    "laptop": "laptops",
    "shoes": "shoes",
}
COLORS = {"black", "white", "blue", "red", "green", "yellow", "grey", "gray", "silver", "gold", "natural", "brown"}
SIZES = {"xs", "s", "m", "l", "xl", "xxl", "small", "medium", "large"}
STOPWORDS = {
    "i",
    "need",
    "want",
    "looking",
    "for",
    "show",
    "me",
    "that",
    "are",
    "is",
    "a",
    "an",
    "the",
    "with",
    "good",
    "best",
    "cheap",
    "cheapest",
    "affordable",
    "detail",
    "details",
    "of",
    "available",
    "now",
    "in",
    "stock",
    "under",
    "below",
    "less",
    "than",
    "rs",
    "inr",
    "and",
    "or",
    "at",
    "least",
}


@dataclass
class AIProvider:
    name: str = "deterministic-fallback"

    def extract_intent(self, message: str) -> BuyerIntent:
        raise NotImplementedError


class DeterministicFallbackProvider(AIProvider):
    def __init__(self):
        super().__init__(name="deterministic-fallback")

    def extract_intent(self, message: str) -> BuyerIntent:
        parser = FallbackIntentParser()
        return parser.parse(message)


class IntentExtractor:
    def __init__(self, provider: AIProvider | None = None):
        self.provider = provider or DeterministicFallbackProvider()

    def extract(self, message: str) -> BuyerIntent:
        try:
            return self.provider.extract_intent(message)
        except Exception:
            return BuyerIntent(
                intent="product_search",
                query=clean_query(message),
                requires_in_stock=True,
            )


class FallbackIntentParser:
    def parse(self, message: str) -> BuyerIntent:
        normalized = normalize_message(message)
        max_price = first_decimal(patterns=PRICE_PATTERNS, message=normalized)
        min_price = first_decimal(patterns=(MIN_PRICE_PATTERN,), message=normalized)
        category = extract_category(normalized)
        brand = extract_brand(normalized)
        color = extract_token(normalized, COLORS)
        size = extract_token(normalized, SIZES)
        quantity = extract_quantity(normalized)
        requires_in_stock = extract_stock_requirement(normalized)
        features = extract_features(normalized)
        battery_hours = first_int(BATTERY_PATTERN, normalized)

        attributes: dict = {"features": features}
        if color:
            attributes["color"] = color
        if size:
            attributes["size"] = size
        if "wireless" in normalized:
            attributes["connectivity"] = "wireless"
        if battery_hours is not None:
            attributes["battery_life_hours_min"] = battery_hours

        return BuyerIntent(
            intent="product_search",
            query=clean_query(normalized),
            category=category,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            attributes=attributes,
            quantity=quantity,
            requires_in_stock=requires_in_stock,
        )


def normalize_message(message: str) -> str:
    return " ".join(message.replace("₹", " ₹").lower().strip().split())


def first_decimal(patterns: tuple[re.Pattern[str], ...], message: str) -> Decimal | None:
    for pattern in patterns:
        match = pattern.search(message)
        if match:
            try:
                return Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:
                return None
    return None


def first_int(pattern: re.Pattern[str], message: str) -> int | None:
    match = pattern.search(message)
    return int(match.group(1)) if match else None


def extract_quantity(message: str) -> int:
    match = QUANTITY_PATTERN.search(message)
    if match:
        return int(match.group(1))
    match = PRODUCT_QUANTITY_PATTERN.search(message)
    return int(match.group(1)) if match else 1


def extract_category(message: str) -> str | None:
    for token, category in KNOWN_CATEGORIES.items():
        if re.search(rf"\b{re.escape(token)}\b", message):
            return category
    return None


def extract_brand(message: str) -> str | None:
    match = re.search(r"\bbrand\s+([a-z0-9][a-z0-9 -]{1,40})", message)
    return match.group(1).strip() if match else None


def extract_token(message: str, values: set[str]) -> str | None:
    for value in values:
        if re.search(rf"\b{re.escape(value)}\b", message):
            return value
    return None


def extract_stock_requirement(message: str) -> bool:
    if any(phrase in message for phrase in ("in stock", "available", "available now", "ready to ship")):
        return True
    if any(phrase in message for phrase in ("out of stock", "include unavailable", "any availability")):
        return False
    return True


def extract_features(message: str) -> list[str]:
    features: list[str] = []
    if "good battery" in message or "battery life" in message:
        features.append("good battery life")
    if "cheap" in message or "affordable" in message:
        features.append("affordable")
    if "wireless" in message:
        features.append("wireless")
    return features


def clean_query(message: str) -> str:
    text = re.sub(r"(?:rs\.?|inr|₹)?\s*[0-9][0-9,]*(?:\.[0-9]+)?", " ", message.lower())
    text = re.sub(r"\b(?:under|below|less than|upto|up to|max(?:imum)?|above|over|more than|min(?:imum)?|at least)\b", " ", text)
    words = [word.strip(".,!?") for word in text.split()]
    meaningful = [word for word in words if word and word not in STOPWORDS and not word.isdigit()]
    return " ".join(meaningful[:8])
