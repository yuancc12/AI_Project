# -*- coding: utf-8 -*-
"""
app_helpers.py — 健康生活助手輔助模組
純 Python 函式：DB helpers、工具定義常數、歷史壓縮、純文字工具函式
匯入方式：from app_helpers import (DB_PATH, _db, check_login, ...)
"""
import os
import json
import sqlite3
import asyncio
import concurrent.futures
from datetime import datetime
import anthropic
from openai import OpenAI
from mcp import Client

_HERE = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB_PATH):
    import seed as _seed
    _seed.main()

from mcp_server import (
    search_grocery,
    recommend_high_protein,
    check_inventory,
    submit_inquiry,
    find_nearby_stores,
    find_route,
    get_current_time,
    get_weather,
    search_recipe,
    analyze_meal_nutrition,
    recommend_after_meal,
    calculate_tdee,
    get_gym_courses,
    enroll_gym_course,
    find_sports_venues,
    mcp as _mcp,
)

_ollama = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
OLLAMA_MODEL = "qwen2.5:7b"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def check_login(username, password):
    con = _db()
    row = con.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def _ensure_users_columns():
    """為舊版 DB 補上新欄位（ALTER TABLE 若欄位已存在會靜默失敗）。"""
    con = _db()
    for col, defn in [
        ("birthday",     "TEXT NOT NULL DEFAULT ''"),
        ("email",        "TEXT NOT NULL DEFAULT ''"),
        ("dietary_pref", "TEXT NOT NULL DEFAULT ''"),
    ]:
        try:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
        except Exception:
            pass
    con.commit(); con.close()

_ensure_users_columns()


def register_user(username, password, gender="", birthday="",
                  height_cm=0.0, weight_kg=0.0,
                  email="", dietary_pref="",
                  county_code="", district_code="",
                  address="", contact_phone=""):
    try:
        con = _db()
        con.execute(
            "INSERT INTO users "
            "(username,password,gender,birthday,height_cm,weight_kg,"
            "email,dietary_pref,county_code,district_code,address,contact_phone,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, password, gender, birthday, height_cm, weight_kg,
             email, dietary_pref, county_code, district_code,
             address, contact_phone, datetime.now().isoformat()),
        )
        con.commit(); con.close(); return True
    except Exception:
        return False


def get_counties() -> list:
    """回傳所有縣市 [(code, name), ...]，依 code 排序。"""
    con = _db()
    rows = con.execute("SELECT code, name FROM sys_county ORDER BY code").fetchall()
    con.close()
    return [(r["code"], r["name"]) for r in rows]


def get_districts(county_code: str) -> list:
    """回傳指定縣市的行政區 [(code, name), ...]。"""
    con = _db()
    rows = con.execute(
        "SELECT code, name FROM sys_district WHERE county_code=? ORDER BY code",
        (county_code,)
    ).fetchall()
    con.close()
    return [(r["code"], r["name"]) for r in rows]


