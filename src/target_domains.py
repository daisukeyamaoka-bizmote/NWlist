"""Target industry domains for Neutral Works ABM campaign.

ターゲット条件:
- CPC 1,000円以上の業界
- 受注単価 数百万円以上
- 粗利率が高い
- ウェブマーケティング浸透済み
- リスティング広告出稿が盛ん

カテゴリ:
1. HRtech / BtoB SaaS
2. 不動産仲介・不動産テック
3. 金融（保険・投資・ローン・クレジットカード）
4. 法律・士業
5. 医療・美容クリニック
6. 教育・EdTech
7. 人材紹介・転職
8. ウェディング・ブライダル
9. 自動車（中古車・カーリース）
10. BtoBマーケティング・MA/CRM
"""

# 業界カテゴリとターゲットドメインの定義
INDUSTRY_TARGETS: dict[str, dict] = {
    "HRtech_BtoB_SaaS": {
        "label": "HRtech / BtoB SaaS",
        "domains": [
            "smarthr.jp",
            "hrbrain.jp",
            "kaonavi.jp",
            "jinjer.biz",
            "teamspirit.com",
            "freee.co.jp",
            "moneyforward.com",
            "cybozu.co.jp",
            "sansan.com",
            "chatwork.com",
            "biz.and-and.co.jp",
            "hrmos.co",
            "talentio.com",
            "minagine.jp",
            "obc.co.jp",
            "king-of-time.jp",
            "jobcan.ne.jp",
            "rakurakumeisai.jp",
            "works-hi.co.jp",
            "hennge.com",
            "yayoi-kk.co.jp",
            "boxil.jp",
            "itreview.jp",
            "and-and.co.jp",
            "satori.marketing",
            "b-dash.com",
            "plaid.co.jp",
            "repro.io",
            "because-intelligence.com",
            "salesforce.com",
            "hubspot.jp",
            "marketo.com",
            "pardot.com",
            "zoho.com",
            "kintone.cybozu.co.jp",
            "notion.so",
            "backlog.com",
            "wrike.com",
            "asana.com",
            "trello.com",
            "slack.com",
            "zoom.us",
            "whereby.com",
            "bellface.jp",
            "miitel.com",
            "andpad.co.jp",
            "shakehands.co.jp",
            "receptionist.jp",
            "airregi.jp",
            "smaregi.jp",
        ],
    },
    "real_estate": {
        "label": "不動産仲介・不動産テック",
        "domains": [
            "suumo.jp",
            "homes.co.jp",
            "athome.co.jp",
            "nomu.com",
            "rehouse.co.jp",
            "livable.co.jp",
            "sumitomo-rd.co.jp",
            "tokyu-livable.co.jp",
            "century21.jp",
            "housedo.co.jp",
            "openhouse-group.com",
            "katitas.jp",
            "property-bank.co.jp",
            "ga-tech.co.jp",
            "renosy.com",
            "ielove.co.jp",
            "ieshil.com",
            "cowcamo.jp",
            "mansion-review.jp",
            "o-uccino.jp",
            "smocca.jp",
            "chintai.net",
            "apamanshop.com",
            "minimini.jp",
            "eheya.net",
            "door.ac",
            "oheyago.jp",
            "canary-app.jp",
            "sumai-surfin.com",
            "reds.co.jp",
        ],
    },
    "finance_insurance": {
        "label": "金融・保険・投資",
        "domains": [
            "hoken-clinic.com",
            "hokende.com",
            "hokenmarket.net",
            "fp-moneydoctor.com",
            "zexy-en-soudan.net",
            "kakaku.com",
            "money-book.jp",
            "rakuten-sec.co.jp",
            "sbisec.co.jp",
            "monex.co.jp",
            "matsui.co.jp",
            "kabu.com",
            "dmm.com",
            "gmo-click.com",
            "line-sec.co.jp",
            "smbc-card.com",
            "jcb.co.jp",
            "saisoncard.co.jp",
            "orico.co.jp",
            "acom.co.jp",
            "promise.co.jp",
            "lake.jp",
            "aiful.co.jp",
            "mobit.ne.jp",
            "flat35.com",
            "jutakuloan.mamoris.jp",
            "cardloan-shinsa.jp",
            "navinavi-hoken.com",
            "o-clinic.com",
            "sumai-value.jp",
        ],
    },
    "legal_professional": {
        "label": "法律・士業",
        "domains": [
            "bengo4.com",
            "bengoshi.com",
            "legalmedia.jp",
            "rikon-pro.com",
            "samurai-law.com",
            "zeirishi.or.jp",
            "freee.co.jp",
            "biz.moneyforward.com",
            "zeiri4.com",
            "sozoku-pro.info",
            "souzoku-zeirishi.jp",
            "shiho-shoshi.or.jp",
            "sr-osaka.jp",
            "sharoushi.or.jp",
            "lancers.jp",
            "crowdworks.jp",
            "coconala.com",
            "saimu4.com",
            "hasan-web.jp",
            "adire.jp",
        ],
    },
    "medical_beauty": {
        "label": "医療・美容クリニック",
        "domains": [
            "s-b-c.net",
            "tcb-beauty.net",
            "biyougeka.com",
            "takasu.co.jp",
            "shinagawa.com",
            "noel-clinic.com",
            "aoyamaceles.com",
            "gorilla.clinic",
            "rizeclinic.com",
            "reginaclinic.jp",
            "musee-pla.com",
            "be-escort.com",
            "mens-rize.com",
            "rinx.co.jp",
            "datumou-labo.jp",
            "aga-yobou.jp",
            "agaskin.net",
            "aga-clinic.com",
            "hairs-medical.com",
            "caloo.jp",
            "byoinnavi.jp",
            "doctorsfile.jp",
            "clinicfor.life",
            "dmmclinic.com",
            "emishia-clinic.jp",
            "tokyobeauty.jp",
            "asc-clinic.jp",
            "kirei-c.com",
            "mypearl.jp",
            "lucmo.jp",
        ],
    },
    "education_edtech": {
        "label": "教育・EdTech",
        "domains": [
            "studysapuri.jp",
            "benesse.co.jp",
            "zkai.co.jp",
            "shingakunet.com",
            "schoolie.jp",
            "progate.com",
            "schoo.jp",
            "udemy.com",
            "techacademy.jp",
            "codecamp.jp",
            "dmm.com",
            "runteq.jp",
            "dive-into-code.jp",
            "tech-camp.in",
            "potepan.com",
            "tech-is.jp",
            "internet-academy.co.jp",
            "winschool.jp",
            "aviva.co.jp",
            "nativecamps.com",
        ],
    },
    "recruitment_hr": {
        "label": "人材紹介・転職",
        "domains": [
            "recruit.co.jp",
            "doda.jp",
            "mynavi.jp",
            "en-japan.com",
            "type.jp",
            "bizreach.jp",
            "green-japan.com",
            "wantedly.com",
            "geekly.co.jp",
            "levtech.jp",
            "workport.co.jp",
            "r-agent.com",
            "pasona.co.jp",
            "jac-recruitment.jp",
            "randstad.co.jp",
            "hays.co.jp",
            "robertwalters.co.jp",
            "michaelpage.co.jp",
            "itstaffing.jp",
            "careerindex.jp",
        ],
    },
    "wedding_bridal": {
        "label": "ウェディング・ブライダル",
        "domains": [
            "zexy.net",
            "mywedding.jp",
            "weddingpark.net",
            "hanayume.com",
            "sugukon.com",
            "photorait.net",
            "primavera.co.jp",
            "tgn.co.jp",
            "bestbridal.co.jp",
            "watabe-wedding.co.jp",
        ],
    },
    "auto_lease": {
        "label": "自動車・中古車・カーリース",
        "domains": [
            "carsensor.net",
            "goo-net.com",
            "kurumaerabi.com",
            "autoc-one.jp",
            "carview.co.jp",
            "navikuru.jp",
            "kinto-jp.com",
            "carlease-online.jp",
            "cosmo-mycar.com",
            "sompo-de-noru.jp",
        ],
    },
    "btob_marketing": {
        "label": "BtoBマーケティング・MA/CRM",
        "domains": [
            "ferret-plus.com",
            "markezine.jp",
            "webtan.impress.co.jp",
            "liskul.com",
            "contentmarketinglab.jp",
            "wacul.co.jp",
            "basicinc.jp",
            "innova-jp.com",
            "willgate.co.jp",
            "plan-b.co.jp",
            "digitalidentity.co.jp",
            "gyro-n.com",
            "ahrefs.jp",
            "semrush.com",
            "mieruca.co.jp",
            "search-write.jp",
            "seohacks.net",
            "seo-hacker.jp",
            "allegro-inc.com",
            "and-and.co.jp",
        ],
    },
}


def get_all_domains() -> list[str]:
    """Get all target domains as a flat list (deduplicated)."""
    seen = set()
    domains = []
    for industry in INDUSTRY_TARGETS.values():
        for domain in industry["domains"]:
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
    return domains


def get_domains_by_industry(industry_key: str) -> list[str]:
    """Get domains for a specific industry."""
    if industry_key not in INDUSTRY_TARGETS:
        raise ValueError(
            f"Unknown industry: {industry_key}. "
            f"Available: {list(INDUSTRY_TARGETS.keys())}"
        )
    return INDUSTRY_TARGETS[industry_key]["domains"]


def get_industry_label(industry_key: str) -> str:
    """Get the Japanese label for an industry."""
    return INDUSTRY_TARGETS[industry_key]["label"]
