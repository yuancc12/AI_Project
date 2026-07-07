# -*- coding: utf-8 -*-
"""
seed.py — 建立 AI 生活管家的 SQLite 資料庫並塞入擬真假資料。
資料模型參考統一資訊命題資料集（pms_form / pms_form_topic / sys_county ...），
為了單人黑客松開發，改用 SQLite（零安裝）並做了精簡。

執行：  python seed.py
產出：  butler.db
"""
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "butler.db")

# 題型代碼（沿用命題資料集的定義）
# 1簡答 2詳答 3單選 4複選 5地區選單 6上傳照片 7備註 8聯絡資料 9日期 10聯絡資料(不含地址)

SCHEMA = """
DROP TABLE IF EXISTS service_category;
DROP TABLE IF EXISTS pms_form;
DROP TABLE IF EXISTS pms_form_topic;
DROP TABLE IF EXISTS pms_topic_option;
DROP TABLE IF EXISTS service_vendor;
DROP TABLE IF EXISTS vendor_service_area;
DROP TABLE IF EXISTS sys_county;
DROP TABLE IF EXISTS sys_district;
DROP TABLE IF EXISTS pms_form_feedback;

-- 服務分類（對應命題的 cms_homepage_service_vendor），keyword 供 AI 判斷服務類型用
CREATE TABLE service_category (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    keywords    TEXT NOT NULL,          -- 逗號分隔，用來把使用者描述對應到此分類
    description TEXT
);

-- 表單主檔
CREATE TABLE pms_form (
    id            INTEGER PRIMARY KEY,
    category_id   INTEGER NOT NULL,
    type          TEXT NOT NULL,        -- 1 C端無評估 / 2 C端需評估(估價) ...
    sub_type      TEXT NOT NULL,        -- 1 一般 / 2 估價
    name          TEXT NOT NULL,
    intro_content TEXT,
    is_enable     TEXT NOT NULL DEFAULT '1'
);

-- 表單題目
CREATE TABLE pms_form_topic (
    id          INTEGER PRIMARY KEY,
    form_id     INTEGER NOT NULL,
    type        TEXT NOT NULL,          -- 見上方題型代碼
    title       TEXT NOT NULL,
    remark      TEXT,
    is_required TEXT NOT NULL DEFAULT '0',
    sort        INTEGER NOT NULL
);

-- 題目選項（單選/複選用；有單價即可做估價）
CREATE TABLE pms_topic_option (
    id          INTEGER PRIMARY KEY,
    topic_id    INTEGER NOT NULL,
    option_name TEXT NOT NULL,
    unit_price  INTEGER,
    unit        TEXT,
    sort        INTEGER NOT NULL
);

-- 服務廠商
CREATE TABLE service_vendor (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    rating      REAL NOT NULL DEFAULT 4.5,
    phone       TEXT
);

-- 廠商服務範圍（哪個廠商服務哪個行政區）
CREATE TABLE vendor_service_area (
    vendor_id     INTEGER NOT NULL,
    county_code   TEXT NOT NULL,
    district_code TEXT NOT NULL
);

-- 縣市 / 行政區
CREATE TABLE sys_county (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE sys_district (
    code        TEXT PRIMARY KEY,
    county_code TEXT NOT NULL,
    name        TEXT NOT NULL,
    zip         TEXT
);

-- 使用者帳號
CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT UNIQUE NOT NULL,
    password   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 留資單 / 諮詢單（消費者填完的需求）
CREATE TABLE pms_form_feedback (
    feedback_no    TEXT PRIMARY KEY,
    form_id        INTEGER NOT NULL,
    category_id    INTEGER NOT NULL,
    user_id        INTEGER,
    contact_name   TEXT,
    contact_mobile TEXT,
    county_code    TEXT,
    district_code  TEXT,
    description    TEXT,
    answers_json   TEXT,
    status         TEXT NOT NULL DEFAULT '01',  -- 01待處理 02已聯繫 03已承接 80已完成
    is_read        TEXT NOT NULL DEFAULT '0',
    cre_time       TEXT NOT NULL
);
"""

# ---- 假資料 ----------------------------------------------------------------

COUNTIES = [
    ("01", "台北市"),
    ("02", "新北市"),
    ("03", "桃園市"),
    ("04", "台中市"),
    ("05", "高雄市"),
]

DISTRICTS = [
    # code, county_code, name, zip
    ("001", "01", "大安區", "106"),
    ("002", "01", "信義區", "110"),
    ("003", "01", "中山區", "104"),
    ("004", "02", "板橋區", "220"),
    ("005", "02", "三重區", "241"),
    ("006", "03", "中壢區", "320"),
    ("007", "04", "西屯區", "407"),
    ("008", "05", "左營區", "813"),
]

CATEGORIES = [
    # id, name, keywords, description
    (1, "水電修繕", "漏水,水管,馬桶,電燈,跳電,插座,修繕,水電,故障,堵塞,水龍頭,排水,漏電,燈泡,開關,冷氣,冷暖,暖氣", "家庭水電與修繕服務"),
    (2, "家事清潔", "打掃,清潔,洗衣機,家事,油污,居家清潔,大掃除,除塵,洗地,擦窗,整理,髒,臭,黴,掃地,拖地", "居家清潔與家事服務"),
    (3, "餐廳訂位", "訂位,餐廳,吃飯,聚餐,訂桌,用餐,包廂,訂餐,晚餐,午餐,早餐,飯局,宴席,慶生,吃,飯,訂晚餐,訂午餐,約吃,約飯,請客", "餐廳訂位服務"),
    (4, "商城購物", "購買,買,商品,購物,團購,限時購,預購,下單,訂購,買東西,採購", "商城購物服務"),
    (5, "美食外送", "外送,送餐,叫餐,外帶,便當,叫外賣,外賣,點餐,送到家,宅配餐,宅配食,叫食,送食物", "美食外送服務"),
]