def get_my_inquiries(user_id: int) -> list:
    con = _db()
    rows = con.execute(
        """SELECT f.*, m.order_no as delivery_no
           FROM pms_form_feedback f
           LEFT JOIN mms_order_record m ON f.feedback_no = m.feedback_no
           WHERE f.user_id=? ORDER BY f.created_at DESC""",
        (user_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_user_reply(feedback_no: str, message: str, username: str = "用戶"):
    ts = datetime.now().strftime("%m/%d %H:%M")
    entry = f"{ts} [{username}]: {message}\n"
    con = _db()
    con.execute(
        "UPDATE pms_form_feedback SET user_reply = COALESCE(user_reply,'') || ? WHERE feedback_no=?",
        (entry, feedback_no),
    )
    con.commit()
    con.close()


def delete_conversation(conv_id: int):
    con = _db()
    con.execute("DELETE FROM conversation WHERE id=?", (conv_id,))
    con.commit(); con.close()


def rename_conversation(conv_id: int, new_title: str):
    con = _db()
    con.execute("UPDATE conversation SET title=? WHERE id=?", (new_title.strip(), conv_id))
    con.commit(); con.close()


# ── 對話記錄 DB（不跟 seed.py 耦合，用 CREATE IF NOT EXISTS）──────────────────

def _ensure_conversation_table():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS conversation (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            title       TEXT NOT NULL DEFAULT '新對話',
            disp_json   TEXT NOT NULL DEFAULT '[]',
            ollama_json TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    con.commit(); con.close()

_ensure_conversation_table()


def _ensure_users_schema():
    """既有 users 表缺少欄位時自動補上（不刪資料）。"""
    con = _db()
    cols = {row[1] for row in con.execute("PRAGMA table_info(users)")}
    for col, defn in [
        ("gender",        "TEXT NOT NULL DEFAULT ''"),
        ("age",           "INTEGER NOT NULL DEFAULT 0"),
        ("height_cm",     "REAL NOT NULL DEFAULT 0"),
        ("weight_kg",     "REAL NOT NULL DEFAULT 0"),
        ("fitness_goal",  "TEXT NOT NULL DEFAULT ''"),
        ("county_code",   "TEXT NOT NULL DEFAULT ''"),
        ("district_code", "TEXT NOT NULL DEFAULT ''"),
        ("address",       "TEXT NOT NULL DEFAULT ''"),
        ("contact_phone", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in cols:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
    con.commit()
    con.close()


_COUNTIES_DATA = [
    ('01','台北市'),('02','新北市'),('03','基隆市'),('04','桃園市'),
    ('05','新竹縣'),('06','新竹市'),('07','苗栗縣'),('08','台中市'),
    ('09','南投縣'),('10','彰化縣'),('11','雲林縣'),('12','嘉義縣'),
    ('13','嘉義市'),('14','台南市'),('15','高雄市'),('16','屏東縣'),
    ('17','宜蘭縣'),('18','花蓮縣'),('19','台東縣'),('20','澎湖縣'),
    ('21','金門縣'),('22','連江縣'),
]
_DISTRICTS_DATA = [
    ('001','01','中正區','100'),('002','01','大同區','103'),('003','01','中山區','104'),
    ('004','01','萬華區','108'),('005','01','信義區','110'),('006','01','松山區','105'),
    ('007','01','大安區','106'),('008','01','南港區','115'),('009','01','北投區','112'),
    ('010','01','內湖區','114'),('011','01','士林區','111'),('012','01','文山區','116'),
    ('013','02','板橋區','220'),('014','02','新莊區','242'),('015','02','泰山區','243'),
    ('016','02','林口區','244'),('017','02','淡水區','251'),('018','02','金山區','208'),
    ('019','02','八里區','249'),('020','02','萬里區','207'),('021','02','石門區','253'),
    ('022','02','三芝區','252'),('023','02','瑞芳區','224'),('024','02','汐止區','221'),
    ('025','02','平溪區','226'),('026','02','貢寮區','228'),('027','02','雙溪區','227'),
    ('028','02','深坑區','222'),('029','02','石碇區','223'),('030','02','新店區','231'),
    ('031','02','坪林區','232'),('032','02','烏來區','233'),('033','02','中和區','235'),
    ('034','02','永和區','234'),('035','02','土城區','236'),('036','02','三峽區','237'),
    ('037','02','樹林區','238'),('038','02','鶯歌區','239'),('039','02','三重區','241'),
    ('040','02','蘆洲區','247'),('041','02','五股區','248'),
    ('042','03','仁愛區','200'),('043','03','中正區','202'),('044','03','信義區','201'),
    ('045','03','中山區','203'),('046','03','安樂區','204'),('047','03','暖暖區','205'),
    ('048','03','七堵區','206'),
    ('049','04','桃園區','330'),('050','04','中壢區','320'),('051','04','平鎮區','324'),
    ('052','04','八德區','334'),('053','04','楊梅區','326'),('054','04','蘆竹區','338'),
    ('055','04','龜山區','333'),('056','04','龍潭區','325'),('057','04','大溪區','335'),
    ('058','04','大園區','337'),('059','04','觀音區','328'),('060','04','新屋區','327'),
    ('061','04','復興區','336'),
    ('062','05','竹北市','302'),('063','05','竹東鎮','310'),('064','05','新埔鎮','305'),
    ('065','05','關西鎮','306'),('066','05','峨眉鄉','315'),('067','05','寶山鄉','308'),
    ('068','05','北埔鄉','314'),('069','05','橫山鄉','312'),
    ('238','14','山上區','743'),('239','14','新市區','744'),('240','14','安定區','745'),
    ('241','15','楠梓區','811'),('242','15','左營區','813'),('243','15','鼓山區','804'),
    ('244','15','三民區','807'),('245','15','鹽埕區','803'),('246','15','前金區','801'),
    ('247','15','新興區','800'),('248','15','苓雅區','802'),('249','15','前鎮區','806'),
    ('250','15','小港區','812'),('251','15','旗津區','805'),('252','15','鳳山區','830'),
    ('253','15','大寮區','831'),('254','15','鳥松區','833'),('255','15','林園區','832'),
    ('256','15','仁武區','814'),('257','15','大樹區','840'),('258','15','大社區','815'),
    ('259','15','岡山區','820'),('260','15','路竹區','821'),('261','15','橋頭區','825'),
    ('262','15','梓官區','826'),('263','15','彌陀區','827'),('264','15','永安區','828'),
    ('265','15','燕巢區','824'),('266','15','田寮區','823'),('267','15','阿蓮區','822'),
    ('268','15','茄萣區','852'),('269','15','湖內區','829'),('270','15','旗山區','842'),
    ('271','15','美濃區','843'),('272','15','內門區','845'),('273','15','杉林區','846'),
    ('274','15','甲仙區','847'),('275','15','六龜區','844'),('276','15','茂林區','851'),
    ('277','15','桃源區','848'),('278','15','那瑪夏區','849'),
    ('279','16','屏東市','900'),('280','16','潮州鎮','920'),('281','16','東港鎮','928'),
    ('282','16','恆春鎮','946'),('283','16','萬丹鄉','913'),('284','16','長治鄉','908'),
    ('285','16','麟洛鄉','909'),('286','16','九如鄉','904'),('287','16','里港鄉','905'),
    ('288','16','鹽埔鄉','907'),('289','16','高樹鄉','906'),('290','16','萬巒鄉','923'),
    ('291','16','內埔鄉','912'),('292','16','竹田鄉','911'),('293','16','新埤鄉','925'),
    ('294','16','枋寮鄉','940'),('295','16','新園鄉','932'),('296','16','崁頂鄉','924'),
    ('297','16','林邊鄉','927'),('298','16','南州鄉','926'),('299','16','佳冬鄉','931'),
    ('300','16','琉球鄉','929'),('301','16','車城鄉','944'),('302','16','滿州鄉','947'),
    ('303','16','枋山鄉','941'),('304','16','霧台鄉','902'),('305','16','瑪家鄉','903'),
    ('306','16','泰武鄉','921'),('307','16','來義鄉','922'),('308','16','春日鄉','942'),
    ('309','16','獅子鄉','943'),('310','16','牡丹鄉','945'),('311','16','三地門鄉','901'),
    ('312','17','宜蘭市','260'),('313','17','羅東鎮','265'),('314','17','蘇澳鎮','270'),
    ('315','17','頭城鎮','261'),('316','17','礁溪鄉','262'),('317','17','壯圍鄉','263'),
    ('318','17','員山鄉','264'),('319','17','冬山鄉','269'),('320','17','五結鄉','268'),
    ('321','17','三星鄉','266'),('322','17','大同鄉','267'),('323','17','南澳鄉','272'),
    ('324','18','花蓮市','970'),('325','18','鳳林鎮','975'),('326','18','玉里鎮','981'),
    ('327','18','新城鄉','971'),('328','18','吉安鄉','973'),('329','18','壽豐鄉','974'),
    ('330','18','秀林鄉','972'),('331','18','光復鄉','976'),('332','18','豐濱鄉','977'),
    ('333','18','瑞穗鄉','978'),('334','18','萬榮鄉','979'),('335','18','富里鄉','983'),
    ('336','18','卓溪鄉','982'),
    ('337','19','台東市','950'),('338','19','成功鎮','961'),('339','19','關山鎮','956'),
    ('340','19','長濱鄉','962'),('341','19','海端鄉','957'),('342','19','池上鄉','958'),
    ('343','19','東河鄉','959'),('344','19','鹿野鄉','955'),('345','19','延平鄉','953'),
    ('346','19','卑南鄉','954'),('347','19','金峰鄉','964'),('348','19','大武鄉','965'),
    ('349','19','達仁鄉','966'),('350','19','綠島鄉','951'),('351','19','蘭嶼鄉','952'),
    ('352','19','太麻里鄉','963'),
    ('353','20','馬公市','880'),('354','20','湖西鄉','885'),('355','20','白沙鄉','884'),
    ('356','20','西嶼鄉','881'),('357','20','望安鄉','882'),('358','20','七美鄉','883'),
    ('359','21','金城鎮','893'),('360','21','金湖鎮','891'),('361','21','金沙鎮','890'),
    ('362','21','金寧鄉','892'),('363','21','烈嶼鄉','894'),('364','21','烏坵鄉','896'),
    ('365','22','南竿鄉','209'),('366','22','北竿鄉','210'),
    ('367','22','莒光鄉','211'),('368','22','東引鄉','212'),
]


def _ensure_county_data():
    """若 sys_county 仍為舊的 5 筆資料，自動更新為完整 22 縣市。"""
    con = _db()
    count = con.execute("SELECT COUNT(*) FROM sys_county").fetchone()[0]
    if count < 22:
        con.execute("DELETE FROM sys_county")
        con.execute("DELETE FROM sys_district")
        con.executemany("INSERT OR IGNORE INTO sys_county (code,name) VALUES (?,?)", _COUNTIES_DATA)
        con.executemany(
            "INSERT OR IGNORE INTO sys_district (code,county_code,name,zip) VALUES (?,?,?,?)",
            _DISTRICTS_DATA,
        )
        con.commit()
    con.close()

_ensure_users_schema()
_ensure_county_data()


def get_conversations(user_id: int, limit: int = 25) -> list:
    con = _db()
    rows = con.execute(
        "SELECT id, title, updated_at FROM conversation "
        "WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def load_conv_from_db(conv_id: int) -> dict:
    con = _db()
    row = con.execute("SELECT * FROM conversation WHERE id=?", (conv_id,)).fetchone()
    con.close()
    return dict(row) if row else {}


def save_conv_to_db(user_id: int, conv_id, display_msgs: list, ollama_history: list) -> int:
    title = "新對話"
    for msg in display_msgs:
        content = (msg.get("content") or "").strip()
        if msg.get("role") == "user" and content and not content.startswith("（"):
            title = content[:28]
            break
    now = datetime.now().isoformat()
    dj  = json.dumps(display_msgs,   ensure_ascii=False)
    oj  = json.dumps(ollama_history,  ensure_ascii=False)
    con = _db()
    if conv_id:
        con.execute(
            "UPDATE conversation SET title=?,disp_json=?,ollama_json=?,updated_at=? WHERE id=?",
            (title, dj, oj, now, conv_id),
        )
    else:
        cur    = con.execute(
            "INSERT INTO conversation (user_id,title,disp_json,ollama_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, title, dj, oj, now, now),
        )
        conv_id = cur.lastrowid
    con.commit(); con.close()
    return conv_id


# ── Claude 工具定義 ───────────────────────────────────────────────────────────

CLAUDE_TOOLS = [
    {
        "name": "search_grocery",
        "description": (
            "在統一集團各業務（7-11、萬家福、康是美、統一生機）搜尋健康商品。"
            "當用戶詢問特定商品在哪裡可以買到，或想瀏覽某類商品時使用。\n"
            "【CRITICAL】keyword **只接受單一商品關鍵字**，禁止用逗號、頓號分隔多個商品名稱。"
            "需查多個商品請分次呼叫，每次傳一個關鍵字。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "單一商品關鍵字，如：雞胸肉（禁止傳入「雞胸肉,豆腐」等多個）"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "recommend_high_protein",
        "description": (
            "根據健康目標與採買預算，推薦高蛋白商品組合。"
            "當用戶有採買/推薦商品需求時使用，禁止在此場景呼叫 calculate_tdee。\n"
            "goal 和 budget 從對話中判斷填入；若 goal 缺少，工具會回傳詢問訊息讓 AI 向用戶提問；"
            "若 budget 缺少，請先詢問用戶再呼叫。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "integer", "description": "採買預算（台幣）"},
                "goal":   {"type": "string",  "description": "健康目標：增肌 或 減脂（從對話判斷）"},
            },
            "required": ["budget"],
        },
    },
    {
        "name": "check_inventory",
        "description": (
            "查詢某商品在各通路的庫存狀況。"
            "當用戶詢問某商品是否有貨、庫存剩多少時使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "商品名稱或關鍵字"},
            },
            "required": ["product_name"],
        },
    },
    {
        "name": "submit_inquiry",
        "description": (
            "【寫入工具】建立諮詢單，將用戶需求記錄到後台讓工作人員跟進。\n"
            "【呼叫前提 CRITICAL】必須同時滿足：\n"
            "① 用戶明確說「好」「要」「幫我建立」「下單」「確認」等同意詞語\n"
            "② 已收到真實姓名（非佔位符）AND 真實電話（非佔位符）\n"
            "③ 已確認取件方式（自取或外送），外送時已收到配送地址\n"
            "【products_json 規則】只放用戶明確指定的商品物件，禁止放整批搜尋結果。\n"
            "【delivery_type 規則】用戶說「自取」「我去拿」→ 傳 '自取'；其他情況預設 '外送'。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal":          {"type": "string",  "description": "目標/需求，例如「增肌採買」「搬家諮詢」"},
                "contact_name":  {"type": "string",  "description": "聯絡人姓名"},
                "contact_phone": {"type": "string",  "description": "聯絡電話"},
                "budget":        {"type": "integer", "description": "預算（選填）"},
                "keyword":       {"type": "string",  "description": "關鍵字（選填）"},
                "note":          {"type": "string",  "description": "備註與需求詳情（選填）"},
                "address":       {"type": "string",  "description": "外送地址（delivery_type='外送' 時必填）"},
                "products_json": {"type": "string",  "description": "用戶指定商品的 JSON 陣列，只放明確指定的品項"},
                "user_id":       {"type": "integer", "description": "用戶 ID（系統自動填入）"},
                "delivery_type": {"type": "string",  "description": "'外送'（預設）或 '自取'",
                                  "enum": ["外送", "自取"]},
                "pickup_store":  {"type": "string",  "description": "自取門市名稱（delivery_type='自取' 時選填）"},
            },
            "required": ["goal", "contact_name", "contact_phone"],
        },
    },
    {
        "name": "get_current_time",
        "description": (
            "取得台灣當前時間、日期與星期幾。"
            "當用戶問現在幾點、今天星期幾、或需根據時段判斷門市是否營業時使用。"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_nearby_stores",
        "description": (
            "搜尋用戶附近的地點，使用 OpenStreetMap Overpass API。\n"
            "由 AI 根據用戶需求判斷並填入 name 與 category 參數後呼叫。\n"
            "lat/lng 由系統自動注入，AI 不需傳入。\n\n"
            "【AI 判斷規則】\n"
            "・用戶問 7-11 / 7-Eleven / 便利商店 / 超商 / 附近哪裡買 → name=\"7-ELEVEN\", category=\"convenience\"（name 必填，不可空白）\n"
            "・用戶問萬家福 / 超市 → name=\"萬家福\", category=\"supermarket\"\n"
            "・用戶問康是美 / Cosmed / 藥妝 → name=\"康是美\", category=\"\"\n"
            "・用戶問統一生機 → name=\"統一生機\", category=\"\"\n"
            "・用戶問餐廳 / 吃飯 → name=\"\", category=\"restaurant\"\n"
            "・用戶問咖啡廳 / 咖啡 → name=\"\", category=\"cafe\"\n"
            "・用戶問健身房 / gym → name=\"\", category=\"fitness_centre\"\n"
            "・用戶問藥局 / 藥房 → name=\"\", category=\"pharmacy\"\n"
            "・用戶問診所 → name=\"\", category=\"clinic\"\n"
            "・用戶問醫院 → name=\"\", category=\"hospital\"\n"
            "・用戶問麵包店 → name=\"\", category=\"bakery\"\n"
            "・其他特定品牌（如「麥當勞」「星巴克」）→ name 填品牌名，category 填對應類型\n"
            "【重要】用戶詢問任何附近地點時，直接呼叫此工具，不要說「我的功能限於統一門市」。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lat":      {"type": "number",  "description": "緯度（系統自動注入，AI 可省略不填）"},
                "lng":      {"type": "number",  "description": "經度（系統自動注入，AI 可省略不填）"},
                "radius_m": {"type": "integer", "description": "搜尋半徑（公尺），預設 1500，用戶說「更遠一點」可傳 3000"},
                "name":     {"type": "string",  "description": "店家名稱或品牌（OSM name/brand/operator 精確比對），例：7-ELEVEN、萬家福、麥當勞"},
                "category": {"type": "string",  "description": "OSM 地點類型：convenience/supermarket/restaurant/cafe/pharmacy/clinic/hospital/bakery/fitness_centre/sports_centre"},
            },
            "required": [],
        },
    },
    {
        "name": "find_route",
        "description": (
            "計算從多個取貨門市到用戶配送地址的最佳路線，使用 OSRM 計算實際道路距離與順序。"
            "當用戶詢問外送路線、最佳取貨順序，或確認配送路徑時使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "stops_json":   {"type": "string", "description": "取貨停靠點 JSON 陣列，每項含 name 和 lat/lng 或 address"},
                "dest_lat":     {"type": "number", "description": "目的地緯度"},
                "dest_lng":     {"type": "number", "description": "目的地經度"},
                "dest_address": {"type": "string", "description": "配送目的地文字地址"},
            },
            "required": ["stops_json"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "查詢指定地點的即時天氣（氣溫、體感溫度、天氣狀況、濕度、風速），"
            "並給出是否適合外出採買或戶外運動的建議。使用 Open-Meteo 免費 API，無需金鑰。\n"
            "lat/lng 由系統自動注入，AI 不需手動填入。"
            "若無 GPS 座標，可傳入 city（例如「台北市」「新竹市」）自動地理編碼。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lat":  {"type": "number", "description": "緯度（系統自動注入，AI 可省略）"},
                "lng":  {"type": "number", "description": "經度（系統自動注入，AI 可省略）"},
                "city": {"type": "string", "description": "城市名稱，無 GPS 時使用，例如「台北市」"},
            },
            "required": [],
        },
    },
    {
        "name": "search_recipe",
        "description": (
            "依食材或料理名稱搜尋食譜，回傳食材清單、烹飪步驟與所需時間。\n"
            "當用戶問「用雞胸肉可以做什麼」「推薦低卡晚餐」「蛋炒飯怎麼做」時呼叫。\n"
            "優先使用 Spoonacular API，若未設定則改用 Edamam Recipe API。\n"
            "query 盡量用英文效果最好（如 chicken breast、pasta、fried rice）；"
            "中文也可，但 API 回傳結果可能較少。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "料理關鍵字，例如「chicken breast」「low calorie dinner」「蛋炒飯」",
                },
                "ingredients": {
                    "type": "string",
                    "description": "手邊食材（逗號分隔），例如「chicken,broccoli,olive oil」",
                },
                "diet": {
                    "type": "string",
                    "description": "飲食限制：vegetarian / vegan / gluten+free / ketogenic / low-carb / high-protein",
                },
                "cuisine": {
                    "type": "string",
                    "description": "料理類型：chinese / japanese / italian / thai / mexican / korean",
                },
                "max_results": {
                    "type": "integer",
                    "description": "回傳食譜數量（1-5，預設 3）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyze_meal_nutrition",
        "description": (
            "查詢單一食物的營養成分，依攝取克數計算熱量與蛋白質等。"
            "每次只查詢一種食物。當用戶描述今日飲食時，AI 應從自然語言中判斷每項食物名稱與克數，"
            "然後逐項呼叫此工具；最後將所有結果的 calories 與 protein_g 加總，"
            "傳入 recommend_after_meal 取得補充採買建議。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "food_name": {
                    "type": "string",
                    "description": "單一食物名稱，例如「雞胸肉」「白飯」「雞蛋」「燕麥」",
                },
                "amount_g": {
                    "type": "number",
                    "description": "攝取量（公克），例如 150、400、120",
                },
            },
            "required": ["food_name", "amount_g"],
        },
    },
    {
        "name": "recommend_after_meal",
        "description": (
            "根據用戶今日已攝取的總熱量與總蛋白質，從商品庫推薦應補充購買的健康食品。"
            "在 analyze_meal_nutrition 多次呼叫後，將各次的 calories 相加得到 calories_eaten，"
            "將各次的 protein_g 相加得到 protein_eaten，再呼叫此工具。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "calories_eaten": {"type": "number",  "description": "今日已攝取總熱量（kcal），為多次查詢加總"},
                "protein_eaten":  {"type": "number",  "description": "今日已攝取總蛋白質（g），為多次查詢加總"},
                "fitness_goal":   {"type": "string",  "description": "健康目標：增肌 或 減脂，預設增肌"},
                "budget":         {"type": "integer", "description": "採買預算（元），預設 500"},
            },
            "required": ["calories_eaten", "protein_eaten"],
        },
    },
    {
        "name": "calculate_tdee",
        "description": (
            "計算基礎代謝率（BMR）與每日總能量消耗（TDEE），給出個人化熱量與三大營養素建議。\n"
            "【唯一觸發條件】用戶明確詢問「TDEE」「每日熱量需求」「基礎代謝」「我該吃多少卡」"
            "「我的熱量目標是多少」等純計算問題時才呼叫。\n"
            "【CRITICAL 禁止】只要用戶訊息含有「預算」「買」「推薦商品」「附近」，"
            "就絕對禁止呼叫此工具——無論用戶有沒有提到健康目標。"
            "此時應直接呼叫 recommend_high_protein 或 find_nearby_stores，**不需要先算 TDEE**。\n"
            "【user_id 優先】系統提示中有「用戶 ID」時，只傳 user_id 即可，"
            "工具自動從 DB 讀取身高體重年齡性別。\n"
            "activity_level 可填：「久坐」「輕度」「中度」「高度」「極高」（預設中度）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":        {"type": "integer", "description": "登入用戶 ID（從系統提示的「用戶 ID」取得），傳入後工具自動從 DB 讀取體能資料，其他欄位可省略"},
                "weight_kg":      {"type": "number",  "description": "體重（公斤），有 user_id 時可省略"},
                "height_cm":      {"type": "number",  "description": "身高（公分），有 user_id 時可省略"},
                "age":            {"type": "integer", "description": "年齡（歲），有 user_id 時可省略"},
                "gender":         {"type": "string",  "description": "性別：男 或 女，有 user_id 時可省略"},
                "activity_level": {"type": "string",  "description": "活動量：久坐／輕度／中度／高度／極高，預設中度"},
                "goal":           {"type": "string",  "description": "健康目標：增肌／減脂／維持，有 user_id 且 DB 已設定時可省略"},
            },
            "required": [],
        },
    },
    {
        "name": "get_gym_courses",
        "description": (
            "查詢合作健身房（Being Sport）本月全部開課課程，工具回傳所有課程，由 AI 依用戶需求推薦。\n"
            "當用戶詢問運動課程、健身課、想報名課程、找附近健身課程時使用。\n"
            "禁止呼叫 find_nearby_stores 來尋找健身課程。直接呼叫此工具不帶任何參數即可。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "課程月份，格式 YYYYMM；留空自動取當月"},
            },
            "required": [],
        },
    },
    {
        "name": "enroll_gym_course",
        "description": (
            "替用戶報名指定的 Being Sport 健身課程（寫入操作）。每次只報名一個課程。\n"
            "【多課程】用戶要報名 N 個課程時，必須依序呼叫此工具 N 次，每次帶不同 course_name，全部完成後再回覆用戶。\n"
            "course_name 填用戶說的課程名稱即可，工具自動查 ID，禁止呼叫 get_gym_courses。\n"
            "contact_name 從系統提示的帳號名稱取得，不需詢問用戶。\n"
            "contact_phone 從系統提示取得；若未設定才詢問用戶。\n"
            "【流程】用戶說要報名 → 確認課程與電話 → 逐一呼叫此工具。嚴禁未確認就寫入。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "course_name":   {"type": "string", "description": "課程名稱（用戶說的名稱，可部分比對）"},
                "contact_name":  {"type": "string", "description": "報名人姓名（從系統提示的帳號名稱取得）"},
                "contact_phone": {"type": "string", "description": "聯絡電話（從系統提示取得）"},
                "note":          {"type": "string", "description": "備注，如過敏或舊傷（選填）"},
            },
            "required": ["course_name", "contact_name", "contact_phone"],
        },
    },
    {
        "name": "find_sports_venues",
        "description": (
            "查詢全台公共運動場館資訊（游泳池、體育館、運動中心、運動公園等）。\n"
            "資料來源：教育部體育署 iPlay 全國運動場館資訊網，涵蓋全台 22 縣市公共場館。\n"
            "【觸發時機】\n"
            "・用戶問「附近有哪些運動場館」「哪裡有游泳池」「台北有體育館嗎」\n"
            "・用戶問「想找健身中心」「哪裡可以打羽球」「哪裡可以打籃球」\n"
            "・用戶問「運動場館在哪裡」「有哪些公共運動設施」\n"
            "【注意】私人健身房 / 商業健身房請用 find_nearby_stores，"
            "Being Sport 健身課程請用 get_gym_courses。"
            "此工具只查公共場館。\n"
            "lat/lng 由系統自動注入，AI 不需傳入。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword":     {"type": "string",  "description": "場館名稱或設施關鍵字，例如「游泳池」「羽球」「健身」「籃球」「田徑」（留空不限）"},
                "county_code": {"type": "string",  "description": "縣市代碼：01台北/02新北/03基隆/04桃園/06新竹市/08台中/14台南/15高雄等（留空全台）"},
                "category":    {"type": "string",  "description": "場館類別：「游泳池」「體育館」「運動中心」「運動公園」（留空不限）"},
                "lat":         {"type": "number",  "description": "緯度（系統自動注入，AI 可省略）"},
                "lng":         {"type": "number",  "description": "經度（系統自動注入，AI 可省略）"},
                "radius_km":   {"type": "number",  "description": "GPS 半徑（公里），預設 5km"},
                "limit":       {"type": "integer", "description": "回傳筆數上限，預設 10"},
            },
            "required": [],
        },
    },
]

