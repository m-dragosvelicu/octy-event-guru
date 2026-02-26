from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

RESULTS_PER_QUERY = 20


def search_event_urls(
    *,
    api_key: str,
    queries: list[str],
    timeout_seconds: int = 15,
) -> list[str]:
    if not api_key:
        logger.error("BRAVE_SEARCH_API_KEY is empty, cannot search for events")
        return []

    seen_urls: set[str] = set()
    ordered_urls: list[str] = []

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }

    for query in queries:
        try:
            resp = requests.get(
                BRAVE_SEARCH_URL,
                params={"q": query, "count": str(RESULTS_PER_QUERY)},
                headers=headers,
                timeout=timeout_seconds,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("Brave Search request failed", exc_info=True, extra={"query": query})
            continue

        data = resp.json()
        web_results = (data.get("web") or {}).get("results") or []

        for result in web_results:
            url = result.get("url")
            if not url or url in seen_urls:
                continue
            if not _is_crawlable(url):
                continue
            seen_urls.add(url)
            ordered_urls.append(url)

        logger.info(
            "Brave Search query complete",
            extra={"query": query, "results": len(web_results), "new_urls": len(ordered_urls)},
        )

    logger.info("Search phase complete", extra={"total_urls": len(ordered_urls)})
    return ordered_urls


def _is_crawlable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").lower()

    skip_domains = {
        "youtube.com", "www.youtube.com",
        "twitter.com", "x.com",
        "instagram.com", "www.instagram.com",
        "tiktok.com", "www.tiktok.com",
        "pinterest.com", "www.pinterest.com",
        "reddit.com", "www.reddit.com",
    }
    if host in skip_domains:
        return False

    skip_extensions = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mp3", ".zip")
    if parsed.path.lower().endswith(skip_extensions):
        return False

    return True
