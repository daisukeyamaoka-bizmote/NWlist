"""担当者（役員・部長クラス）自動調査モジュール.

企業のマーケティング/ウェブ担当責任者を以下のソースから調査:
1. 企業サイトの役員紹介・チームページ
2. PR TIMES等のプレスリリース
3. メディア記事検索（MarkeZine, Web担当者Forum, ferret）

Claude Sonnet APIが利用可能な場合:
- スクレイピングした記事/ページ本文をAIで読解
- 正規表現では拾えない人名・役職・就任時期を正確に抽出
- 情報の鮮度（記事日付）も判定

取得情報:
- 担当者名
- 役職
- 情報ソースURL
- 記事日付（AI抽出時）
- 信頼度（AI抽出時）
"""

import ipaddress
import json
import logging
import os
import re
import socket
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Claude Sonnet client (lazy init)
# -------------------------------------------------------------------
_anthropic_client = None
_anthropic_init_lock = threading.Lock()


def _get_anthropic_client():
    """Anthropicクライアントをlazy初期化（スレッドセーフ）."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client

    with _anthropic_init_lock:
        if _anthropic_client is not None:
            return _anthropic_client

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key == "your_anthropic_api_key_here":
            return None

        try:
            import anthropic
            _anthropic_client = anthropic.Anthropic(api_key=api_key)
            logger.info("Anthropic API client initialized (Claude Sonnet)")
            return _anthropic_client
        except Exception as e:
            logger.warning(f"Anthropic API client init failed: {e}")
            return None


def _is_ai_available() -> bool:
    return _get_anthropic_client() is not None


# -------------------------------------------------------------------
# AI extraction via Claude Sonnet
# -------------------------------------------------------------------
_EXTRACT_PROMPT = """\
以下は企業「{company_name}」({domain})に関するWebページまたは記事のテキストです。

このテキストから、この企業のマーケティング・デジタル・ウェブ・広報・経営に関わる\
担当者の情報を抽出してください。

### 抽出ルール
- 対象企業に所属する人物のみ抽出（インタビュアーや記者は除外）
- 役職が明記されている人物のみ
- 最大5名まで
- 記事の公開日・更新日があれば記載

### 出力形式（JSON配列）
```json
[
  {{
    "person_name": "姓 名",
    "person_title": "役職名",
    "article_date": "YYYY-MM-DD or empty",
    "confidence": "high/medium/low",
    "reason": "抽出根拠を1行で"
  }}
]
```

人物が見つからない場合は空配列 `[]` を返してください。
JSON以外のテキストは出力しないでください。

