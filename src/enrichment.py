"""Site information enrichment: company name, contact info, etc.

Ahrefs APIでは取得できない企業情報を補完するモジュール。
Webスクレイピングにより以下を取得:
- 企業名（title, meta, 会社概要ページ）
- 電話番号（tel:リンク、ページ内テキスト）
- 担当者名（運営者情報ページ等）
"""

import re
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


def _fetch_page(url: str, timeout: int = 10) -> BeautifulSoup | None:
    """Fetch a page and return BeautifulSoup object."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
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


def enrich_domain(domain: str) -> dict:
    """Enrich a domain with company info by scraping its website.

    Returns:
        {
            "company_name": str,
            "phone_numbers": list[str],
            "contact_page": str,
            "company_page": str,
        }
    """
    result = {
        "company_name": "",
        "phone_numbers": [],
        "contact_page": "",
        "company_page": "",
    }

    base_url = f"https://{domain}"

    # 1. Fetch top page
    soup = _fetch_page(base_url)
    if soup:
        result["company_name"] = _extract_company_name_from_soup(soup)
        result["phone_numbers"] = _extract_phone_numbers(soup)

    # 2. Try company page for more info
    for path in COMPANY_PAGE_PATHS:
        url = f"{base_url}{path}"
        soup = _fetch_page(url)
        if soup:
            result["company_page"] = url
            if not result["company_name"]:
                result["company_name"] = _extract_company_name_from_soup(soup)
            if not result["phone_numbers"]:
                result["phone_numbers"] = _extract_phone_numbers(soup)
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

    return result


def enrich_domains_batch(domains: list[str],
                          progress_callback=None) -> list[dict]:
    """Enrich multiple domains with company info.

    Args:
        domains: List of domain names
        progress_callback: Optional callback(current, total, domain)

    Returns: List of enrichment dicts.
    """
    results = []
    total = len(domains)

    for i, domain in enumerate(domains):
        if progress_callback:
            progress_callback(i + 1, total, domain)

        try:
            info = enrich_domain(domain)
        except Exception as e:
            info = {
                "company_name": "",
                "phone_numbers": [],
                "contact_page": "",
                "company_page": "",
                "error": str(e),
            }

        info["domain"] = domain
        results.append(info)

    return results
