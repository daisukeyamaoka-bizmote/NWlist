"""担当者（役員・部長クラス）自動調査モジュール.

企業のマーケティング/ウェブ担当責任者を以下のソースから調査:
1. 企業サイトの役員紹介・チームページ
2. PR TIMES等のプレスリリース
3. Google検索（企業名 × 役職キーワード）

取得情報:
- 担当者名
- 役職
- 情報ソースURL
"""

import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

# 調査対象の役職キーワード
TARGET_TITLES = [
    "CMO", "CTO", "COO", "CDO", "CIO",
    "マーケティング", "デジタル", "ウェブ", "Web",
    "取締役", "執行役員", "代表",
    "VP", "Vice President",
]

# 役職として認識するパターン
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

# 日本人名のパターン（姓名の間にスペース）
NAME_PATTERN = re.compile(
    r'([一-龥ぁ-んァ-ヶ]{1,4})\s*([一-龥ぁ-んァ-ヶ]{1,4})'
)

# 企業サイトの役員・チームページパス候補
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

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
})


def _fetch_page(url: str, timeout: int = 10) -> BeautifulSoup | None:
    try:
        resp = _SESSION.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _is_marketing_related(title: str) -> bool:
    """役職がマーケ/ウェブ/デジタル関連かどうか."""
    marketing_keywords = [
        "マーケ", "デジタル", "ウェブ", "Web", "web",
        "CMO", "CDO", "広報", "PR", "グロース", "Growth",
        "SEO", "コンテンツ", "ブランド", "コミュニケーション",
    ]
    return any(kw.lower() in title.lower() for kw in marketing_keywords)


def _extract_persons_from_soup(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """HTMLから役職+名前のペアを抽出."""
    persons = []
    text = soup.get_text(separator="\n")
    lines = text.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or len(line) > 200:
            continue

        # 役職パターンにマッチするか
        matched_title = ""
        for pattern in TITLE_PATTERNS:
            m = re.search(pattern, line)
            if m:
                matched_title = m.group(1).strip()
                break

        if not matched_title:
            continue

        # 同じ行か前後2行から名前を探す
        search_range = lines[max(0, i-1):i+3]
        for search_line in search_range:
            search_line = search_line.strip()
            name_match = NAME_PATTERN.search(search_line)
            if name_match:
                name = f"{name_match.group(1)} {name_match.group(2)}"
                # 役職文字列自体を名前として誤検出しないようチェック
                if name != matched_title and len(name) >= 3:
                    persons.append({
                        "person_name": name,
                        "person_title": matched_title,
                        "person_source": source_url,
                        "is_marketing_related": _is_marketing_related(matched_title),
                    })
                    break

    return persons


def _search_company_team_pages(domain: str) -> list[dict]:
    """企業サイトの役員/チームページから担当者を探す."""
    base_url = f"https://{domain}"
    persons = []

    for path in TEAM_PAGE_PATHS:
        url = f"{base_url}{path}"
        soup = _fetch_page(url)
        if soup:
            found = _extract_persons_from_soup(soup, url)
            persons.extend(found)
            if found:
                break  # 見つかったら最初のページで十分

    return persons


def _search_prtimes(company_name: str, max_results: int = 5) -> list[dict]:
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

        # PR TIMESの検索結果からリンクを取得
        articles = soup.find_all("a", href=True)
        count = 0
        for a in articles:
            href = a["href"]
            if "/main/html/rd/p/" in href and count < max_results:
                article_url = href if href.startswith("http") else f"https://prtimes.jp{href}"
                article_soup = _fetch_page(article_url)
                if article_soup:
                    found = _extract_persons_from_soup(article_soup, article_url)
                    persons.extend(found)
                    count += 1
                    if persons:
                        return persons  # 見つかったら早期リターン

    return persons


def _search_google(company_name: str, max_results: int = 3) -> list[dict]:
    """Google検索で担当者情報を探す.

    Google Custom Search APIが無い場合はスキップ。
    代わりにメディア記事の直接検索を試みる。
    """
    if not company_name:
        return []

    persons = []

    # 主要メディアで直接検索
    media_searches = [
        ("MarkeZine", f"https://markezine.jp/search?q={urllib.parse.quote(company_name + ' マーケティング')}"),
        ("Web担当者Forum", f"https://webtan.impress.co.jp/search/node/{urllib.parse.quote(company_name)}"),
        ("ferret", f"https://ferret-plus.com/search?q={urllib.parse.quote(company_name + ' マーケティング責任者')}"),
    ]

    for media_name, search_url in media_searches:
        soup = _fetch_page(search_url)
        if not soup:
            continue

        # 検索結果の記事リンクを取得
        links = soup.find_all("a", href=True)
        count = 0
        for link in links:
            href = link["href"]
            # 記事ページっぽいURLだけ対象
            if any(p in href for p in ["/article/", "/articles/", "/interview/"]):
                article_url = href if href.startswith("http") else f"https://{urllib.parse.urlparse(search_url).netloc}{href}"
                article_soup = _fetch_page(article_url)
                if article_soup:
                    found = _extract_persons_from_soup(article_soup, article_url)
                    persons.extend(found)
                    count += 1
                    if count >= max_results or persons:
                        break

        if persons:
            break

    return persons


def find_key_persons(domain: str, company_name: str = "") -> list[dict]:
    """企業のマーケ/ウェブ担当責任者を調査.

    優先順位:
    1. 企業サイトの役員/チームページ
    2. PR TIMESのプレスリリース
    3. メディア記事検索

    Returns:
        List of {
            "person_name": str,
            "person_title": str,
            "person_source": str,
            "is_marketing_related": bool,
        }
    """
    all_persons = []

    # 1. 企業サイトの役員ページ
    team_persons = _search_company_team_pages(domain)
    all_persons.extend(team_persons)

    # 2. PR TIMES検索
    if company_name:
        pr_persons = _search_prtimes(company_name)
        all_persons.extend(pr_persons)

    # 3. メディア記事検索（まだマーケ関連の人が見つかっていない場合）
    marketing_found = any(p["is_marketing_related"] for p in all_persons)
    if not marketing_found and company_name:
        media_persons = _search_google(company_name)
        all_persons.extend(media_persons)

    # 重複排除（名前ベース）
    seen_names = set()
    unique = []
    for p in all_persons:
        if p["person_name"] not in seen_names:
            seen_names.add(p["person_name"])
            unique.append(p)

    # マーケ関連を優先、その後役員クラスを表示
    marketing = [p for p in unique if p["is_marketing_related"]]
    others = [p for p in unique if not p["is_marketing_related"]]

    return (marketing + others)[:5]  # 最大5名


def find_key_persons_batch(domains_with_names: list[tuple[str, str]],
                            progress_callback=None) -> dict[str, list[dict]]:
    """複数ドメインの担当者を一括調査.

    Args:
        domains_with_names: List of (domain, company_name) tuples
        progress_callback: Optional callback(current, total, domain)

    Returns:
        Dict mapping domain -> list of person dicts
    """
    results = {}
    total = len(domains_with_names)

    for i, (domain, company_name) in enumerate(domains_with_names):
        if progress_callback:
            progress_callback(i + 1, total, domain)

        try:
            persons = find_key_persons(domain, company_name)
        except Exception:
            persons = []

        results[domain] = persons

    return results