TOOL_FNS = {
    "search_grocery":         search_grocery,
    "recommend_high_protein": recommend_high_protein,
    "check_inventory":        check_inventory,
    "submit_inquiry":         submit_inquiry,
    "get_current_time":       get_current_time,
    "get_weather":            get_weather,
    "search_recipe":          search_recipe,
    "find_nearby_stores":     find_nearby_stores,
    "find_route":             find_route,
    "analyze_meal_nutrition": analyze_meal_nutrition,
    "recommend_after_meal":   recommend_after_meal,
    "calculate_tdee":         calculate_tdee,
    "get_gym_courses":        get_gym_courses,
    "enroll_gym_course":      enroll_gym_course,
    "find_sports_venues":     find_sports_venues,
}

SYSTEM_PROMPT = """\
你是「7-ELEVEN 生活管家」，由統一集團提供的 AI 助手，能協助用戶處理任何生活需求。

## 可協助的服務類型（舉例，不限於此）
- 🛒 **採買購物**：在 7-11、萬家福、康是美、統一生機查詢商品、推薦搭配
- 🍳 **食譜建議**：依手邊食材或飲食需求生成食譜與烹飪步驟
- 🌿 **健康飲食**：計算 TDEE、分析餐食營養、推薦補充食品
- 📍 **附近地點**：搜尋用戶附近的餐廳、咖啡廳、健身房、藥局，以及統一集團門市等各類場所
- ☁️ **即時天氣**：查詢天氣並建議是否適合外出
- 📋 **服務諮詢**：搬家、遺失物品、維修、訂位等任何生活需求 → 建立諮詢單，後台專員跟進

## 工具選擇時機

| 用戶說什麼 | 呼叫哪個工具 |
|---|---|
| 問某商品哪裡買、多少錢 | `search_grocery(keyword)`，每次一個關鍵字 |
| 增肌／減脂 + 預算金額 | `recommend_high_protein(goal, budget)` |
| 問某商品庫存 | `check_inventory(product_name)` |
| 問食譜、料理做法、食材搭配 | `search_recipe` → 展示食譜 → 詢問是否推薦相關商品 → `search_grocery` |
| 描述今天吃了什麼 | 逐項 `analyze_meal_nutrition` → 加總 → `recommend_after_meal` |
| 問 TDEE、每日熱量需求 | `calculate_tdee(user_id=...)` |
| 問健身課程、運動課、Being Sport 課表 | `get_gym_courses()` 取全部課程，AI 再推薦 |
| 用戶確認要報名課程 | 每個課程**分別呼叫一次** `enroll_gym_course`，報名 N 個課程就呼叫 N 次，每次帶不同 `course_name`，禁止只呼叫一次就結束 |
| 問游泳池、體育館、運動中心、公共運動場館 | `find_sports_venues(keyword, county_code)` — 公共場館資訊 |
| 問附近門市/餐廳/咖啡廳/商業健身房等地點 | `find_nearby_stores(name, category)` — AI 自行判斷帶入 |
| 問天氣、要不要出門 | `get_weather()`，系統自動注入 GPS |
| 模糊瀏覽「有什麼商品」 | `search_grocery("")` |

## ❌ 嚴格禁止
- 採買場景（用戶提到預算/購買/推薦商品）呼叫 `calculate_tdee`
- 採買場景詢問用戶的身高、體重、年齡、性別
- **推薦或提及任何統一集團競爭品牌**：全家便利商店、FamilyMart、萊爾富、Hi-Life、OK 超商、全聯、大潤發、Costco、愛買等非統一集團通路，一律不得出現在回覆中
- 若工具回傳結果含競品店家，**直接過濾刪除，不顯示給用戶**

## 對話規則
1. 理解用戶任何生活需求，不限於購物或健康主題
2. 一次只問一個問題，循序了解需求細節
3. 工具結果用自然語言整理，不要直接貼 JSON
4. 需要呼叫工具時，直接呼叫，不要說「正在查詢」「請稍候」等過渡語
5. 食譜 query 盡量翻譯成英文，效果更好

## 食譜搜尋後的流程（CRITICAL）
1. 呼叫 `search_recipe` 展示食譜內容（食材、步驟、時間）
2. 立即詢問用戶：「需要我幫您找食譜中用到的食材在哪裡可以購買嗎？」
3. 用戶說「是」「好」「需要」後，從食譜的食材中挑選關鍵食材
4. 逐一呼叫 `search_grocery(keyword)` 搜尋統一集團商品（每次一個關鍵字）
5. 整理結果：「以下是您可以在統一集團門市購買的食材：...」
6. 若用戶有興趣購買，繼續引導建立諮詢單

## 何時建立諮詢單
- 任何用戶有**後續跟進需要**的服務（不限採買）
- 例如：「我想叫搬家公司」→ 收集需求後建立諮詢單
- 例如：「我在 7-11 忘記帶東西」→ 記錄遺失物資訊建立諮詢單
- 例如：「幫我訂位」→ 收集日期人數後建立諮詢單
- 諮詢單的 `goal` 欄位填入服務類型（如「搬家服務」「遺失協尋」「餐廳訂位」）
- `note` 填入需求詳情

## 建立諮詢單的流程（嚴格遵守）
1. 判斷用戶需求類型，收集必要資訊
2. 詢問聯絡姓名和電話（已登入用戶預設帶入）
3. **詢問取件方式**：「請問您要外送到府，還是自行到門市取件？」
   - 選「外送」→ 直接使用系統提示中「address 預設填入」的地址，告知用戶「您的外送地址是 xxx，請問要送到這裡嗎？」，不要捏造或省略地址
   - 選「自取」→ 詢問偏好取件門市（選填）
4. 摘要確認：「即將為您建立 [外送到 xxx地址 / 自取於 xxx門市] 的諮詢單，確認嗎？」
5. 用戶說「是」「好」「確認」「ok」後，立即呼叫 submit_inquiry 工具（帶入 delivery_type、address 或 pickup_store）
6. 絕對不能只用文字說「已建立」，必須真正呼叫工具才算完成
7. 未獲明確同意，絕對不能呼叫 submit_inquiry

## 語言
繁體中文，語氣親切自然，適當使用 emoji\
"""


