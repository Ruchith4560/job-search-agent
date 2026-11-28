"""Registry and factory for ATS portal automation adapters."""

from __future__ import annotations

from typing import Any, List

from agent.apply.adapters.base import BasePortalAdapter, FormFillResult, SubmissionResult
from agent.apply.adapters.generic import GenericAdapter
from agent.apply.adapters.greenhouse import GreenhouseAdapter
from agent.apply.adapters.lever import LeverAdapter
from agent.apply.adapters.phenom import PhenomAdapter
from agent.apply.adapters.smartrecruiters import SmartRecruitersAdapter

__all__ = [
    "BasePortalAdapter",
    "FormFillResult",
    "SubmissionResult",
    "GreenhouseAdapter",
    "LeverAdapter",
    "SmartRecruitersAdapter",
    "PhenomAdapter",
    "GenericAdapter",
    "get_adapter",
]

# Order matters: specialized enterprise & ATS adapters before generic fallback
_REGISTERED_ADAPTERS: List[BasePortalAdapter] = [
    PhenomAdapter(),
    GreenhouseAdapter(),
    LeverAdapter(),
    SmartRecruitersAdapter(),
    GenericAdapter(),
]


def get_adapter(page: Any, url: str) -> BasePortalAdapter:
    """Select the best matching portal adapter for the given URL and page state."""
    for adapter in _REGISTERED_ADAPTERS:
        try:
            if adapter.can_handle(page, url):
                return adapter
        except Exception:
            continue
    return GenericAdapter()
