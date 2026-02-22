import logging
from urllib.parse import urlparse

import requests
import yaml
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..domain.models import RawPage, SourceConfig

logger = logging.getLogger(__name__)


def load_source_registry(path: str = "app/sources/registry.yaml") -> list[SourceConfig]:
    with open(path, "r", encoding="utf-8") as registry_file:
        data = yaml.safe_load(registry_file) or []
    return [SourceConfig.model_validate(item) for item in data]


def _is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if not allowed_domains:
        return True

    normalized = {domain.lower() for domain in allowed_domains}
    return any(host == domain or host.endswith(f".{domain}") for domain in normalized)


class SourceFetcher:
    def __init__(self, timeout_seconds: int = 10, user_agent: str = "event-guru-ingest/0.1"):
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def _fetch(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response

    def fetch_url(self, url: str, *, area_id: str = "unknown") -> RawPage | None:
        parsed = urlparse(url)
        provider = (parsed.hostname or "unknown").replace("www.", "")

        try:
            response = self._fetch(url)
        except requests.RequestException:
            logger.info("Failed to fetch", extra={"url": url})
            return None

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "html" not in content_type:
            return None

        html = response.text.strip()
        if len(html) < 64:
            return None

        return RawPage(
            area_id=area_id,
            provider=provider,
            sport_hint=None,
            url=response.url,
            html=html,
        )

    def fetch_source(self, source: SourceConfig, max_pages: int | None = None) -> list[RawPage]:
        pages: list[RawPage] = []

        for url in source.seed_urls:
            if max_pages is not None and len(pages) >= max_pages:
                break

            if not _is_allowed_domain(url, source.allowed_domains):
                logger.info("Skipping URL outside allowed domains", extra={"provider": source.provider})
                continue

            try:
                response = self._fetch(url)
            except requests.RequestException:
                logger.warning("Skipping unreachable URL", extra={"provider": source.provider})
                continue

            content_type = (response.headers.get("Content-Type") or "").lower()
            if "html" not in content_type:
                logger.info("Skipping non-HTML URL", extra={"provider": source.provider})
                continue

            html = response.text.strip()
            if len(html) < 64:
                logger.info("Skipping invalid/blocked page", extra={"provider": source.provider})
                continue

            pages.append(
                RawPage(
                    area_id=source.area_id,
                    provider=source.provider,
                    sport_hint=source.sport_hint,
                    url=response.url,
                    html=html,
                )
            )

        return pages
