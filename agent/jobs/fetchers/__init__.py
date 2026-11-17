"""Job board fetchers package exposing all legal, free job discovery engines."""

from agent.jobs.fetchers.base import BaseJobFetcher
from agent.jobs.fetchers.enterprise_careers import EnterpriseCareersFetcher
from agent.jobs.fetchers.remotive import RemotiveFetcher
from agent.jobs.fetchers.remoteok import RemoteOKFetcher
from agent.jobs.fetchers.greenhouse import GreenhouseFetcher
from agent.jobs.fetchers.lever import LeverFetcher
from agent.jobs.fetchers.adzuna import AdzunaFetcher
from agent.jobs.fetchers.arbeitnow import ArbeitnowFetcher
from agent.jobs.fetchers.jobicy import JobicyFetcher
from agent.jobs.fetchers.himalayas import HimalayasFetcher
from agent.jobs.fetchers.weworkremotely import WeWorkRemotelyFetcher
from agent.jobs.fetchers.python_org import PythonOrgFetcher
from agent.jobs.fetchers.linkedin import LinkedInFetcher
from agent.jobs.fetchers.internshala import InternshalaFetcher
from agent.jobs.fetchers.unstop import UnstopFetcher
from agent.jobs.fetchers.freshersworld import FreshersworldFetcher
from agent.jobs.fetchers.indian_portals import IndianPortalsFetcher
from agent.jobs.fetchers.smartrecruiters import SmartRecruitersFetcher

__all__ = [
    "BaseJobFetcher",
    "EnterpriseCareersFetcher",
    "RemotiveFetcher",
    "RemoteOKFetcher",
    "GreenhouseFetcher",
    "LeverFetcher",
    "AdzunaFetcher",
    "ArbeitnowFetcher",
    "JobicyFetcher",
    "HimalayasFetcher",
    "WeWorkRemotelyFetcher",
    "PythonOrgFetcher",
    "LinkedInFetcher",
    "InternshalaFetcher",
    "UnstopFetcher",
    "FreshersworldFetcher",
    "IndianPortalsFetcher",
    "SmartRecruitersFetcher",
]
