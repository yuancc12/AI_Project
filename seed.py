# -*- coding: utf-8 -*-
"""
seed.py — 建立健身採買助手的 SQLite 資料庫並塞入擬真假資料。
執行：  python seed.py
產出：  butler.db
注意：DB Schema 完全符合 README.pdf 官方規範（2026 黑客松統一資訊命題）
"""
import sqlite3
import os
import base64
import hashlib
import time
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DB = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "butler.db"))

# ── AES-256-GCM 加密工具（符合官方規範）────────────────────────────────────
_ENCRYPT_KEY_HEX = os.getenv(
    "ENCRYPT_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
)
if len(_ENCRYPT_KEY_HEX) == 64:
    _KEY_BYTES = bytes.fromhex(_ENCRYPT_KEY_HEX)
elif len(_ENCRYPT_KEY_HEX) == 44:
    _KEY_BYTES = base64.b64decode(_ENCRYPT_KEY_HEX)
else:
    _KEY_BYTES = hashlib.sha256(_ENCRYPT_KEY_HEX.encode()).digest()

def _encrypt(plaintext: str) -> str:
    """AES-256-GCM 加密，回傳 base64（官方規範 bytea，SQLite 用 TEXT 儲存）"""
    if not plaintext:
        return ""
    nonce = os.urandom(12)
    ct = AESGCM(_KEY_BYTES).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def _hash(plaintext: str) -> str:
    """SHA-256 hash（官方規範：_hash 欄位用於查詢比對）"""
    if not plaintext:
        return ""
    return hashlib.sha256(plaintext.encode()).hexdigest()

def _uuid7() -> str:
    """UUID v7：前段依毫秒時間戳遞增，後段隨機（官方規範）
    格式：xxxxxxxx-xxxx-7xxx-[89ab]xxx-xxxxxxxxxxxx
    """
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48-bit timestamp
    rand_bytes = os.urandom(10)
    rand_int = int.from_bytes(rand_bytes, 'big')
    # 組合：48bit ts | 4bit ver(7) | 12bit rand_a | 2bit var | 62bit rand_b
    rand_a = (rand_int >> 50) & 0xFFF
    rand_b = rand_int & 0x3FFFFFFFFFFFFFFF
    h = f"{ts_ms:012x}{rand_a:03x}{rand_b:016x}"
    return f"{h[0:8]}-{h[8:12]}-7{h[13:16]}-{(0x80|(rand_b>>60)&0x3F):02x}{h[17:20]}-{h[20:32]}"