# 表單 + 題目 + 選項
FORMS = [
    {
        "form": (1, 1, "2", "2", "水電修繕估價單", "描述您的修繕需求，師傅將為您報價"),
        "topics": [
            # id, form_id, type, title, remark, is_required, sort
            (101, 1, "2", "問題描述", "請描述故障狀況，例如：廚房水槽下方漏水", "1", 1),
            (102, 1, "3", "緊急程度", None, "1", 2),
            (103, 1, "5", "服務地區", "請選擇您所在的行政區", "1", 3),
            (104, 1, "6", "現場照片", "上傳故障處照片，方便師傅評估", "0", 4),
            (105, 1, "9", "希望到府時間", None, "1", 5),
            (106, 1, "8", "聯絡資料", None, "1", 6),
        ],
        "options": [
            # id, topic_id, option_name, unit_price, unit, sort
            (1001, 102, "今天就要（急件）", 500, "趟", 1),
            (1002, 102, "三天內", 0, "趟", 2),
            (1003, 102, "一週內皆可", 0, "趟", 3),
        ],
    },
    {
        "form": (2, 2, "1", "1", "居家清潔預約單", "選擇清潔項目，預約專人到府服務"),
        "topics": [
            (201, 2, "3", "清潔類型", None, "1", 1),
            (202, 2, "4", "加購項目", "可複選", "0", 2),
            (203, 2, "5", "服務地區", None, "1", 3),
            (204, 2, "9", "希望服務日期", None, "1", 4),
            (205, 2, "8", "聯絡資料", None, "1", 5),
        ],
        "options": [
            (2001, 201, "一般居家清潔", 1800, "次", 1),
            (2002, 201, "深度大掃除", 3500, "次", 2),
            (2003, 202, "洗衣機清洗", 1600, "台", 1),
            (2004, 202, "冷氣清洗", 1500, "台", 2),
            (2005, 202, "玻璃窗清潔", 800, "面", 3),
        ],
    },
    {
        "form": (3, 3, "1", "1", "餐廳訂位單", "填寫訂位資訊，餐廳將為您保留座位"),
        "topics": [
            (301, 3, "3", "用餐人數", None, "1", 1),
            (302, 3, "9", "訂位時間", None, "1", 2),
            (303, 3, "1", "特殊需求", "例如：靠窗、慶生、素食", "0", 3),
            (304, 3, "10", "聯絡資料", "免填地址", "1", 4),
        ],
        "options": [
            (3001, 301, "1-2 人", None, "桌", 1),
            (3002, 301, "3-4 人", None, "桌", 2),
            (3003, 301, "5-8 人", None, "桌", 3),
            (3004, 301, "8 人以上（包廂）", None, "桌", 4),
        ],
    },
]

VENDORS = [
    # id, name, category_id, rating, phone, [(county, district), ...]
    (1, "大安水電行", 1, 4.8, "02-2700-1111", [("01", "001"), ("01", "002")]),
    (2, "新北快修水電", 1, 4.5, "02-2980-2222", [("02", "004"), ("02", "005")]),
    (3, "桃園阿明水電", 1, 4.6, "03-4520-3333", [("03", "006")]),
    (4, "潔淨家事服務", 2, 4.7, "02-2701-4444", [("01", "001"), ("01", "002"), ("01", "003")]),
    (5, "新北亮潔清潔隊", 2, 4.4, "02-2982-5555", [("02", "004")]),
    (6, "鼎泰豐（信義店）", 3, 4.9, "02-2720-6666", [("01", "002")]),
    (7, "海港餐廳（板橋店）", 3, 4.3, "02-2960-7777", [("02", "004")]),
    (8, "好食外送", 5, 4.2, "0800-123-456", [("01", "001"), ("01", "002"), ("01", "003")]),
]


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    cur.executemany("INSERT INTO sys_county VALUES (?,?)", COUNTIES)
    cur.executemany("INSERT INTO sys_district VALUES (?,?,?,?)", DISTRICTS)
    cur.executemany(
        "INSERT INTO service_category VALUES (?,?,?,?)", CATEGORIES
    )

    for f in FORMS:
        cur.execute(
            "INSERT INTO pms_form (id,category_id,type,sub_type,name,intro_content) "
            "VALUES (?,?,?,?,?,?)",
            f["form"],
        )
        cur.executemany(
            "INSERT INTO pms_form_topic "
            "(id,form_id,type,title,remark,is_required,sort) VALUES (?,?,?,?,?,?,?)",
            f["topics"],
        )
        cur.executemany(
            "INSERT INTO pms_topic_option "
            "(id,topic_id,option_name,unit_price,unit,sort) VALUES (?,?,?,?,?,?)",
            f["options"],
        )

    for v in VENDORS:
        vid, name, cat, rating, phone, areas = v
        cur.execute(
            "INSERT INTO service_vendor (id,name,category_id,rating,phone) "
            "VALUES (?,?,?,?,?)",
            (vid, name, cat, rating, phone),
        )
        for county, district in areas:
            cur.execute(
                "INSERT INTO vendor_service_area VALUES (?,?,?)",
                (vid, county, district),
            )

    con.commit()

    # 簡單統計
    for t in ["service_category", "pms_form", "pms_form_topic",
              "pms_topic_option", "service_vendor", "vendor_service_area",
              "sys_county", "sys_district"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<22} {n} 筆")
    con.close()
    print(f"\n✅ 資料庫建立完成：{DB}")


if __name__ == "__main__":
    main()
