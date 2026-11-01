"""Base job board fetcher abstract class with retries and rate limit respect."""

from abc import ABC, abstractmethod
import logging
import time
from typing import Any, Dict, List, Optional
import requests
from agent.jobs.schema import Job

logger = logging.getLogger(__name__)


class BaseJobFetcher(ABC):
    """Abstract base class for legal, public job board fetchers."""

    def __init__(self, name: str, timeout: int = 20) -> None:
        """Initialize fetcher.

        Args:
            name: Identifier name of the job board source.
            timeout: HTTP request timeout in seconds.
        """
        self.name = name.lower()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        })

    def _get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Optional[Any]:
        """Execute HTTP GET with exponential backoff on transient errors and rate limits.

        Args:
            url: Target API endpoint.
            params: Optional query parameters.
            max_retries: Maximum number of retry attempts.
            base_delay: Initial sleep delay in seconds.

        Returns:
            Decoded JSON payload, or None on failure.
        """
        for attempt in range(max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "[%s] HTTP %d for %s. Retrying in %.1fs...",
                            self.name,
                            resp.status_code,
                            url,
                            delay,
                        )
                        time.sleep(delay)
                        continue

                logger.warning("[%s] HTTP %d received for %s", self.name, resp.status_code, url)
                return None

            except (requests.RequestException, ValueError) as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "[%s] Request error (%s) on %s. Retrying in %.1fs...",
                        self.name,
                        e,
                        url,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("[%s] Max retries exceeded for %s: %s", self.name, url, e)
                    return None

        return None

    @abstractmethod
    def fetch(self, limit: Optional[int] = None) -> List[Job]:
        """Fetch and return normalized Job instances.

        Args:
            limit: Maximum number of jobs to fetch.

        Returns:
            List of Job objects.
        """
        pass