SCHEMA = """
DROP TABLE IF EXISTS pms_form_feedback;
DROP TABLE IF EXISTS mms_order_record;
DROP TABLE IF EXISTS pms_topic_media;
DROP TABLE IF EXISTS pms_topic_option;
DROP TABLE IF EXISTS pms_form_topic;
DROP TABLE IF EXISTS pms_form_group;
DROP TABLE IF EXISTS pms_form;
DROP TABLE IF EXISTS cms_homepage_service;
DROP TABLE IF EXISTS cms_homepage_service_vendor;
DROP TABLE IF EXISTS sys_district;
DROP TABLE IF EXISTS sys_county;
DROP TABLE IF EXISTS fitness_product;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS inquiry;
DROP TABLE IF EXISTS course_enrollment;
DROP TABLE IF EXISTS gym_course;
DROP TABLE IF EXISTS partner_vendor;
DROP TABLE IF EXISTS vendor_users;

CREATE TABLE fitness_product (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    vendor     TEXT NOT NULL,
    category   TEXT NOT NULL,
    protein_g  REAL NOT NULL DEFAULT 0,
    calories   INTEGER NOT NULL DEFAULT 0,
    price      INTEGER NOT NULL,
    stock      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password      TEXT NOT NULL,
    gender        TEXT NOT NULL DEFAULT '',
    birthday      TEXT NOT NULL DEFAULT '',
    height_cm     REAL NOT NULL DEFAULT 0,
    weight_kg     REAL NOT NULL DEFAULT 0,
    email         TEXT NOT NULL DEFAULT '',
    dietary_pref  TEXT NOT NULL DEFAULT '',
    county_code   TEXT NOT NULL DEFAULT '',
    district_code TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    uuid          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    age           INTEGER NOT NULL DEFAULT 0,
    fitness_goal  TEXT NOT NULL DEFAULT ''
);

-- ── 官方表 1：sys_county（縣市代碼檔）──────────────────────────────────────
CREATE TABLE sys_county (
    code       TEXT PRIMARY KEY,          -- varchar(2)
    name       TEXT NOT NULL,             -- varchar(10)
    sort       INTEGER NOT NULL DEFAULT 0,
    is_deleted TEXT NOT NULL DEFAULT '0', -- 0正常 / 1刪除
    upd_time   TEXT NOT NULL DEFAULT '',
    cre_time   TEXT NOT NULL DEFAULT '',
    upd_id     TEXT NOT NULL DEFAULT '',
    cre_id     TEXT NOT NULL DEFAULT ''
);

-- ── 官方表 2：sys_district（行政區代碼檔）──────────────────────────────────
CREATE TABLE sys_district (
    code             TEXT NOT NULL,          -- varchar(3)
    county_code      TEXT NOT NULL,          -- FK → sys_county.code
    name             TEXT NOT NULL,          -- varchar(20)
    name_with_county TEXT NOT NULL DEFAULT '',-- varchar(20)
    zip              TEXT NOT NULL DEFAULT '',-- varchar(6)
    sort             INTEGER NOT NULL DEFAULT 0,
    is_deleted       TEXT NOT NULL DEFAULT '0',
    upd_time         TEXT NOT NULL DEFAULT '',
    cre_time         TEXT NOT NULL DEFAULT '',
    upd_id           TEXT NOT NULL DEFAULT '',
    cre_id           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (code, county_code),
    FOREIGN KEY (county_code) REFERENCES sys_county(code)
);

-- ── 官方表 3：cms_homepage_service_vendor（服務商主檔）─────────────────────
CREATE TABLE cms_homepage_service_vendor (
    id          INTEGER PRIMARY KEY,  -- int4
    name        TEXT NOT NULL,        -- varchar
    description TEXT NOT NULL DEFAULT '', -- varchar
    -- 自訂擴充欄位
    category    TEXT NOT NULL DEFAULT '',
    rating      REAL NOT NULL DEFAULT 5.0,
    phone       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    county_code TEXT NOT NULL DEFAULT '',
    is_enable   INTEGER NOT NULL DEFAULT 1
);

-- ── 官方表 4：cms_homepage_service（服務項目主檔）──────────────────────────
CREATE TABLE cms_homepage_service (
    id                INTEGER PRIMARY KEY,  -- int4
    service_vendor_id INTEGER NOT NULL,     -- FK → cms_homepage_service_vendor.id
    type              TEXT NOT NULL DEFAULT '11', -- varchar(2)，service type
    name              TEXT NOT NULL,        -- varchar
    img_url           TEXT NOT NULL DEFAULT '',   -- varchar
    description       TEXT NOT NULL DEFAULT '',   -- text
    -- 自訂擴充欄位
    intro_content     TEXT NOT NULL DEFAULT '',
    is_enable         INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (service_vendor_id) REFERENCES cms_homepage_service_vendor(id)
);

-- ── 官方表 5：pms_form（表單主檔）──────────────────────────────────────────
CREATE TABLE pms_form (
    id               INTEGER PRIMARY KEY AUTOINCREMENT, -- serial4
    service_vendor_id INTEGER NOT NULL DEFAULT 0,       -- 服務提供商 ID
    type             TEXT NOT NULL DEFAULT '1',         -- 1 C端(無評估)/2 C端(需評估)/3 B端/4轉訂單/5客服
    sub_type         TEXT NOT NULL DEFAULT '1',         -- 1一般表單/2估價表單
    name             TEXT NOT NULL,                     -- varchar(50)
    intro_content    TEXT NOT NULL DEFAULT '',          -- html
    notice_content   TEXT NOT NULL DEFAULT '',          -- html
    terms_content    TEXT NOT NULL DEFAULT '',          -- html
    review_status    TEXT NOT NULL DEFAULT '0',         -- 0未審核/1已審核
    reviewed_id      TEXT NOT NULL DEFAULT '',          -- uuid
    reviewed_time    TEXT NOT NULL DEFAULT '',
    is_enable        TEXT NOT NULL DEFAULT '1',         -- 0禁用/1啟用
    is_deleted       TEXT NOT NULL DEFAULT '0',         -- 0未刪除/1已刪除
    feature          TEXT NOT NULL DEFAULT '{}',        -- jsonb
    upd_time         TEXT NOT NULL DEFAULT '',
    cre_time         TEXT NOT NULL DEFAULT '',
    upd_id           TEXT NOT NULL DEFAULT '',
    cre_id           TEXT NOT NULL DEFAULT ''
);

-- ── 官方表 6：pms_form_group（表單題組主檔）────────────────────────────────
CREATE TABLE pms_form_group (
    id       INTEGER PRIMARY KEY AUTOINCREMENT, -- serial4
    form_id  INTEGER NOT NULL,                  -- FK → pms_form.id
    name     TEXT NOT NULL,                     -- varchar(50)
    sort     INTEGER NOT NULL DEFAULT 0,
    feature  TEXT NOT NULL DEFAULT '{}',        -- jsonb
    upd_time TEXT NOT NULL DEFAULT '',
    cre_time TEXT NOT NULL DEFAULT '',
    upd_id   TEXT NOT NULL DEFAULT '',
    cre_id   TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (form_id) REFERENCES pms_form(id)
);

-- ── 官方表 7：pms_form_topic（表單題目主檔）────────────────────────────────
CREATE TABLE pms_form_topic (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT, -- serial4
    form_id                 INTEGER NOT NULL,   -- FK → pms_form.id
    form_group_id           INTEGER NOT NULL,   -- FK → pms_form_group.id（官方欄位名）
    type                    TEXT NOT NULL DEFAULT '1', -- 題目類別 1~10
    title                   TEXT NOT NULL,      -- varchar(200)
    remark                  TEXT NOT NULL DEFAULT '', -- varchar(500)
    is_required             TEXT NOT NULL DEFAULT '0', -- 0非必填/1必填
    sort                    INTEGER NOT NULL DEFAULT 0,
    is_number_only          TEXT NOT NULL DEFAULT '0', -- 簡答題：0未指定/1數字
    minimum_medias_upload   INTEGER NOT NULL DEFAULT 0, -- 照片題
    maximum_medias_upload   INTEGER NOT NULL DEFAULT 0,
    specified_medias_upload INTEGER NOT NULL DEFAULT 0,
    start_date_offset_days  INTEGER NOT NULL DEFAULT 0, -- 日期題
    end_date_offset_days    INTEGER NOT NULL DEFAULT 0,
    feature                 TEXT NOT NULL DEFAULT '{}', -- jsonb
    upd_time                TEXT NOT NULL DEFAULT '',
    cre_time                TEXT NOT NULL DEFAULT '',
    upd_id                  TEXT NOT NULL DEFAULT '',
    cre_id                  TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (form_id)       REFERENCES pms_form(id),
    FOREIGN KEY (form_group_id) REFERENCES pms_form_group(id)
);

-- ── 官方表 8：pms_topic_media（題目輔助圖片檔）─────────────────────────────
CREATE TABLE pms_topic_media (
    id       INTEGER PRIMARY KEY AUTOINCREMENT, -- serial4
    form_id  INTEGER NOT NULL,   -- FK → pms_form.id
    topic_id INTEGER NOT NULL,   -- FK → pms_form_topic.id
    img_url  TEXT NOT NULL DEFAULT '', -- text
    sort     INTEGER NOT NULL DEFAULT 0,
    upd_time TEXT NOT NULL DEFAULT '',
    cre_time TEXT NOT NULL DEFAULT '',
    upd_id   TEXT NOT NULL DEFAULT '',
    cre_id   TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (form_id)  REFERENCES pms_form(id),
    FOREIGN KEY (topic_id) REFERENCES pms_form_topic(id)
);

-- ── 官方表 9：pms_topic_option（題目選項主檔）──────────────────────────────
CREATE TABLE pms_topic_option (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT, -- serial4
    form_id             INTEGER NOT NULL,   -- FK → pms_form.id
    topic_id            INTEGER NOT NULL,   -- FK → pms_form_topic.id
    option_name         TEXT NOT NULL,      -- varchar(200)
    unit_price          INTEGER NOT NULL DEFAULT 0, -- int4
    unit                TEXT NOT NULL DEFAULT '',   -- varchar(30)
    is_quantity         TEXT NOT NULL DEFAULT '0',  -- 0不可選/1可選
    min_quantity        INTEGER NOT NULL DEFAULT 0,
    max_quantity        INTEGER NOT NULL DEFAULT 0,
    is_quoted_separately TEXT NOT NULL DEFAULT '0', -- 0否/1是
    remark              TEXT NOT NULL DEFAULT '',   -- varchar(500)
    sort                INTEGER NOT NULL DEFAULT 0,
    feature             TEXT NOT NULL DEFAULT '{}', -- jsonb
    upd_time            TEXT NOT NULL DEFAULT '',
    cre_time            TEXT NOT NULL DEFAULT '',
    upd_id              TEXT NOT NULL DEFAULT '',
    cre_id              TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (form_id)  REFERENCES pms_form(id),
    FOREIGN KEY (topic_id) REFERENCES pms_form_topic(id)
);

-- ── 官方表 10：pms_form_feedback（表單回饋檔）─────────────────────────────
CREATE TABLE pms_form_feedback (
    -- 官方 PK：feedback_no varchar(16)
    feedback_no                 TEXT PRIMARY KEY NOT NULL,  -- 回饋單號（14碼純數字）
    service_id                  INTEGER NOT NULL DEFAULT 1, -- → cms_homepage_service.id
    platform_code               TEXT NOT NULL DEFAULT '01', -- 平台代號
    form_id                     INTEGER NOT NULL DEFAULT 1, -- FK → pms_form.id
    feedback_content            TEXT NOT NULL DEFAULT '{}', -- jsonb 表單回饋內容
    form_type                   TEXT NOT NULL DEFAULT '1',  -- 表單類型
    is_read                     TEXT NOT NULL DEFAULT '0',  -- 0未讀/1已讀
    status                      TEXT NOT NULL DEFAULT '01', -- 01待處理/02配送中/03預留中/04待簽名/05待後台確認/80已完成/90已拒絕
    -- 官方加密欄位（AES-256-GCM，SQLite 用 TEXT 儲存 base64）
    contact_name                TEXT NOT NULL DEFAULT '',   -- bytea
    contact_name_hash           TEXT NOT NULL DEFAULT '',   -- SHA-256
    contact_mobile              TEXT NOT NULL DEFAULT '',   -- bytea
    contact_mobile_hash         TEXT NOT NULL DEFAULT '',   -- SHA-256
    contact_landline            TEXT NOT NULL DEFAULT '',   -- bytea（市話）
    contact_landline_hash       TEXT NOT NULL DEFAULT '',
    contact_email               TEXT NOT NULL DEFAULT '',   -- bytea
    contact_email_hash          TEXT NOT NULL DEFAULT '',
    preferred_contact_time      TEXT NOT NULL DEFAULT '3',  -- 1上午/2下午/3皆可
    contact_address_county      TEXT NOT NULL DEFAULT '',   -- → sys_county.code
    contact_address_district    TEXT NOT NULL DEFAULT '',   -- → sys_district.code
    contact_address_detail      TEXT NOT NULL DEFAULT '',   -- bytea（加密）
    contact_address_detail_hash TEXT NOT NULL DEFAULT '',
    description                 TEXT NOT NULL DEFAULT '',   -- varchar(1000) 備註
    inbr_account_id             TEXT NOT NULL DEFAULT '',   -- uuid，會員編號
    cre_time                    TEXT NOT NULL DEFAULT '',
    upd_id                      TEXT NOT NULL DEFAULT '',   -- uuid
    upd_time                    TEXT NOT NULL DEFAULT '',
    -- 自訂擴充欄位（業務邏輯用）
    goal                TEXT NOT NULL DEFAULT '',
    budget              INTEGER NOT NULL DEFAULT 0,
    keyword             TEXT NOT NULL DEFAULT '',
    county_code         TEXT NOT NULL DEFAULT '',
    district_code       TEXT NOT NULL DEFAULT '',
    contact_phone       TEXT NOT NULL DEFAULT '',
    note                TEXT NOT NULL DEFAULT '',
    address             TEXT NOT NULL DEFAULT '',
    delivery_type       TEXT NOT NULL DEFAULT '外送',
    pickup_store        TEXT NOT NULL DEFAULT '',
    products_json       TEXT NOT NULL DEFAULT '[]',
    user_id             INTEGER NOT NULL DEFAULT 0,
    user_reply          TEXT NOT NULL DEFAULT '',
    vendor_reply        TEXT NOT NULL DEFAULT '',
    accepted_at         TEXT NOT NULL DEFAULT '',
    images_json         TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT NOT NULL DEFAULT '',
    contact_name_display TEXT NOT NULL DEFAULT ''  -- 解密後顯示用（非加密）
);

-- 合作廠商（餐廳、搬家、清潔、健身房等）
CREATE TABLE partner_vendor (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,   -- 健身房 / 餐廳 / 搬家 / 清潔
    phone       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    county_code TEXT NOT NULL DEFAULT '',
    rating      REAL NOT NULL DEFAULT 5.0,
    description TEXT NOT NULL DEFAULT '',
    is_enable   INTEGER NOT NULL DEFAULT 1
);

-- 健身房每月課程
CREATE TABLE gym_course (
    id           INTEGER PRIMARY KEY,
    gym_id       INTEGER NOT NULL,
    course_name  TEXT NOT NULL,
    coach        TEXT NOT NULL DEFAULT '',
    course_type  TEXT NOT NULL DEFAULT '',  -- 有氧 / 重訓 / 瑜珈 / 格鬥 / 舞蹈
    weekday      TEXT NOT NULL DEFAULT '',  -- 週一,週三,週五 (逗號分隔)
    time_start   TEXT NOT NULL DEFAULT '',  -- HH:MM
    duration_min INTEGER NOT NULL DEFAULT 60,
    max_slots    INTEGER NOT NULL DEFAULT 20,
    enrolled     INTEGER NOT NULL DEFAULT 0,
    price_month  INTEGER NOT NULL DEFAULT 0,
    month        TEXT NOT NULL DEFAULT '',  -- YYYYMM
    min_students INTEGER NOT NULL DEFAULT 8,  -- 最低開課人數
    status       TEXT NOT NULL DEFAULT '招生中',  -- 招生中 / 已開課 / 已取消
    is_enable    INTEGER NOT NULL DEFAULT 1
);

-- 後台廠商帳號
CREATE TABLE vendor_users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,
    store_name  TEXT NOT NULL,
    brand       TEXT NOT NULL,
    address     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

-- 對話紀錄（app_helpers.py _ensure_conversation_table 同步）
CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    title       TEXT NOT NULL DEFAULT '新對話',
    disp_json   TEXT NOT NULL DEFAULT '[]',
    ollama_json TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 課程報名記錄（enroll_gym_course 寫入）
CREATE TABLE course_enrollment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id     INTEGER NOT NULL,
    feedback_no   TEXT NOT NULL DEFAULT '',  -- 對應諮詢單（可空）
    contact_name  TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '報名中',  -- 報名中 / 確認開課 / 已取消
    notified      INTEGER NOT NULL DEFAULT 0,       -- 1=已通知開課
    enrolled_at   TEXT NOT NULL
);

-- ── 官方表 11：mms_order_record（訂單/訂位統一紀錄表）──────────────────────
CREATE TABLE mms_order_record (
    record_id             INTEGER PRIMARY KEY AUTOINCREMENT, -- bigserial
    order_no              TEXT NOT NULL,                -- 訂單編號（與 service_id 組成 UK）
    service_vendor_id     INTEGER NOT NULL DEFAULT 0,   -- → cms_homepage_service_vendor.id
    service_id            INTEGER NOT NULL DEFAULT 0,   -- → cms_homepage_service.id
    platform_code         TEXT NOT NULL DEFAULT '01',   -- 01:OP APP
    inbr_account_id       TEXT NOT NULL DEFAULT '',     -- uuid，會員編號
    -- 官方加密欄位（AES-256-GCM，SQLite 用 TEXT 儲存 base64）
    member_name           TEXT NOT NULL DEFAULT '',     -- bytea
    member_name_hash      TEXT NOT NULL DEFAULT '',     -- SHA-256
    member_phone          TEXT NOT NULL DEFAULT '',     -- bytea
    member_phone_hash     TEXT NOT NULL DEFAULT '',
    member_email          TEXT NOT NULL DEFAULT '',     -- bytea
    member_email_hash     TEXT NOT NULL DEFAULT '',
    -- 訂單資訊
    order_type            TEXT NOT NULL DEFAULT '05',   -- 01服務/02訂位/03預約/04其他/05商品/06訂餐
    order_status          TEXT NOT NULL DEFAULT '02',   -- 依 order_type 而異
    order_time            TEXT NOT NULL DEFAULT '',
    deposit_time          TEXT NOT NULL DEFAULT '',
    confirm_time          TEXT NOT NULL DEFAULT '',
    service_time          TEXT NOT NULL DEFAULT '',
    complete_time         TEXT NOT NULL DEFAULT '',
    cancel_time           TEXT NOT NULL DEFAULT '',
    -- 金額
    deposit_amount        REAL NOT NULL DEFAULT 0,
    original_amount       REAL NOT NULL DEFAULT 0,
    discount_amount       REAL NOT NULL DEFAULT 0,
    shipping_fee_amount   REAL NOT NULL DEFAULT 0,
    final_amount          REAL NOT NULL DEFAULT 0,
    refund_amount         REAL NOT NULL DEFAULT 0,
    -- 點數
    order_points          REAL NOT NULL DEFAULT 0,
    used_points           REAL NOT NULL DEFAULT 0,
    refund_points         REAL NOT NULL DEFAULT 0,
    earn_points           REAL NOT NULL DEFAULT 0,
    point_status          TEXT NOT NULL DEFAULT '01',   -- 01待發放/02已發放/03不發放/04已取消
    point_grant_time      TEXT NOT NULL DEFAULT '',
    -- JSONB 欄位
    vendor_data           TEXT NOT NULL DEFAULT '{}',   -- 服務商特定欄位
    order_items           TEXT NOT NULL DEFAULT '[]',   -- 訂單品項明細
    -- 其他
    remark                TEXT NOT NULL DEFAULT '',
    cancel_reason         TEXT NOT NULL DEFAULT '',
    refund_reason         TEXT NOT NULL DEFAULT '',
    source_file           TEXT NOT NULL DEFAULT '',     -- varchar(200)
    import_batch          TEXT NOT NULL DEFAULT '',     -- varchar(50)
    quote_approved_by     TEXT NOT NULL DEFAULT '',     -- uuid
    quote_approved_time   TEXT NOT NULL DEFAULT '',
    quote_no              TEXT NOT NULL DEFAULT '',     -- varchar(64)
    comment_status        TEXT NOT NULL DEFAULT '00',   -- 00無須/01未評/02已評
    is_deleted            INTEGER NOT NULL DEFAULT 0,
    cre_id                TEXT NOT NULL DEFAULT '',     -- uuid
    cre_time              TEXT NOT NULL DEFAULT '',
    upd_id                TEXT NOT NULL DEFAULT '',     -- uuid
    upd_time              TEXT NOT NULL DEFAULT '',
    -- 自訂擴充欄位（配送業務邏輯用）
    feedback_no           TEXT NOT NULL DEFAULT '',
    vendor_name           TEXT NOT NULL DEFAULT '',
    estimated_minutes     INTEGER NOT NULL DEFAULT 60,
    reply_message         TEXT NOT NULL DEFAULT '',
    delivery_company      TEXT NOT NULL DEFAULT '',
    tracking_no           TEXT NOT NULL DEFAULT '',
    driver_name           TEXT NOT NULL DEFAULT '',
    status                TEXT NOT NULL DEFAULT '01',
    created_at            TEXT NOT NULL DEFAULT '',
    UNIQUE (order_no, service_id)
);
"""

