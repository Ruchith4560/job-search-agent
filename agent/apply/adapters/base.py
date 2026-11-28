"""Base class and common types for ATS portal automation adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FormFillResult:
    """Outcome of attempting to fill an application form."""
    unknown: List[Dict[str, Any]] = field(default_factory=list)
    filled: List[str] = field(default_factory=list)
    status: str = "READY"
    error: Optional[str] = None


@dataclass
class SubmissionResult:
    """Outcome of attempting to submit an application form."""
    success: bool
    status: str
    confirmation_id: Optional[str] = None
    confirmation_text: Optional[str] = None
    error: Optional[str] = None


class BasePortalAdapter(ABC):
    """Abstract base class for portal-specific application drivers."""

    name: str = "base"

    @abstractmethod
    def can_handle(self, page: Any, url: str) -> bool:
        """Determine whether this adapter should handle the current page and URL."""
        pass

    def navigate_to_form(self, page: Any, url: str) -> bool:
        """Optional hook to click 'Apply' buttons or navigate landing pages to reach the actual form."""
        return True

    @abstractmethod
    def fill(
        self,
        page: Any,
        job: Dict[str, Any],
        profile: Dict[str, Any],
        answers: Dict[str, Any],
    ) -> FormFillResult:
        """Fill application inputs using profile data and custom answers."""
        pass

    @abstractmethod
    def submit(self, page: Any) -> SubmissionResult:
        """Execute form submission and return verified submission status."""
        pass

    def verify_confirmation(self, page: Any, timeout: int = 20) -> Tuple[bool, Optional[str]]:
        """Verify whether the employer portal displayed authentic submission confirmation."""
        return False, None
