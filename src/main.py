"""NWlist: Neutral Works ABM prospect list generator.

Ahrefs API + Webスクレイピングで、SEO/AIO/LLMO提案先の
ターゲットリストを生成するツール。

ターゲット条件:
- 自社メディア/オウンドメディアを運営している企業
- DR(Domain Rating)が中程度 → SEO伸びしろあり
- CPC高・受注単価高の業界
- リスティング広告出稿中（=ウェブマーケに投資意欲あり）

出力:
- ドメイン, 企業名, 業界, DR, オーガニックトラフィック,
  参照ドメイン数, 電話番号, 問い合わせページ, 会社概要ページ,
  担当者名, 役職, 情報ソース
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

from ahrefs_client import AhrefsClient
from enrichment import enrich_domains_batch
from history import filter_new_domains, get_history_stats, load_history, save_history
from person_finder import find_key_persons_batch
from target_domains import (
    INDUSTRY_TARGETS,
    get_all_domains,
    get_domains_by_industry,
    get_industry_label,
)

load_dotenv()


def get_industry_for_domain(domain: str) -> str:
    """Find industry label for a domain."""
    for key, info in INDUSTRY_TARGETS.items():
        if domain in info["domains"]:
            return info["label"]
    return "不明"


def run_ahrefs_analysis(client: AhrefsClient, domains: list[str],
                         dr_min: int = 10, dr_max: int = 70) -> pd.DataFrame:
    """Run Ahrefs batch analysis and filter by DR range."""
    print(f"\n[1/5] Ahrefs Batch Analysis ({len(domains)} domains)...")
    print(f"  DR filter: {dr_min} <= DR <= {dr_max}")

    results = client.batch_analysis_chunked(domains)

    df = pd.DataFrame(results)

    if "domain_rating" in df.columns:
        df["domain_rating"] = pd.to_numeric(df["domain_rating"], errors="coerce")
        before = len(df)
        df = df[(df["domain_rating"] >= dr_min) & (df["domain_rating"] <= dr_max)]
        print(f"  DR filter: {before} → {len(df)} domains")

    # Add industry labels
    if "target" in df.columns:
        df["industry"] = df["target"].apply(get_industry_for_domain)

    # Sort by organic_traffic desc (higher traffic = bigger opportunity)
    if "organic_traffic" in df.columns:
        df = df.sort_values("organic_traffic", ascending=False)

    return df.reset_index(drop=True)


def run_competitor_discovery(client: AhrefsClient, seed_domains: list[str],
                              dr_min: int = 10, dr_max: int = 70,
                              seeds_to_use: int = 30,
                              per_seed_limit: int = 20) -> pd.DataFrame:
    """Discover new domains via Ahrefs organic competitor analysis."""
    print(f"\n[2/5] Competitor Discovery (using {min(seeds_to_use, len(seed_domains))} seeds)...")

    # Use a subset of seeds to avoid excessive API calls
    seeds = seed_domains[:seeds_to_use]

    discovered = client.discover_competitors_for_seeds(
        seeds,
        per_seed_limit=per_seed_limit,
        dr_min=dr_min,
        dr_max=dr_max,
    )

    if not discovered:
        print("  No new competitors discovered.")
        return pd.DataFrame()

    df = pd.DataFrame(discovered)

    # Rename 'domain' to 'target' for consistency
    if "domain" in df.columns:
        df = df.rename(columns={"domain": "target"})

    # Mark as auto-discovered
    df["discovery_method"] = "auto"

    print(f"  Found {len(df)} new prospect domains")
    return df.reset_index(drop=True)


def run_enrichment(domains: list[str]) -> pd.DataFrame:
    """Enrich domains with company info via web scraping."""
    print(f"\n[3/5] Enriching site info ({len(domains)} domains)...")

    pbar = tqdm(total=len(domains), desc="  Scraping")

    def progress(current, total, domain):
        pbar.update(1)
        pbar.set_postfix_str(domain[:30])

    results = enrich_domains_batch(domains, progress_callback=progress)
    pbar.close()

    df = pd.DataFrame(results)

    # Convert phone_numbers list to string
    if "phone_numbers" in df.columns:
        df["phone_numbers"] = df["phone_numbers"].apply(
            lambda x: " / ".join(x) if isinstance(x, list) else ""
        )

    return df


def run_person_search(domains: list[str], company_names: dict[str, str]) -> pd.DataFrame:
    """Search for key persons (marketing/web department heads) for each domain."""
    print(f"\n[4/5] Key Person Search ({len(domains)} domains)...")

    pairs = [(d, company_names.get(d, "")) for d in domains]

    pbar = tqdm(total=len(domains), desc="  Searching")

    def progress(current, total, domain):
        pbar.update(1)
        pbar.set_postfix_str(domain[:30])

    results = find_key_persons_batch(pairs, progress_callback=progress)
    pbar.close()

    # Flatten: pick the best person per domain (marketing-related first)
    rows = []
    for domain, persons in results.items():
        if persons:
            # First person is already prioritized (marketing > others)
            best = persons[0]
            row = {
                "domain": domain,
                "person_name": best["person_name"],
                "person_title": best["person_title"],
                "person_source": best["person_source"],
            }
            # If there are additional persons, add as person_2, person_3
            for i, p in enumerate(persons[1:3], start=2):
                row[f"person_{i}_name"] = p["person_name"]
                row[f"person_{i}_title"] = p["person_title"]
                row[f"person_{i}_source"] = p["person_source"]
        else:
            row = {
                "domain": domain,
                "person_name": "",
                "person_title": "",
                "person_source": "",
            }
        rows.append(row)

    return pd.DataFrame(rows)


def merge_and_export(ahrefs_df: pd.DataFrame, enrichment_df: pd.DataFrame,
                      person_df: pd.DataFrame, output_dir: str,
                      limit: int | None = None,
                      update_history: bool = False,
                      history_path: str = "") -> str:
    """Merge all data and export to CSV + Excel."""
    print(f"\n[5/5] Merging & exporting...")

    # Merge Ahrefs + enrichment
    if "target" in ahrefs_df.columns and "domain" in enrichment_df.columns:
        merged = ahrefs_df.merge(enrichment_df, left_on="target", right_on="domain", how="left")
    else:
        merged = ahrefs_df

    # Merge person data
    if not person_df.empty and "target" in merged.columns and "domain" in person_df.columns:
        merged = merged.merge(person_df, left_on="target", right_on="domain",
                               how="left", suffixes=("", "_person"))
        # Drop duplicate domain column
        if "domain_person" in merged.columns:
            merged = merged.drop(columns=["domain_person"])

    if limit:
        merged = merged.head(limit)

    # Reorder columns for readability
    preferred_order = [
        "target", "company_name", "industry", "domain_rating", "ahrefs_rank",
        "organic_traffic", "organic_keywords", "referring_domains", "linked_domains",
        "person_name", "person_title", "person_source",
        "person_2_name", "person_2_title", "person_2_source",
        "person_3_name", "person_3_title", "person_3_source",
        "phone_numbers", "contact_page", "company_page",
        "discovery_method", "discovered_from",
    ]
    existing_cols = [c for c in preferred_order if c in merged.columns]
    other_cols = [c for c in merged.columns if c not in preferred_order]
    merged = merged[existing_cols + other_cols]

    # Rename columns for Japanese output
    column_names = {
        "target": "ドメイン",
        "company_name": "企業名",
        "industry": "業界",
        "domain_rating": "DR",
        "ahrefs_rank": "Ahrefsランク",
        "organic_traffic": "オーガニックトラフィック",
        "organic_keywords": "オーガニックKW数",
        "referring_domains": "被リンクドメイン数",
        "linked_domains": "発リンクドメイン数",
        "person_name": "担当者名",
        "person_title": "役職",
        "person_source": "情報ソース",
        "person_2_name": "担当者名2",
        "person_2_title": "役職2",
        "person_2_source": "情報ソース2",
        "person_3_name": "担当者名3",
        "person_3_title": "役職3",
        "person_3_source": "情報ソース3",
        "phone_numbers": "電話番号",
        "contact_page": "問い合わせページ",
        "company_page": "会社概要ページ",
        "discovery_method": "発見方法",
        "discovered_from": "発見元ドメイン",
    }
    merged = merged.rename(columns=column_names)

    # Export
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = os.path.join(output_dir, f"nw_prospect_list_{timestamp}.csv")
    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")

    xlsx_path = os.path.join(output_dir, f"nw_prospect_list_{timestamp}.xlsx")
    merged.to_excel(xlsx_path, index=False, sheet_name="Prospect List")

    print(f"  CSV:   {csv_path}")
    print(f"  Excel: {xlsx_path}")
    print(f"  Total: {len(merged)} prospects")

    # Update history with exported domains
    if update_history and "ドメイン" in merged.columns:
        exported_domains = merged["ドメイン"].tolist()
        save_history(exported_domains, history_path or os.path.join(output_dir, "history.csv"))

    return csv_path


def run_demo_mode(output_dir: str, limit: int = 50, skip_persons: bool = False):
    """Demo mode: generate list without Ahrefs API."""
    print("=" * 60)
    print("NWlist - Demo Mode (No Ahrefs API)")
    print("=" * 60)

    domains = get_all_domains()
    if limit:
        domains = domains[:limit]

    print(f"\nTarget domains: {len(domains)}")

    # Create basic DataFrame
    rows = []
    for domain in domains:
        rows.append({
            "target": domain,
            "industry": get_industry_for_domain(domain),
            "domain_rating": "N/A (API required)",
            "organic_traffic": "N/A",
            "organic_keywords": "N/A",
            "referring_domains": "N/A",
        })
    ahrefs_df = pd.DataFrame(rows)

    # Enrichment
    enrichment_df = run_enrichment(domains)

    # Person search
    person_df = pd.DataFrame()
    if not skip_persons:
        company_names = {}
        if "domain" in enrichment_df.columns and "company_name" in enrichment_df.columns:
            company_names = dict(zip(enrichment_df["domain"], enrichment_df["company_name"]))
        person_df = run_person_search(domains, company_names)

    # Export
    csv_path = merge_and_export(ahrefs_df, enrichment_df, person_df, output_dir, limit)

    print(f"\n{'=' * 60}")
    print("Done! Ahrefs APIキーを設定すると、DR・トラフィック等の")
    print("SEO指標も含めた完全なリストが生成されます。")
    print(f"{'=' * 60}")

    return csv_path


def main():
    parser = argparse.ArgumentParser(
        description="NWlist: Neutral Works ABM prospect list generator"
    )
    parser.add_argument(
        "--industry", "-i",
        choices=list(INDUSTRY_TARGETS.keys()) + ["all"],
        default="all",
        help="Target industry (default: all)",
    )
    parser.add_argument(
        "--dr-min", type=int, default=10,
        help="Minimum Domain Rating (default: 10)",
    )
    parser.add_argument(
        "--dr-max", type=int, default=70,
        help="Maximum Domain Rating (default: 70, targets with SEO upside)",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=50,
        help="Max number of prospects to output (default: 50)",
    )
    parser.add_argument(
        "--output-dir", "-o", type=str,
        default=os.getenv("OUTPUT_DIR", "./output"),
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run in demo mode without Ahrefs API",
    )
    parser.add_argument(
        "--enrich-only", action="store_true",
        help="Skip Ahrefs API, only run enrichment on domain list",
    )
    parser.add_argument(
        "--discover", action="store_true", default=True,
        help="Enable competitor auto-discovery via Ahrefs API (default: on)",
    )
    parser.add_argument(
        "--no-discover", action="store_true",
        help="Disable competitor auto-discovery",
    )
    parser.add_argument(
        "--discovery-seeds", type=int, default=30,
        help="Number of seed domains to use for competitor discovery (default: 30)",
    )
    parser.add_argument(
        "--skip-persons", action="store_true",
        help="Skip key person search (faster execution)",
    )
    parser.add_argument(
        "--exclude-history", action="store_true",
        help="Exclude previously exported domains (for weekly new list generation)",
    )
    parser.add_argument(
        "--history-path", type=str, default="",
        help="Path to history CSV file (default: output/history.csv)",
    )
    parser.add_argument(
        "--reset-history", action="store_true",
        help="Clear export history and start fresh",
    )
    parser.add_argument(
        "--history-stats", action="store_true",
        help="Show history statistics and exit",
    )

    args = parser.parse_args()

    history_path = args.history_path or os.path.join(args.output_dir, "history.csv")

    # History stats
    if args.history_stats:
        stats = get_history_stats(history_path)
        print("=" * 60)
        print("NWlist - Export History Stats")
        print("=" * 60)
        print(f"  Total exported domains: {stats['total_domains']}")
        print(f"  Total export runs:      {stats.get('total_exports', 'N/A')}")
        print(f"  First export:           {stats.get('first_export', 'N/A')}")
        print(f"  Last export:            {stats.get('last_export', 'N/A')}")
        return

    # Reset history
    if args.reset_history:
        if os.path.exists(history_path):
            os.remove(history_path)
            print(f"History cleared: {history_path}")
        else:
            print("No history file found.")
        return

    # Demo mode
    if args.demo or args.enrich_only:
        run_demo_mode(args.output_dir, args.limit, args.skip_persons)
        return

    # Check API token
    api_token = os.getenv("AHREFS_API_TOKEN")
    if not api_token or api_token == "your_ahrefs_api_token_here":
        print("ERROR: AHREFS_API_TOKEN not set.")
        print("  1. Copy .env.example to .env")
        print("  2. Set your Ahrefs API token")
        print("  Or run with --demo flag for demo mode.")
        sys.exit(1)

    client = AhrefsClient(api_token)

    # Get target domains
    if args.industry == "all":
        domains = get_all_domains()
        print(f"All industries: {len(domains)} domains")
    else:
        domains = get_domains_by_industry(args.industry)
        label = get_industry_label(args.industry)
        print(f"Industry: {label} ({len(domains)} domains)")

    print("=" * 60)
    print("NWlist - Neutral Works ABM Prospect List Generator")
    print("=" * 60)

    # Step 1: Ahrefs Analysis on seed domains
    ahrefs_df = run_ahrefs_analysis(client, domains, args.dr_min, args.dr_max)

    if ahrefs_df.empty:
        print("\nNo domains matched the DR filter. Try adjusting --dr-min / --dr-max.")
        sys.exit(0)

    # Step 2: Competitor Discovery (auto-expand domain list)
    if args.discover and not args.no_discover:
        seed_domains = ahrefs_df["target"].tolist()
        discovered_df = run_competitor_discovery(
            client, seed_domains,
            dr_min=args.dr_min, dr_max=args.dr_max,
            seeds_to_use=args.discovery_seeds,
        )

        if not discovered_df.empty:
            # Mark original domains
            ahrefs_df["discovery_method"] = "seed"

            # Combine seed + discovered
            ahrefs_df = pd.concat([ahrefs_df, discovered_df], ignore_index=True)

            # Remove duplicates
            if "target" in ahrefs_df.columns:
                ahrefs_df = ahrefs_df.drop_duplicates(subset=["target"], keep="first")

            print(f"  Total domains after discovery: {len(ahrefs_df)}")

    # Exclude previously exported domains
    if args.exclude_history and "target" in ahrefs_df.columns:
        all_targets = ahrefs_df["target"].tolist()
        new_targets = filter_new_domains(all_targets, history_path)

        if len(new_targets) < len(all_targets):
            ahrefs_df = ahrefs_df[ahrefs_df["target"].isin(new_targets)].reset_index(drop=True)
            print(f"  After history exclusion: {len(ahrefs_df)} new domains")

        if ahrefs_df.empty:
            print("\nAll discovered domains have been exported previously.")
            print("Try increasing --discovery-seeds or adding new seed domains.")
            sys.exit(0)

    # Step 3: Enrichment
    filtered_domains = ahrefs_df["target"].tolist()
    if args.limit:
        filtered_domains = filtered_domains[:args.limit]
    enrichment_df = run_enrichment(filtered_domains)

    # Step 4: Key Person Search
    person_df = pd.DataFrame()
    if not args.skip_persons:
        company_names = {}
        if "domain" in enrichment_df.columns and "company_name" in enrichment_df.columns:
            company_names = dict(zip(enrichment_df["domain"], enrichment_df["company_name"]))
        person_df = run_person_search(filtered_domains, company_names)

    # Step 5: Merge & Export
    csv_path = merge_and_export(ahrefs_df, enrichment_df, person_df,
                                 args.output_dir, args.limit,
                                 update_history=args.exclude_history,
                                 history_path=history_path)

    print(f"\n{'=' * 60}")
    print("Complete! Generated prospect list for Neutral Works ABM.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
