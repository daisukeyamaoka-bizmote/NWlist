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
  参照ドメイン数, 電話番号, 問い合わせページ, 会社概要ページ
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
    """Run Ahrefs batch analysis and filter by DR range.

    Args:
        client: AhrefsClient instance
        domains: List of domains to analyze
        dr_min: Minimum DR (inclusive) — lower DR = more SEO upside
        dr_max: Maximum DR (inclusive) — upper bound
    """
    print(f"\n[1/3] Ahrefs Batch Analysis ({len(domains)} domains)...")
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


def run_enrichment(domains: list[str]) -> pd.DataFrame:
    """Enrich domains with company info via web scraping."""
    print(f"\n[2/3] Enriching site info ({len(domains)} domains)...")

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


def merge_and_export(ahrefs_df: pd.DataFrame, enrichment_df: pd.DataFrame,
                      output_dir: str, limit: int | None = None) -> str:
    """Merge Ahrefs data with enrichment data and export."""
    print(f"\n[3/3] Merging & exporting...")

    # Merge on domain/target
    if "target" in ahrefs_df.columns and "domain" in enrichment_df.columns:
        merged = ahrefs_df.merge(enrichment_df, left_on="target", right_on="domain", how="left")
    else:
        merged = ahrefs_df

    if limit:
        merged = merged.head(limit)

    # Reorder columns for readability
    preferred_order = [
        "target", "company_name", "industry", "domain_rating", "ahrefs_rank",
        "organic_traffic", "organic_keywords", "referring_domains", "linked_domains",
        "phone_numbers", "contact_page", "company_page",
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
        "phone_numbers": "電話番号",
        "contact_page": "問い合わせページ",
        "company_page": "会社概要ページ",
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

    return csv_path


def run_demo_mode(output_dir: str, limit: int = 50):
    """Demo mode: generate list without Ahrefs API (uses domain list + enrichment only).

    APIキーがない場合でもドメインリストからスクレイピングベースの
    リストを生成できるデモモード。
    """
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

    # Export
    csv_path = merge_and_export(ahrefs_df, enrichment_df, output_dir, limit)

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

    args = parser.parse_args()

    # Demo mode
    if args.demo or args.enrich_only:
        run_demo_mode(args.output_dir, args.limit)
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

    # Step 1: Ahrefs Analysis
    ahrefs_df = run_ahrefs_analysis(client, domains, args.dr_min, args.dr_max)

    if ahrefs_df.empty:
        print("\nNo domains matched the DR filter. Try adjusting --dr-min / --dr-max.")
        sys.exit(0)

    # Step 2: Enrichment
    filtered_domains = ahrefs_df["target"].tolist()
    if args.limit:
        filtered_domains = filtered_domains[:args.limit]
    enrichment_df = run_enrichment(filtered_domains)

    # Step 3: Merge & Export
    csv_path = merge_and_export(ahrefs_df, enrichment_df, args.output_dir, args.limit)

    print(f"\n{'=' * 60}")
    print("Complete! Generated prospect list for Neutral Works ABM.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
