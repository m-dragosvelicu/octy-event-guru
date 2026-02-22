from __future__ import annotations

from urllib.parse import urljoin

import extruct

from ..domain.models import ExtractedEvent, RawPage


def _iterate_jsonld_nodes(document: object):
    if isinstance(document, list):
        for item in document:
            yield from _iterate_jsonld_nodes(item)
        return

    if not isinstance(document, dict):
        return

    yield document

    graph = document.get("@graph")
    if isinstance(graph, list):
        for node in graph:
            yield from _iterate_jsonld_nodes(node)


def _type_contains_event(node_type: object) -> bool:
    if isinstance(node_type, str):
        return node_type.lower() == "event"
    if isinstance(node_type, list):
        return any(isinstance(item, str) and item.lower() == "event" for item in node_type)
    return False


def _extract_identifier(node: dict) -> str | None:
    identifier = node.get("identifier")
    if isinstance(identifier, str):
        return identifier
    if isinstance(identifier, dict):
        for key in ("value", "@id"):
            value = identifier.get(key)
            if isinstance(value, str):
                return value

    node_id = node.get("@id")
    if isinstance(node_id, str):
        return node_id

    return None


def _extract_address(location: object) -> tuple[str | None, str | None]:
    if isinstance(location, str):
        return location, location

    if not isinstance(location, dict):
        return None, None

    location_name = location.get("name") if isinstance(location.get("name"), str) else None
    address = location.get("address")

    if isinstance(address, str):
        return location_name, address

    if isinstance(address, dict):
        address_parts = [
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("postalCode"),
            address.get("addressCountry"),
        ]
        compact_address = ", ".join(part.strip() for part in address_parts if isinstance(part, str) and part.strip())
        return location_name, compact_address or None

    return location_name, None


def parse_jsonld_events(raw_page: RawPage) -> list[ExtractedEvent]:
    try:
        extracted = extruct.extract(
            raw_page.html,
            base_url=raw_page.url,
            syntaxes=["json-ld"],
            uniform=True,
        )
    except Exception:
        return []

    events: list[ExtractedEvent] = []
    jsonld_documents = extracted.get("json-ld", [])

    for document in jsonld_documents:
        for node in _iterate_jsonld_nodes(document):
            if not _type_contains_event(node.get("@type")):
                continue

            location_name, location_address = _extract_address(node.get("location"))
            source_url = node.get("url") if isinstance(node.get("url"), str) else raw_page.url
            canonical_id = _extract_identifier(node)

            events.append(
                ExtractedEvent(
                    area_id=raw_page.area_id,
                    provider=raw_page.provider,
                    sport_hint=raw_page.sport_hint,
                    source_url=urljoin(raw_page.url, source_url),
                    title=node.get("name") if isinstance(node.get("name"), str) else None,
                    description=node.get("description") if isinstance(node.get("description"), str) else None,
                    start_time_text=node.get("startDate") if isinstance(node.get("startDate"), str) else None,
                    end_time_text=node.get("endDate") if isinstance(node.get("endDate"), str) else None,
                    location_name=location_name,
                    location_address=location_address,
                    canonical_id=canonical_id,
                )
            )

    return events
