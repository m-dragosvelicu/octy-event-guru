from app.domain.models import RawPage
from app.extract.jsonld import parse_jsonld_events


def test_parse_jsonld_events_extracts_event_fields() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Event",
          "name": "Bucharest Night Run",
          "startDate": "2026-03-10T18:00:00+02:00",
          "location": {
            "@type": "Place",
            "name": "Parcul Herastrau",
            "address": {
              "@type": "PostalAddress",
              "streetAddress": "Sos. Kiseleff 32",
              "addressLocality": "Bucharest",
              "addressCountry": "RO"
            },
            "geo": {
              "@type": "GeoCoordinates",
              "latitude": 44.47211,
              "longitude": 26.08507
            }
          },
          "url": "/events/bucharest-night-run"
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    page = RawPage(
        area_id="bucharest",
        provider="test",
        sport_hint="running",
        url="https://example.com/calendar",
        html=html,
    )

    events = parse_jsonld_events(page)

    assert len(events) == 1
    event = events[0]
    assert event.title == "Bucharest Night Run"
    assert event.start_time_text == "2026-03-10T18:00:00+02:00"
    assert event.location_name == "Parcul Herastrau"
    assert event.location_address == "Sos. Kiseleff 32, Bucharest, RO"
    assert event.source_url == "https://example.com/events/bucharest-night-run"
