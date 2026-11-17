"""Tests for individual job board fetchers with mocked network responses."""

from unittest.mock import MagicMock, patch
from agent.jobs.fetchers.arbeitnow import ArbeitnowFetcher
from agent.jobs.fetchers.enterprise_careers import EnterpriseCareersFetcher
from agent.jobs.fetchers.freshersworld import FreshersworldFetcher
from agent.jobs.fetchers.greenhouse import GreenhouseFetcher
from agent.jobs.fetchers.himalayas import HimalayasFetcher
from agent.jobs.fetchers.indian_portals import IndianPortalsFetcher
from agent.jobs.fetchers.internshala import InternshalaFetcher
from agent.jobs.fetchers.jobicy import JobicyFetcher
from agent.jobs.fetchers.lever import LeverFetcher
from agent.jobs.fetchers.linkedin import LinkedInFetcher
from agent.jobs.fetchers.python_org import PythonOrgFetcher
from agent.jobs.fetchers.remotive import RemotiveFetcher
from agent.jobs.fetchers.remoteok import RemoteOKFetcher
from agent.jobs.fetchers.smartrecruiters import SmartRecruitersFetcher
from agent.jobs.fetchers.unstop import UnstopFetcher
from agent.jobs.fetchers.weworkremotely import WeWorkRemotelyFetcher


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


def test_arbeitnow_fetcher() -> None:
    mock_payload = {
        "data": [
            {
                "slug": "ai-engineer-1",
                "company_name": "NextGen AI",
                "title": "Junior AI Engineer",
                "description": "<p>Build agentic AI systems.</p>",
                "remote": True,
                "url": "https://www.arbeitnow.com/jobs/1",
                "tags": ["Python", "AI"],
                "job_types": ["Full-Time"],
                "location": "Remote",
                "created_at": 1730000000,
            }
        ]
    }
    fetcher = ArbeitnowFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Junior AI Engineer"
        assert jobs[0].company == "NextGen AI"
        assert jobs[0].source == "arbeitnow"
        assert jobs[0].is_remote is True


def test_jobicy_fetcher() -> None:
    mock_payload = {
        "jobs": [
            {
                "id": 505,
                "jobTitle": "Full Stack Developer Intern",
                "companyName": "WebSphere",
                "url": "https://jobicy.com/jobs/505",
                "jobGeo": "Remote / Worldwide",
                "jobType": ["Internship"],
                "jobIndustry": ["Tech"],
                "jobDescription": "<div>Develop React and Node.js applications</div>",
                "pubDate": "2026-10-31",
            }
        ]
    }
    fetcher = JobicyFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Full Stack Developer Intern"
        assert jobs[0].company == "WebSphere"
        assert jobs[0].source == "jobicy"


def test_himalayas_fetcher() -> None:
    mock_payload = {
        "jobs": [
            {
                "title": "Associate Software Engineer",
                "companyName": "CloudMetrics",
                "applicationLink": "https://himalayas.app/jobs/606",
                "locationRestrictions": ["Worldwide"],
                "categories": ["Engineering", "Python"],
                "seniority": "Entry-level",
                "description": "<p>Join our core backend team.</p>",
                "pubDate": "2026-10-31T08:00:00Z",
            }
        ]
    }
    fetcher = HimalayasFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Associate Software Engineer"
        assert jobs[0].company == "CloudMetrics"
        assert jobs[0].source == "himalayas"


def test_weworkremotely_fetcher() -> None:
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>We Work Remotely</title>
        <item>
          <title>GitLab: Backend Engineer Intern</title>
          <link>https://weworkremotely.com/jobs/707</link>
          <description>&lt;p&gt;Work on GitLab CI/CD&lt;/p&gt;</description>
          <pubDate>Thu, 30 Oct 2026 12:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>"""
    fetcher = WeWorkRemotelyFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = xml_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Backend Engineer Intern"
        assert jobs[0].company == "GitLab"
        assert jobs[0].source == "weworkremotely"


def test_python_org_fetcher() -> None:
    xml_data = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Python Jobs</title>
        <item>
          <title>Python Software Developer, DataFlow Inc</title>
          <link>https://www.python.org/jobs/808/</link>
          <description>&lt;p&gt;High-performance Python backends&lt;/p&gt;</description>
          <pubDate>Thu, 30 Oct 2026 12:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>"""
    fetcher = PythonOrgFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = xml_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=10)
        assert len(jobs) == 1
        assert jobs[0].title == "Python Software Developer"
        assert jobs[0].company == "DataFlow Inc"
        assert jobs[0].source == "python_org"


