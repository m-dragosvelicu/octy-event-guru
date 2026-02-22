import re

_STREET_TOKEN_RE = re.compile(
    r"\b(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|ct|court|way|pl|place)\b",
    re.IGNORECASE,
)


def score_geocode(location_text: str, geocode_result: dict | None) -> float:
    if not geocode_result:
        return 0.0

    feature = geocode_result.get("feature") or {}
    full_address = _best_full_address(feature)

    address_score = 1.0 if _has_full_street_address(location_text) else 0.0
    city_postal_score = 1.0 if _city_or_postal_matches(location_text, full_address) else 0.0

    confidence = geocode_result.get("confidence")
    confidence_score = confidence if isinstance(confidence, (float, int)) else 0.0
    confidence_score = max(0.0, min(1.0, float(confidence_score)))

    weighted_score = (0.4 * address_score) + (0.2 * city_postal_score) + (0.4 * confidence_score)
    return max(0.0, min(1.0, weighted_score))


def passes_precision_gate(score: float, threshold: float = 0.75) -> bool:
    return score >= threshold


def _has_full_street_address(location_text: str) -> bool:
    has_number = any(char.isdigit() for char in location_text)
    has_street_keyword = bool(_STREET_TOKEN_RE.search(location_text))
    return has_number and has_street_keyword


def _best_full_address(feature: dict) -> str:
    properties = feature.get("properties") or {}

    for key in ("full_address", "place_formatted", "name"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.lower()

    place_name = feature.get("place_name")
    if isinstance(place_name, str):
        return place_name.lower()

    return ""


def _city_or_postal_matches(location_text: str, full_address: str) -> bool:
    lowered_location = location_text.lower()

    postal_candidates = re.findall(r"\b\d{5}(?:-\d{4})?\b", lowered_location)
    if postal_candidates and any(postal in full_address for postal in postal_candidates):
        return True

    tokens = [token for token in re.findall(r"[a-z]{3,}", lowered_location) if token not in {"street", "avenue", "road", "boulevard", "drive", "lane", "court", "place"}]
    return any(token in full_address for token in tokens)