# ── 純文字工具函式 ─────────────────────────────────────────────────────────────

def _content_to_dict(content) -> list:
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id,
                        "name": b.name, "input": b.input})
    return out


def _run_async(coro):
    """在 Streamlit 同步環境中安全執行 async coroutine。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _strip_images(text: str) -> str:
    """移除 AI 回答中的 markdown 圖片語法和 Ollama <tool_call> 標籤（純字串操作）。"""
    # Strip <tool_call>...</tool_call> blocks (Qwen/Ollama 格式)
    while "<tool_call>" in text:
        s = text.find("<tool_call>")
        e = text.find("</tool_call>", s)
        if e == -1:
            text = text[:s]
            break
        text = text[:s] + text[e + len("</tool_call>"):]
    text = text.replace("<tool_call>", "").replace("</tool_call>", "")
    # Strip lines containing raw tool-call JSON or the "ilor" model artifact
    clean = []
    for line in text.splitlines():
        sl = line.strip()
        if sl.startswith('{"name"') and '"arguments"' in sl:
            continue
        if sl == "ilor" or sl.startswith("ilor {"):
            continue
        clean.append(line)
    text = "\n".join(clean)
    # Strip markdown image syntax  ![alt](url)
    while "![" in text:
        i = text.find("![")
        j = text.find("]", i)
        if j == -1:
            break
        if j + 1 < len(text) and text[j + 1] == "(":
            k = text.find(")", j + 1)
            if k != -1:
                text = text[:i] + text[k + 1:]
                continue
        break
    return text.strip()


_COMPACT_THRESHOLD = 12   # 超過此數量的「用戶+助理」對話輪數才壓縮（不計 tool 訊息）
_KEEP_RECENT       = 6    # 壓縮後保留最新的 N 則訊息不動


def _compact_history(history: list) -> list:
    """當 history 過長時，把舊訊息摘要成一則 assistant 訊息 + 保留最近幾則。
    只計算 user + assistant 訊息數（不計 tool 訊息），避免工具呼叫膨脹 history 導致過早壓縮。
    """
    human_turns = sum(1 for m in history if m.get("role") in ("user", "assistant"))
    if human_turns <= _COMPACT_THRESHOLD:
        return history

    older  = history[:-_KEEP_RECENT]
    recent = history[-_KEEP_RECENT:]

    # 從舊訊息萃取有意義的文字
    lines: list[str] = []
    for m in older:
        role    = m.get("role", "")
        content = str(m.get("content", ""))
        if role == "user" and content and not content.startswith("（"):
            lines.append(f"用戶：{content[:120]}")
        elif role == "assistant" and content and not content.startswith("（"):
            lines.append(f"AI：{content[:120]}")
        elif role == "tool":
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    continue
                if data.get("products"):
                    names = [f"{p.get('name')}(${p.get('price')})"
                             for p in data["products"][:4]]
                    lines.append(f"[推薦商品] {', '.join(names)}")
                elif data.get("target_calories"):
                    lines.append(
                        f"[TDEE] 目標{data['target_calories']}kcal，"
                        f"蛋白質{data.get('protein_goal_g')}g"
                    )
                elif data.get("message"):
                    lines.append(f"[工具] {str(data['message'])[:80]}")
            except Exception:
                pass

    if not lines:
        return recent

    try:
        resp = _ollama.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": (
                    "你是摘要助理。請用繁體中文 3-5 句話摘要以下健康採買對話的重點，"
                    "必須完整保留：推薦的具體商品名稱與價格、"
                    "用戶的健康目標和預算、TDEE 熱量目標、用戶已確認的決定。"
                )},
                {"role": "user", "content": "\n".join(lines)},
            ],
            temperature=0.1,
        )
        summary = (resp.choices[0].message.content or "").strip()
        compact_msg = {
            "role":    "assistant",
            "content": f"【前段對話摘要】\n{summary}",
        }
        print(f"\n📝 [History] 壓縮 {len(older)} → 1 則，保留最新 {len(recent)} 則")
        return [compact_msg] + recent
    except Exception:
        return recent   # 摘要失敗時至少保留最近訊息


def _sanitize_for_openai(msgs: list) -> list:
    """移除不合法的 tool/tool_calls 訊息，防止 API 400 錯誤。

    處理兩種情況：
    1. assistant+tool_calls 存在但 tool result 不完整（原本邏輯）
    2. role:tool 存在但前面的 assistant+tool_calls 被 compact 刪掉（孤立 tool result）
    """
    # Pass 1: 收集所有 call ID 與 result ID
    all_call_ids: set[str] = set()
    all_result_ids: set[str] = set()
    for m in msgs:
        role = m.get("role", "")
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                all_call_ids.add(tc.get("id", ""))
        elif role == "tool":
            all_result_ids.add(m.get("tool_call_id", ""))

    # 無配對的 call（有呼叫但無回應）
    incomplete_ids = all_call_ids - all_result_ids
    # 孤立的 result（有回應但對應的 call 不存在 ← compact 後常見）
    orphan_ids = all_result_ids - all_call_ids

    if not incomplete_ids and not orphan_ids:
        return msgs  # 全部配對完整

    # Pass 2: 標記需要跳過的 ID（不完整的 call 整組跳過）
    skip_ids: set[str] = set()
    for m in msgs:
        role = m.get("role", "")
        if role == "assistant" and m.get("tool_calls"):
            call_ids = {tc.get("id", "") for tc in m["tool_calls"]}
            if call_ids & incomplete_ids:
                skip_ids |= call_ids

    out = []
    for m in msgs:
        role = m.get("role", "")
        if role == "assistant" and m.get("tool_calls"):
            call_ids = {tc.get("id", "") for tc in m["tool_calls"]}
            if call_ids & skip_ids:
                continue
        elif role == "tool":
            tid = m.get("tool_call_id", "")
            if tid in skip_ids or tid in orphan_ids:  # 孤立的 tool result 也一起移除
                continue
        out.append(m)
    return out