# id, name, vendor, category, protein_g, calories, price, stock
PRODUCTS = [
    (1,  "雞胸肉(去骨)",        "萬家福",  "蛋白質", 31.0, 165,  65,  120),
    (2,  "舒肥雞胸肉(原味)",    "7-11",    "即食",   23.0, 110,  49,   80),
    (3,  "醬燒舒肥雞胸肉",      "7-11",    "即食",   20.0, 130,  55,   70),
    (4,  "水煮蛋(2入)",         "7-11",    "蛋白質",  6.0,  70,  15,  150),
    (5,  "鮪魚罐頭(水漬)",      "7-11",    "蛋白質", 26.0, 130,  45,   90),
    (6,  "無糖豆漿(450ml)",     "7-11",    "乳製品",  7.0,  70,  30,  100),
    (7,  "低脂牛奶(400ml)",     "7-11",    "乳製品",  8.0, 100,  35,  100),
    (8,  "蒸地瓜(170g)",        "7-11",    "主食",    2.0, 100,  35,   60),
    (9,  "鮭魚排(180g)",        "萬家福",  "蛋白質", 25.0, 200, 180,   40),
    (10, "牛腱肉(200g)",        "萬家福",  "蛋白質", 28.0, 175, 150,   30),
    (11, "雞蛋(10入)",          "萬家福",  "蛋白質",  6.0,  70,  65,  200),
    (12, "鮮蝦仁(200g)",        "萬家福",  "蛋白質", 24.0, 100, 180,   50),
    (13, "板豆腐(300g)",        "萬家福",  "蛋白質",  8.0,  75,  30,  100),
    (14, "希臘優格(無糖)",      "萬家福",  "乳製品", 10.0, 100,  65,   60),
    (15, "茅屋起司(200g)",      "萬家福",  "乳製品", 11.0, 100, 120,   30),
    (16, "地瓜(600g)",          "萬家福",  "主食",    2.0, 130,  40,  200),
    (17, "花椰菜(400g)",        "萬家福",  "蔬果",    3.0,  30,  35,  100),
    (18, "冷凍毛豆(500g)",      "萬家福",  "蔬果",   11.0, 120,  60,   80),
    (19, "菠菜(300g)",          "萬家福",  "蔬果",    3.0,  25,  30,  120),
    (20, "酪梨",                "萬家福",  "蔬果",    2.0, 160,  60,   60),
    (21, "乳清蛋白粉(巧克力)",  "康是美",  "保健品", 25.0, 120, 1280,  30),
    (22, "乳清蛋白粉(原味)",    "康是美",  "保健品", 25.0, 110, 1180,  25),
    (23, "高蛋白能量棒",        "康是美",  "即食",   20.0, 200,  89,   40),
    (24, "BCAA胺基酸粉",        "康是美",  "保健品",  0.0,  10, 890,   25),
    (25, "胺基酸補充飲(330ml)", "康是美",  "保健品",  5.0,  30,  49,   60),
    (26, "膠原蛋白粉",          "康是美",  "保健品",  9.0,  40, 650,   35),
    (27, "燕麥片(500g)",        "統一生機", "主食",  13.0, 389, 150,   60),
    (28, "全穀雜糧麵包",        "統一生機", "主食",   7.0, 250,  85,   40),
    (29, "綜合堅果(200g)",      "統一生機", "保健品",  8.0, 180, 120,  50),
    (30, "黑豆漿(946ml)",       "統一生機", "乳製品",  9.0,  80,  55,   50),
    (31, "燕麥奶(1000ml)",      "統一生機",    "乳製品",  3.0, 120,  85,   40),
    # Mister Donut
    (32, "原味甜甜圈",           "Mister Donut", "甜食",   3.0, 210,  35,  80),
    (33, "蜂蜜甜甜圈",           "Mister Donut", "甜食",   3.0, 240,  35,  80),
    (34, "波堤甜甜圈(5入)",      "Mister Donut", "甜食",   6.0, 520, 150,  50),
    (35, "巧克力甜甜圈",         "Mister Donut", "甜食",   3.5, 280,  40,  70),
    (36, "卡士達奶油泡芙",       "Mister Donut", "甜食",   4.0, 250,  45,  60),
    # Cold Stone
    (37, "招牌冰淇淋(小)",       "Cold Stone",   "甜點",   3.0, 280, 120,  50),
    (38, "招牌冰淇淋(中)",       "Cold Stone",   "甜點",   4.5, 420, 180,  50),
    (39, "水果奶昔(中)",         "Cold Stone",   "飲料",   5.0, 380, 200,  40),
    (40, "冰淇淋蛋糕(6吋)",      "Cold Stone",   "甜點",  10.0, 900, 680,  20),
    (41, "巧克力布朗尼聖代",     "Cold Stone",   "甜點",   5.0, 580, 260,  40),
    # 21plus
    (42, "台灣啤酒(330ml)",      "21plus",       "酒類",   0.7,  45,  55, 100),
    (43, "朝日SuperDry(350ml)",  "21plus",       "酒類",   0.5,  44,  65,  80),
    (44, "金牌台灣啤酒(330ml)",  "21plus",       "酒類",   0.7,  48,  55, 100),
    (45, "智利紅酒(750ml)",      "21plus",       "酒類",   0.0, 510, 480,  30),
    (46, "梅酒(720ml)",          "21plus",       "酒類",   0.0, 630, 520,  25),
    # 統一星巴克
    (47, "美式咖啡Tall(354ml)",  "統一星巴克",   "咖啡",   1.0,  15, 145,  60),
    (48, "拿鐵咖啡Tall(354ml)",  "統一星巴克",   "咖啡",   7.0, 130, 165,  60),
    (49, "卡布奇諾Tall(354ml)",  "統一星巴克",   "咖啡",   6.0, 110, 155,  50),
    (50, "抹茶拿鐵Tall(354ml)",  "統一星巴克",   "咖啡",   7.0, 200, 175,  50),
    (51, "冷萃咖啡Tall(354ml)",  "統一星巴克",   "咖啡",   2.0,  25, 160,  40),
    # 聖德科斯
    (52, "有機藜麥(400g)",       "聖德科斯",     "有機食品", 14.0, 368, 280,  35),
    (53, "有機椰子油(250ml)",    "聖德科斯",     "有機食品",  0.0, 900, 320,  25),
    (54, "有機奇亞籽(250g)",     "聖德科斯",     "有機食品", 17.0, 486, 250,  30),
    (55, "天然燕麥片(500g)",     "聖德科斯",     "有機食品", 13.0, 389, 160,  50),
    (56, "有機蜂蜜(350g)",       "聖德科斯",     "有機食品",  0.3, 304, 280,  30),
    # ── 蔬菜類（萬家福）──────────────────────────────────────────────────────
    (57,  "番茄(600g)",          "萬家福",  "蔬果",    1.5,  36,  35, 150),
    (58,  "芹菜(300g)",          "萬家福",  "蔬果",    1.0,  16,  25, 120),
    (59,  "蕪菁(400g)",          "萬家福",  "蔬果",    0.9,  28,  30,  80),
    (60,  "紅蘿蔔(500g)",        "萬家福",  "蔬果",    0.9,  41,  30, 130),
    (61,  "洋蔥(600g)",          "萬家福",  "蔬果",    1.1,  40,  30, 140),
    (62,  "大蒜(200g)",          "萬家福",  "蔬果",    6.4, 149,  25, 100),
    (63,  "薑(150g)",            "萬家福",  "蔬果",    1.8,  80,  20, 100),
    (64,  "青椒(300g)",          "萬家福",  "蔬果",    1.0,  26,  30, 100),
    (65,  "甜椒(紅/黃,300g)",    "萬家福",  "蔬果",    1.0,  31,  45,  80),
    (66,  "玉米(2入)",           "萬家福",  "蔬果",    3.2,  86,  30,  90),
    (67,  "小黃瓜(300g)",        "萬家福",  "蔬果",    0.7,  16,  25, 120),
    (68,  "高麗菜(半顆)",        "萬家福",  "蔬果",    1.3,  25,  30, 130),
    (69,  "韭菜(200g)",          "萬家福",  "蔬果",    2.1,  28,  20, 100),
    (70,  "豆芽菜(300g)",        "萬家福",  "蔬果",    2.0,  30,  20, 120),
    (71,  "青蔥(200g)",          "萬家福",  "蔬果",    1.8,  31,  20, 150),
    (72,  "大白菜(半顆)",        "萬家福",  "蔬果",    1.0,  20,  25, 130),
    (73,  "苦瓜(350g)",          "萬家福",  "蔬果",    1.0,  24,  30,  80),
    (74,  "茄子(300g)",          "萬家福",  "蔬果",    1.0,  25,  25,  90),
    (75,  "南瓜(600g)",          "萬家福",  "蔬果",    1.0,  80,  45,  80),
    (76,  "山藥(400g)",          "萬家福",  "蔬果",    2.0, 118,  55,  60),
    (77,  "蘑菇(200g)",          "萬家福",  "蔬果",    3.1,  27,  45,  80),
    (78,  "金針菇(200g)",        "萬家福",  "蔬果",    2.7,  38,  30, 100),
    (79,  "鴻喜菇(200g)",        "萬家福",  "蔬果",    2.5,  37,  35,  90),
    (80,  "香菇(200g)",          "萬家福",  "蔬果",    3.0,  35,  55,  70),
    # ── 豆類・雜糧（萬家福）──────────────────────────────────────────────────
    (81,  "紅扁豆(500g)",        "萬家福",  "豆類",    9.0, 116, 120,  60),
    (82,  "綠扁豆(500g)",        "萬家福",  "豆類",    9.0, 116, 110,  60),
    (83,  "黑豆(600g)",          "萬家福",  "豆類",   36.0, 367,  90,  60),
    (84,  "綠豆(600g)",          "萬家福",  "豆類",   23.0, 347,  70,  70),
    (85,  "鷹嘴豆(罐頭,400g)",   "萬家福",  "豆類",    8.9, 164,  65,  80),
    (86,  "紅腰豆(罐頭,400g)",   "萬家福",  "豆類",    8.7, 127,  60,  80),
    (87,  "糙米(2kg)",           "萬家福",  "主食",    7.9, 370, 120,  80),
    (88,  "白米(2kg)",           "萬家福",  "主食",    6.8, 360,  90, 100),
    (89,  "義大利麵(500g)",      "萬家福",  "主食",   13.0, 371,  55, 100),
    (90,  "全麥吐司(12片)",      "萬家福",  "主食",    9.0, 244,  55,  80),
    # ── 高湯・調味料（萬家福）────────────────────────────────────────────────
    (91,  "蔬菜高湯(1000ml)",    "萬家福",  "調味料",  0.5,  15,  55,  80),
    (92,  "雞骨高湯(1000ml)",    "萬家福",  "調味料",  2.0,  20,  65,  80),
    (93,  "牛骨高湯(1000ml)",    "萬家福",  "調味料",  3.0,  25,  75,  60),
    (94,  "低鈉醬油(500ml)",     "萬家福",  "調味料",  8.0,  70,  65, 100),
    (95,  "橄欖油(500ml)",       "萬家福",  "調味料",  0.0, 884, 220,  60),
    (96,  "黑胡椒粉(50g)",       "萬家福",  "調味料",  0.0,   0,  30, 100),
    # ── 肉類・海鮮（萬家福）──────────────────────────────────────────────────
    (97,  "豬里肌(200g)",        "萬家福",  "蛋白質", 22.0, 143, 120,  60),
    (98,  "豬絞肉(300g)",        "萬家福",  "蛋白質", 17.0, 260, 110,  60),
    (99,  "雞腿排(去骨,200g)",   "萬家福",  "蛋白質", 27.0, 175,  90,  80),
    (100, "牛絞肉(300g)",        "萬家福",  "蛋白質", 21.0, 215, 160,  40),
    (101, "透抽(200g)",          "萬家福",  "蛋白質", 18.0,  82, 130,  50),
    (102, "蛤蠣(300g)",          "萬家福",  "蛋白質", 14.0,  74,  90,  60),
    (103, "鱸魚片(200g)",        "萬家福",  "蛋白質", 19.0, 100, 150,  40),
    (104, "豬肝(200g)",          "萬家福",  "蛋白質", 21.0, 131, 100,  40),
    # ── 水果（萬家福）────────────────────────────────────────────────────────
    (105, "香蕉(5入)",           "萬家福",  "蔬果",    1.1,  89,  40, 100),
    (106, "蘋果(3入)",           "萬家福",  "蔬果",    0.3,  52,  60,  80),
    (107, "藍莓(200g)",          "萬家福",  "蔬果",    0.7,  57,  85,  50),
    (108, "草莓(250g)",          "萬家福",  "蔬果",    0.8,  33,  80,  50),
    (109, "芒果(2入)",           "萬家福",  "蔬果",    0.8,  60,  70,  60),
    (110, "奇異果(4入)",         "萬家福",  "蔬果",    1.1,  61,  75,  60),
    # ── 乳製品・蛋（萬家福）──────────────────────────────────────────────────
    (111, "雞蛋(6入)",           "萬家福",  "蛋白質",  6.0,  70,  45, 200),
    (112, "無鹽奶油(200g)",      "萬家福",  "乳製品",  0.6, 717, 120,  60),
    (113, "莫扎瑞拉起司(200g)", "萬家福",   "乳製品", 22.0, 280, 150,  40),
    (114, "無糖優格(500g)",      "萬家福",  "乳製品",  5.0,  60,  85,  50),
    (115, "豆腐(嫩豆腐,300g)",  "萬家福",   "蛋白質",  5.0,  53,  30, 100),
    # ── 冷凍食品（萬家福）────────────────────────────────────────────────────
    (116, "冷凍菠菜(500g)",      "萬家福",  "蔬果",    2.9,  23,  45, 100),
    (117, "冷凍花椰菜(500g)",    "萬家福",  "蔬果",    2.5,  27,  45, 100),
    (118, "冷凍玉米粒(500g)",    "萬家福",  "蔬果",    3.2,  86,  45, 100),
    (119, "冷凍蝦仁(300g)",      "萬家福",  "蛋白質", 24.0,  99, 160,  60),
    (120, "冷凍鮭魚切片(300g)",  "萬家福",  "蛋白質", 25.0, 200, 220,  40),
    # ── 有機食品（聖德科斯追加）──────────────────────────────────────────────
    (121, "有機糙米(2kg)",       "聖德科斯", "有機食品", 7.9, 370, 220,  40),
    (122, "有機黑芝麻(200g)",    "聖德科斯", "有機食品",18.0, 573, 180,  30),
    (123, "有機亞麻籽(250g)",    "聖德科斯", "有機食品",18.3, 534, 220,  30),
    (124, "有機椰棗(200g)",      "聖德科斯", "有機食品", 2.5, 282, 180,  25),
    (125, "有機花生醬(350g)",    "聖德科斯", "有機食品",25.0, 588, 260,  30),
    # ── 7-11 追加生鮮 ─────────────────────────────────────────────────────────
    (126, "茶葉蛋",              "7-11",    "即食",    8.0,  80,  10, 300),
    (127, "關東煮豆腐",          "7-11",    "即食",    5.0,  60,  15, 200),
    (128, "關東煮蛋",            "7-11",    "即食",    6.0,  80,  15, 200),
    (129, "御飯糰(鮭魚)",        "7-11",    "即食",    8.0, 200,  39, 120),
    (130, "御飯糰(鮪魚)",        "7-11",    "即食",    9.0, 195,  39, 120),
    (131, "希臘優格飲(200ml)",   "7-11",    "乳製品",  8.0,  90,  45,  80),
    (132, "高蛋白牛奶(300ml)",   "7-11",    "乳製品", 15.0, 120,  55,  80),
    (133, "全麥三明治",          "7-11",    "即食",   12.0, 280,  55,  80),
]

