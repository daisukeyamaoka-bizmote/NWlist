"""Site information enrichment: company name, contact info, etc.

Ahrefs APIでは取得できない企業情報を補完するモジュール。
Webスクレイピングにより以下を取得:
- 企業名（title, meta, 会社概要ページ）
- 電話番号（tel:リンク、ページ内テキスト）
- 担当者名（運営者情報ページ等）
"""

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# 電話番号の正規表現パターン（日本の電話番号）
PHONE_PATTERNS = [
    r'0\d{1,4}-\d{1,4}-\d{3,4}',      # 03-1234-5678
    r'0\d{9,10}',                        # 0312345678
    r'\+81-?\d{1,4}-?\d{1,4}-?\d{3,4}', # +81-3-1234-5678
]

# 会社概要ページのパス候補
COMPANY_PAGE_PATHS = [
    "/company",
    "/about",
    "/corporate",
    "/company/",
    "/about/",
    "/corporate/",
    "/about-us",
    "/company-info",
    "/corporate/outline",
    "/company/outline",
    "/company/about",
]

# 問い合わせページのパス候補
CONTACT_PAGE_PATHS = [
    "/contact",
    "/contact/",
    "/inquiry",
    "/inquiry/",
    "/otoiawase",
]


_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}


def _is_safe_url(url: str) -> bool:
    """URLが内部ネットワーク/メタデータエンドポイントでないか検証."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname in _BLOCKED_HOSTS:
            return False
        # DNS解決して内部IPでないか確認
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def _fetch_page(url: str, timeout: int = 10) -> BeautifulSoup | None:
    """Fetch a page and return BeautifulSoup object (SSRF保護付き)."""
    if not _is_safe_url(url):
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        # リダイレクト先もSSRF検証
        if resp.url != url and not _is_safe_url(resp.url):
            return None
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _extract_company_name_from_soup(soup: BeautifulSoup) -> str:
    """Extract company name from page HTML."""
    # 1. Try og:site_name
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()

    # 2. Try title tag
    title = soup.find("title")
    if title and title.string:
        # Clean common suffixes
        name = title.string.strip()
        for sep in [" | ", " - ", " – ", "｜", "：", " :: "]:
            if sep in name:
                parts = name.split(sep)
                # Usually company name is the last part
                return parts[-1].strip()
        return name

    return ""


def _extract_phone_numbers(soup: BeautifulSoup) -> list[str]:
    """Extract phone numbers from page."""
    phones = set()

    # 1. tel: links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:"):
            phone = href.replace("tel:", "").strip()
            phone = re.sub(r'[^\d\-\+]', '', phone)
            if len(phone) >= 10:
                phones.add(phone)

    # 2. Regex in text
    text = soup.get_text()
    for pattern in PHONE_PATTERNS:
        for match in re.findall(pattern, text):
            phones.add(match)

    return list(phones)[:3]  # Max 3 numbers


def _check_freshness(url: str, soup: BeautifulSoup | None) -> dict:
    """ページの鮮度をチェック.

    Returns:
        {"freshness_status": "OK" | "STALE" | "UNKNOWN",
         "last_updated": str,  # 検出できた場合の日付
         "freshness_detail": str}
    """
    result = {"freshness_status": "UNKNOWN", "last_updated": "", "freshness_detail": ""}

    # 1. HTTP Last-Modified ヘッダーチェック
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        last_modified = resp.headers.get("Last-Modified", "")
        if last_modified:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(last_modified)
            result["last_updated"] = dt.strftime("%Y-%m-%d")
            days_ago = (datetime.now(dt.tzinfo) - dt).days if dt.tzinfo else (datetime.now() - dt).days
            if days_ago <= 365:
                result["freshness_status"] = "OK"
                result["freshness_detail"] = f"Last-Modified: {days_ago}日前"
                return result
            else:
                result["freshness_status"] = "STALE"
                result["freshness_detail"] = f"Last-Modified: {days_ago}日前（1年以上前）"
                return result
    except Exception:
        pass

    # 2. HTMLのmeta/copyright/footerから年を検出
    if soup:
        text = soup.get_text()
        current_year = datetime.now().year
        # copyright や © の後の年
        year_patterns = [
            rf'(?:copyright|©|&copy;)\s*(?:\d{{4}}\s*[-–]\s*)?({current_year}|{current_year - 1})',
            rf'({current_year}|{current_year - 1})\s*(?:年)',
        ]
        for pattern in year_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                found_year = m.group(1)
                result["freshness_status"] = "OK"
                result["last_updated"] = found_year
                result["freshness_detail"] = f"ページ内に{found_year}年の記載あり"
                return result

        # 古い年だけしか見つからない場合
        old_year_match = re.search(r'(?:copyright|©|&copy;)\s*(?:\d{4}\s*[-–]\s*)?(\d{4})', text, re.IGNORECASE)
        if old_year_match:
            found_year = int(old_year_match.group(1))
            if found_year < current_year - 1:
                result["freshness_status"] = "STALE"
                result["last_updated"] = str(found_year)
                result["freshness_detail"] = f"最新年が{found_year}年（古い可能性あり）"
                return result

    result["freshness_detail"] = "鮮度情報を検出できず"
    return result


def enrich_domain(domain: str) -> dict:
    """Enrich a domain with company info by scraping its website.

    Returns:
        {
            "company_name": str,
            "phone_numbers": list[str],
            "contact_page": str,
            "company_page": str,
            "freshness_status": str,
            "last_updated": str,
            "freshness_detail": str,
        }
    """
    result = {
        "company_name": "",
        "phone_numbers": [],
        "contact_page": "",
        "company_page": "",
        "freshness_status": "UNKNOWN",
        "last_updated": "",
        "freshness_detail": "",
    }

    base_url = f"https://{domain}"

    # 1. Fetch top page
    soup = _fetch_page(base_url)
    if soup:
        result["company_name"] = _extract_company_name_from_soup(soup)
        result["phone_numbers"] = _extract_phone_numbers(soup)

    # 2. Try company page for more info
    company_soup = None
    for path in COMPANY_PAGE_PATHS:
        url = f"{base_url}{path}"
        company_soup = _fetch_page(url)
        if company_soup:
            result["company_page"] = url
            if not result["company_name"]:
                result["company_name"] = _extract_company_name_from_soup(company_soup)
            if not result["phone_numbers"]:
                result["phone_numbers"] = _extract_phone_numbers(company_soup)
            break

    # 3. Try contact page
    for path in CONTACT_PAGE_PATHS:
        url = f"{base_url}{path}"
        try:
            resp = requests.head(url, timeout=5, allow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                result["contact_page"] = url
                break
        except Exception:
            continue

    # 4. Freshness check (company page優先、なければトップページ)
    check_url = result["company_page"] or base_url
    check_soup = company_soup or soup
    freshness = _check_freshness(check_url, check_soup)
    result.update(freshness)

    return result


def enrich_domains_batch(domains: list[str],
                          progress_callback=None,
                          max_workers: int = 10) -> list[dict]:
    """Enrich multiple domains with company info (並列処理).

    Args:
        domains: List of domain names
        progress_callback: Optional callback(current, total, domain)
        max_workers: 並列スレッド数（デフォルト10）

    Returns: List of enrichment dicts.
    """
    total = len(domains)
    completed = 0
    results_map: dict[str, dict] = {}

    def _process(domain: str) -> tuple[str, dict]:
        try:
            info = enrich_domain(domain)
        except Exception as e:
            info = {
                "company_name": "",
                "phone_numbers": [],
                "contact_page": "",
                "company_page": "",
                "freshness_status": "UNKNOWN",
                "last_updated": "",
                "freshness_detail": "",
                "error": str(e),
            }
        info["domain"] = domain
        return domain, info

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, d): d for d in domains}
        for future in as_completed(futures):
            domain, info = future.result()
            results_map[domain] = info
            completed += 1
            if progress_callback:
                progress_callback(completed, total, domain)

    # 元の順序を維持
    return [results_map[d] for d in domains if d in results_map]
