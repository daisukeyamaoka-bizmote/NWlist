# NWlist - Neutral Works ABM Prospect List Generator

Ahrefs API v3 + Webスクレイピングで、SEO/AIO/LLMO提案先のターゲットリストを自動生成するツール。

## 概要

ニュートラルワークス社のABM施策として、以下の条件でターゲット企業リストを生成:

- **自社メディア/オウンドメディアを運営**している企業
- **DR(Domain Rating)が中程度**（SEO伸びしろあり）
- **CPC高・受注単価高**の業界（HRtech、不動産、金融、士業、医療美容 etc.）
- **リスティング広告出稿中**（ウェブマーケ投資意欲あり）

## 出力項目

| 項目 | データソース |
|---|---|
| ドメイン | ターゲットリスト |
| 企業名 | Webスクレイピング |
| 業界 | カテゴリ定義 |
| DR (Domain Rating) | Ahrefs API |
| オーガニックトラフィック | Ahrefs API |
| オーガニックKW数 | Ahrefs API |
| 被リンクドメイン数 | Ahrefs API |
| 電話番号 | Webスクレイピング |
| 問い合わせページ | Webスクレイピング |
| 会社概要ページ | Webスクレイピング |

## セットアップ

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# 環境変数の設定
cp .env.example .env
# .env にAhrefs APIトークンを設定
```

## 使い方

### Ahrefs API使用（フルモード）

```bash
# 全業界 50件
python src/main.py --limit 50

# HRtech/SaaSのみ
python src/main.py --industry HRtech_BtoB_SaaS

# DR 20〜50 に絞り込み
python src/main.py --dr-min 20 --dr-max 50

# 1000件リスト生成
python src/main.py --limit 1000

# 特定業界のみ、DR指定
python src/main.py -i real_estate --dr-min 15 --dr-max 60 -n 100
```

### デモモード（APIキー不要）

```bash
# Webスクレイピングのみで企業情報を取得
python src/main.py --demo --limit 50
```

## 業界カテゴリ

| キー | 業界 |
|---|---|
| `HRtech_BtoB_SaaS` | HRtech / BtoB SaaS |
| `real_estate` | 不動産仲介・不動産テック |
| `finance_insurance` | 金融・保険・投資 |
| `legal_professional` | 法律・士業 |
| `medical_beauty` | 医療・美容クリニック |
| `education_edtech` | 教育・EdTech |
| `recruitment_hr` | 人材紹介・転職 |
| `wedding_bridal` | ウェディング・ブライダル |
| `auto_lease` | 自動車・中古車・カーリース |
| `btob_marketing` | BtoBマーケティング・MA/CRM |

## ドメインリストの拡張

`src/target_domains.py` の `INDUSTRY_TARGETS` にドメインを追加することで、リストを拡張できます。

## 必要条件

- Python 3.10+
- Ahrefs API v3 トークン（Enterprise プランまたはAPI契約）
  - デモモードではAPIキー不要