COUNTIES = [
    ('01', '台北市'), ('02', '新北市'), ('03', '基隆市'), ('04', '桃園市'),
    ('05', '新竹縣'), ('06', '新竹市'), ('07', '苗栗縣'), ('08', '台中市'),
    ('09', '南投縣'), ('10', '彰化縣'), ('11', '雲林縣'), ('12', '嘉義縣'),
    ('13', '嘉義市'), ('14', '台南市'), ('15', '高雄市'), ('16', '屏東縣'),
    ('17', '宜蘭縣'), ('18', '花蓮縣'), ('19', '台東縣'), ('20', '澎湖縣'),
    ('21', '金門縣'), ('22', '連江縣'),
]

DISTRICTS = [
    # 台北市 01
    ('001','01','中正區','100'), ('002','01','大同區','103'), ('003','01','中山區','104'),
    ('004','01','萬華區','108'), ('005','01','信義區','110'), ('006','01','松山區','105'),
    ('007','01','大安區','106'), ('008','01','南港區','115'), ('009','01','北投區','112'),
    ('010','01','內湖區','114'), ('011','01','士林區','111'), ('012','01','文山區','116'),
    # 新北市 02
    ('013','02','板橋區','220'), ('014','02','新莊區','242'), ('015','02','泰山區','243'),
    ('016','02','林口區','244'), ('017','02','淡水區','251'), ('018','02','金山區','208'),
    ('019','02','八里區','249'), ('020','02','萬里區','207'), ('021','02','石門區','253'),
    ('022','02','三芝區','252'), ('023','02','瑞芳區','224'), ('024','02','汐止區','221'),
    ('025','02','平溪區','226'), ('026','02','貢寮區','228'), ('027','02','雙溪區','227'),
    ('028','02','深坑區','222'), ('029','02','石碇區','223'), ('030','02','新店區','231'),
    ('031','02','坪林區','232'), ('032','02','烏來區','233'), ('033','02','中和區','235'),
    ('034','02','永和區','234'), ('035','02','土城區','236'), ('036','02','三峽區','237'),
    ('037','02','樹林區','238'), ('038','02','鶯歌區','239'), ('039','02','三重區','241'),
    ('040','02','蘆洲區','247'), ('041','02','五股區','248'),
    # 基隆市 03
    ('042','03','仁愛區','200'), ('043','03','中正區','202'), ('044','03','信義區','201'),
    ('045','03','中山區','203'), ('046','03','安樂區','204'), ('047','03','暖暖區','205'),
    ('048','03','七堵區','206'),
    # 桃園市 04
    ('049','04','桃園區','330'), ('050','04','中壢區','320'), ('051','04','平鎮區','324'),
    ('052','04','八德區','334'), ('053','04','楊梅區','326'), ('054','04','蘆竹區','338'),
    ('055','04','龜山區','333'), ('056','04','龍潭區','325'), ('057','04','大溪區','335'),
    ('058','04','大園區','337'), ('059','04','觀音區','328'), ('060','04','新屋區','327'),
    ('061','04','復興區','336'),
    # 新竹縣 05
    ('062','05','竹北市','302'), ('063','05','竹東鎮','310'), ('064','05','新埔鎮','305'),
    ('065','05','關西鎮','306'), ('066','05','峨眉鄉','315'), ('067','05','寶山鄉','308'),
    ('068','05','北埔鄉','314'), ('069','05','橫山鄉','312'),
    # 台南市 14（部分區域）
    ('238','14','山上區','743'), ('239','14','新市區','744'), ('240','14','安定區','745'),
    # 高雄市 15
    ('241','15','楠梓區','811'), ('242','15','左營區','813'), ('243','15','鼓山區','804'),
    ('244','15','三民區','807'), ('245','15','鹽埕區','803'), ('246','15','前金區','801'),
    ('247','15','新興區','800'), ('248','15','苓雅區','802'), ('249','15','前鎮區','806'),
    ('250','15','小港區','812'), ('251','15','旗津區','805'), ('252','15','鳳山區','830'),
    ('253','15','大寮區','831'), ('254','15','鳥松區','833'), ('255','15','林園區','832'),
    ('256','15','仁武區','814'), ('257','15','大樹區','840'), ('258','15','大社區','815'),
    ('259','15','岡山區','820'), ('260','15','路竹區','821'), ('261','15','橋頭區','825'),
    ('262','15','梓官區','826'), ('263','15','彌陀區','827'), ('264','15','永安區','828'),
    ('265','15','燕巢區','824'), ('266','15','田寮區','823'), ('267','15','阿蓮區','822'),
    ('268','15','茄萣區','852'), ('269','15','湖內區','829'), ('270','15','旗山區','842'),
    ('271','15','美濃區','843'), ('272','15','內門區','845'), ('273','15','杉林區','846'),
    ('274','15','甲仙區','847'), ('275','15','六龜區','844'), ('276','15','茂林區','851'),
    ('277','15','桃源區','848'), ('278','15','那瑪夏區','849'),
    # 屏東縣 16
    ('279','16','屏東市','900'), ('280','16','潮州鎮','920'), ('281','16','東港鎮','928'),
    ('282','16','恆春鎮','946'), ('283','16','萬丹鄉','913'), ('284','16','長治鄉','908'),
    ('285','16','麟洛鄉','909'), ('286','16','九如鄉','904'), ('287','16','里港鄉','905'),
    ('288','16','鹽埔鄉','907'), ('289','16','高樹鄉','906'), ('290','16','萬巒鄉','923'),
    ('291','16','內埔鄉','912'), ('292','16','竹田鄉','911'), ('293','16','新埤鄉','925'),
    ('294','16','枋寮鄉','940'), ('295','16','新園鄉','932'), ('296','16','崁頂鄉','924'),
    ('297','16','林邊鄉','927'), ('298','16','南州鄉','926'), ('299','16','佳冬鄉','931'),
    ('300','16','琉球鄉','929'), ('301','16','車城鄉','944'), ('302','16','滿州鄉','947'),
    ('303','16','枋山鄉','941'), ('304','16','霧台鄉','902'), ('305','16','瑪家鄉','903'),
    ('306','16','泰武鄉','921'), ('307','16','來義鄉','922'), ('308','16','春日鄉','942'),
    ('309','16','獅子鄉','943'), ('310','16','牡丹鄉','945'), ('311','16','三地門鄉','901'),
    # 宜蘭縣 17
    ('312','17','宜蘭市','260'), ('313','17','羅東鎮','265'), ('314','17','蘇澳鎮','270'),
    ('315','17','頭城鎮','261'), ('316','17','礁溪鄉','262'), ('317','17','壯圍鄉','263'),
    ('318','17','員山鄉','264'), ('319','17','冬山鄉','269'), ('320','17','五結鄉','268'),
    ('321','17','三星鄉','266'), ('322','17','大同鄉','267'), ('323','17','南澳鄉','272'),
    # 花蓮縣 18
    ('324','18','花蓮市','970'), ('325','18','鳳林鎮','975'), ('326','18','玉里鎮','981'),
    ('327','18','新城鄉','971'), ('328','18','吉安鄉','973'), ('329','18','壽豐鄉','974'),
    ('330','18','秀林鄉','972'), ('331','18','光復鄉','976'), ('332','18','豐濱鄉','977'),
    ('333','18','瑞穗鄉','978'), ('334','18','萬榮鄉','979'), ('335','18','富里鄉','983'),
    ('336','18','卓溪鄉','982'),
    # 台東縣 19
    ('337','19','台東市','950'), ('338','19','成功鎮','961'), ('339','19','關山鎮','956'),
    ('340','19','長濱鄉','962'), ('341','19','海端鄉','957'), ('342','19','池上鄉','958'),
    ('343','19','東河鄉','959'), ('344','19','鹿野鄉','955'), ('345','19','延平鄉','953'),
    ('346','19','卑南鄉','954'), ('347','19','金峰鄉','964'), ('348','19','大武鄉','965'),
    ('349','19','達仁鄉','966'), ('350','19','綠島鄉','951'), ('351','19','蘭嶼鄉','952'),
    ('352','19','太麻里鄉','963'),
    # 澎湖縣 20
    ('353','20','馬公市','880'), ('354','20','湖西鄉','885'), ('355','20','白沙鄉','884'),
    ('356','20','西嶼鄉','881'), ('357','20','望安鄉','882'), ('358','20','七美鄉','883'),
    # 金門縣 21
    ('359','21','金城鎮','893'), ('360','21','金湖鎮','891'), ('361','21','金沙鎮','890'),
    ('362','21','金寧鄉','892'), ('363','21','烈嶼鄉','894'), ('364','21','烏坵鄉','896'),
    # 連江縣 22
    ('365','22','南竿鄉','209'), ('366','22','北竿鄉','210'),
    ('367','22','莒光鄉','211'), ('368','22','東引鄉','212'),
    # 新竹市 06
    ('369','06','東區','300'), ('370','06','北區','300'), ('371','06','香山區','300'),
    # 苗栗縣 07
    ('372','07','苗栗市','360'), ('373','07','竹南鎮','350'), ('374','07','頭份市','351'),
    ('375','07','後龍鎮','356'), ('376','07','通霄鎮','357'), ('377','07','苑裡鎮','358'),
    ('378','07','公館鄉','363'), ('379','07','銅鑼鄉','366'), ('380','07','三義鄉','367'),
    ('381','07','西湖鄉','368'), ('382','07','卓蘭鎮','369'), ('383','07','大湖鄉','364'),
    ('384','07','泰安鄉','365'), ('385','07','南庄鄉','353'), ('386','07','獅潭鄉','354'),
    # 台中市 08
    ('387','08','中區','400'), ('388','08','東區','401'), ('389','08','南區','402'),
    ('390','08','西區','403'), ('391','08','北區','404'), ('392','08','北屯區','406'),
    ('393','08','西屯區','407'), ('394','08','南屯區','408'), ('395','08','太平區','411'),
    ('396','08','大里區','412'), ('397','08','霧峰區','413'), ('398','08','烏日區','414'),
    ('399','08','豐原區','420'), ('400','08','后里區','421'), ('401','08','石岡區','422'),
    ('402','08','東勢區','423'), ('403','08','和平區','424'), ('404','08','新社區','426'),
    ('405','08','潭子區','427'), ('406','08','大雅區','428'), ('407','08','神岡區','429'),
    ('408','08','大肚區','432'), ('409','08','沙鹿區','433'), ('410','08','龍井區','434'),
    ('411','08','梧棲區','435'), ('412','08','清水區','436'), ('413','08','大甲區','437'),
    ('414','08','外埔區','438'), ('415','08','大安區','439'),
    # 南投縣 09
    ('416','09','南投市','540'), ('417','09','中寮鄉','541'), ('418','09','草屯鎮','542'),
    ('419','09','國姓鄉','544'), ('420','09','埔里鎮','545'), ('421','09','仁愛鄉','546'),
    ('422','09','名間鄉','551'), ('423','09','集集鎮','552'), ('424','09','水里鄉','553'),
    ('425','09','魚池鄉','555'), ('426','09','信義鄉','556'), ('427','09','竹山鎮','557'),
    ('428','09','鹿谷鄉','558'),
    # 彰化縣 10
    ('429','10','彰化市','500'), ('430','10','芬園鄉','502'), ('431','10','花壇鄉','503'),
    ('432','10','秀水鄉','504'), ('433','10','鹿港鎮','505'), ('434','10','福興鄉','506'),
    ('435','10','線西鄉','507'), ('436','10','和美鎮','508'), ('437','10','伸港鄉','509'),
    ('438','10','員林市','510'), ('439','10','社頭鄉','511'), ('440','10','永靖鄉','512'),
    ('441','10','埔心鄉','513'), ('442','10','溪湖鎮','514'), ('443','10','大村鄉','515'),
    ('444','10','埔鹽鄉','516'), ('445','10','田中鎮','520'), ('446','10','北斗鎮','521'),
    ('447','10','田尾鄉','522'), ('448','10','埤頭鄉','523'), ('449','10','溪州鄉','524'),
    ('450','10','竹塘鄉','525'), ('451','10','二林鎮','526'), ('452','10','大城鄉','527'),
    ('453','10','芳苑鄉','528'), ('454','10','二水鄉','530'),
    # 雲林縣 11
    ('455','11','斗六市','640'), ('456','11','斗南鎮','630'), ('457','11','虎尾鎮','632'),
    ('458','11','西螺鎮','648'), ('459','11','土庫鎮','633'), ('460','11','北港鎮','651'),
    ('461','11','古坑鄉','646'), ('462','11','大埤鄉','631'), ('463','11','莿桐鄉','647'),
    ('464','11','林內鄉','643'), ('465','11','二崙鄉','649'), ('466','11','崙背鄉','637'),
    ('467','11','麥寮鄉','638'), ('468','11','東勢鄉','634'), ('469','11','褒忠鄉','635'),
    ('470','11','台西鄉','636'), ('471','11','元長鄉','655'), ('472','11','四湖鄉','654'),
    ('473','11','口湖鄉','653'), ('474','11','水林鄉','652'),
    # 嘉義縣 12
    ('475','12','太保市','612'), ('476','12','朴子市','613'), ('477','12','布袋鎮','625'),
    ('478','12','大林鎮','622'), ('479','12','民雄鄉','621'), ('480','12','溪口鄉','623'),
    ('481','12','新港鄉','616'), ('482','12','六腳鄉','615'), ('483','12','東石鄉','614'),
    ('484','12','義竹鄉','624'), ('485','12','鹿草鄉','611'), ('486','12','水上鄉','608'),
    ('487','12','中埔鄉','606'), ('488','12','竹崎鄉','604'), ('489','12','梅山鄉','603'),
    ('490','12','番路鄉','602'), ('491','12','大埔鄉','607'), ('492','12','阿里山鄉','605'),
    # 嘉義市 13
    ('493','13','東區','600'), ('494','13','西區','600'),
    # 台南市 14（補齊其餘 34 區）
    ('495','14','中西區','700'), ('496','14','東區','701'), ('497','14','南區','702'),
    ('498','14','北區','704'), ('499','14','安平區','708'), ('500','14','安南區','709'),
    ('501','14','永康區','710'), ('502','14','歸仁區','711'), ('503','14','新化區','712'),
    ('504','14','左鎮區','713'), ('505','14','玉井區','714'), ('506','14','楠西區','715'),
    ('507','14','南化區','716'), ('508','14','仁德區','717'), ('509','14','關廟區','718'),
    ('510','14','龍崎區','719'), ('511','14','官田區','720'), ('512','14','麻豆區','721'),
    ('513','14','佳里區','722'), ('514','14','西港區','723'), ('515','14','七股區','724'),
    ('516','14','將軍區','725'), ('517','14','學甲區','726'), ('518','14','北門區','727'),
    ('519','14','新營區','730'), ('520','14','後壁區','731'), ('521','14','白河區','732'),
    ('522','14','東山區','733'), ('523','14','六甲區','734'), ('524','14','下營區','735'),
    ('525','14','柳營區','736'), ('526','14','鹽水區','737'), ('527','14','善化區','741'),
    ('528','14','大內區','742'),
]

