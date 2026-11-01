"""Tests for individual job board fetchers with mocked network responses."""

from unittest.mock import MagicMock, patch
from agent.jobs.fetchers.greenhouse import GreenhouseFetcher
from agent.jobs.fetchers.lever import LeverFetcher
from agent.jobs.fetchers.remotive import RemotiveFetcher
from agent.jobs.fetchers.remoteok import RemoteOKFetcher


def test_remotive_fetcher() -> None:
    mock_payload = {
        "jobs": [
            {
                "id": 101,
                "url": "https://remotive.com/jobs/101",
                "title": "Python Developer",
                "company_name": "CloudScale",
                "candidate_required_location": "Worldwide",
                "tags": ["python", "django"],
                "description": "<p>We are seeking a <b>Python</b> dev.</p>",
                "publication_date": "2026-10-30T10:00:00Z",
            }
        ]
    }

    fetcher = RemotiveFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        job = jobs[0]
        assert job.title == "Python Developer"
        assert job.company == "CloudScale"
        assert job.source == "remotive"
        assert job.is_remote is True
        assert "<p>" not in job.description
        assert "Python dev" in job.description


def test_remoteok_fetcher() -> None:
    mock_payload = [
        {"legal": "API usage notice"},  # Disclaimer item to skip
        {
            "id": "202",
            "position": "Backend Engineer",
            "company": "TechStart",
            "url": "https://remoteok.com/l/202",
            "location": "Remote",
            "tags": ["fastapi", "postgres"],
            "description": "<div>Build high speed APIs</div>",
            "date": "2026-10-29",
        },
    ]

    fetcher = RemoteOKFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Backend Engineer"
        assert jobs[0].company == "TechStart"
        assert jobs[0].source == "remoteok"


def test_greenhouse_fetcher() -> None:
    mock_payload = {
        "jobs": [
            {
                "id": 303,
                "title": "Software Engineer, Core Infrastructure",
                "absolute_url": "https://boards.greenhouse.io/canonical/jobs/303",
                "location": {"name": "Home Based - EMEA"},
                "content": "<p>Canonical is hiring an engineer.</p>",
                "updated_at": "2026-10-28T12:00:00Z",
            }
        ]
    }

    fetcher = GreenhouseFetcher(companies=["canonical"])
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Software Engineer, Core Infrastructure"
        assert jobs[0].company == "Canonical"
        assert jobs[0].source == "greenhouse"


def test_lever_fetcher() -> None:
    mock_payload = [
        {
            "id": "404",
            "text": "Full Stack Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/404",
            "categories": {
                "location": "Remote - US",
                "team": "Engineering",
                "commitment": "Full Time",
            },
            "workplaceType": "remote",
            "descriptionPlain": "Develop cloud applications with React and Python.",
            "createdAt": 1730000000000,
        }
    ]

    fetcher = LeverFetcher(companies=["palantir"])
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Full Stack Engineer"
        assert jobs[0].company == "Palantir"
        assert jobs[0].is_remote is True
        assert jobs[0].source == "lever"
