"""Unit tests for the date_only time contract in normalization."""
from app.domain.models import ExtractedEvent
from app.extract.normalize import _is_date_only, normalize_event


def test_is_date_only_with_date_string() -> None:
    assert _is_date_only("2026-06-15") is True


def test_is_date_only_with_datetime_string() -> None:
    assert _is_date_only("2026-06-15T20:00:00+03:00") is False


def test_is_date_only_with_datetime_utc() -> None:
    assert _is_date_only("2026-06-15T20:00:00Z") is False


def test_is_date_only_with_padded_date() -> None:
    assert _is_date_only("  2026-06-15  ") is True


def test_normalize_sets_date_only_true_for_date_input() -> None:
    event = ExtractedEvent(
        area_id="test",
        provider="test-provider",
        sport_hint=None,
        source_url="https://example.com/e/1",
        title="Summer Festival",
        start_time_text="2026-06-15",
        location_name="Central Park",
        location_address="New York",
        location_lat=40.785091,
        location_lng=-73.968285,
    )

    result = normalize_event(event, timezone_name="America/New_York")
    assert result is not None
    assert result.date_only is True


def test_normalize_sets_date_only_false_for_datetime_input() -> None:
    event = ExtractedEvent(
        area_id="test",
        provider="test-provider",
        sport_hint=None,
        source_url="https://example.com/e/2",
        title="Evening Concert",
        start_time_text="2026-06-15T20:00:00+03:00",
        location_name="Arena Hall",
        location_address="Bucharest",
        location_lat=44.4268,
        location_lng=26.1025,
    )

    result = normalize_event(event, timezone_name="Europe/Bucharest")
    assert result is not None
    assert result.date_only is False
