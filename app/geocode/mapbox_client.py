from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class MapboxClient:
    BASE_URL = "https://api.mapbox.com/search/geocode/v6/forward"

    def __init__(
        self,
        access_token: str,
        *,
        permanent: bool = True,
        timeout_seconds: int = 10,
    ) -> None:
        self.access_token = access_token
        self.permanent = permanent
        self.timeout_seconds = timeout_seconds

    def geocode(
        self,
        query: str,
        *,
        country: str | None = None,
        bbox: str | None = None,
    ) -> dict | None:
        if not query.strip():
            return None

        params = {
            "q": query,
            "access_token": self.access_token,
            "limit": 1,
        }
        if self.permanent:
            params["permanent"] = "true"
        if country:
            params["country"] = country
        if bbox:
            params["bbox"] = bbox

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("Mapbox geocoding request failed")
            return None

        payload = response.json()
        features = payload.get("features") or []
        if not features:
            return None

        feature = features[0]
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        lng = coordinates[0] if len(coordinates) > 0 else None
        lat = coordinates[1] if len(coordinates) > 1 else None

        return {
            "lat": lat,
            "lng": lng,
            "feature": feature,
            "confidence": _extract_confidence(feature),
        }


def _extract_confidence(feature: dict) -> float:
    properties = feature.get("properties") or {}
    match_code = properties.get("match_code") or {}

    for key in ("confidence", "match_confidence"):
        value = match_code.get(key)
        parsed = _to_confidence_float(value)
        if parsed is not None:
            return parsed

    parsed = _to_confidence_float(properties.get("confidence"))
    if parsed is not None:
        return parsed

    accuracy = properties.get("coordinates", {}).get("accuracy")
    if isinstance(accuracy, str):
        accuracy = accuracy.lower()
        if accuracy in {"rooftop", "parcel", "point"}:
            return 0.95
        if accuracy in {"interpolated", "street"}:
            return 0.8
        if accuracy in {"place", "city"}:
            return 0.6

    return 0.5


def _to_confidence_float(value: object) -> float | None:
    if isinstance(value, (float, int)):
        numeric = float(value)
        if 0 <= numeric <= 1:
            return numeric

    if isinstance(value, str):
        lowered = value.strip().lower()
        named = {
            "exact": 1.0,
            "high": 0.9,
            "medium": 0.7,
            "low": 0.4,
        }
        if lowered in named:
            return named[lowered]

        try:
            numeric = float(lowered)
        except ValueError:
            return None

        if 0 <= numeric <= 1:
            return numeric

    return None
