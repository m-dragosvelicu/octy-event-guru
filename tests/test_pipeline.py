from datetime import UTC

from app.domain.models import ExtractedEvent, NormalizedEvent
from app.extract.normalize import normalize_event
from app.geocode.scoring import passes_precision_gate, score_geocode
from app.sink.dedupe import build_external_event_id, dedupe_in_batch


def test_normalize_event_requires_minimum_fields() -> None:
    event = ExtractedEvent(
        area_id="area-1",
        provider="source_a",
        sport_hint="running",
        source_url="https://example.com/events/1",
        title="Morning Run",
        start_time_text="2026-03-02 08:00",
        location_name=None,
        location_address=None,
    )

    normalized = normalize_event(event)

    assert normalized is None


def test_normalize_event_parses_datetime_to_utc() -> None:
    event = ExtractedEvent(
        area_id="area-1",
        provider="source_a",
        sport_hint="running",
        source_url="https://example.com/events/1",
        title="Morning Run",
        description="Weekly run",
        start_time_text="2026-03-02 08:00 UTC",
        location_name="Central Park",
        location_address="59th St, New York, NY 10022",
    )

    normalized = normalize_event(event)

    assert normalized is not None
    assert normalized.start_time.tzinfo == UTC
    assert normalized.title == "Morning Run"


def test_build_external_event_id_prefers_canonical_id() -> None:
    event = NormalizedEvent(
        area_id="area-1",
        provider="source_a",
        sport_hint="running",
        source_url="https://example.com/events/1",
        title="Morning Run",
        description=None,
        start_time="2026-03-02T08:00:00+00:00",
        end_time=None,
        location_name="Central Park",
        location_address="59th St, New York, NY",
        location_text="Central Park - 59th St, New York, NY",
        canonical_id=" EVENT-123 ",
    )

    assert build_external_event_id(event) == "event-123"


def test_dedupe_in_batch_removes_duplicate_events() -> None:
    event_1 = NormalizedEvent(
        area_id="area-1",
        provider="source_a",
        sport_hint="running",
        source_url="https://example.com/events/1",
        title="Morning Run",
        description=None,
        start_time="2026-03-02T08:00:00+00:00",
        end_time=None,
        location_name="Central Park",
        location_address="59th St, New York, NY",
        location_text="Central Park - 59th St, New York, NY",
        external_event_id="shared-id",
    )
    event_2 = event_1.model_copy(deep=True)

    unique_events, duplicates = dedupe_in_batch([event_1, event_2])

    assert len(unique_events) == 1
    assert duplicates == 1


def test_precision_gate_respects_threshold() -> None:
    geocode_result = {
        "confidence": 0.9,
        "feature": {
            "properties": {
                "full_address": "59th St, New York, NY 10022",
            }
        },
    }

    score = score_geocode("59th St, New York, NY 10022", geocode_result)

    assert passes_precision_gate(score, threshold=0.75)
