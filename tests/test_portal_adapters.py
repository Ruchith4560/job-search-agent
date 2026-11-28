"""Unit tests for ATS portal adapters."""

from unittest.mock import MagicMock
from agent.apply.adapters import (
    BasePortalAdapter,
    GenericAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    PhenomAdapter,
    SmartRecruitersAdapter,
    get_adapter,
)


def test_greenhouse_adapter_can_handle():
    adapter = GreenhouseAdapter()
    page = MagicMock()
    page.url = "https://boards.greenhouse.io/stripe/jobs/12345"
    page.locator.return_value.count.return_value = 0

    assert adapter.can_handle(page, "https://boards.greenhouse.io/stripe/jobs/12345") is True
    assert adapter.can_handle(page, "https://example.com") is True  # because page.url has greenhouse
    
    page.url = "https://example.com"
    assert adapter.can_handle(page, "https://example.com") is False


def test_lever_adapter_can_handle():
    adapter = LeverAdapter()
    page = MagicMock()
    page.url = "https://jobs.lever.co/netflix/67890"
    page.locator.return_value.count.return_value = 0

    assert adapter.can_handle(page, "https://jobs.lever.co/netflix/67890") is True
    
    page.url = "https://example.com"
    assert adapter.can_handle(page, "https://example.com") is False


def test_smartrecruiters_adapter_can_handle():
    adapter = SmartRecruitersAdapter()
    page = MagicMock()
    page.url = "https://jobs.smartrecruiters.com/AcmeCorp/112233"
    page.locator.return_value.count.return_value = 0

    assert adapter.can_handle(page, "https://jobs.smartrecruiters.com/AcmeCorp/112233") is True
    
    page.url = "https://example.com"
    assert adapter.can_handle(page, "https://example.com") is False


def test_phenom_adapter_can_handle():
    adapter = PhenomAdapter()
    page = MagicMock()
    page.url = "https://careers.mastercard.com/us/en/job/R-12345"
    page.locator.return_value.count.return_value = 0

    assert adapter.can_handle(page, "https://careers.mastercard.com/us/en/job/R-12345") is True
    
    page.url = "https://example.com"
    assert adapter.can_handle(page, "https://example.com") is False


def test_get_adapter_dispatch():
    page = MagicMock()
    page.url = "https://example.com/careers"
    page.locator.return_value.count.return_value = 0

    # Greenhouse
    gh_adapter = get_adapter(page, "https://boards.greenhouse.io/airbnb/jobs/123")
    assert isinstance(gh_adapter, GreenhouseAdapter)

    # Lever
    lever_adapter = get_adapter(page, "https://jobs.lever.co/twitch/456")
    assert isinstance(lever_adapter, LeverAdapter)

    # SmartRecruiters
    sr_adapter = get_adapter(page, "https://jobs.smartrecruiters.com/Visa/789")
    assert isinstance(sr_adapter, SmartRecruitersAdapter)

    # Phenom
    phenom_adapter = get_adapter(page, "https://careers.mastercard.com/job/R-100")
    assert isinstance(phenom_adapter, PhenomAdapter)

    # Fallback Generic
    generic_adapter = get_adapter(page, "https://some-company.com/job/apply")
    assert isinstance(generic_adapter, GenericAdapter)
