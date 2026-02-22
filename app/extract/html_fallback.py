from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..domain.models import ExtractedEvent, RawPage


def _pick_text(node: Tag, selector: str | None) -> str | None:
    if not selector:
        return None

    selected = node.select_one(selector)
    if selected is None:
        return None

    content = selected.get_text(" ", strip=True)
    return content or None


def _pick_link(node: Tag, selector: str | None, base_url: str) -> str:
    if not selector:
        return base_url

    selected = node.select_one(selector)
    if selected is None:
        return base_url

    href = selected.get("href")
    if not isinstance(href, str) or not href.strip():
        return base_url

    return urljoin(base_url, href.strip())


def parse_html_events(raw_page: RawPage, selectors: dict[str, str]) -> list[ExtractedEvent]:
    item_selector = selectors.get("item")
    if not item_selector:
        return []

    soup = BeautifulSoup(raw_page.html, "html.parser")
    events: list[ExtractedEvent] = []

    for item in soup.select(item_selector):
        start_node = item.select_one(selectors.get("start_time", "")) if selectors.get("start_time") else None
        end_node = item.select_one(selectors.get("end_time", "")) if selectors.get("end_time") else None

        start_time = None
        if start_node is not None:
            start_time = start_node.get("datetime") or start_node.get_text(" ", strip=True)

        end_time = None
        if end_node is not None:
            end_time = end_node.get("datetime") or end_node.get_text(" ", strip=True)

        canonical_id = item.get("data-event-id")
        if not isinstance(canonical_id, str):
            canonical_id = None

        events.append(
            ExtractedEvent(
                area_id=raw_page.area_id,
                provider=raw_page.provider,
                sport_hint=raw_page.sport_hint,
                source_url=_pick_link(item, selectors.get("link"), raw_page.url),
                title=_pick_text(item, selectors.get("title")),
                description=_pick_text(item, selectors.get("description")),
                start_time_text=start_time,
                end_time_text=end_time,
                location_name=_pick_text(item, selectors.get("location_name")),
                location_address=_pick_text(item, selectors.get("location_address")),
                canonical_id=canonical_id,
            )
        )

    return events