---
テキスト:
{text}
"""

# AIリクエストのテキスト上限（トークン節約）
_MAX_TEXT_CHARS = 6000


def _extract_persons_with_ai(text: str, domain: str, company_name: str,
                              source_url: str) -> list[dict]:
    """Claude Sonnetで記事/ページ本文から担当者情報を抽出."""
    client = _get_anthropic_client()
    if client is None:
        return []

    # ASCII範囲外の文字を安全に扱う
    text = text.encode("utf-8", errors="replace").decode("utf-8")

    # テキストが長すぎる場合は冒頭と末尾を残して切り詰め
    if len(text) > _MAX_TEXT_CHARS:
        half = _MAX_TEXT_CHARS // 2
        text = text[:half] + "\n...(中略)...\n" + text[-half:]

    prompt = _EXTRACT_PROMPT.format(
        company_name=str(company_name or domain),
        domain=str(domain),
        text=text,
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()

        # JSON部分を抽出（```json ... ``` で囲まれている場合に対応）
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            return []

        persons_raw = json.loads(json_match.group())
        persons = []
        for p in persons_raw:
            if not isinstance(p, dict):
                continue
            name = p.get("person_name", "").strip()
            title = p.get("person_title", "").strip()
            if not name or not title:
                continue
            persons.append({
                "person_name": name,
                "person_title": title,
                "person_source": source_url,
                "is_marketing_related": _is_marketing_related(title),
                "article_date": p.get("article_date", ""),
                "confidence": p.get("confidence", "medium"),
                "ai_reason": p.get("reason", ""),
            })
        return persons

    except Exception as e:
        logger.warning("AI extraction failed for %s: %s", domain, e)
        return []


# -------------------------------------------------------------------
# Constants & patterns (regex fallback)
# -------------------------------------------------------------------
TARGET_TITLES = [
    "CMO", "CTO", "COO", "CDO", "CIO",
    "マーケティング", "デジタル", "ウェブ", "Web",
    "取締役", "執行役員", "代表",
    "VP", "Vice President",
]

TITLE_PATTERNS = [
    r'(代表取締役[社会]?長?)',
    r'(取締役\S{0,10})',
    r'(執行役員\S{0,10})',
    r'((?:上席|常務|専務)?(?:取締役|理事)\S{0,10})',
    r'((?:マーケティング|デジタル|ウェブ|Web|事業|経営企画|広報)\S{0,6}(?:本部長|部長|副部長|室長|責任者|担当役員|リーダー|ディレクター|Director|マネージャー))',
    r'(CMO|CTO|COO|CDO|CIO|CEO)',
    r'(VP\s+of\s+\w+)',
    r'(Head\s+of\s+\w+)',
]

NAME_PATTERN = re.compile(
    r'([一-龥ぁ-んァ-ヶ]{1,4})\s*([一-龥ぁ-んァ-ヶ]{1,4})'
)

TEAM_PAGE_PATHS = [
    "/company/team",
    "/company/officer",
    "/company/officers",
    "/company/member",
    "/company/members",
    "/company/board",
    "/company/management",
    "/corporate/officer",
    "/corporate/officers",
    "/corporate/management",
    "/about/team",
    "/about/members",
    "/about/management",
    "/team",
    "/members",
]

# -------------------------------------------------------------------
# HTTP session (thread-safe)
# -------------------------------------------------------------------
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

_thread_local = threading.local()


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update(_DEFAULT_HEADERS)
    return _thread_local.session


# -------------------------------------------------------------------
# SSRF protection
# -------------------------------------------------------------------
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
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def _fetch_page(url: str, timeout: int = 10) -> BeautifulSoup | None:
    if not _is_safe_url(url):
        return None
    try:
        resp = _get_session().get(url, timeout=timeout, allow_redirects=True)
        if resp.url != url and not _is_safe_url(resp.url):
            return None
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _is_marketing_related(title: str) -> bool:
    """役職がマーケ/ウェブ/デジタル関連かどうか."""
    marketing_keywords = [
        "マーケ", "デジタル", "ウェブ", "Web", "web",
        "CMO", "CDO", "広報", "PR", "グロース", "Growth",
        "SEO", "コンテンツ", "ブランド", "コミュニケーション",
    ]
    return any(kw.lower() in title.lower() for kw in marketing_keywords)


def _extract_persons_from_soup(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """HTMLから役職+名前のペアを正規表現で抽出（フォールバック用）."""
    persons = []
    text = soup.get_text(separator="\n")
    lines = text.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or len(line) > 200:
            continue

        matched_title = ""
        for pattern in TITLE_PATTERNS:
            m = re.search(pattern, line)
            if m:
                matched_title = m.group(1).strip()
                break

        if not matched_title:
            continue

        search_range = lines[max(0, i-1):i+3]
        for search_line in search_range:
            search_line = search_line.strip()
            name_match = NAME_PATTERN.search(search_line)
            if name_match:
                name = f"{name_match.group(1)} {name_match.group(2)}"
                if name != matched_title and len(name) >= 3:
                    persons.append({
                        "person_name": name,
                        "person_title": matched_title,
                        "person_source": source_url,
                        "is_marketing_related": _is_marketing_related(matched_title),
                    })
                    break

    return persons


def _extract_persons_from_soup_smart(soup: BeautifulSoup, source_url: str,
                                      domain: str, company_name: str) -> list[dict]:
    """AI利用可能ならClaude Sonnet、そうでなければ正規表現で抽出."""
    try:
        text = soup.get_text(separator="\n")
    except Exception:
        return []
    # エンコーディングを安全に正規化
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    # 極端に短いページはスキップ
    clean_text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
    if len(clean_text) < 50:
        return []

    if _is_ai_available():
        persons = _extract_persons_with_ai(clean_text, domain, company_name, source_url)
        if persons:
            return persons
        # AI抽出が空なら正規表現にフォールバック

    return _extract_persons_from_soup(soup, source_url)


# -------------------------------------------------------------------
# Source searchers
# -------------------------------------------------------------------
def _search_company_team_pages(domain: str, company_name: str = "") -> list[dict]:
    """企業サイトの役員/チームページから担当者を探す."""
    base_url = f"https://{domain}"
    persons = []

    for path in TEAM_PAGE_PATHS:
        url = f"{base_url}{path}"
        soup = _fetch_page(url)
        if soup:
            found = _extract_persons_from_soup_smart(soup, url, domain, company_name)
            persons.extend(found)
            if found:
                break

    return persons


def _search_prtimes(company_name: str, domain: str = "", max_results: int = 5) -> list[dict]:
    """PR TIMESでプレスリリースから担当者を検索."""
    if not company_name:
        return []

    persons = []
    search_queries = [
        f"{company_name} マーケティング 責任者",
        f"{company_name} 執行役員",
    ]

    for query in search_queries:
        search_url = f"https://prtimes.jp/main/action.php?run=html&page=searchkey&search_word={urllib.parse.quote(query)}"
        soup = _fetch_page(search_url)
        if not soup:
            continue

        articles = soup.find_all("a", href=True)
        count = 0
        for a in articles:
            href = a["href"]
            if "/main/html/rd/p/" in href and count < max_results:
                article_url = href if href.startswith("http") else f"https://prtimes.jp{href}"
                article_soup = _fetch_page(article_url)
                if article_soup:
                    found = _extract_persons_from_soup_smart(
                        article_soup, article_url, domain, company_name)
                    persons.extend(found)
                    count += 1
                    if persons:
                        return persons

    return persons


def _search_media(company_name: str, domain: str = "", max_results: int = 3) -> list[dict]:
    """メディア記事検索で担当者情報を探す."""
    if not company_name:
        return []

    persons = []

    media_searches = [
        ("MarkeZine", f"https://markezine.jp/search?q={urllib.parse.quote(company_name + ' マーケティング')}"),
        ("Web担当者Forum", f"https://webtan.impress.co.jp/search/node/{urllib.parse.quote(company_name)}"),
        ("ferret", f"https://ferret-plus.com/search?q={urllib.parse.quote(company_name + ' マーケティング責任者')}"),
    ]

    for media_name, search_url in media_searches:
        soup = _fetch_page(search_url)
        if not soup:
            continue

        links = soup.find_all("a", href=True)
        count = 0
        for link in links:
            href = link["href"]
            if any(p in href for p in ["/article/", "/articles/", "/interview/"]):
                article_url = href if href.startswith("http") else f"https://{urllib.parse.urlparse(search_url).netloc}{href}"
                article_soup = _fetch_page(article_url)
                if article_soup:
                    found = _extract_persons_from_soup_smart(
                        article_soup, article_url, domain, company_name)
                    persons.extend(found)
                    count += 1
                    if count >= max_results or persons:
                        break

        if persons:
            break

    return persons


# -------------------------------------------------------------------
# Main entry points
# -------------------------------------------------------------------
def find_key_persons(domain: str, company_name: str = "") -> list[dict]:
    """企業のマーケ/ウェブ担当責任者を調査.

    優先順位:
    1. 企業サイトの役員/チームページ
    2. PR TIMESのプレスリリース
    3. メディア記事検索

    AI利用可能な場合はClaude Sonnetで正確に読解。
    利用不可の場合は正規表現にフォールバック。

    Returns:
        List of {
            "person_name": str,
            "person_title": str,
            "person_source": str,
            "is_marketing_related": bool,
            "article_date": str (AI時のみ),
            "confidence": str (AI時のみ),
            "ai_reason": str (AI時のみ),
        }
    """
    all_persons = []

    # 1. 企業サイトの役員ページ
    team_persons = _search_company_team_pages(domain, company_name)
    all_persons.extend(team_persons)

    # 2. PR TIMES検索
    if company_name:
        pr_persons = _search_prtimes(company_name, domain)
        all_persons.extend(pr_persons)

    # 3. メディア記事検索（まだマーケ関連の人が見つかっていない場合）
    marketing_found = any(p.get("is_marketing_related") for p in all_persons)
    if not marketing_found and company_name:
        media_persons = _search_media(company_name, domain)
        all_persons.extend(media_persons)

    # 重複排除（名前ベース）
    seen_names = set()
    unique = []
    for p in all_persons:
        if p["person_name"] not in seen_names:
            seen_names.add(p["person_name"])
            unique.append(p)

    # マーケ関連を優先、その後役員クラスを表示
    marketing = [p for p in unique if p.get("is_marketing_related")]
    others = [p for p in unique if not p.get("is_marketing_related")]

    return (marketing + others)[:5]


def find_key_persons_batch(domains_with_names: list[tuple[str, str]],
                            progress_callback=None,
                            max_workers: int = 8) -> dict[str, list[dict]]:
    """複数ドメインの担当者を一括調査（並列処理）.

    Args:
        domains_with_names: List of (domain, company_name) tuples
        progress_callback: Optional callback(current, total, domain)
        max_workers: 並列スレッド数（デフォルト8）

    Returns:
        Dict mapping domain -> list of person dicts
    """
    results = {}
    total = len(domains_with_names)
    completed = 0

    # AI使用時は並列数を下げてレート制限を守る
    if _is_ai_available():
        max_workers = min(max_workers, 4)
        logger.info("Claude Sonnet AI抽出モード（並列数: %d）", max_workers)
    else:
        logger.info("正規表現フォールバックモード（並列数: %d）", max_workers)

    def _process(pair: tuple[str, str]) -> tuple[str, list[dict]]:
        domain, company_name = pair
        try:
            persons = find_key_persons(domain, company_name)
        except Exception:
            persons = []
        return domain, persons

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, pair): pair for pair in domains_with_names}
        for future in as_completed(futures):
            domain, persons = future.result()
            results[domain] = persons
            completed += 1
            if progress_callback:
                progress_callback(completed, total, domain)

    return results
