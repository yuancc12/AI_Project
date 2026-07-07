# -*- coding: utf-8 -*-
"""
seed.py — 建立健身採買助手的 SQLite 資料庫並塞入擬真假資料。
執行：  python seed.py
產出：  butler.db
"""
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "butler.db")

SCHEMA = """
DROP TABLE IF EXISTS fitness_product;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS inquiry;

CREATE TABLE fitness_product (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    vendor     TEXT NOT NULL,   -- 家樂福 / 7-11 / 康是美 / 統一生機
    category   TEXT NOT NULL,   -- 蛋白質 / 主食 / 蔬果 / 乳製品 / 保健品 / 即食
    protein_g  REAL NOT NULL DEFAULT 0,
    calories   INTEGER NOT NULL DEFAULT 0,
    price      INTEGER NOT NULL,
    stock      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT UNIQUE NOT NULL,
    password   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 健身採買諮詢單（submit_inquiry 寫入此表）
CREATE TABLE inquiry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inquiry_no    TEXT UNIQUE NOT NULL,
    goal          TEXT,          -- 增肌 / 減脂 / 搜尋
    budget        INTEGER DEFAULT 0,
    keyword       TEXT,
    contact_name  TEXT,
    contact_phone TEXT,
    note          TEXT,
    status        TEXT NOT NULL DEFAULT '待處理',
    created_at    TEXT NOT NULL
);
"""

# id, name, vendor, category, protein_g, calories, price, stock
PRODUCTS = [
    (1,  "雞胸肉(去骨)",        "家樂福",  "蛋白質", 31.0, 165,  65,  120),
    (2,  "舒肥雞胸肉(原味)",    "7-11",    "即食",   23.0, 110,  49,   80),
    (3,  "醬燒舒肥雞胸肉",      "7-11",    "即食",   20.0, 130,  55,   70),
    (4,  "水煮蛋(2入)",         "7-11",    "蛋白質",  6.0,  70,  15,  150),
    (5,  "鮪魚罐頭(水漬)",      "7-11",    "蛋白質", 26.0, 130,  45,   90),
    (6,  "無糖豆漿(450ml)",     "7-11",    "乳製品",  7.0,  70,  30,  100),
    (7,  "低脂牛奶(400ml)",     "7-11",    "乳製品",  8.0, 100,  35,  100),
    (8,  "蒸地瓜(170g)",        "7-11",    "主食",    2.0, 100,  35,   60),
    (9,  "鮭魚排(180g)",        "家樂福",  "蛋白質", 25.0, 200, 180,   40),
    (10, "牛腱肉(200g)",        "家樂福",  "蛋白質", 28.0, 175, 150,   30),
    (11, "雞蛋(10入)",          "家樂福",  "蛋白質",  6.0,  70,  65,  200),
    (12, "鮮蝦仁(200g)",        "家樂福",  "蛋白質", 24.0, 100, 180,   50),
    (13, "板豆腐(300g)",        "家樂福",  "蛋白質",  8.0,  75,  30,  100),
    (14, "希臘優格(無糖)",      "家樂福",  "乳製品", 10.0, 100,  65,   60),
    (15, "茅屋起司(200g)",      "家樂福",  "乳製品", 11.0, 100, 120,   30),
    (16, "地瓜(600g)",          "家樂福",  "主食",    2.0, 130,  40,  200),
    (17, "花椰菜(400g)",        "家樂福",  "蔬果",    3.0,  30,  35,  100),
    (18, "冷凍毛豆(500g)",      "家樂福",  "蔬果",   11.0, 120,  60,   80),
    (19, "菠菜(300g)",          "家樂福",  "蔬果",    3.0,  25,  30,  120),
    (20, "酪梨",                "家樂福",  "蔬果",    2.0, 160,  60,   60),
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
    (31, "燕麥奶(1000ml)",      "統一生機", "乳製品",  3.0, 120,  85,   40),
]


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    cur.executemany(
        "INSERT INTO fitness_product "
        "(id,name,vendor,category,protein_g,calories,price,stock) VALUES (?,?,?,?,?,?,?,?)",
        PRODUCTS,
    )
    con.commit()

    for t in ["fitness_product", "users", "inquiry"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<22} {n} 筆")
    con.close()
    print(f"\n✅ 資料庫建立完成：{DB}")


if __name__ == "__main__":
    main()
