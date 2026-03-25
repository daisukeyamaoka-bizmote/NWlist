"""NWlist Web UI - リスト生成をブラウザから操作."""

import io
import os
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, send_file

load_dotenv()

# Add src to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from ahrefs_client import AhrefsClient
from enrichment import enrich_domains_batch
from history import filter_new_domains, get_history_stats, save_history
from person_finder import find_key_persons_batch
from target_domains import INDUSTRY_TARGETS, get_all_domains, get_domains_by_industry

import pandas as pd

app = Flask(__name__)

OUTPUT_BASE = os.path.join(os.path.dirname(__file__), "..", "output")

# Job state
_job_lock = threading.Lock()
_job_state = {
    "running": False,
    "progress": "",
    "step": 0,
    "total_steps": 5,
    "error": "",
    "result_path": "",
}


def _update_progress(step: int, message: str):
    _job_state["step"] = step
    _job_state["progress"] = message


def _get_date_output_dir(base: str = OUTPUT_BASE) -> str:
    """今日の日付フォルダを返す (output/2026-03-25/)."""
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(base, today)
    os.makedirs(path, exist_ok=True)
    return path


def _get_industry_for_domain(domain: str) -> str:
    for key, info in INDUSTRY_TARGETS.items():
        if domain in info["domains"]:
            return info["label"]
    return "不明"