SERVICE_VENDORS = [
    # id, name, description, category, rating, phone, address, county_code, is_enable
    (1, '7-ELEVEN',               '統一超商 7-ELEVEN 健身商品線上採買服務',    '便利商店', 5.0, '0800-711711',    '台北市大安區忠孝東路四段181號',      '01', 1),
    (2, '萬家福',                 '萬家福超市健身食材採買服務',                 '超市',     4.8, '02-2723-6789',   '台北市信義區松高路1號B1',            '01', 1),
    (3, '康是美',                 '康是美藥妝保健品採買服務',                   '藥妝',     4.7, '02-2522-3333',   '台北市中山區南京東路二段168號',      '01', 1),
    (4, '統一生機',               '統一生機有機健康食品採買服務',               '有機食品', 4.6, '02-8712-4444',   '台北市松山區八德路三段32號',         '01', 1),
    (5, '統一多拿滋 Mister Donut','Mister Donut 甜甜圈、飲料外帶採買服務',     '甜食飲料', 4.7, '0800-211-211',   '台北市大安區忠孝東路四段181號1F',   '01', 1),
    (6, 'Cold Stone Creamery',    'Cold Stone Creamery 手工冰淇淋甜點採買服務','冰淇淋甜點',4.8, '02-8787-0101', '台北市信義區松壽路11號1F',           '01', 1),
    (7, '7-ELEVEN 21plus',        '統一超商 21plus 精選啤酒、葡萄酒、清酒採買','成人超商', 4.6, '0800-711-712',   '台北市信義區菸廠路88號',             '01', 1),
    (8, '統一星巴克',             '統一星巴克精品咖啡、茶飲採買服務',           '咖啡飲料', 4.9, '0800-608-608',   '台北市信義區松壽路1號1F',            '01', 1),
    (9, '聖德科斯 Sanitas',       '聖德科斯 Sanitas 天然有機食品、保健品採買',  '自然食品', 4.6, '02-2507-2888',   '台北市中山區南京東路二段30號',       '01', 1),
]