def test_linkedin_fetcher() -> None:
    html_data = """
    <div class="base-card">
      <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/111">
        <h3 class="base-search-card__title">Software Engineer Intern</h3>
      </a>
      <h4 class="base-search-card__subtitle"><a href="#">PayPal</a></h4>
      <span class="job-search-card__location">Bangalore, India</span>
    </div>
    """
    fetcher = LinkedInFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) >= 1
        assert jobs[0].title == "Software Engineer Intern"
        assert jobs[0].company == "PayPal"
        assert jobs[0].source == "linkedin"


def test_internshala_fetcher() -> None:
    html_data = """
    <div>
      <a href="/internship/detail/software-development-internship-at-google-india-999">Apply</a>
    </div>
    """
    fetcher = InternshalaFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) >= 1
        assert "Software Development Internship" in jobs[0].title
        assert jobs[0].company == "Google India"
        assert jobs[0].source == "internshala"


def test_unstop_fetcher() -> None:
    mock_payload = {
        "data": {
            "data": [
                {
                    "id": 987,
                    "title": "Full Stack Developer Intern",
                    "organisation": {"name": "Zerodha"},
                    "public_url": "internships/zerodha-fs-intern",
                    "filters": [{"name": "Internship"}],
                }
            ]
        }
    }
    fetcher = UnstopFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) == 1
        assert jobs[0].title == "Full Stack Developer Intern"
        assert jobs[0].company == "Zerodha"
        assert jobs[0].source == "unstop"


def test_freshersworld_fetcher() -> None:
    html_data = """
    <div>
      <a href="https://www.freshersworld.com/jobs/software-developer-in-hyderabad-for-microsoft-india-12345">View</a>
    </div>
    """
    fetcher = FreshersworldFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) >= 1
        assert jobs[0].title == "Software Developer"
        assert jobs[0].company == "Microsoft India"
        assert "Hyderabad" in jobs[0].location
        assert jobs[0].source == "freshersworld"


def test_indian_portals_fetcher() -> None:
    html_data = """
    <div class="clearfix job-bx">
      <h2><a href="https://www.timesjobs.com/job-detail/python-dev-1">Python Developer Intern</a></h2>
      <h3 class="joblist-comp-name">Tata Consultancy Services</h3>
    </div>
    """
    fetcher = IndianPortalsFetcher()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_data
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) >= 1
        assert jobs[0].title == "Python Developer Intern"
        assert jobs[0].company == "Tata Consultancy Services"
        assert jobs[0].source == "timesjobs"


def test_smartrecruiters_fetcher() -> None:
    mock_payload = {
        "content": [
            {
                "id": "sr-101",
                "name": "Associate Software Engineer",
                "location": {"city": "Bangalore", "country": "India"},
                "releasedDate": "2026-10-31",
            }
        ]
    }
    fetcher = SmartRecruitersFetcher(companies=["visa"])
    with patch.object(fetcher, "_get_json", return_value=mock_payload):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) == 1
        assert jobs[0].title == "Associate Software Engineer"
        assert jobs[0].company == "Visa"
        assert jobs[0].source == "smartrecruiters"


def test_enterprise_careers_fetcher() -> None:
    mock_amz_payload = {
        "jobs": [
            {
                "title": "Software Development Engineer Intern",
                "location": "Hyderabad, IND",
                "job_path": "/jobs/12345/sde-intern",
                "description": "<p>Build high scale cloud systems at Amazon.</p>",
            }
        ]
    }
    fetcher = EnterpriseCareersFetcher()
    with patch.object(fetcher, "_get_json", return_value=mock_amz_payload):
        jobs = fetcher.fetch(limit=5)
        assert len(jobs) >= 1
        assert any(j.company == "Amazon" for j in jobs)
        assert any("Software" in j.title for j in jobs)