def _run_list_generation(industry: str, limit: int, dr_min: int, dr_max: int,
                          exclude_history: bool, discovery_seeds: int,
                          skip_persons: bool):
    """バックグラウンドでリスト生成を実行."""
    try:
        output_dir = _get_date_output_dir()
        history_path = os.path.join(OUTPUT_BASE, "history.csv")

        api_token = os.getenv("AHREFS_API_TOKEN")
        is_demo = not api_token or api_token == "your_ahrefs_api_token_here"

        # Get target domains
        if industry == "all":
            domains = get_all_domains()
        else:
            domains = get_domains_by_industry(industry)

        # === Step 1: Ahrefs Analysis ===
        _update_progress(1, f"Ahrefs分析中... ({len(domains)} ドメイン)")

        if is_demo:
            # Demo mode - no API
            rows = []
            for domain in domains:
                rows.append({
                    "target": domain,
                    "industry": _get_industry_for_domain(domain),
                    "domain_rating": "N/A",
                    "organic_traffic": "N/A",
                    "organic_keywords": "N/A",
                    "referring_domains": "N/A",
                })
            ahrefs_df = pd.DataFrame(rows)
        else:
            client = AhrefsClient(api_token)
            results = client.batch_analysis_chunked(domains)
            ahrefs_df = pd.DataFrame(results)

            if "domain_rating" in ahrefs_df.columns:
                ahrefs_df["domain_rating"] = pd.to_numeric(ahrefs_df["domain_rating"], errors="coerce")
                ahrefs_df = ahrefs_df[
                    (ahrefs_df["domain_rating"] >= dr_min) & (ahrefs_df["domain_rating"] <= dr_max)
                ]

            if "target" in ahrefs_df.columns:
                ahrefs_df["industry"] = ahrefs_df["target"].apply(_get_industry_for_domain)

            if "organic_traffic" in ahrefs_df.columns:
                ahrefs_df = ahrefs_df.sort_values("organic_traffic", ascending=False)

            ahrefs_df = ahrefs_df.reset_index(drop=True)

        # === Step 2: Competitor Discovery ===
        _update_progress(2, "競合ドメイン発見中...")

        if not is_demo and "target" in ahrefs_df.columns:
            seed_domains = ahrefs_df["target"].tolist()[:discovery_seeds]
            discovered = client.discover_competitors_for_seeds(
                seed_domains, per_seed_limit=20, dr_min=dr_min, dr_max=dr_max,
            )
            if discovered:
                disc_df = pd.DataFrame(discovered)
                if "domain" in disc_df.columns:
                    disc_df = disc_df.rename(columns={"domain": "target"})
                disc_df["discovery_method"] = "auto"
                ahrefs_df["discovery_method"] = "seed"
                ahrefs_df = pd.concat([ahrefs_df, disc_df], ignore_index=True)
                ahrefs_df = ahrefs_df.drop_duplicates(subset=["target"], keep="first")
        else:
            _update_progress(2, "競合発見スキップ（デモモード）")

        # Exclude history
        if exclude_history and "target" in ahrefs_df.columns:
            new_targets = filter_new_domains(ahrefs_df["target"].tolist(), history_path)
            ahrefs_df = ahrefs_df[ahrefs_df["target"].isin(new_targets)].reset_index(drop=True)

        if ahrefs_df.empty:
            _job_state["error"] = "対象ドメインが見つかりませんでした。履歴をリセットするか、条件を変更してください。"
            _job_state["running"] = False
            return

        # Apply limit
        filtered_domains = ahrefs_df["target"].tolist()[:limit]

        # === Step 3: Enrichment ===
        _update_progress(3, f"企業情報取得中... ({len(filtered_domains)} 件)")

        enrichment_results = enrich_domains_batch(filtered_domains)
        enrichment_df = pd.DataFrame(enrichment_results)
        if "phone_numbers" in enrichment_df.columns:
            enrichment_df["phone_numbers"] = enrichment_df["phone_numbers"].apply(
                lambda x: " / ".join(x) if isinstance(x, list) else ""
            )

        # === Step 4: Person Search ===
        person_df = pd.DataFrame()
        if not skip_persons:
            _update_progress(4, f"担当者調査中... ({len(filtered_domains)} 件)")
            company_names = {}
            if "domain" in enrichment_df.columns and "company_name" in enrichment_df.columns:
                company_names = dict(zip(enrichment_df["domain"], enrichment_df["company_name"]))
            pairs = [(d, company_names.get(d, "")) for d in filtered_domains]
            person_results = find_key_persons_batch(pairs)

            rows = []
            for domain, persons in person_results.items():
                if persons:
                    best = persons[0]
                    row = {
                        "domain": domain,
                        "person_name": best["person_name"],
                        "person_title": best["person_title"],
                        "person_source": best["person_source"],
                    }
                    for i, p in enumerate(persons[1:3], start=2):
                        row[f"person_{i}_name"] = p["person_name"]
                        row[f"person_{i}_title"] = p["person_title"]
                        row[f"person_{i}_source"] = p["person_source"]
                else:
                    row = {"domain": domain, "person_name": "", "person_title": "", "person_source": ""}
                rows.append(row)
            person_df = pd.DataFrame(rows)
        else:
            _update_progress(4, "担当者調査スキップ")

        # === Step 5: Export ===
        _update_progress(5, "Excel出力中...")

        # Merge
        if "target" in ahrefs_df.columns and "domain" in enrichment_df.columns:
            merged = ahrefs_df.merge(enrichment_df, left_on="target", right_on="domain", how="left")
        else:
            merged = ahrefs_df

        if not person_df.empty and "target" in merged.columns and "domain" in person_df.columns:
            merged = merged.merge(person_df, left_on="target", right_on="domain",
                                   how="left", suffixes=("", "_person"))
            if "domain_person" in merged.columns:
                merged = merged.drop(columns=["domain_person"])

        merged = merged.head(limit)

        # Reorder & rename
        preferred_order = [
            "target", "company_name", "industry", "domain_rating", "ahrefs_rank",
            "organic_traffic", "organic_keywords", "referring_domains", "linked_domains",
            "person_name", "person_title", "person_source",
            "person_2_name", "person_2_title", "person_2_source",
            "person_3_name", "person_3_title", "person_3_source",
            "phone_numbers", "contact_page", "company_page",
            "freshness_status", "last_updated", "freshness_detail",
            "discovery_method", "discovered_from",
        ]
        existing_cols = [c for c in preferred_order if c in merged.columns]
        other_cols = [c for c in merged.columns if c not in preferred_order]
        merged = merged[existing_cols + other_cols]

        column_names = {
            "target": "ドメイン", "company_name": "企業名", "industry": "業界",
            "domain_rating": "DR", "ahrefs_rank": "Ahrefsランク",
            "organic_traffic": "オーガニックトラフィック", "organic_keywords": "オーガニックKW数",
            "referring_domains": "被リンクドメイン数", "linked_domains": "発リンクドメイン数",
            "person_name": "担当者名", "person_title": "役職", "person_source": "情報ソース",
            "person_2_name": "担当者名2", "person_2_title": "役職2", "person_2_source": "情報ソース2",
            "person_3_name": "担当者名3", "person_3_title": "役職3", "person_3_source": "情報ソース3",
            "phone_numbers": "電話番号", "contact_page": "問い合わせページ",
            "company_page": "会社概要ページ",
            "freshness_status": "鮮度ステータス", "last_updated": "最終更新",
            "freshness_detail": "鮮度チェック詳細",
            "discovery_method": "発見方法", "discovered_from": "発見元ドメイン",
        }
        merged = merged.rename(columns=column_names)

        timestamp = datetime.now().strftime("%H%M%S")
        csv_path = os.path.join(output_dir, f"prospect_list_{timestamp}.csv")
        merged.to_csv(csv_path, index=False, encoding="utf-8-sig")

        xlsx_path = os.path.join(output_dir, f"prospect_list_{timestamp}.xlsx")
        merged.to_excel(xlsx_path, index=False, sheet_name="Prospect List")

        # Update history
        if exclude_history and "ドメイン" in merged.columns:
            save_history(merged["ドメイン"].tolist(), os.path.join(OUTPUT_BASE, "history.csv"))

        # Freshness summary
        freshness_col = "鮮度ステータス"
        if freshness_col in merged.columns:
            ok_count = (merged[freshness_col] == "OK").sum()
            stale_count = (merged[freshness_col] == "STALE").sum()
            unknown_count = (merged[freshness_col] == "UNKNOWN").sum()
            freshness_msg = f"（鮮度: OK {ok_count}件 / 要確認 {stale_count}件 / 不明 {unknown_count}件）"
        else:
            freshness_msg = ""

        _job_state["result_path"] = output_dir
        _update_progress(5, f"完了！ {len(merged)} 件のリストを生成しました {freshness_msg}")

    except Exception as e:
        _job_state["error"] = str(e)
    finally:
        _job_state["running"] = False


