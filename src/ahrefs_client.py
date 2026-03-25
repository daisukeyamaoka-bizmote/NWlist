"""Ahrefs API v3 client for Domain Rating and Batch Analysis."""

import time
import requests


class AhrefsClient:
    """Ahrefs API v3 client."""

    BASE_URL = "https://api.ahrefs.com/v3"
    RATE_LIMIT_PER_MIN = 60

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        })
        self._request_timestamps: list[float] = []

    def _rate_limit_wait(self):
        """Simple rate limiter: max 60 requests per minute."""
        now = time.time()
        self._request_timestamps = [
            t for t in self._request_timestamps if now - t < 60
        ]
        if len(self._request_timestamps) >= self.RATE_LIMIT_PER_MIN:
            sleep_time = 60 - (now - self._request_timestamps[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._request_timestamps.append(time.time())

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an API request with rate limiting and retry."""
        self._rate_limit_wait()
        url = f"{self.BASE_URL}/{endpoint}"

        for attempt in range(4):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.ConnectionError:
                if attempt < 3:
                    wait = 2 ** (attempt + 1)
                    print(f"  Connection error. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Failed after 4 attempts: {endpoint}")

    def get_domain_rating(self, domain: str) -> dict:
        """Get Domain Rating for a single domain.

        Returns: {"domain_rating": float, "ahrefs_rank": int}
        """
        resp = self._request("GET", "site-explorer/domain-rating", params={
            "target": domain,
            "date": time.strftime("%Y-%m-%d"),
        })
        return resp

    def batch_analysis(self, targets: list[str], select: list[str] | None = None) -> list[dict]:
        """Run batch analysis on up to 100 targets.

        Args:
            targets: List of domains/URLs (max 100)
            select: Fields to return. Defaults to key SEO metrics.

        Returns: List of metric dicts per target.
        """
        if len(targets) > 100:
            raise ValueError("Batch analysis supports max 100 targets per request")

        if select is None:
            select = [
                "target",
                "domain_rating",
                "ahrefs_rank",
                "organic_traffic",
                "organic_keywords",
                "referring_domains",
                "linked_domains",
            ]

        payload = {
            "targets": targets,
            "select": select,
        }

        resp = self._request("POST", "batch-analysis", json=payload)
        return resp.get("results", resp.get("data", []))

    def batch_analysis_chunked(self, targets: list[str], chunk_size: int = 100,
                                select: list[str] | None = None) -> list[dict]:
        """Run batch analysis on any number of targets, chunking into 100-target batches.

        Args:
            targets: List of domains/URLs (any length)
            chunk_size: Number of targets per batch (max 100)
            select: Fields to return.

        Returns: Combined list of results from all batches.
        """
        all_results = []
        chunk_size = min(chunk_size, 100)

        for i in range(0, len(targets), chunk_size):
            chunk = targets[i:i + chunk_size]
            batch_num = (i // chunk_size) + 1
            total_batches = (len(targets) + chunk_size - 1) // chunk_size
            print(f"  Batch {batch_num}/{total_batches} ({len(chunk)} targets)...")

            results = self.batch_analysis(chunk, select=select)
            all_results.extend(results)

        return all_results

    def get_organic_keywords(self, domain: str, country: str = "jp",
                              limit: int = 10) -> list[dict]:
        """Get top organic keywords for a domain.

        Useful for understanding what keywords a site ranks for.
        """
        resp = self._request("GET", "site-explorer/organic-keywords", params={
            "target": domain,
            "country": country,
            "limit": limit,
            "select": "keyword,volume,position,cpc,traffic",
            "order_by": "traffic:desc",
        })
        return resp.get("keywords", resp.get("data", []))
