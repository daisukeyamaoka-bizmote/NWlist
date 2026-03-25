"""出力履歴管理モジュール.

過去にリストアップしたドメインを記録し、
次回実行時に除外することで毎週新しいリストを生成する。

履歴ファイル: output/history.csv
形式: domain, first_exported, export_count, last_exported
"""

import os
from datetime import datetime

import pandas as pd


DEFAULT_HISTORY_PATH = os.path.join("output", "history.csv")


def load_history(history_path: str = DEFAULT_HISTORY_PATH) -> set[str]:
    """過去に出力したドメインの一覧を読み込む."""
    if not os.path.exists(history_path):
        return set()

    try:
        df = pd.read_csv(history_path)
        return set(df["domain"].tolist())
    except Exception:
        return set()


def save_history(new_domains: list[str], history_path: str = DEFAULT_HISTORY_PATH):
    """新しく出力したドメインを履歴に追加.

    既存の履歴がある場合はマージし、export_countをインクリメント。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)

    # Load existing history
    if os.path.exists(history_path):
        try:
            existing = pd.read_csv(history_path)
        except Exception:
            existing = pd.DataFrame(columns=["domain", "first_exported", "export_count", "last_exported"])
    else:
        existing = pd.DataFrame(columns=["domain", "first_exported", "export_count", "last_exported"])

    existing_domains = set(existing["domain"].tolist()) if not existing.empty else set()

    # New entries
    new_rows = []
    for domain in new_domains:
        if domain in existing_domains:
            # Update existing entry
            idx = existing.index[existing["domain"] == domain][0]
            existing.at[idx, "export_count"] = existing.at[idx, "export_count"] + 1
            existing.at[idx, "last_exported"] = now
        else:
            new_rows.append({
                "domain": domain,
                "first_exported": now,
                "export_count": 1,
                "last_exported": now,
            })

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        existing = pd.concat([existing, new_df], ignore_index=True)

    existing.to_csv(history_path, index=False)
    print(f"  History updated: {history_path} ({len(existing)} total domains)")


def filter_new_domains(domains: list[str], history_path: str = DEFAULT_HISTORY_PATH) -> list[str]:
    """履歴に含まれないドメインのみ返す."""
    history = load_history(history_path)
    if not history:
        return domains

    new = [d for d in domains if d not in history]
    excluded = len(domains) - len(new)
    if excluded > 0:
        print(f"  Excluded {excluded} previously exported domains")
    return new


def get_history_stats(history_path: str = DEFAULT_HISTORY_PATH) -> dict:
    """履歴の統計情報を返す."""
    if not os.path.exists(history_path):
        return {"total_domains": 0, "total_exports": 0}

    try:
        df = pd.read_csv(history_path)
        return {
            "total_domains": len(df),
            "total_exports": int(df["export_count"].sum()),
            "first_export": df["first_exported"].min(),
            "last_export": df["last_exported"].max(),
        }
    except Exception:
        return {"total_domains": 0, "total_exports": 0}
