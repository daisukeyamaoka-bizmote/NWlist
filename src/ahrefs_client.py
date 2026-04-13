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

    def get_organic_competitors(self, domain: str, country: str = "jp",
                                 limit: int = 50) -> list[dict]:
        """Get organic competitors for a domain.

        Finds domains competing for the same organic keywords.

        Returns: List of {"domain": str, "common_keywords": int, ...}
        """
        resp = self._request("GET", "site-explorer/organic-competitors", params={
            "target": domain,
            "country": country,
            "limit": limit,
            "select": "domain,common_keywords,organic_traffic,domain_rating",
            "order_by": "common_keywords:desc",
        })
        return resp.get("competitors", resp.get("data", []))

    def discover_competitors_for_seeds(self, seed_domains: list[str],
                                        country: str = "jp",
                                        per_seed_limit: int = 20,
                                        dr_min: int = 10,
                                        dr_max: int = 70) -> list[dict]:
        """Discover new domains by finding organic competitors of seed domains.

        Args:
            seed_domains: Known domains to use as seeds
            country: Target country
            per_seed_limit: Max competitors per seed domain
            dr_min: Minimum DR filter
            dr_max: Maximum DR filter

        Returns: Deduplicated list of discovered competitor dicts.
        """
        seen = set(seed_domains)
        discovered = []

        for i, seed in enumerate(seed_domains):
            print(f"  Discovering competitors for {seed} ({i+1}/{len(seed_domains)})...")
            try:
                competitors = self.get_organic_competitors(
                    seed, country=country, limit=per_seed_limit
                )
            except Exception as e:
                print(f"    Skipped {seed}: {e}")
                continue

            for comp in competitors:
                domain = comp.get("domain", "")
                if not domain or domain in seen:
                    continue

                dr = comp.get("domain_rating", 0)
                if dr_min <= dr <= dr_max:
                    seen.add(domain)
                    comp["discovered_from"] = seed
                    discovered.append(comp)

        print(f"  Discovered {len(discovered)} new domains from {len(seed_domains)} seeds")
        return discovered

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