# ============================================================
# HTML Template
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NWlist - ABMリスト生成ツール</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #333; }
.header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 24px 32px; }
.header h1 { font-size: 22px; font-weight: 600; }
.header p { font-size: 13px; color: #8892b0; margin-top: 4px; }
.container { max-width: 960px; margin: 32px auto; padding: 0 24px; }

/* Generate Card */
.card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 28px; margin-bottom: 24px; }
.card h2 { font-size: 17px; margin-bottom: 20px; color: #1a1a2e; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 13px; font-weight: 500; color: #555; }
.form-group select, .form-group input { padding: 9px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #4a6cf7; }
.checkbox-group { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.checkbox-group input[type="checkbox"] { width: 16px; height: 16px; }
.checkbox-group label { font-size: 13px; color: #555; }

.btn-generate { background: linear-gradient(135deg, #4a6cf7 0%, #6366f1 100%); color: white; border: none;
  padding: 14px 32px; border-radius: 10px; font-size: 15px; font-weight: 600; cursor: pointer;
  width: 100%; transition: opacity 0.2s; }
.btn-generate:hover { opacity: 0.9; }
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }

/* Progress */
.progress-area { display: none; margin-top: 20px; }
.progress-area.active { display: block; }
.progress-bar-bg { background: #e9ecef; border-radius: 8px; height: 8px; overflow: hidden; }
.progress-bar { background: linear-gradient(90deg, #4a6cf7, #6366f1); height: 100%; border-radius: 8px;
  transition: width 0.5s ease; }
.progress-text { font-size: 13px; color: #666; margin-top: 8px; }
.progress-steps { display: flex; justify-content: space-between; margin-top: 12px; }
.step { font-size: 11px; color: #aaa; }
.step.active { color: #4a6cf7; font-weight: 600; }
.step.done { color: #22c55e; }

/* History */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-box { background: #f8f9fc; border-radius: 8px; padding: 16px; text-align: center; }
.stat-box .num { font-size: 28px; font-weight: 700; color: #1a1a2e; }
.stat-box .label { font-size: 12px; color: #888; margin-top: 4px; }

/* File list */
.date-group { margin-bottom: 16px; }
.date-header { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #f8f9fc; border-radius: 8px 8px 0 0; border-bottom: 1px solid #eee; }
.date-header h3 { font-size: 14px; color: #333; }
.btn-download-all { background: #22c55e; color: white; border: none; padding: 6px 16px;
  border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; text-decoration: none; }
.btn-download-all:hover { opacity: 0.9; }
.file-list { list-style: none; }
.file-item { display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; border-bottom: 1px solid #f0f0f0; }
.file-item:last-child { border-bottom: none; border-radius: 0 0 8px 8px; }
.file-name { font-size: 13px; color: #333; }
.file-size { font-size: 12px; color: #999; }
.btn-dl { background: none; border: 1px solid #ddd; padding: 4px 12px; border-radius: 6px;
  font-size: 12px; cursor: pointer; color: #555; text-decoration: none; }
.btn-dl:hover { border-color: #4a6cf7; color: #4a6cf7; }
.empty { text-align: center; padding: 40px; color: #999; font-size: 14px; }

.error-msg { background: #fef2f2; border: 1px solid #fecaca; color: #dc2626;
  padding: 12px 16px; border-radius: 8px; margin-top: 12px; font-size: 13px; display: none; }
.error-msg.active { display: block; }
</style>
</head>
<body>
<div class="header">
  <h1>NWlist</h1>
  <p>Neutral Works ABM Prospect List Generator</p>
</div>

<div class="container">
  <!-- Generate Card -->
  <div class="card">
    <h2>新規リスト作成</h2>
    <div class="form-grid">
      <div class="form-group">
        <label>業界</label>
        <select id="industry">
          <option value="all">全業界</option>
          {% for key, info in industries.items() %}
          <option value="{{ key }}">{{ info.label }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="form-group">
        <label>件数上限</label>
        <input type="number" id="limit" value="1000" min="10" max="5000">
      </div>
      <div class="form-group">
        <label>DR下限</label>
        <input type="number" id="dr_min" value="10" min="0" max="100">
      </div>
      <div class="form-group">
        <label>DR上限</label>
        <input type="number" id="dr_max" value="70" min="0" max="100">
      </div>
    </div>
    <div class="checkbox-group">
      <input type="checkbox" id="exclude_history" checked>
      <label for="exclude_history">過去に出力したドメインを除外する（毎週新規リスト用）</label>
    </div>
    <div class="checkbox-group" style="margin-bottom: 20px;">
      <input type="checkbox" id="skip_persons">
      <label for="skip_persons">担当者調査をスキップする（高速モード）</label>
    </div>
    <button class="btn-generate" id="btn-generate" onclick="startGeneration()">
      新規リスト作成
    </button>

    <div class="progress-area" id="progress-area">
      <div class="progress-bar-bg"><div class="progress-bar" id="progress-bar" style="width: 0%"></div></div>
      <div class="progress-text" id="progress-text">準備中...</div>
      <div class="progress-steps">
        <span class="step" id="step-1">1. Ahrefs分析</span>
        <span class="step" id="step-2">2. 競合発見</span>
        <span class="step" id="step-3">3. 企業情報</span>
        <span class="step" id="step-4">4. 担当者調査</span>
        <span class="step" id="step-5">5. Excel出力</span>
      </div>
    </div>
    <div class="error-msg" id="error-msg"></div>
  </div>

  <!-- Stats Card -->
  <div class="card">
    <h2>出力履歴</h2>
    <div class="stats-grid" id="stats-grid">
      <div class="stat-box"><div class="num" id="stat-total">-</div><div class="label">累計ドメイン数</div></div>
      <div class="stat-box"><div class="num" id="stat-dates">-</div><div class="label">作成日数</div></div>
      <div class="stat-box"><div class="num" id="stat-last">-</div><div class="label">最終作成日</div></div>
    </div>
  </div>

  <!-- File List Card -->
  <div class="card">
    <h2>作成済みリスト</h2>
    <div id="file-list-area"><div class="empty">リストはまだ作成されていません</div></div>
  </div>
</div>

<script>
let pollTimer = null;

function startGeneration() {
  const btn = document.getElementById('btn-generate');
  btn.disabled = true;
  btn.textContent = '生成中...';
  document.getElementById('progress-area').classList.add('active');
  document.getElementById('error-msg').classList.remove('active');

  const params = new URLSearchParams({
    industry: document.getElementById('industry').value,
    limit: document.getElementById('limit').value,
    dr_min: document.getElementById('dr_min').value,
    dr_max: document.getElementById('dr_max').value,
    exclude_history: document.getElementById('exclude_history').checked,
    skip_persons: document.getElementById('skip_persons').checked,
  });

  fetch('/api/generate?' + params, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        showError(data.error);
        resetBtn();
        return;
      }
      pollTimer = setInterval(pollProgress, 1000);
    })
    .catch(e => { showError(e.message); resetBtn(); });
}

function pollProgress() {
  fetch('/api/progress')
    .then(r => r.json())
    .then(data => {
      const pct = Math.round((data.step / data.total_steps) * 100);
      document.getElementById('progress-bar').style.width = pct + '%';
      document.getElementById('progress-text').textContent = data.progress;

      for (let i = 1; i <= 5; i++) {
        const el = document.getElementById('step-' + i);
        el.className = 'step' + (i < data.step ? ' done' : (i === data.step ? ' active' : ''));
      }

      if (!data.running) {
        clearInterval(pollTimer);
        if (data.error) {
          showError(data.error);
        }
        resetBtn();
        loadFiles();
        loadStats();
      }
    });
}

function showError(msg) {
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.classList.add('active');
}

function resetBtn() {
  const btn = document.getElementById('btn-generate');
  btn.disabled = false;
  btn.textContent = '新規リスト作成';
}

function loadFiles() {
  fetch('/api/files')
    .then(r => r.json())
    .then(data => {
      const area = document.getElementById('file-list-area');
      if (!data.dates || data.dates.length === 0) {
        area.innerHTML = '<div class="empty">リストはまだ作成されていません</div>';
        return;
      }
      let html = '';
      data.dates.forEach(d => {
        html += '<div class="date-group">';
        html += '<div class="date-header"><h3>' + d.date + '</h3>';
        html += '<a class="btn-download-all" href="/download/zip/' + d.date + '">一括ダウンロード (.zip)</a></div>';
        html += '<ul class="file-list">';
        d.files.forEach(f => {
          html += '<li class="file-item">';
          html += '<span class="file-name">' + f.name + '</span>';
          html += '<span><span class="file-size">' + f.size + '</span> ';
          html += '<a class="btn-dl" href="/download/file/' + d.date + '/' + f.name + '">DL</a></span>';
          html += '</li>';
        });
        html += '</ul></div>';
      });
      area.innerHTML = html;
    });
}

function loadStats() {
  fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
      document.getElementById('stat-total').textContent = data.total_domains.toLocaleString();
      document.getElementById('stat-dates').textContent = data.date_count;
      document.getElementById('stat-last').textContent = data.last_export || '-';
    });
}

// Load on page ready
loadFiles();
loadStats();
</script>
</body>
</html>
"""


# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, industries=INDUSTRY_TARGETS)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    with _job_lock:
        if _job_state["running"]:
            return jsonify({"error": "既にリスト生成が実行中です。完了までお待ちください。"})

        _job_state["running"] = True
        _job_state["progress"] = "開始中..."
        _job_state["step"] = 0
        _job_state["error"] = ""
        _job_state["result_path"] = ""

    from flask import request
    industry = request.args.get("industry", "all")
    limit = int(request.args.get("limit", 1000))
    dr_min = int(request.args.get("dr_min", 10))
    dr_max = int(request.args.get("dr_max", 70))
    exclude_history = request.args.get("exclude_history", "true") == "true"
    skip_persons = request.args.get("skip_persons", "false") == "true"
    discovery_seeds = 30

    thread = threading.Thread(
        target=_run_list_generation,
        args=(industry, limit, dr_min, dr_max, exclude_history, discovery_seeds, skip_persons),
        daemon=True,
    )
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/progress")
def api_progress():
    return jsonify(_job_state)


@app.route("/api/stats")
def api_stats():
    history_stats = get_history_stats(os.path.join(OUTPUT_BASE, "history.csv"))

    # Count date folders
    date_count = 0
    if os.path.exists(OUTPUT_BASE):
        for name in os.listdir(OUTPUT_BASE):
            if os.path.isdir(os.path.join(OUTPUT_BASE, name)) and len(name) == 10:
                date_count += 1

    return jsonify({
        "total_domains": history_stats.get("total_domains", 0),
        "date_count": date_count,
        "last_export": history_stats.get("last_export", ""),
    })


@app.route("/api/files")
def api_files():
    if not os.path.exists(OUTPUT_BASE):
        return jsonify({"dates": []})

    dates = []
    for name in sorted(os.listdir(OUTPUT_BASE), reverse=True):
        dir_path = os.path.join(OUTPUT_BASE, name)
        if not os.path.isdir(dir_path) or len(name) != 10:
            continue

        files = []
        for fname in sorted(os.listdir(dir_path)):
            fpath = os.path.join(dir_path, fname)
            if os.path.isfile(fpath):
                size_bytes = os.path.getsize(fpath)
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024*1024):.1f} MB"
                files.append({"name": fname, "size": size_str})

        if files:
            dates.append({"date": name, "files": files})

    return jsonify({"dates": dates})


@app.route("/download/file/<date>/<filename>")
def download_file(date, filename):
    """個別ファイルダウンロード."""
    # Prevent path traversal
    safe_date = os.path.basename(date)
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_BASE, safe_date, safe_name)

    if not os.path.exists(file_path):
        return "File not found", 404

    return send_file(file_path, as_attachment=True)


@app.route("/download/zip/<date>")
def download_zip(date):
    """日付フォルダのファイルを一括ZIPダウンロード."""
    safe_date = os.path.basename(date)
    dir_path = os.path.join(OUTPUT_BASE, safe_date)

    if not os.path.isdir(dir_path):
        return "Date folder not found", 404

    # Create ZIP in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(dir_path):
            fpath = os.path.join(dir_path, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, fname)

    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"nwlist_{safe_date}.zip",
    )


if __name__ == "__main__":
    os.makedirs(OUTPUT_BASE, exist_ok=True)
    print("=" * 50)
    print("NWlist Web UI")
    print("http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