SERVICES = [
    # id, service_vendor_id, type, name, img_url, description, intro_content, is_enable
    (1, 1, '11', '7-ELEVEN 商城購物',       '', '統一超商 7-ELEVEN 健身商品線上採買服務',           '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (2, 2, '11', '萬家福 商城購物',         '', '萬家福超市健身食材採買服務',                       '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (3, 3, '11', '康是美 商城購物',         '', '康是美藥妝保健品採買服務',                         '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (4, 4, '11', '統一生機 商城購物',       '', '統一生機有機健康食品採買服務',                     '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (5, 5, '11', '統一多拿滋 甜食點心',     '', 'Mister Donut 甜甜圈、飲料外帶採買服務',           '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (6, 6, '11', 'Cold Stone 冰淇淋',       '', 'Cold Stone Creamery 手工冰淇淋甜點採買服務',       '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (7, 7, '11', '21plus 成人精選商品',     '', '統一超商 21plus 精選啤酒、葡萄酒、清酒採買服務',   '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (8, 8, '11', '統一星巴克 咖啡飲料',     '', '統一星巴克精品咖啡、茶飲採買服務',                 '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
    (9, 9, '11', '聖德科斯 天然自然食品',   '', '聖德科斯 Sanitas 天然有機食品、保健品採買服務',   '填寫您的採買需求，後台人員將主動聯繫安排配送。', 1),
]

FORMS = [
    # id, service_vendor_id, type, sub_type, name, intro_content, is_enable
    (1, 1, '1', '1', '健身採買諮詢單', '填寫您的健身目標與採買需求，後台人員將主動聯繫安排採購配送。', '1'),
]

FORM_GROUPS = [
    # id, form_id, name, sort
    (1, 1, '基本資訊', 1),
    (2, 1, '採買需求', 2),
]

FORM_TOPICS = [
    # id, form_id, form_group_id, type, title, remark, is_required, sort
    (1, 1, 1, '3', '健身目標',       '請選擇您的健身目標',             '1', 1),
    (2, 1, 1, '1', '採買預算（元）', '輸入本次採買的預算金額',         '1', 2),
    (3, 1, 1, '8', '聯絡資料',       '方便後台人員與您聯繫',           '1', 3),
    (4, 1, 2, '1', '搜尋關鍵字',     '指定想找的商品名稱（選填）',     '0', 1),
    (5, 1, 2, '2', '特殊需求備註',   '例如：素食、過敏食材、指定品牌', '0', 2),
]

TOPIC_OPTIONS = [
    # id, form_id, topic_id, option_name, unit_price, unit, is_quantity, remark, sort
    (1, 1, 1, '增肌',     0, '', '0', '', 1),
    (2, 1, 1, '減脂',     0, '', '0', '', 2),
    (3, 1, 1, '維持體重', 0, '', '0', '', 3),
    (4, 1, 1, '搜尋商品', 0, '', '0', '', 4),
]

# id, name, category, phone, address, county_code, rating, description, is_enable
PARTNER_VENDORS = [
    # 健身房（Being Sport — 統一集團旗下健身俱樂部）
    (1,  'Being Sport 信義店', '健身房', '02-2345-0001', '台北市信義區松高路11號',           '01', 4.9, 'Being Sport 旗艦店，多元精品課程，24小時智能門禁',     1),
    (2,  'Being Sport 大安店', '健身房', '02-2700-1234', '台北市大安區敦化南路一段100號',    '01', 4.8, '鄰近捷運，游泳池＋重訓室，專業教練常駐',               1),
    (3,  'Being Sport 板橋店', '健身房', '02-2987-5678', '新北市板橋區文化路二段25號',       '02', 4.7, '雙北最大 Being Sport 館，停車場免費，設備新穎',         1),
    (4,  'Being Sport 桃園店', '健身房', '03-3355-6677', '桃園市桃園區中正路88號',           '03', 4.6, '桃園地區旗艦館，大型有氧教室，提供兒童課程',           1),
    (5,  'Being Sport 台中店', '健身房', '04-2255-8888', '台中市西屯區文心路三段200號',      '04', 4.7, '台中核心地段，多間專業教室，課程種類最豐富',           1),
    # 餐廳
    (6,  '輕食廚房',          '餐廳',   '02-2321-8888', '台北市大安區和平東路一段45號',  '01', 4.7, '提供低卡高蛋白輕食套餐，適合健身族群，可線上訂餐',     1),
    (7,  '蛋白質料理坊',      '餐廳',   '02-2778-9999', '台北市信義區松仁路22號',         '01', 4.6, '專業健身餐盒，每日新鮮製作，提供增肌與減脂兩種菜單', 1),
    (8,  '健康滋味便當',      '餐廳',   '02-2200-3456', '新北市新店區中正路112號',        '02', 4.5, '均衡配餐，少油少鹽，提供外送服務，支援客製菜單',       1),
    (9,  '植物蛋白廚房',      '餐廳',   '04-2255-7788', '台中市西屯區文心路三段200號',    '04', 4.4, '以植物性食材為主，提供素食健身餐，富含植物蛋白',       1),
    # 搬家公司（統一速達搬運部門）
    (10, '統一速達 搬家服務（北部）', '搬家', '0800-020-030', '台北市中山區民族東路410號',     '01', 4.8, '統一集團旗下，專業搬家服務，提供打包、搬運、組裝一條龍',       1),
    (11, '統一速達 搬家服務（中部）', '搬家', '0800-020-030', '台中市西屯區工業區一路2號',     '04', 4.7, '統一集團旗下，中部搬家服務，費用透明，提供大型家具搬運',       1),
    (12, '統一速達 搬家服務（桃園）', '搬家', '0800-020-030', '桃園市中壢區中央西路一段80號',  '03', 4.6, '統一集團旗下，桃園地區搬家，同日報價，環境清潔一條龍',         1),
    # 清潔公司
    (13, '舒潔居家清潔',             '清潔', '02-2345-4444', '台北市大安區信義路三段60號',    '01', 4.9, '到府居家清潔，專業設備，可預約定期清潔，使用環保清潔劑',       1),
    (14, '快速清潔公司',             '清潔', '02-2800-5555', '新北市中和區中正路100號',       '02', 4.7, '公寓、辦公室清潔，深層清潔，紗窗、冷氣、地板拋光',           1),
    (15, '亮潔家事服務',             '清潔', '04-2358-6666', '台中市北屯區太原路三段180號',   '04', 4.6, '台中地區居家清潔，提供一次性與定期清潔方案',                 1),
    # 快遞運輸（統一速達黑貓宅急便）
    (16, '統一速達黑貓宅急便（北部）','快遞運輸','0800-020-030','台北市中山區民族東路410號',  '01', 4.9, '統一集團旗下，全台最大宅配服務，次日達、低溫宅配、ibon 寄件', 1),
    (17, '統一速達黑貓宅急便（中部）','快遞運輸','0800-020-030','台中市西屯區工業區一路2號',  '04', 4.8, '統一集團旗下，中部快遞服務，次日達，支援 7-ELEVEN 取件',       1),
    (18, '統一速達黑貓宅急便（南部）','快遞運輸','0800-020-030','高雄市左營區博愛三路208號',  '05', 4.8, '統一集團旗下，南部快遞服務，提供冷藏低溫宅配，B2C 配送',     1),
    # 保險（統超保險經紀人）
    (19, '統超保險經紀人',           '保險',  '0800-555-880', '台北市大安區光復南路280號',    '01', 4.9, '統一集團旗下保險經紀人，旅遊險、壽險、產險一站式服務，可透過 ibon 投保', 1),
    # 金融證券（統一證券）
    (20, '統一證券',                 '金融',  '0800-060-123', '台北市信義區莊敬路388號',      '01', 4.8, '統一集團旗下證券公司，提供股票、基金、債券、理財規劃，APP 數位開戶', 1),
]

# id, gym_id, course_name, coach, course_type, weekday, time_start, duration_min,
#     max_slots, enrolled, price_month, month, min_students, status, is_enable
GYM_COURSES = [
    # Being Sport 信義店 (gym_id=1)
    (1,  1, '飛輪有氧訓練',   '陳教練', '有氧', '週一,週三,週五', '07:00', 45,  20, 15, 800,  '202607', 10, '已開課', 1),
    (2,  1, '核心肌群強化',   '林教練', '重訓', '週二,週四',      '18:30', 60,  15, 12, 900,  '202607', 10, '已開課', 1),
    (3,  1, '壺鈴功能訓練',   '王教練', '重訓', '週六',           '10:00', 60,  12, 10, 1000, '202607',  8, '已開課', 1),
    (4,  1, '哈他瑜珈初階',   '李教練', '瑜珈', '週二,週四',      '07:00', 60,  15, 15, 750,  '202607',  8, '已開課', 1),
    (5,  1, '有氧舞蹈 Zumba', '陳教練', '舞蹈', '週一,週三',      '19:00', 55,  20, 18, 850,  '202607', 10, '已開課', 1),
    # Being Sport 大安店 (gym_id=2)
    (6,  2, '拳擊有氧',       '張教練', '格鬥', '週一,週三,週五', '19:00', 50,  18, 14, 900,  '202607', 10, '已開課', 1),
    (7,  2, '重訓基礎入門',   '吳教練', '重訓', '週二,週六',      '10:00', 90,  10,  8, 1200, '202607',  6, '已開課', 1),
    (8,  2, '皮拉提斯',       '許教練', '瑜珈', '週三,週五',      '08:00', 60,  12, 11, 950,  '202607',  8, '已開課', 1),
    (9,  2, '泰拳訓練',       '黃教練', '格鬥', '週二,週四',      '20:00', 60,  15, 13, 1000, '202607', 10, '已開課', 1),
    (10, 2, 'TRX 懸吊訓練',   '吳教練', '重訓', '週六,週日',      '14:00', 60,  10,  9, 1100, '202607',  8, '已開課', 1),
    # Being Sport 板橋店 (gym_id=3)
    (11, 3, '晨間有氧操',     '鄭教練', '有氧', '週一至週五',     '06:30', 40,  25, 20, 600,  '202607', 12, '已開課', 1),
    (12, 3, '陰瑜珈放鬆',     '蔡教練', '瑜珈', '週三,週五',      '20:00', 75,  15, 14, 700,  '202607',  8, '已開課', 1),
    (13, 3, '自由重量訓練',   '鄭教練', '重訓', '週二,週四,週六', '17:00', 60,  12,  7, 800,  '202607',  8, '招生中', 1),
    # Being Sport 桃園店 (gym_id=4)
    (14, 4, '動感單車',       '游教練', '有氧', '週一,週三,週五', '18:00', 45,  20, 16, 750,  '202607', 10, '已開課', 1),
    (15, 4, '格鬥有氧 MMA',   '游教練', '格鬥', '週二,週六',      '19:30', 60,  15, 11, 900,  '202607', 10, '已開課', 1),
    (16, 4, '冥想瑜珈',       '謝教練', '瑜珈', '週日',           '09:00', 90,  15, 13, 650,  '202607',  8, '已開課', 1),
    # Being Sport 台中店 (gym_id=5) — 示範各種招生狀態
    (17, 5, '早晨瑜珈',       '吳教練', '瑜珈', '週一,週三,週五', '07:30', 60,  15,  9, 900,  '202607',  8, '已開課', 1),
    (18, 5, '核心強化訓練',   '陳教練', '重訓', '週二,週四',      '19:00', 60,  12,  7, 1000, '202607', 10, '招生中', 1),
    (19, 5, '有氧搏擊',       '林教練', '格鬥', '週三,週六',      '18:30', 50,  15,  8, 950,  '202607',  8, '招生中', 1),
    (20, 5, '重訓入門班',     '陳教練', '重訓', '週六,週日',      '10:00', 90,  10,  5, 1200, '202607', 12, '招生中', 1),
    (21, 5, '伸展放鬆課',     '吳教練', '瑜珈', '週五',           '21:00', 45,  20, 10, 650,  '202607',  6, '已開課', 1),
    # ── 8月份課程 ──
    # Being Sport 信義店 (gym_id=1)
    (22, 1, '飛輪有氧訓練',   '陳教練', '有氧', '週一,週三,週五', '07:00', 45,  20,  3, 800,  '202608', 10, '招生中', 1),
    (23, 1, '核心肌群強化',   '林教練', '重訓', '週二,週四',      '18:30', 60,  15,  2, 900,  '202608', 10, '招生中', 1),
    (24, 1, '壺鈴功能訓練',   '王教練', '重訓', '週六',           '10:00', 60,  12,  0, 1000, '202608',  8, '招生中', 1),
    (25, 1, '哈他瑜珈初階',   '李教練', '瑜珈', '週二,週四',      '07:00', 60,  15,  4, 750,  '202608',  8, '招生中', 1),
    (26, 1, '有氧舞蹈 Zumba', '陳教練', '舞蹈', '週一,週三',      '19:00', 55,  20,  5, 850,  '202608', 10, '招生中', 1),
    # Being Sport 大安店 (gym_id=2)
    (27, 2, '拳擊有氧',       '張教練', '格鬥', '週一,週三,週五', '19:00', 50,  18,  4, 900,  '202608', 10, '招生中', 1),
    (28, 2, '重訓基礎入門',   '吳教練', '重訓', '週二,週六',      '10:00', 90,  10,  2, 1200, '202608',  6, '招生中', 1),
    (29, 2, '皮拉提斯',       '許教練', '瑜珈', '週三,週五',      '08:00', 60,  12,  3, 950,  '202608',  8, '招生中', 1),
    (30, 2, '泰拳訓練',       '黃教練', '格鬥', '週二,週四',      '20:00', 60,  15,  6, 1000, '202608', 10, '招生中', 1),
    (31, 2, 'TRX 懸吊訓練',   '吳教練', '重訓', '週六,週日',      '14:00', 60,  10,  1, 1100, '202608',  8, '招生中', 1),
    # Being Sport 板橋店 (gym_id=3)
    (32, 3, '晨間有氧操',     '鄭教練', '有氧', '週一至週五',     '06:30', 40,  25,  5, 600,  '202608', 12, '招生中', 1),
    (33, 3, '陰瑜珈放鬆',     '蔡教練', '瑜珈', '週三,週五',      '20:00', 75,  15,  3, 700,  '202608',  8, '招生中', 1),
    (34, 3, '自由重量訓練',   '鄭教練', '重訓', '週二,週四,週六', '17:00', 60,  12,  2, 800,  '202608',  8, '招生中', 1),
    # Being Sport 桃園店 (gym_id=4)
    (35, 4, '動感單車',       '游教練', '有氧', '週一,週三,週五', '18:00', 45,  20,  4, 750,  '202608', 10, '招生中', 1),
    (36, 4, '格鬥有氧 MMA',   '游教練', '格鬥', '週二,週六',      '19:30', 60,  15,  3, 900,  '202608', 10, '招生中', 1),
    (37, 4, '冥想瑜珈',       '謝教練', '瑜珈', '週日',           '09:00', 90,  15,  2, 650,  '202608',  8, '招生中', 1),
    # Being Sport 台中店 (gym_id=5)
    (38, 5, '早晨瑜珈',       '吳教練', '瑜珈', '週一,週三,週五', '07:30', 60,  15,  1, 900,  '202608',  8, '招生中', 1),
    (39, 5, '核心強化訓練',   '陳教練', '重訓', '週二,週四',      '19:00', 60,  12,  0, 1000, '202608', 10, '招生中', 1),
    (40, 5, '有氧搏擊',       '林教練', '格鬥', '週三,週六',      '18:30', 50,  15,  0, 950,  '202608',  8, '招生中', 1),
    (41, 5, '重訓入門班',     '陳教練', '重訓', '週六,週日',      '10:00', 90,  10,  0, 1200, '202608', 12, '招生中', 1),
    (42, 5, '伸展放鬆課',     '吳教練', '瑜珈', '週五',           '21:00', 45,  20,  2, 650,  '202608',  6, '招生中', 1),
]

# id, course_id, feedback_no, contact_name, contact_phone, note, status, notified, enrolled_at
COURSE_ENROLLMENTS = [
    # Being Sport 早晨瑜珈 (course_id=17, enrolled=9, min=8, 已開課)
    (1,  17, '',  '王小明', '0912-111-001', '希望安排靠近門口的位置', '確認開課', 1, '2026-07-01T09:00:00'),
    (2,  17, '',  '李美玲', '0912-111-002', '',                       '確認開課', 1, '2026-07-01T10:30:00'),
    (3,  17, '',  '張志遠', '0912-111-003', '第一次上瑜珈課',         '確認開課', 1, '2026-07-02T08:00:00'),
    (4,  17, '',  '陳宜臻', '0912-111-004', '',                       '確認開課', 1, '2026-07-02T14:00:00'),
    (5,  17, '',  '林大衛', '0912-111-005', '有膝蓋舊傷',             '確認開課', 1, '2026-07-03T11:00:00'),
    (6,  17, '',  '黃雅婷', '0912-111-006', '',                       '確認開課', 1, '2026-07-03T16:00:00'),
    (7,  17, '',  '劉建豪', '0912-111-007', '',                       '確認開課', 1, '2026-07-04T09:00:00'),
    (8,  17, '',  '吳雅雯', '0912-111-008', '懷孕初期，需低強度',     '確認開課', 1, '2026-07-05T10:00:00'),
    (9,  17, '',  '蔡俊宏', '0912-111-009', '',                       '確認開課', 1, '2026-07-05T13:00:00'),
    # Being Sport 核心強化訓練 (course_id=18, enrolled=7, min=10, 招生中)
    (10, 18, '',  '許志豪', '0933-222-001', '',                       '報名中',   0, '2026-07-03T09:00:00'),
    (11, 18, '',  '余佩珊', '0933-222-002', '想加強腹部訓練',         '報名中',   0, '2026-07-04T10:00:00'),
    (12, 18, '',  '郭明哲', '0933-222-003', '',                       '報名中',   0, '2026-07-05T11:00:00'),
    (13, 18, '',  '謝淑芬', '0933-222-004', '',                       '報名中',   0, '2026-07-06T09:00:00'),
    (14, 18, '',  '洪建志', '0933-222-005', '有腰傷需告知教練',       '報名中',   0, '2026-07-07T14:00:00'),
    (15, 18, '',  '曾雅芳', '0933-222-006', '',                       '報名中',   0, '2026-07-08T10:00:00'),
    (16, 18, '',  '廖永祥', '0933-222-007', '',                       '報名中',   0, '2026-07-09T09:00:00'),
    # Being Sport 有氧搏擊 (course_id=19, enrolled=8, min=8, 招生中 → 剛好達標可開課)
    (17, 19, '',  '簡俊達', '0966-333-001', '',                       '報名中',   0, '2026-07-02T09:00:00'),
    (18, 19, '',  '蕭美玲', '0966-333-002', '',                       '報名中',   0, '2026-07-02T11:00:00'),
    (19, 19, '',  '鄭文豪', '0966-333-003', '要求安排較輕量練習',     '報名中',   0, '2026-07-03T09:00:00'),
    (20, 19, '',  '楊淑惠', '0966-333-004', '',                       '報名中',   0, '2026-07-04T10:00:00'),
    (21, 19, '',  '彭建明', '0966-333-005', '',                       '報名中',   0, '2026-07-05T09:00:00'),
    (22, 19, '',  '羅雅文', '0966-333-006', '',                       '報名中',   0, '2026-07-06T11:00:00'),
    (23, 19, '',  '江俊輝', '0966-333-007', '',                       '報名中',   0, '2026-07-07T09:00:00'),
    (24, 19, '',  '邱淑貞', '0966-333-008', '第一次上課',             '報名中',   0, '2026-07-08T14:00:00'),
    # Being Sport 重訓入門班 (course_id=20, enrolled=5, min=12, 招生中)
    (25, 20, '',  '葉志明', '0988-444-001', '',                       '報名中',   0, '2026-07-05T09:00:00'),
    (26, 20, '',  '施雅惠', '0988-444-002', '',                       '報名中',   0, '2026-07-06T10:00:00'),
    (27, 20, '',  '侯建宏', '0988-444-003', '想增肌減脂',             '報名中',   0, '2026-07-07T09:00:00'),
    (28, 20, '',  '沈美華', '0988-444-004', '',                       '報名中',   0, '2026-07-08T11:00:00'),
    (29, 20, '',  '卓永信', '0988-444-005', '',                       '報名中',   0, '2026-07-09T09:00:00'),
    # Being Sport 伸展放鬆課 (course_id=21, enrolled=10, min=6, 已開課)
    (30, 21, '',  '莊淑芳', '0911-555-001', '',                       '確認開課', 1, '2026-07-01T09:00:00'),
    (31, 21, '',  '蔣志豪', '0911-555-002', '',                       '確認開課', 1, '2026-07-01T11:00:00'),
    (32, 21, '',  '潘美珍', '0911-555-003', '需要低強度伸展',         '確認開課', 1, '2026-07-02T09:00:00'),
    (33, 21, '',  '馮建國', '0911-555-004', '',                       '確認開課', 1, '2026-07-03T10:00:00'),
    (34, 21, '',  '溫淑靜', '0911-555-005', '',                       '確認開課', 1, '2026-07-04T09:00:00'),
    (35, 21, '',  '袁俊偉', '0911-555-006', '',                       '確認開課', 1, '2026-07-05T11:00:00'),
    (36, 21, '',  '龍雅婷', '0911-555-007', '',                       '確認開課', 1, '2026-07-06T09:00:00'),
    (37, 21, '',  '方建成', '0911-555-008', '',                       '確認開課', 1, '2026-07-07T10:00:00'),
    (38, 21, '',  '安志遠', '0911-555-009', '辦公室久坐，需重點伸展', '確認開課', 1, '2026-07-08T09:00:00'),
    (39, 21, '',  '費淑芬', '0911-555-010', '',                       '確認開課', 1, '2026-07-09T11:00:00'),
]


def main():
    # 保護：EC2 上 DB 已存在時，必須明確設定 ALLOW_SEED_RESET=yes 才能重建
    if os.path.exists(DB):
        if os.getenv("ALLOW_SEED_RESET", "").lower() not in ("yes", "1", "true"):
            print(f"[seed] butler.db 已存在，略過重建。如需強制重建請設 ALLOW_SEED_RESET=yes")
            return
        os.remove(DB)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    now = datetime.now().isoformat()
    sys_uuid = _uuid7()  # 系統操作者 UUID（seed 用）

    cur.executemany(
        "INSERT INTO fitness_product "
        "(id,name,vendor,category,protein_g,calories,price,stock) VALUES (?,?,?,?,?,?,?,?)",
        PRODUCTS,
    )
    # sys_county：補上官方欄位
    cur.executemany(
        "INSERT INTO sys_county (code,name,sort,is_deleted,upd_time,cre_time,upd_id,cre_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(c[0], c[1], i+1, '0', now, now, sys_uuid, sys_uuid)
         for i, c in enumerate(COUNTIES)],
    )
    # sys_district：補上官方欄位（name_with_county = name + 縣市名）
    county_name_map = {c[0]: c[1] for c in COUNTIES}
    cur.executemany(
        "INSERT INTO sys_district "
        "(code,county_code,name,name_with_county,zip,sort,is_deleted,upd_time,cre_time,upd_id,cre_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(d[0], d[1], d[2],
          d[2] + county_name_map.get(d[1], ''),
          d[3], i+1, '0', now, now, sys_uuid, sys_uuid)
         for i, d in enumerate(DISTRICTS)],
    )
    # cms_homepage_service_vendor：對齊官方欄位
    cur.executemany(
        "INSERT INTO cms_homepage_service_vendor "
        "(id,name,description,category,rating,phone,address,county_code,is_enable) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        SERVICE_VENDORS,
    )
    # cms_homepage_service：service_vendor_id（官方欄位名）
    cur.executemany(
        "INSERT INTO cms_homepage_service "
        "(id,service_vendor_id,type,name,img_url,description,intro_content,is_enable) "
        "VALUES (?,?,?,?,?,?,?,?)",
        SERVICES,
    )
    # pms_form：補上官方欄位
    cur.executemany(
        "INSERT INTO pms_form "
        "(id,service_vendor_id,type,sub_type,name,intro_content,is_enable,cre_time,upd_time,cre_id,upd_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(f[0], f[1], f[2], f[3], f[4], f[5], f[6], now, now, sys_uuid, sys_uuid)
         for f in FORMS],
    )
    # pms_form_group
    cur.executemany(
        "INSERT INTO pms_form_group (id,form_id,name,sort,cre_time,upd_time,cre_id,upd_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(g[0], g[1], g[2], g[3], now, now, sys_uuid, sys_uuid)
         for g in FORM_GROUPS],
    )
    # pms_form_topic：form_group_id（官方欄位名）
    cur.executemany(
        "INSERT INTO pms_form_topic "
        "(id,form_id,form_group_id,type,title,remark,is_required,sort,cre_time,upd_time,cre_id,upd_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], now, now, sys_uuid, sys_uuid)
         for t in FORM_TOPICS],
    )
    # pms_topic_option：補上官方欄位（form_id, is_quantity, remark, feature）
    cur.executemany(
        "INSERT INTO pms_topic_option "
        "(id,form_id,topic_id,option_name,unit_price,unit,is_quantity,remark,sort,cre_time,upd_time,cre_id,upd_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], now, now, sys_uuid, sys_uuid)
         for o in TOPIC_OPTIONS],
    )
    cur.executemany(
        "INSERT INTO partner_vendor "
        "(id,name,category,phone,address,county_code,rating,description,is_enable) VALUES (?,?,?,?,?,?,?,?,?)",
        PARTNER_VENDORS,
    )
    cur.executemany(
        "INSERT INTO gym_course "
        "(id,gym_id,course_name,coach,course_type,weekday,time_start,duration_min,"
        " max_slots,enrolled,price_month,month,min_students,status,is_enable) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        GYM_COURSES,
    )
    cur.executemany(
        "INSERT INTO course_enrollment "
        "(id,course_id,feedback_no,contact_name,contact_phone,note,status,notified,enrolled_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        COURSE_ENROLLMENTS,
    )
    cur.executemany(
        "INSERT INTO vendor_users (username,password,store_name,brand,address,created_at) VALUES (?,?,?,?,?,?)",
        [
            ("7-11-A",      "vendor123", "7-11 A門市",           "7-11",         "台北市信義區松仁路28號",       now),
            ("7-11-B",      "vendor123", "7-11 B門市",           "7-11",         "台北市信義區基隆路一段200號",   now),
            ("wanjiafu",    "vendor123", "萬家福信義店",           "萬家福",       "台北市信義區忠孝東路五段68號",  now),
            ("cosmed",      "vendor123", "康是美中山店",           "康是美",       "台北市中山區南京東路二段100號", now),
            ("misterdonut", "vendor123", "Mister Donut 大安店",   "Mister Donut", "台北市大安區忠孝東路四段181號1F", now),
            ("coldstone",   "vendor123", "Cold Stone 信義店",     "Cold Stone",   "台北市信義區松壽路11號1F",     now),
            ("21plus",      "vendor123", "21plus 信義旗艦店",     "21plus",       "台北市信義區菸廠路88號",       now),
            ("starbucks",   "vendor123", "統一星巴克 信義店",     "統一星巴克",   "台北市信義區松壽路1號1F",      now),
            ("sanitas",     "vendor123", "聖德科斯 中山店",       "聖德科斯",     "台北市中山區南京東路二段30號",  now),
            ("beingsport",  "gym123",    "Being Sport 健身中心",  "健身房",       "台北市信義區松高路11號",       now),
            ("insurance",   "ins123",    "統超保險經紀人",         "保險",         "台北市大安區光復南路280號",    now),
            ("unisec",      "sec123",    "統一證券",              "金融",         "台北市信義區莊敬路388號",      now),
            ("driver1",     "driver123", "外送員 小明",           "外送員",       "",                            now),
            ("driver2",     "driver123", "外送員 小華",           "外送員",       "",                            now),
            ("admin",       "admin123",  "管理員",                "全部",         "",                            now),
        ],
    )
    con.commit()

    tables = [
        "fitness_product", "users", "sys_county", "sys_district",
        "cms_homepage_service_vendor", "cms_homepage_service",
        "pms_form", "pms_form_group", "pms_form_topic",
        "pms_topic_media", "pms_topic_option",
        "pms_form_feedback", "mms_order_record",
        "partner_vendor", "gym_course", "course_enrollment",
    ]
    for t in tables:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<32} {n} 筆")
    con.close()
    print(f"\n資料庫建立完成：{DB}")


if __name__ == "__main__":
    main()
