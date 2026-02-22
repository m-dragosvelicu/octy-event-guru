from .source_a import SELECTORS as SOURCE_A_SELECTORS
from .source_b import SELECTORS as SOURCE_B_SELECTORS

_SELECTOR_REGISTRY = {
    "source_a": SOURCE_A_SELECTORS,
    "source_b": SOURCE_B_SELECTORS,
}


def get_selectors(provider: str) -> dict[str, str]:
    return _SELECTOR_REGISTRY.get(provider, {})
