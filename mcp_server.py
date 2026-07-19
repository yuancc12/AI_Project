# -*- coding: utf-8 -*-
"""
mcp_server.py — 7-ELEVEN 生活管家 MCP Server

把統一集團各類服務包裝成 MCP 工具，讓 Claude / 任何 MCP Agent 調用。

啟動（stdio transport）：  python mcp_server.py
本機測試工具邏輯：         python mcp_server.py --selftest
"""
import sqlite3
import os
import sys
import json
import uuid
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from mcp.server import MCPServer

# 手動讀 .env，注入環境變數
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DB = os.path.join(os.path.dirname(__file__), "butler.db")
mcp = MCPServer("life-butler")


def _ensure_schema():
    """建立官方表格（pms_form_feedback / mms_order_record），並將舊 inquiry 表資料遷移。"""
    con = _db()

    # Create pms_form_feedback if not exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS pms_form_feedback (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_no   TEXT UNIQUE NOT NULL,
            form_id       INTEGER NOT NULL DEFAULT 1,
            service_id    INTEGER NOT NULL DEFAULT 1,
            goal          TEXT NOT NULL DEFAULT '',
            budget        INTEGER NOT NULL DEFAULT 0,
            keyword       TEXT NOT NULL DEFAULT '',
            county_code   TEXT NOT NULL DEFAULT '',
            district_code TEXT NOT NULL DEFAULT '',
            contact_name  TEXT NOT NULL DEFAULT '',
            contact_phone TEXT NOT NULL DEFAULT '',
            note          TEXT NOT NULL DEFAULT '',
            user_id       INTEGER NOT NULL DEFAULT 0,
            products_json TEXT NOT NULL DEFAULT '',
            user_reply    TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT '待處理',
            vendor_reply  TEXT NOT NULL DEFAULT '',
            accepted_at   TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        )
    """)

    # Create mms_order_record if not exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS mms_order_record (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no          TEXT UNIQUE NOT NULL,
            feedback_no       TEXT NOT NULL,
            order_type        TEXT NOT NULL DEFAULT '05',
            vendor_name       TEXT NOT NULL DEFAULT '',
            estimated_minutes INTEGER NOT NULL DEFAULT 60,
            reply_message     TEXT NOT NULL DEFAULT '',
            status            TEXT NOT NULL DEFAULT '01',
            driver_name       TEXT NOT NULL DEFAULT '',
            created_at        TEXT NOT NULL
        )
    """)

    # Add address column to users if missing
    try:
        cols_u = {r[1] for r in con.execute("PRAGMA table_info(users)")}
        if 'address' not in cols_u:
            con.execute("ALTER TABLE users ADD COLUMN address TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    # Add address to cms_homepage_service_vendor if missing
    try:
        cols_sv = {r[1] for r in con.execute("PRAGMA table_info(cms_homepage_service_vendor)")}
        if 'address' not in cols_sv:
            con.execute("ALTER TABLE cms_homepage_service_vendor ADD COLUMN address TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE cms_homepage_service_vendor SET address='台北市大安區忠孝東路四段181號' WHERE name LIKE '%7%'")
            con.execute("UPDATE cms_homepage_service_vendor SET address='台北市信義區松高路1號B1' WHERE name='萬家福'")
            con.execute("UPDATE cms_homepage_service_vendor SET address='台北市中山區南京東路二段168號' WHERE name='康是美'")
            con.execute("UPDATE cms_homepage_service_vendor SET address='台北市松山區八德路三段32號' WHERE name='統一生機'")
    except Exception:
        pass
    # Add address / delivery_type columns to pms_form_feedback if missing
    try:
        cols_f = {r[1] for r in con.execute("PRAGMA table_info(pms_form_feedback)")}
        if 'address' not in cols_f:
            con.execute("ALTER TABLE pms_form_feedback ADD COLUMN address TEXT NOT NULL DEFAULT ''")
        if 'delivery_type' not in cols_f:
            con.execute("ALTER TABLE pms_form_feedback ADD COLUMN delivery_type TEXT NOT NULL DEFAULT '外送'")
        if 'pickup_store' not in cols_f:
            con.execute("ALTER TABLE pms_form_feedback ADD COLUMN pickup_store TEXT NOT NULL DEFAULT ''")
        if 'images_json' not in cols_f:
            con.execute("ALTER TABLE pms_form_feedback ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'")
        if 'feedback_content' not in cols_f:
            con.execute("ALTER TABLE pms_form_feedback ADD COLUMN feedback_content TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    # Add / migrate mms_order_record columns to match real schema
    try:
        cols_m = {r[1] for r in con.execute("PRAGMA table_info(mms_order_record)")}
        for _col, _defn in [
            ("driver_name",       "TEXT NOT NULL DEFAULT ''"),
            ("delivery_company",  "TEXT NOT NULL DEFAULT ''"),
            ("tracking_no",       "TEXT NOT NULL DEFAULT ''"),
            ("order_status",      "TEXT NOT NULL DEFAULT '12'"),
            ("platform_code",     "TEXT NOT NULL DEFAULT '01'"),
            ("service_vendor_id", "INTEGER NOT NULL DEFAULT 0"),
            ("service_id",        "INTEGER NOT NULL DEFAULT 0"),
            ("inbr_account_id",   "TEXT NOT NULL DEFAULT ''"),
            ("deposit_amount",    "REAL NOT NULL DEFAULT 0"),
            ("final_amount",      "REAL NOT NULL DEFAULT 0"),
            ("order_items",       "TEXT NOT NULL DEFAULT ''"),
        ]:
            if _col not in cols_m:
                con.execute(f"ALTER TABLE mms_order_record ADD COLUMN {_col} {_defn}")
    except Exception:
        pass

    # 合作廠商表
    con.execute("""
        CREATE TABLE IF NOT EXISTS partner_vendor (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            category    TEXT NOT NULL,
            phone       TEXT NOT NULL DEFAULT '',
            address     TEXT NOT NULL DEFAULT '',
            county_code TEXT NOT NULL DEFAULT '',
            rating      REAL NOT NULL DEFAULT 5.0,
            description TEXT NOT NULL DEFAULT '',
            is_enable   INTEGER NOT NULL DEFAULT 1
        )
    """)

    # 健身房每月課程表
    con.execute("""
        CREATE TABLE IF NOT EXISTS gym_course (
            id           INTEGER PRIMARY KEY,
            gym_id       INTEGER NOT NULL,
            course_name  TEXT NOT NULL,
            coach        TEXT NOT NULL DEFAULT '',
            course_type  TEXT NOT NULL DEFAULT '',
            weekday      TEXT NOT NULL DEFAULT '',
            time_start   TEXT NOT NULL DEFAULT '',
            duration_min INTEGER NOT NULL DEFAULT 60,
            max_slots    INTEGER NOT NULL DEFAULT 20,
            enrolled     INTEGER NOT NULL DEFAULT 0,
            price_month  INTEGER NOT NULL DEFAULT 0,
            month        TEXT NOT NULL DEFAULT '',
            min_students INTEGER NOT NULL DEFAULT 8,
            status       TEXT NOT NULL DEFAULT '招生中',
            is_enable    INTEGER NOT NULL DEFAULT 1
        )
    """)
    # 課程報名記錄表
    con.execute("""
        CREATE TABLE IF NOT EXISTS course_enrollment (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id     INTEGER NOT NULL,
            feedback_no   TEXT NOT NULL DEFAULT '',
            contact_name  TEXT NOT NULL DEFAULT '',
            contact_phone TEXT NOT NULL DEFAULT '',
            note          TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT '報名中',
            notified      INTEGER NOT NULL DEFAULT 0,
            enrolled_at   TEXT NOT NULL
        )
    """)
    # gym_course 補欄位（舊資料庫升級）
    try:
        gc_cols = {r[1] for r in con.execute("PRAGMA table_info(gym_course)")}
        if 'min_students' not in gc_cols:
            con.execute("ALTER TABLE gym_course ADD COLUMN min_students INTEGER NOT NULL DEFAULT 8")
        if 'status' not in gc_cols:
            con.execute("ALTER TABLE gym_course ADD COLUMN status TEXT NOT NULL DEFAULT '招生中'")
    except Exception:
        pass

    # Migrate old inquiry table if it exists
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'inquiry' in tables:
        try:
            old_rows = con.execute("SELECT * FROM inquiry").fetchall()
            old_cols = [d[0] for d in con.execute("PRAGMA table_info(inquiry)").fetchall()]
            for row in old_rows:
                row_dict = dict(zip(old_cols, row))
                old_no = row_dict.get('inquiry_no', '')
                if not old_no:
                    continue
                # Convert IQ prefix to FB prefix for the feedback_no
                new_no = 'FB' + old_no[2:] if old_no.startswith('IQ') else old_no
                try:
                    con.execute("""
                        INSERT OR IGNORE INTO pms_form_feedback
                        (feedback_no, goal, budget, keyword, contact_name, contact_phone,
                         note, user_id, products_json, user_reply, status, vendor_reply,
                         accepted_at, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (new_no,
                          row_dict.get('goal',''), row_dict.get('budget',0),
                          row_dict.get('keyword',''), row_dict.get('contact_name',''),
                          row_dict.get('contact_phone',''), row_dict.get('note',''),
                          row_dict.get('user_id',0), row_dict.get('products_json',''),
                          row_dict.get('user_reply',''), row_dict.get('status','待處理'),
                          row_dict.get('vendor_reply',''), row_dict.get('accepted_at',''),
                          row_dict.get('created_at', datetime.now().isoformat())))
                    # Migrate delivery_no to mms_order_record
                    delivery_no = row_dict.get('delivery_no','')
                    if delivery_no:
                        new_order_no = 'DL' + delivery_no[2:] if delivery_no.startswith('DL') else delivery_no
                        con.execute("""
                            INSERT OR IGNORE INTO mms_order_record
                            (order_no, feedback_no, vendor_name, accepted_at, created_at)
                            VALUES (?,?,?,?,?)
                        """, (new_order_no, new_no,
                              row_dict.get('vendor_reply','').split(']')[0].lstrip('[') if row_dict.get('vendor_reply','').startswith('[') else '',
                              row_dict.get('accepted_at',''), row_dict.get('created_at', datetime.now().isoformat())))
                except Exception:
                    pass
            con.execute("DROP TABLE IF EXISTS inquiry")
        except Exception:
            pass

    con.commit()
    con.close()


def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


# 模組匯入時自動執行 schema migration（不影響現有資料）
try:
    _ensure_schema()
except Exception:
    pass  # inquiry 表可能還不存在（seed 前），忽略


# ---------------------------------------------------------------------------
# 工具 1：依關鍵字搜尋健康商品
# ---------------------------------------------------------------------------
@mcp.tool()
def search_grocery(keyword: str) -> str:
    """在統一集團各業務（7-11、萬家福、康是美、統一生機）的健康商品庫中，
    依關鍵字搜尋符合的商品，回傳商品清單（含所屬業務、蛋白質、熱量、價格、庫存）。
    當使用者想查詢某種食材、品項或商品是否有售、在哪裡買得到時，呼叫此工具。
    例如：「有沒有雞胸肉」「乳清蛋白哪裡賣」「我想找高蛋白零食」。

    參數:
        keyword: 搜尋關鍵字，例如「雞胸」「乳清」「豆漿」「燕麥」

    回傳:
        JSON 字串，含符合的商品清單。
    """
    con = _db()
    rows = con.execute(
        "SELECT * FROM fitness_product "
        "WHERE name LIKE ? OR category LIKE ? OR vendor LIKE ? "
        "ORDER BY protein_g DESC",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
    ).fetchall()
    con.close()
    products = [dict(r) for r in rows]
    return json.dumps(
        {"count": len(products), "products": products,
         "message": f"找到 {len(products)} 筆商品。" if products
                    else f"找不到含「{keyword}」的商品。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 2：提供預算內的高蛋白商品清單，交由 AI 決策組合
# ---------------------------------------------------------------------------
@mcp.tool()
def recommend_high_protein(budget: int, goal: str = "") -> str:
    if not goal:
        return json.dumps({
            "needs_clarification": True,
            "message": "請問您的健康目標是「增肌」還是「減脂」？",
        }, ensure_ascii=False)

    con = _db()
    rows = con.execute(
        "SELECT * FROM fitness_product WHERE stock > 0 AND price <= ?",
        (budget,)
    ).fetchall()
    con.close()

    candidates = [dict(r) for r in rows]

    # 依目標排序：減脂優先蛋白質/熱量比，增肌優先蛋白質絕對量
    if goal == "減脂":
        candidates.sort(key=lambda p: -(p["protein_g"] / max(p["calories"], 1) * 100))
    else:
        candidates.sort(key=lambda p: -p["protein_g"])

    # 貪婪選法：在總預算內選最多蛋白質的組合
    selected = []
    remaining = budget
    for p in candidates:
        if p["price"] <= remaining:
            selected.append(p)
            remaining -= p["price"]

    total_protein = round(sum(p["protein_g"] for p in selected), 1)
    total_price   = sum(p["price"] for p in selected)

    return json.dumps(
        {
            "count":          len(selected),
            "message":        f"在預算 ${budget} 內，為您挑選 {len(selected)} 項商品，合計 ${total_price}，蛋白質 {total_protein}g。",
            "products":       selected,
            "user_goal":      goal,
            "user_budget":    budget,
            "total_protein_g": total_protein,
            "total_price":    total_price,
        },
        ensure_ascii=False,
    )

# ---------------------------------------------------------------------------
# 工具 3：查詢特定商品在各業務的庫存狀況
# ---------------------------------------------------------------------------
@mcp.tool()
def check_inventory(product_name: str) -> str:
    """查詢某個商品在統一集團各業務（7-11、萬家福、康是美、統一生機）的庫存狀況，
    回傳哪家有貨、庫存數量為何。
    當使用者想確認商品是否有庫存、或想比較哪個通路還有貨時，呼叫此工具。
    例如：「雞胸肉還有庫存嗎」「康是美的乳清剩多少」。

    參數:
        product_name: 商品名稱或關鍵字，例如「雞胸肉」「乳清蛋白」「豆漿」

    回傳:
        JSON 字串，含各通路的庫存明細。
    """
    con = _db()
    rows = con.execute(
        "SELECT name, vendor, stock, price, protein_g, calories FROM fitness_product "
        "WHERE name LIKE ? ORDER BY stock DESC",
        (f"%{product_name}%",),
    ).fetchall()
    con.close()

    items = [dict(r) for r in rows]
    in_stock = [i for i in items if i["stock"] > 0]

    return json.dumps(
        {"query": product_name, "found": len(items), "in_stock": len(in_stock),
         "items": items,
         "message": f"找到 {len(items)} 筆，其中 {len(in_stock)} 筆有庫存。"
                    if items else f"查無「{product_name}」相關商品。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 4：建立健康採買諮詢單（寫入操作，必須使用者確認後才能呼叫）
# ---------------------------------------------------------------------------
@mcp.tool()
def submit_inquiry(goal: str, contact_name: str, contact_phone: str,
                   budget: int = 0, keyword: str = "", note: str = "",
                   address: str = "", products_json: str = "", user_id: int = 0,
                   delivery_type: str = "外送", pickup_store: str = "",
                   images_json: str = "") -> str:
    """將使用者的需求寫入後台諮詢單，讓後台人員跟進與協助。

    【重要】這是寫入操作。呼叫前必須已告知用戶「將為您建立諮詢單」並獲得明確確認。

    參數:
        goal:          目標/需求，例如「增肌採買」「搬家諮詢」「餐廳訂位」
        contact_name:  聯絡人姓名
        contact_phone: 聯絡電話
        budget:        預算（選填）
        keyword:       搜尋關鍵字（選填）
        note:          備註與需求詳情（選填）
        address:       外送地址（delivery_type="外送" 時必填）
        products_json: 指定商品 JSON 字串（選填）
        delivery_type: "外送"（預設）或 "自取"
        pickup_store:  自取門市名稱（delivery_type="自取" 時填入，選填）

    回傳:
        JSON 字串，含諮詢單編號 feedback_no。
    """
    if not contact_name or not contact_name.strip():
        return json.dumps({"success": False,
                           "message": "尚未收集到聯絡姓名，請先詢問用戶的姓名再呼叫此工具。"},
                          ensure_ascii=False)
    if not contact_phone or not contact_phone.strip():
        return json.dumps({"success": False,
                           "message": "尚未收集到聯絡電話，請先詢問用戶的電話再呼叫此工具。"},
                          ensure_ascii=False)

    feedback_no = "FB" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:6].upper()

    # 建立 feedback_content（官方格式）
    _img_paths = []
    try:
        _img_paths = json.loads(images_json) if images_json else []
    except Exception:
        pass
    _answer_stub = {"answerId": None, "quantity": None, "countyCode": None,
                    "countyName": None, "districtCode": None, "districtName": None,
                    "isQuotedSeparately": None}
    _fc_data = [
        {"type": "1", "topicId": 1, "answerList": [{**_answer_stub, "answer": goal}]},
    ]
    if note:
        _fc_data.append({"type": "2", "topicId": 2, "answerList": [{**_answer_stub, "answer": note}]})
    for _i, _ip in enumerate(_img_paths):
        _fc_data.append({"type": "6", "topicId": 54 + _i,
                         "answerList": [{**_answer_stub, "answer": _ip, "topicId": 54 + _i}]})
    feedback_content = json.dumps(
        {"data": _fc_data, "formId": 1, "calculations": {"totalAmount": budget}},
        ensure_ascii=False,
    )

    con = _db()
    con.execute(
        "INSERT INTO pms_form_feedback "
        "(feedback_no,goal,budget,keyword,contact_name,contact_phone,note,address,"
        " products_json,user_id,delivery_type,pickup_store,images_json,feedback_content,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (feedback_no, goal, budget, keyword,
         contact_name, contact_phone, note, address, products_json, user_id,
         delivery_type, pickup_store, json.dumps(_img_paths, ensure_ascii=False),
         feedback_content, datetime.now().isoformat()),
    )
    con.commit()
    con.close()
    dtype_label = "自取" if delivery_type == "自取" else "外送"
    pickup_msg  = f"（自取門市：{pickup_store}）" if pickup_store else ""
    delivery_msg = f"（外送地址：{address}）" if address and delivery_type == "外送" else ""
    return json.dumps(
        {"success": True, "feedback_no": feedback_no, "inquiry_no": feedback_no,
         "delivery_type": delivery_type,
         "message": f"諮詢單 {feedback_no} 已建立（{dtype_label}{pickup_msg}{delivery_msg}）！後台人員將主動與您聯繫。"},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Email 輔助（供 dispatch_delivery 及 send_email_notification 共用）
# ---------------------------------------------------------------------------

def _send_email(to_email: str, subject: str, body: str) -> bool:
    """用環境變數設定的 SMTP 發信，成功回傳 True，失敗靜默回傳 False。
    需在 .env 設定：SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS
    """
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    if not (host and user and pwd):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = user
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(host, port, timeout=10) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(user, pwd)
            srv.sendmail(user, [to_email], msg.as_string())
        return True
    except Exception:
        return False


@mcp.tool()
def send_email_notification(to_email: str, subject: str, body: str) -> str:
    """發送 Email 通知給指定收件人。
    適用場景：接單通知、訂單狀態更新、系統公告等。
    需在 .env 設定 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS。

    參數:
        to_email: 收件人 Email 地址，例如「user@example.com」
        subject:  郵件主旨
        body:     郵件內文（純文字）

    回傳:
        JSON：{"success": true/false, "message": "..."}
    """
    ok = _send_email(to_email, subject, body)
    if ok:
        return json.dumps({"success": True,  "message": f"Email 已發送至 {to_email}"},
                          ensure_ascii=False)
    smtp_set = bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER"))
    reason = "SMTP 未設定，請在 .env 加入 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS" \
             if not smtp_set else "SMTP 連線或發送失敗，請確認帳密與伺服器設定"
    return json.dumps({"success": False, "message": reason}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 5：後台接單並派送外送服務（寫入操作，由後台人員確認後呼叫）
# ---------------------------------------------------------------------------
@mcp.tool()
def dispatch_delivery(inquiry_no: str, vendor_name: str,
                      estimated_minutes: int = 60, reply_message: str = "",
                      delivery_company: str = "", tracking_no: str = "") -> str:
    """後台人員確認接受採買諮詢單後，建立外送配送訂單並更新諮詢單狀態。

    【重要】這是寫入操作，必須由後台人員在後台介面確認接單後才能呼叫。
    呼叫後將：
    1. 產生外送單號（DL...）
    2. 將諮詢單狀態改為「配送中」
    3. 記錄接單廠商、配送業者、回覆訊息與接單時間

    參數:
        inquiry_no:        諮詢單編號，例如「FB260708XXXXXX」
        vendor_name:       接單廠商或門市，例如「萬家福信義店」
        estimated_minutes: 預計送達分鐘數，預設 60
        reply_message:     廠商給用戶的回覆訊息（選填）
        delivery_company:  配送業者，例如「黑貓宅配」「新竹物流」「自家配送」（選填）
        tracking_no:       物流追蹤單號（選填）

    回傳:
        JSON 字串，含外送單號 delivery_no。
    """
    order_no = datetime.now().strftime("%y%m%d") + f"{uuid.uuid4().int % 100000000:08d}"
    now_iso  = datetime.now().isoformat()

    # 組合回覆訊息：加入配送業者與追蹤單號
    full_reply = reply_message or ""
    if delivery_company and delivery_company != "自家配送":
        full_reply += f"\n📦 配送業者：{delivery_company}"
        if tracking_no:
            full_reply += f"\n🔍 追蹤單號：{tracking_no}"
    full_reply = full_reply.strip()

    stored_reply = f"[{vendor_name}] {full_reply}".strip()

    con = _db()

    # 查詢諮詢單資料（商品、預算、user_id）
    fb_row = con.execute(
        "SELECT products_json, budget, user_id FROM pms_form_feedback WHERE feedback_no=?",
        (inquiry_no,)
    ).fetchone()
    products = []
    budget_val = 0
    user_id_val = 0
    if fb_row:
        budget_val  = int(fb_row["budget"] or 0)
        user_id_val = int(fb_row["user_id"] or 0)
        if fb_row["products_json"]:
            try:
                products = json.loads(fb_row["products_json"])
            except Exception:
                pass

    # 扣除庫存（每項 -1，最低到 0）
    for p in products:
        pid = p.get("id")
        if pid:
            con.execute(
                "UPDATE fitness_product SET stock = MAX(0, stock - 1) WHERE id = ?",
                (pid,),
            )

    # 查詢 service_vendor_id / service_id（依廠商名稱模糊比對）
    sv_row = con.execute(
        "SELECT id FROM cms_homepage_service_vendor WHERE name LIKE ? AND is_enable=1 LIMIT 1",
        (f"%{vendor_name.split('門市')[0].split('店')[0]}%",),
    ).fetchone()
    service_vendor_id = sv_row["id"] if sv_row else 0

    svc_row = con.execute(
        "SELECT id FROM cms_homepage_service WHERE vendor_id=? AND is_enable=1 LIMIT 1",
        (service_vendor_id,),
    ).fetchone() if service_vendor_id else None
    service_id = svc_row["id"] if svc_row else 0

    # 組 order_items JSON（對照真實格式）
    order_items_obj = {
        "orderItems": [
            {
                "itemName":   p.get("name", ""),
                "quantity":   1,
                "unitPrice":  int(p.get("price", 0)),
                "itemAmount": int(p.get("price", 0)),
                "unit":       None,
                "attribute":  [],
            }
            for p in products
        ],
        "totalAmount": sum(int(p.get("price", 0)) for p in products),
    }
    order_items_str = json.dumps(order_items_obj, ensure_ascii=False)
    final_amount = float(budget_val) if budget_val else float(order_items_obj["totalAmount"])

    con.execute(
        "INSERT INTO mms_order_record "
        "(order_no, feedback_no, order_type, order_status, platform_code, "
        " service_vendor_id, service_id, inbr_account_id, "
        " vendor_name, estimated_minutes, reply_message, "
        " delivery_company, tracking_no, status, "
        " deposit_amount, final_amount, order_items, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order_no, inquiry_no, '01', '12', '01',
         service_vendor_id, service_id, str(user_id_val),
         vendor_name, estimated_minutes, full_reply,
         delivery_company, tracking_no, '01',
         final_amount, final_amount, order_items_str, now_iso),
    )
    con.execute(
        "UPDATE pms_form_feedback "
        "SET status='配送中', accepted_at=?, vendor_reply=? "
        "WHERE feedback_no=?",
        (now_iso, stored_reply, inquiry_no),
    )
    con.commit()

    # 自動發 Email 通知用戶
    if user_id_val:
        _urow = con.execute(
            "SELECT email, username FROM users WHERE id=?", (user_id_val,)
        ).fetchone()
        if _urow and _urow["email"]:
            _carrier = f"\n配送業者：{delivery_company}" if delivery_company else ""
            _track   = f"\n追蹤單號：{tracking_no}"      if tracking_no    else ""
            _eta = (f"{estimated_minutes // 1440} 天" if estimated_minutes >= 1440
                    else f"{estimated_minutes} 分鐘")
            _send_email(
                to_email=_urow["email"],
                subject=f"【統一生活管家】諮詢單 {inquiry_no} 已接單",
                body=(
                    f"您好 {_urow['username']}，\n\n"
                    f"您的諮詢單 {inquiry_no} 已由「{vendor_name}」接單。\n"
                    f"預計送達：{_eta}{_carrier}{_track}\n"
                    + (f"\n廠商回覆：{full_reply}\n" if full_reply else "")
                    + "\n感謝您使用統一生活管家！"
                ),
            )
    con.close()

    carrier_msg = f"（{delivery_company}）" if delivery_company and delivery_company != "自家配送" else ""
    return json.dumps(
        {
            "success":           True,
            "delivery_no":       order_no,
            "inquiry_no":        inquiry_no,
            "vendor_name":       vendor_name,
            "delivery_company":  delivery_company,
            "tracking_no":       tracking_no,
            "estimated_minutes": estimated_minutes,
            "message": (
                f"🚚 外送單 {order_no} 已建立！"
                f"{vendor_name}{carrier_msg} 預計 {estimated_minutes} 分鐘內送達。"
            ),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 工具 6：計算最佳配送路線（OSRM）
# ---------------------------------------------------------------------------
@mcp.tool()
def find_route(stops_json: str, dest_lat: float = 0, dest_lng: float = 0, dest_address: str = "") -> str:
    """計算從多個取貨門市到用戶地址的最佳配送路線。
    使用 OSRM（OpenStreetMap Routing Machine）計算實際道路距離與最佳配送順序，
    取貨門市若無座標則自動用 Nominatim 地理編碼。

    參數:
        stops_json:    取貨停靠點 JSON 陣列，每項含 name（必填）和 lat/lng 或 address
        dest_lat:      配送目的地緯度（用戶 GPS 或地址解析後的座標）
        dest_lng:      配送目的地經度
        dest_address:  配送目的地文字地址（若 dest_lat/dest_lng 為 0 則自動地理編碼）

    回傳:
        JSON 含 route（排序後的停靠點清單）、total_distance_km、estimated_minutes
    """
    import math

    NOM_HDR = {"User-Agent": "FitnessGroceryBot/1.0 (Hackathon)"}

    def _geocode(address: str):
        import re as _re
        # Build candidate list: full address first, then county+district fallback
        candidates = [address]
        m = _re.match(r'^(.{2,5}[市縣].{2,4}[區鄉鎮市])', address)
        if m and m.group(1) != address:
            candidates.append(m.group(1))
        # Also try just county if district fallback still fails
        m2 = _re.match(r'^(.{2,5}[市縣])', address)
        if m2 and m2.group(1) not in candidates:
            candidates.append(m2.group(1))

        for cand in candidates:
            try:
                r = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": cand, "format": "json", "limit": 1, "countrycodes": "tw"},
                    headers=NOM_HDR, timeout=6,
                )
                results = r.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
            except Exception:
                pass
        return None, None

    def _dist(lat1, lng1, lat2, lng2):
        """Haversine 公式（公尺），比直角近似更準確。"""
        R = 6_371_000
        p = math.pi / 180
        a = (math.sin((lat2 - lat1) * p / 2) ** 2
             + math.cos(lat1 * p) * math.cos(lat2 * p)
             * math.sin((lng2 - lng1) * p / 2) ** 2)
        return 2 * R * math.asin(math.sqrt(a))

    # Parse stops
    try:
        stops = json.loads(stops_json) if isinstance(stops_json, str) else stops_json
    except Exception:
        return json.dumps({"success": False, "message": "stops_json 格式錯誤，需為 JSON 陣列"}, ensure_ascii=False)

    if not stops:
        return json.dumps({"success": False, "message": "無取貨停靠點"}, ensure_ascii=False)

    # Geocode destination
    if (not dest_lat or not dest_lng) and dest_address:
        dest_lat, dest_lng = _geocode(dest_address)
    if not dest_lat or not dest_lng:
        return json.dumps({"success": False, "message": "無法取得目的地座標，請提供 GPS 座標或正確地址"}, ensure_ascii=False)

    # Ensure all stops have lat/lng (geocode those that don't)
    valid_stops = []
    for s in stops:
        lat = s.get("lat") or 0
        lng = s.get("lng") or 0
        if not lat or not lng:
            addr = s.get("address") or s.get("name", "")
            lat, lng = _geocode(addr)
        if lat and lng:
            valid_stops.append({**s, "lat": lat, "lng": lng})

    if not valid_stops:
        return json.dumps({"success": False, "message": "取貨點座標無法取得，請確認地址資訊"}, ensure_ascii=False)

    # Try OSRM Trip API（主要 + 備用端點）
    _OSRM_HOSTS = [
        "https://router.project-osrm.org",
        "https://routing.openstreetmap.de",
    ]
    coords = ";".join(f"{s['lng']},{s['lat']}" for s in valid_stops)
    coords += f";{dest_lng},{dest_lat}"

    for _host in _OSRM_HOSTS:
        try:
            osrm_resp = requests.get(
                f"{_host}/trip/v1/driving/{coords}",
                params={"roundtrip": "false", "source": "first", "destination": "last",
                        "steps": "false", "overview": "full", "geometries": "geojson"},
                timeout=8,
            )
            if osrm_resp.status_code != 200:
                continue
            osrm = osrm_resp.json()
            if osrm.get("code") != "Ok":
                continue
            waypoints = osrm.get("waypoints", [])
            wp_sorted = sorted(waypoints, key=lambda w: w.get("waypoint_index", 0))
            route_stops = []
            for i, wp in enumerate(wp_sorted[:-1]):
                src_idx = min(wp.get("waypoint_index", i), len(valid_stops) - 1)
                route_stops.append({
                    "order": len(route_stops) + 1,
                    "name":    valid_stops[src_idx].get("name", ""),
                    "address": valid_stops[src_idx].get("address", ""),
                    "lat":     valid_stops[src_idx]["lat"],
                    "lng":     valid_stops[src_idx]["lng"],
                })
            route_stops.append({
                "order": len(route_stops) + 1,
                "name": "配送目的地",
                "address": dest_address,
                "lat": dest_lat, "lng": dest_lng,
            })
            trip = osrm.get("trips", [{}])[0]
            total_km  = round(trip.get("distance", 0) / 1000, 2)
            total_min = round(trip.get("duration", 0) / 60)
            # GeoJSON geometry: coordinates 是 [[lng,lat], ...] 格式
            geometry = trip.get("geometry", {}).get("coordinates", [])
            return json.dumps({
                "success": True, "source": "OSRM",
                "total_distance_km": total_km,
                "estimated_minutes": total_min,
                "route": route_stops,
                "geometry": geometry,
                "message": f"最佳路線：{len(valid_stops)} 個取貨點 → 目的地，共 {total_km} km，預計 {total_min} 分鐘",
            }, ensure_ascii=False)
        except Exception:
            continue

    # Fallback: greedy nearest-neighbour
    remaining = list(valid_stops)
    ordered = []
    cur_lat, cur_lng = remaining[0]["lat"], remaining[0]["lng"]
    while remaining:
        nearest = min(remaining, key=lambda s: _dist(cur_lat, cur_lng, s["lat"], s["lng"]))
        remaining.remove(nearest)
        ordered.append(nearest)
        cur_lat, cur_lng = nearest["lat"], nearest["lng"]

    total_d = sum(
        _dist(ordered[i]["lat"], ordered[i]["lng"],
              ordered[i+1]["lat"] if i+1 < len(ordered) else dest_lat,
              ordered[i+1]["lng"] if i+1 < len(ordered) else dest_lng)
        for i in range(len(ordered))
    ) + _dist(ordered[-1]["lat"] if ordered else dest_lat,
              ordered[-1]["lng"] if ordered else dest_lng,
              dest_lat, dest_lng)
    total_km_fb  = round(total_d / 1000, 2)
    total_min_fb = round(total_km_fb / 20 * 60)  # 台灣市區平均約 20 km/h

    route_fb = [
        {"order": i+1, "name": s.get("name",""), "address": s.get("address",""),
         "lat": s["lat"], "lng": s["lng"]}
        for i, s in enumerate(ordered)
    ] + [{"order": len(ordered)+1, "name": "配送目的地", "address": dest_address,
          "lat": dest_lat, "lng": dest_lng}]

    return json.dumps({
        "success": True,
        "source": "nearest-neighbour",
        "total_distance_km": total_km_fb,
        "estimated_minutes": total_min_fb,
        "route": route_fb,
        "message": f"（最近鄰演算法）{len(valid_stops)} 個取貨點 → 目的地，約 {total_km_fb} km，預計 {total_min_fb} 分鐘"
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 7：取得台灣當前時間
# ---------------------------------------------------------------------------
@mcp.tool()
def get_current_time() -> str:
    """取得台灣當前時間、日期與星期幾。
    當用戶詢問現在幾點、或需要根據時段給出門市營業提示時使用。
    例如：「現在幾點」「今天星期幾」「現在還有開嗎」。
    """
    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    period = (
        "清晨" if now.hour < 6 else
        "早晨" if now.hour < 12 else
        "下午" if now.hour < 18 else
        "晚上" if now.hour < 22 else "深夜"
    )
    return json.dumps({
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": f"星期{weekdays[now.weekday()]}",
        "is_weekend": now.weekday() >= 5,
        "period": period,
        "hour": now.hour,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 8：查詢即時天氣（Open-Meteo，免費無需 API 金鑰）
# ---------------------------------------------------------------------------
@mcp.tool()
def get_weather(lat: float = 0, lng: float = 0, city: str = "") -> str:
    """查詢指定地點的即時天氣狀況，包含氣溫、體感溫度、天氣描述、濕度與風速。
    並依天氣給出是否適合外出採買或戶外運動的建議。
    使用 Open-Meteo 免費 API，無需 API 金鑰。

    參數:
        lat:  緯度（系統 GPS 自動注入，AI 可省略）
        lng:  經度（系統 GPS 自動注入，AI 可省略）
        city: 城市或地址名稱；lat/lng 為 0 時自動用 Nominatim 地理編碼

    回傳:
        JSON 含 temperature, feels_like, description, humidity, wind_speed_kmh, suggestion
    """
    NOM_HDR = {"User-Agent": "FitnessGroceryBot/1.0 (Hackathon)"}

    if (not lat or not lng) and city:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1, "countrycodes": "tw"},
                headers=NOM_HDR, timeout=6,
            )
            results = r.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
        except Exception:
            pass

    if not lat or not lng:
        return json.dumps(
            {"success": False, "message": "無法取得地點座標，請提供 GPS 座標或城市名稱。"},
            ensure_ascii=False,
        )

    WMO_DESC = {
        0: "晴天", 1: "大致晴天", 2: "局部多雲", 3: "陰天",
        45: "霧", 48: "霧淞",
        51: "輕微毛毛雨", 53: "中等毛毛雨", 55: "濃密毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        80: "陣雨", 81: "中等陣雨", 82: "強陣雨",
        95: "雷雨", 96: "冰雹雷雨", 99: "強冰雹雷雨",
    }

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lng,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "Asia/Taipei",
            },
            timeout=8,
        )
        if resp.status_code != 200:
            return json.dumps(
                {"success": False, "message": f"天氣 API 回應異常（{resp.status_code}）"},
                ensure_ascii=False,
            )

        cur = resp.json().get("current", {})
        temp     = cur.get("temperature_2m", 0)
        feels    = cur.get("apparent_temperature", 0)
        humidity = cur.get("relative_humidity_2m", 0)
        wind     = cur.get("wind_speed_10m", 0)
        code     = cur.get("weather_code", 0)
        desc     = WMO_DESC.get(code, f"天氣代碼 {code}")

        is_rainy = code in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}
        if is_rainy:
            suggestion = "目前有雨，建議選擇線上訂購配送，或等雨停後再出門採買。"
        elif temp >= 33:
            suggestion = f"氣溫 {temp}°C 偏高，注意防曬補水，冷藏食品買完請盡快回家存放。"
        elif temp <= 10:
            suggestion = f"氣溫 {temp}°C 偏低，注意保暖，可考慮補充熱量較高的食品維持體能。"
        else:
            suggestion = "天氣舒適，適合外出採買或戶外運動訓練。"

        return json.dumps({
            "success":        True,
            "temperature":    temp,
            "feels_like":     feels,
            "humidity":       humidity,
            "wind_speed_kmh": wind,
            "weather_code":   code,
            "description":    desc,
            "suggestion":     suggestion,
            "message": (
                f"目前天氣：{desc}，氣溫 {temp}°C（體感 {feels}°C），"
                f"濕度 {humidity}%，風速 {wind} km/h。"
            ),
        }, ensure_ascii=False)

    except requests.exceptions.Timeout:
        return json.dumps({"success": False, "message": "天氣 API 連線逾時，請稍後再試。"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "message": f"查詢天氣失敗：{str(e)}"}, ensure_ascii=False)


@mcp.tool()
def find_nearby_stores(
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_m: int = 1500,
    name: str = "",
    category: str = "",
) -> str:
    """搜尋用戶附近的地點。由 AI 根據用戶意圖決定 name / category 的值後呼叫。

    參數:
        lat, lng:   用戶 GPS 座標（系統自動注入）
        radius_m:   搜尋半徑（公尺），預設 1500
        name:       店家名稱或品牌，直接用於 OSM name / brand / operator 欄位精確比對。
                    例：7-ELEVEN、統一超商、萬家福、康是美、Cosmed、麥當勞、星巴克
        category:   OSM 地點類型，填入標準 OSM tag value。
                    amenity 類：restaurant, cafe, pharmacy, clinic, hospital, fast_food, bar
                    shop 類：convenience, supermarket, bakery, health_food
                    leisure 類：fitness_centre, sports_centre
                    留空表示不限類型（name 不為空時才有意義）

    使用原則（AI 須遵守）:
        - 用戶問「7-11 / 7-Eleven / 便利商店 / 超商」→ name="7-ELEVEN", category="convenience"
        - 用戶問「萬家福 / 超市」→ name="萬家福", category="supermarket"
        - 用戶問「康是美 / 藥妝」→ name="康是美", category=""
        - 用戶問「餐廳 / 吃飯」→ name="", category="restaurant"
        - 用戶問「咖啡廳 / 咖啡」→ name="", category="cafe"
        - 用戶問「健身房 / gym」→ name="", category="fitness_centre"
        - 用戶問「藥局 / 藥房」→ name="", category="pharmacy"
        - 用戶問「麵包店」→ name="", category="bakery"
        - 用戶問特定品牌 → name 填品牌名，category 填對應類型
    """
    import requests, json, math

    if not lat or not lng:
        return json.dumps({"message": "尚未取得 GPS 位置，請在側欄開啟位置偵測後再試。"}, ensure_ascii=False)

    if not name and not category:
        return json.dumps({"message": "請提供 name 或 category 參數。"}, ensure_ascii=False)

    _OVERPASS_MIRRORS = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    headers = {"User-Agent": "LifeButlerBot/1.0 (Hackathon)"}

    _api_ok   = False   # 至少有一個 mirror 成功回應
    _api_err  = ""

    def _post_overpass(ql: str) -> list:
        nonlocal _api_ok, _api_err
        for _url in _OVERPASS_MIRRORS:
            try:
                r = requests.post(_url, data={"data": ql}, headers=headers, timeout=20)
                if r.status_code == 200:
                    _api_ok = True
                    return r.json().get("elements", [])
                else:
                    _api_err = f"HTTP {r.status_code} from {_url}"
            except Exception as e:
                _api_err = str(e)
        return []

    def _dist(s):
        dlat = (s["lat"] - lat) * 111000
        dlng = (s["lng"] - lng) * 111000 * math.cos(math.radians(lat))
        return math.sqrt(dlat**2 + dlng**2)

    def _parse(elements: list) -> list:
        results = []
        for el in elements:
            tags = el.get("tags", {})
            el_name = tags.get("name") or tags.get("name:zh") or tags.get("brand") or ""
            if not el_name:
                continue
            if el["type"] == "node":
                s_lat, s_lng = el.get("lat"), el.get("lon")
            else:
                c = el.get("center", {})
                s_lat, s_lng = c.get("lat"), c.get("lon")
            if not s_lat or not s_lng:
                continue
            addr = (
                tags.get("addr:full")
                or "".join(filter(None, [
                    tags.get("addr:city"), tags.get("addr:district"),
                    tags.get("addr:street"), tags.get("addr:housenumber"),
                ]))
                or ""
            )
            results.append({
                "name":     el_name,
                "address":  addr,
                "lat":      s_lat,
                "lng":      s_lng,
                "phone":    tags.get("phone") or tags.get("contact:phone") or "",
                "category": tags.get("amenity") or tags.get("shop") or tags.get("leisure") or category,
            })
        return results

    area = f"(around:{radius_m},{lat},{lng})"
    lines = []

    # 按 name / brand / operator 精確比對店名
    if name:
        for field in ("name", "brand", "operator"):
            lines.append(f'nwr["{field}"="{name}"]{area};')

    # 按 OSM category 類型搜尋（name 有值時略過，避免撈到競品）
    if category and not name:
        for tk in ("amenity", "shop", "leisure"):
            lines.append(f'nwr["{tk}"="{category}"]{area};')

    ql = f'[out:json][timeout:25];({" ".join(lines)});out center tags;'
    seen, raw = set(), []
    for el in _post_overpass(ql):
        eid = (el.get("type"), el.get("id"))
        if eid not in seen:
            seen.add(eid)
            raw.append(el)

    stores = _parse(raw)
    search_label = " ".join(filter(None, [name, category]))

    if not stores:
        if not _api_ok:
            msg = f"地圖查詢服務暫時無法連線（{_api_err or '所有 Overpass 鏡像逾時'}），請稍後再試。"
        else:
            msg = f"半徑 {radius_m}m 內找不到「{search_label}」（GPS: {lat:.4f},{lng:.4f}，OSM 返回 {len(raw)} 筆原始資料），可試著擴大搜尋半徑。"
        return json.dumps({"message": msg}, ensure_ascii=False)

    unique = {(s["name"], round(s["lat"], 4), round(s["lng"], 4)): s for s in stores}
    final  = sorted(unique.values(), key=_dist)[:12]

    # 補距離、補地址（Nominatim 反向地理編碼）
    nom_url  = "https://nominatim.openstreetmap.org/reverse"
    nom_hdrs = {"User-Agent": "LifeButlerBot/1.0 (Hackathon)"}
    for s in final:
        s["distance_m"] = round(_dist(s))
        if not s["address"]:
            try:
                r = requests.get(nom_url, params={
                    "lat": s["lat"], "lon": s["lng"],
                    "format": "jsonv2", "zoom": 18, "addressdetails": 1,
                }, headers=nom_hdrs, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    a = d.get("address", {})
                    s["address"] = "".join(filter(None, [
                        a.get("city") or a.get("town"),
                        a.get("suburb") or a.get("neighbourhood"),
                        a.get("road"),
                        a.get("house_number"),
                    ]))
            except Exception:
                pass

    return json.dumps({"count": len(final), "stores": final, "search_label": search_label}, ensure_ascii=False)
    
def _try_edamam(food_name: str, amount_g: float):
    """若設有 EDAMAM_APP_ID / EDAMAM_APP_KEY 環境變數，呼叫 Edamam Nutrition API 查詢單一食物。"""
    app_id  = os.environ.get("EDAMAM_APP_ID", "")
    app_key = os.environ.get("EDAMAM_APP_KEY", "")
    if not app_id or not app_key:
        return None
    try:
        ingr   = f"{amount_g:.0f}g {food_name}"
        url    = "https://api.edamam.com/api/nutrition-data"
        params = {
            "app_id": app_id, "app_key": app_key,
            "nutrition-type": "logging", "ingr": ingr,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        n    = data.get("totalNutrients", {})
        cal  = round(data.get("calories", 0), 1)
        pro  = round(n.get("PROCNT", {}).get("quantity", 0), 1)
        fat  = round(n.get("FAT",    {}).get("quantity", 0), 1)
        cho  = round(n.get("CHOCDF", {}).get("quantity", 0), 1)
        return {
            "success":   True,
            "food":      food_name,
            "amount_g":  amount_g,
            "calories":  cal,
            "protein_g": pro,
            "fat_g":     fat,
            "carbs_g":   cho,
            "source":    "Edamam",
            "message":   f"(Edamam) {food_name} {amount_g:.0f}g → {cal} kcal，蛋白質 {pro}g",
        }
    except Exception:
        return None


def _query_openfoodfacts(food_name: str, amount_g: float):
    """Open Food Facts 公開 API（免費，無需金鑰）查詢食物每 100g 營養，換算指定克數後回傳。"""
    headers = {"User-Agent": "FitnessGroceryBot/1.0 (Student Project)"}
    query = food_name.strip().replace(" ", "+")
    url = (
        "https://world.openfoodfacts.net/cgi/search.pl"
        f"?search_terms={query}&search_simple=1&action=process&json=1&page_size=1"
    )
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        products = resp.json().get("products", [])
        if not products:
            return None
        p  = products[0]
        nm = p.get("nutriments", {})
        kcal100 = float(nm.get("energy-kcal_100g") or nm.get("energy-kcal") or 0)
        pro100  = float(nm.get("proteins_100g")     or nm.get("proteins")    or 0)
        fat100  = float(nm.get("fat_100g")           or nm.get("fat")         or 0)
        cho100  = float(nm.get("carbohydrates_100g") or nm.get("carbohydrates") or 0)
        ratio   = amount_g / 100.0
        cal = round(kcal100 * ratio, 1)
        pro = round(pro100  * ratio, 1)
        fat = round(fat100  * ratio, 1)
        cho = round(cho100  * ratio, 1)
        name = p.get("product_name_zh") or p.get("product_name", food_name)
        return {
            "success":   True,
            "food":      name,
            "amount_g":  amount_g,
            "calories":  cal,
            "protein_g": pro,
            "fat_g":     fat,
            "carbs_g":   cho,
            "source":    "Open Food Facts",
            "message":   f"{name} {amount_g:.0f}g → {cal} kcal，蛋白質 {pro}g",
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 工具 X：食譜搜尋（Spoonacular → Edamam Recipe API 雙後備）
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def search_recipe(query: str, ingredients: str = "", diet: str = "",
                  cuisine: str = "", max_results: int = 3) -> str:
    """依食材或料理名稱搜尋食譜，回傳食材清單、烹飪步驟、所需時間與來源連結。
    適合用戶詢問「用雞胸肉可以做什麼」「推薦低卡晚餐食譜」「素食義大利麵怎麼做」時呼叫。

    優先使用 Spoonacular API（需設定 SPOONACULAR_API_KEY 環境變數）；
    若無，自動改用 Edamam Recipe API（需設定 EDAMAM_RECIPE_APP_ID 與 EDAMAM_RECIPE_APP_KEY）。
    兩者均未設定時回傳提示訊息。

    參數:
        query:       料理關鍵字，例如「chicken breast」「pasta」「蛋炒飯」
        ingredients: 手邊食材（逗號分隔），例如「雞胸肉,花椰菜,橄欖油」
        diet:        飲食限制，Spoonacular: vegetarian/vegan/gluten+free/ketogenic/paleo；
                     Edamam: balanced/high-protein/low-fat/low-carb
        cuisine:     料理類型，例如 chinese/japanese/italian/thai/mexican
        max_results: 回傳食譜數量（1-5，預設 3）
    """
    max_results = max(1, min(max_results, 5))
    headers = {"User-Agent": "LifeButlerBot/1.0 (Hackathon)"}

    # ── 嘗試 Spoonacular ────────────────────────────────────────────────────
    spoon_key = os.environ.get("SPOONACULAR_API_KEY", "") or "8118232606424cc2b050b2244d124054"
    spoon_tried = False  # 記錄是否成功連線 Spoonacular（但可能 0 結果）
    if spoon_key:
        def _spoon_search(q: str) -> list:
            params = {
                "apiKey": spoon_key,
                "query":  q,
                "number": max_results,
                "addRecipeInformation": True,
                "fillIngredients":      True,
            }
            if diet:
                params["diet"] = diet
            if cuisine:
                params["cuisine"] = cuisine
            resp = requests.get(
                "https://api.spoonacular.com/recipes/complexSearch",
                params=params, headers=headers, timeout=10,
            )
            if resp.status_code != 200:
                return []
            hits = resp.json().get("results", [])
            results = []
            for r in hits:
                rid = r.get("id")
                steps = [
                    f"{s['number']}. {s['step']}"
                    for sec in (r.get("analyzedInstructions") or [])
                    for s in sec.get("steps", [])
                ]
                # 若 complexSearch 沒回傳步驟，另外抓一次
                if not steps and rid:
                    try:
                        instr_resp = requests.get(
                            f"https://api.spoonacular.com/recipes/{rid}/analyzedInstructions",
                            params={"apiKey": spoon_key}, headers=headers, timeout=8,
                        )
                        if instr_resp.status_code == 200:
                            steps = [
                                f"{s['number']}. {s['step']}"
                                for sec in instr_resp.json()
                                for s in sec.get("steps", [])
                            ]
                    except Exception:
                        pass
                ingr_list = [i["original"] for i in (r.get("extendedIngredients") or [])]
                results.append({
                    "title":            r.get("title", ""),
                    "ready_in_minutes": r.get("readyInMinutes", 0),
                    "servings":         r.get("servings", 0),
                    "source_url":       r.get("sourceUrl", ""),
                    "ingredients":      ingr_list,
                    "steps":            steps,
                    "source":           "Spoonacular",
                })
            return results

        try:
            spoon_tried = True
            # 食材並入 query，避免過濾太嚴
            combined_query = f"{query} {ingredients}".strip() if ingredients else query
            recipes = _spoon_search(combined_query)
            # 逐步縮短 query 重試：取前兩詞 → 取第一詞
            if not recipes:
                words = combined_query.split()
                for n in (2, 1):
                    short_q = " ".join(words[:n])
                    if short_q and short_q != combined_query:
                        recipes = _spoon_search(short_q)
                        if recipes:
                            break
            if recipes:
                return json.dumps({
                    "count": len(recipes), "recipes": recipes,
                    "message": f"找到 {len(recipes)} 道食譜（來源：Spoonacular）",
                }, ensure_ascii=False)
        except Exception:
            spoon_tried = False

    # ── 嘗試 Edamam Recipe API v2 ──────────────────────────────────────────
    edamam_id  = os.environ.get("EDAMAM_RECIPE_APP_ID", "")
    edamam_key = os.environ.get("EDAMAM_RECIPE_APP_KEY", "")
    if edamam_id and edamam_key:
        try:
            params = {
                "type":    "public",
                "q":       f"{query} {ingredients}".strip(),
                "app_id":  edamam_id,
                "app_key": edamam_key,
            }
            if diet:
                params["diet"] = diet
            if cuisine:
                params["cuisineType"] = cuisine

            resp = requests.get(
                "https://api.edamam.com/api/recipes/v2",
                params=params, headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])[:max_results]
                recipes = []
                for h in hits:
                    r = h.get("recipe", {})
                    n = r.get("totalNutrients", {})
                    recipes.append({
                        "title":            r.get("label", ""),
                        "ready_in_minutes": int(r.get("totalTime", 0)),
                        "servings":         int(r.get("yield", 0)),
                        "source_url":       r.get("url", ""),
                        "ingredients":      r.get("ingredientLines", []),
                        "calories_per_serving": round(
                            r.get("calories", 0) / max(r.get("yield", 1), 1), 0
                        ),
                        "protein_g_per_serving": round(
                            n.get("PROCNT", {}).get("quantity", 0) / max(r.get("yield", 1), 1), 1
                        ),
                        "diet_labels":   r.get("dietLabels", []),
                        "health_labels": r.get("healthLabels", [])[:6],
                        "source":        "Edamam",
                    })
                if recipes:
                    return json.dumps({
                        "count": len(recipes), "recipes": recipes,
                        "message": f"找到 {len(recipes)} 道食譜（來源：Edamam）",
                    }, ensure_ascii=False)
        except Exception:
            pass

    if spoon_tried:
        return json.dumps({
            "count": 0, "recipes": [],
            "message": f"找不到「{query}」的相關食譜，建議用英文關鍵字，例如「pasta」「chicken rice」「stir fry」。",
        }, ensure_ascii=False)

    return json.dumps({
        "count": 0, "recipes": [],
        "message": "尚未設定 SPOONACULAR_API_KEY，請確認 .streamlit/secrets.toml 已正確設定。",
    }, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# 工具 A：查詢單一食物（每次一項）的卡路里與三大營養素
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def analyze_meal_nutrition(food_name: str, amount_g: float) -> str:
    """查詢指定食物的營養成分，依攝取克數計算熱量與三大營養素。

    【重要】每次只查詢一種食物，由 AI 負責從用戶的自然語言中判斷每項食物與克數。
    例如用戶說「我吃了雞胸肉150g和白飯400g和雞蛋2顆(120g)」，
    AI 應分別呼叫三次，最後將三次的 calories 與 protein_g 加總後傳給 recommend_after_meal。

    資料來源優先順序：
    1. Edamam Nutrition API（設定 EDAMAM_APP_ID / EDAMAM_APP_KEY 環境變數時啟用）
    2. Open Food Facts API（免費，無需金鑰，自動作為後備）

    參數:
        food_name: 單一食物名稱，例如「雞胸肉」「白飯」「雞蛋」「香蕉」「蘋果」
        amount_g:  攝取量（公克），例如 150、400、120
    """
    edamam = _try_edamam(food_name, amount_g)
    if edamam:
        return json.dumps(edamam, ensure_ascii=False)

    off = _query_openfoodfacts(food_name, amount_g)
    if off:
        return json.dumps(off, ensure_ascii=False)

    return json.dumps({
        "success": False,
        "food":    food_name,
        "message": (
            f"找不到「{food_name}」的營養資料。"
            "請嘗試更具體的食物名稱（如「香蕉」「蘋果」「雞胸肉」「白飯」），"
            "或設定 EDAMAM_APP_ID / EDAMAM_APP_KEY 環境變數以啟用更精確的查詢。"
        ),
    }, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# 工具 B：根據已攝取營養，推薦補充採買的健康商品
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def recommend_after_meal(calories_eaten: float, protein_eaten: float,
                          fitness_goal: str = "增肌", budget: int = 500) -> str:
    """根據用戶今日已攝取的熱量與蛋白質，從商品庫推薦應補充購買的健康食品。
    通常緊接在 analyze_meal_nutrition 之後呼叫，提供個人化採買建議。

    參數:
        calories_eaten: 今天已攝取的熱量（kcal），從 analyze_meal_nutrition 的 total_calories 帶入
        protein_eaten:  今天已攝取的蛋白質（g），從 analyze_meal_nutrition 的 total_protein_g 帶入
        fitness_goal:   健康目標，「增肌」或「減脂」（預設：增肌）
        budget:         本次採買預算（元），預設 500

    回傳:
        JSON 含 recommended_products, calories_gap, protein_gap, message
    """
    daily = (
        {"calories": 1800, "protein": 140}
        if fitness_goal == "減脂"
        else {"calories": 2500, "protein": 175}
    )
    cal_gap = max(0.0, daily["calories"] - calories_eaten)
    pro_gap = max(0.0, daily["protein"]  - protein_eaten)

    con = _db()
    rows = con.execute(
        "SELECT * FROM fitness_product WHERE stock > 0 AND price <= ? "
        "ORDER BY protein_g DESC LIMIT 20",
        (budget,),
    ).fetchall()
    con.close()

    products = [dict(r) for r in rows]
    if fitness_goal == "減脂":
        products.sort(key=lambda p: -(p["protein_g"] / max(p["calories"], 1) * 100))
    else:
        products.sort(key=lambda p: -p["protein_g"])

    recommended = products[:5]

    return json.dumps({
        "fitness_goal":         fitness_goal,
        "calories_eaten":       calories_eaten,
        "protein_eaten":        protein_eaten,
        "daily_target":         daily,
        "calories_gap":         round(cal_gap, 1),
        "protein_gap":          round(pro_gap, 1),
        "budget":               budget,
        "recommended_products": recommended,
        "message": (
            f"今日已攝取 {calories_eaten} kcal、蛋白質 {protein_eaten}g。"
            f"依「{fitness_goal}」目標，還需補充約 {round(cal_gap)} kcal 與 {round(pro_gap)}g 蛋白質。"
            f"以下推薦 {len(recommended)} 項商品供您選購。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 C：個人化 TDEE 計算（Harris-Benedict / Mifflin-St Jeor）
# ---------------------------------------------------------------------------
@mcp.tool()
def calculate_tdee(weight_kg: float = 0, height_cm: float = 0, age: int = 0,
                   gender: str = "",
                   activity_level: str = "中度",
                   goal: str = "",
                   user_id: Optional[int] = None) -> str:
    """根據身體數據計算基礎代謝率（BMR）與每日總能量消耗（TDEE），
    並依健康目標給出個人化的熱量與三大營養素建議。

    【優先使用 user_id】若用戶已登入，只需傳入 user_id，工具會自動從資料庫讀取
    該用戶的身高、體重、年齡、性別、健康目標，不需 AI 手動帶入這些數值。
    AI 仍可傳入 activity_level（活動量）與 goal（若想覆蓋已儲存的目標）。

    參數:
        user_id:        登入用戶的 ID（優先使用，自動讀取 DB 體能資料）
        weight_kg:      體重（公斤），user_id 已提供時可省略
        height_cm:      身高（公分），user_id 已提供時可省略
        age:            年齡（歲），user_id 已提供時可省略
        gender:         性別，「男」或「女」，user_id 已提供時可省略
        activity_level: 活動量：「久坐」「輕度」「中度」「高度」「極高」，預設「中度」
        goal:           健康目標：「增肌」「減脂」「維持」，user_id 有設定時可省略

    回傳:
        JSON 字串，含 bmr, tdee, target_calories, protein_goal_g, carbs_goal_g, fat_goal_g。
    """
    # 若有 user_id，從 DB 讀取體能資料補缺值
    if user_id:
        try:
            con = _db()
            row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            con.close()
            if row:
                row = dict(row)
                if not weight_kg:    weight_kg = float(row.get("weight_kg") or 0)
                if not height_cm:    height_cm = float(row.get("height_cm") or 0)
                if not age:          age       = int(row.get("age") or 0)
                if not gender:       gender    = row.get("gender") or ""
                if not goal:         goal      = row.get("fitness_goal") or ""
        except Exception:
            pass

    # 補預設值
    if not gender: gender = "男"
    if not goal:   goal   = "增肌"

    if not weight_kg or not height_cm or not age:
        return json.dumps({
            "success": False,
            "message": (
                "缺少必要資料（體重、身高或年齡）。"
                "請在個人資料中填寫，或直接告訴我您的身高體重年齡。"
            ),
        }, ensure_ascii=False)

    # Mifflin-St Jeor BMR
    if gender == "女":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5

    activity_map = {
        "久坐": 1.2,
        "輕度": 1.375,
        "中度": 1.55,
        "高度": 1.725,
        "極高": 1.9,
    }
    multiplier = activity_map.get(activity_level, 1.55)
    tdee = round(bmr * multiplier, 0)

    goal_map = {"減脂": 0.85, "增肌": 1.10, "維持": 1.0}
    target_calories = round(tdee * goal_map.get(goal, 1.10), 0)

    # 蛋白質目標：減脂 2.2g/kg，增肌 2.0g/kg，維持 1.6g/kg
    protein_ratio = {"減脂": 2.2, "增肌": 2.0, "維持": 1.6}.get(goal, 2.0)
    protein_g = round(weight_kg * protein_ratio, 0)

    # 脂肪佔目標熱量 25%，其餘為碳水
    fat_g   = round(target_calories * 0.25 / 9, 0)
    carbs_g = round((target_calories - protein_g * 4 - fat_g * 9) / 4, 0)
    carbs_g = max(carbs_g, 0)

    activity_desc = {
        "久坐": "幾乎不運動",
        "輕度": "每週輕度運動 1-3 天",
        "中度": "每週中度運動 3-5 天",
        "高度": "每週高強度運動 6-7 天",
        "極高": "體力勞動或競技訓練",
    }.get(activity_level, activity_level)

    return json.dumps({
        "gender":          gender,
        "weight_kg":       weight_kg,
        "height_cm":       height_cm,
        "age":             age,
        "activity_level":  activity_level,
        "activity_desc":   activity_desc,
        "goal":            goal,
        "bmr":             round(bmr, 0),
        "tdee":            tdee,
        "target_calories": target_calories,
        "protein_goal_g":  protein_g,
        "fat_goal_g":      fat_g,
        "carbs_goal_g":    carbs_g,
        "message": (
            f"{'男' if gender == '男' else '女'}性 {age} 歲、{weight_kg}kg／{height_cm}cm，"
            f"活動量「{activity_level}」：\n"
            f"BMR {round(bmr)} kcal，TDEE {tdee} kcal。\n"
            f"依「{goal}」目標，建議每日攝取 {target_calories} kcal，"
            f"蛋白質 {protein_g}g、碳水 {carbs_g}g、脂肪 {fat_g}g。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 D：查詢健身房每月課程
# ---------------------------------------------------------------------------
@mcp.tool()
def get_gym_courses(month: str = "") -> str:
    """查詢合作健身房（Being Sport）本月全部開課課程，回傳所有課程供 AI 推薦。
    當使用者詢問運動課程、健身課、想報名課程、找健身課程時呼叫此工具。
    工具回傳所有課程，AI 再依用戶需求從結果中篩選推薦，不在工具層過濾。

    參數:
        month: 課程月份，格式 YYYYMM；留空自動取當月

    回傳:
        JSON 字串，含本月全部課程清單。
    """
    if not month:
        month = datetime.now().strftime("%Y%m")

    con = _db()
    query = """
        SELECT gc.*, pv.name AS gym_name, pv.address AS gym_address,
               pv.phone AS gym_phone, pv.rating AS gym_rating,
               pv.county_code AS gym_county,
               (gc.max_slots - gc.enrolled) AS available_slots
        FROM gym_course gc
        JOIN partner_vendor pv ON pv.id = gc.gym_id AND pv.is_enable = 1
        WHERE gc.is_enable = 1 AND gc.month = ?
    """
    params: list = [month]

    query += " ORDER BY pv.rating DESC, gc.time_start ASC"

    rows = con.execute(query, params).fetchall()
    con.close()

    courses = []
    for r in rows:
        d = dict(r)
        courses.append({
            "course_id":       d["id"],
            "gym_name":        d["gym_name"],
            "gym_address":     d["gym_address"],
            "gym_phone":       d["gym_phone"],
            "gym_rating":      d["gym_rating"],
            "course_name":     d["course_name"],
            "coach":           d["coach"],
            "course_type":     d["course_type"],
            "weekday":         d["weekday"],
            "time_start":      d["time_start"],
            "duration_min":    d["duration_min"],
            "max_slots":       d["max_slots"],
            "enrolled":        d["enrolled"],
            "available_slots": d["available_slots"],
            "price_month":     d["price_month"],
            "month":           d["month"],
        })

    return json.dumps({
        "month":   month,
        "count":   len(courses),
        "courses": courses,
        "message": (
            f"{month[:4]}年{month[4:]}月共找到 {len(courses)} 堂課程。"
            if courses else
            f"{month[:4]}年{month[4:]}月暫無課程資料。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 E：查詢合作廠商（餐廳、搬家、清潔等）
# ---------------------------------------------------------------------------
@mcp.tool()
def get_partner_vendors(category: str = "", county_code: str = "",
                        keyword: str = "") -> str:
    """查詢統一集團合作的生活服務廠商，包含健身房、餐廳、搬家公司、清潔公司等。
    當使用者詢問合作廠商、推薦餐廳、需要搬家或清潔服務、問附近有哪些合作廠商時呼叫。
    例如：「有合作的餐廳嗎」「幫我推薦清潔公司」「搬家服務怎麼找」「有合作健身房嗎」。

    參數:
        category:    廠商類別，例如「健身房」「餐廳」「搬家」「清潔」；留空回傳全部類別
        county_code: 縣市代碼（01台北/02新北/03桃園/04台中/05高雄）；留空回傳全部縣市
        keyword:     廠商名稱或地址關鍵字（選填）

    回傳:
        JSON 字串，含符合條件的合作廠商清單（依評分排序）。
    """
    con = _db()
    query = "SELECT * FROM partner_vendor WHERE is_enable = 1"
    params: list = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if county_code:
        query += " AND county_code = ?"
        params.append(county_code)
    if keyword:
        query += " AND (name LIKE ? OR address LIKE ? OR description LIKE ?)"
        params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]

    query += " ORDER BY rating DESC"

    rows = con.execute(query, params).fetchall()
    con.close()

    vendors = [dict(r) for r in rows]
    cat_label = f"【{category}】" if category else ""
    return json.dumps({
        "count":   len(vendors),
        "vendors": vendors,
        "message": (
            f"找到 {len(vendors)} 家{cat_label}合作廠商。"
            if vendors else
            f"目前無符合條件的{cat_label}合作廠商。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 F：報名 Being Sport 健身課程（寫入操作，用戶確認後才能呼叫）
# ---------------------------------------------------------------------------
@mcp.tool()
def enroll_gym_course(course_name: str, contact_name: str, contact_phone: str,
                      note: str = "", user_id: int = 0) -> str:
    """替使用者報名指定的 Being Sport 健身課程，建立報名記錄並同步建立諮詢單。

    【重要】這是寫入操作。呼叫前必須已告知用戶「將為您報名此課程」並獲得明確確認。

    參數:
        course_name:   課程名稱（用戶說的課程名稱，工具自動查詢對應 ID）
        contact_name:  報名人姓名（從系統提示的帳號名稱取得，不需詢問用戶）
        contact_phone: 聯絡電話（從系統提示的聯絡電話取得；若未設定才詢問用戶）
        note:          備注（過敏、舊傷、特殊需求，選填）

    回傳:
        JSON 字串，含報名編號 enrollment_id 與諮詢單編號 feedback_no。
    """
    if not course_name or not course_name.strip():
        return json.dumps({"success": False,
                           "message": "課程名稱不能為空，請填入用戶想報名的課程名稱。"},
                          ensure_ascii=False)
    if not contact_phone or not contact_phone.strip():
        return json.dumps({"success": False,
                           "message": "尚未收集到電話，請先詢問用戶的聯絡電話再呼叫此工具。"},
                          ensure_ascii=False)

    con = _db()
    # 依課程名稱模糊查詢（本月優先）
    month_now = datetime.now().strftime("%Y%m")
    row = con.execute("""
        SELECT gc.*, pv.name AS gym_name
        FROM gym_course gc
        JOIN partner_vendor pv ON pv.id = gc.gym_id
        WHERE gc.is_enable = 1 AND gc.course_name LIKE ?
        ORDER BY (gc.month = ?) DESC, gc.id ASC
        LIMIT 1
    """, (f"%{course_name}%", month_now)).fetchone()

    if not row:
        con.close()
        return json.dumps({"success": False,
                           "message": f"找不到名稱含「{course_name}」的課程，請確認課程名稱。"},
                          ensure_ascii=False)

    course = dict(row)
    if course["enrolled"] >= course["max_slots"]:
        con.close()
        return json.dumps({"success": False,
                           "message": f"「{course['course_name']}」名額已滿（{course['max_slots']}/{course['max_slots']}），無法報名。"},
                          ensure_ascii=False)

    if course["status"] == "已取消":
        con.close()
        return json.dumps({"success": False,
                           "message": f"「{course['course_name']}」已取消，無法報名。"},
                          ensure_ascii=False)

    now_iso = datetime.now().isoformat()

    # 建立諮詢單（pms_form_feedback）—— keyword 存 course_id，供後台接單時識別課程
    feedback_no = "FB" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:6].upper()
    goal_text = f"課程報名：{course['gym_name']} {course['course_name']}"
    con.execute(
        "INSERT INTO pms_form_feedback "
        "(feedback_no,goal,keyword,contact_name,contact_phone,note,status,user_id,created_at) "
        "VALUES (?,?,?,?,?,?,'待處理',?,?)",
        (feedback_no, goal_text, str(course["id"]), contact_name, contact_phone, note, user_id or 0, now_iso),
    )

    # 建立報名記錄（course_enrollment）
    con.execute(
        "INSERT INTO course_enrollment "
        "(course_id,feedback_no,contact_name,contact_phone,note,status,notified,enrolled_at) "
        "VALUES (?,?,?,?,?,'報名中',0,?)",
        (course["id"], feedback_no, contact_name, contact_phone, note, now_iso),
    )
    con.commit()
    con.close()

    min_students = course["min_students"]
    open_hint = (
        f"目前課程開課門檻為 {min_students} 人，報名確認後將計入名額，"
        f"後台同意報名後會主動通知您！"
    )

    return json.dumps({
        "success":     True,
        "feedback_no": feedback_no,
        "course_id":   course["id"],
        "course_name": course["course_name"],
        "gym_name":    course["gym_name"],
        "weekday":     course["weekday"],
        "time_start":  course["time_start"],
        "price_month": course["price_month"],
        "message": (
            f"✅ 您的報名申請已提交！\n"
            f"📋 諮詢單號：{feedback_no}\n"
            f"🏋️ 課程：「{course['gym_name']}」【{course['course_name']}】\n"
            f"📅 上課時間：{course['weekday']} {course['time_start']}（每堂 {course['duration_min']} 分鐘）\n"
            f"💰 月費：NT${course['price_month']}\n"
            f"{open_hint}"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 G：查詢全台運動場館（iPlay 全國運動場館資訊網 / 教育部體育署開放資料）
# ---------------------------------------------------------------------------

# 內建樣本場館（API 與開放資料均無法取得時的 fallback）
_BUILTIN_VENUES = [
    {"name": "台北市立體育場", "county": "台北市", "county_code": "01",
     "district": "松山區", "category": "綜合體育館",
     "address": "台北市松山區敦化北路1號",
     "phone": "02-2716-3800", "lat": 25.0590, "lng": 121.5500,
     "status": "營運中", "hours": "週一至日 06:00-22:00",
     "facilities": "田徑場、游泳池、健身房", "website": ""},
    {"name": "台北市立游泳池（中正）", "county": "台北市", "county_code": "01",
     "district": "中正區", "category": "游泳池",
     "address": "台北市中正區汀州路三段1號",
     "phone": "02-2362-1234", "lat": 25.0133, "lng": 121.5239,
     "status": "營運中", "hours": "週二至日 06:00-21:00",
     "facilities": "室內游泳池、烤箱", "website": ""},
    {"name": "台北市立大安運動中心", "county": "台北市", "county_code": "01",
     "district": "大安區", "category": "運動中心",
     "address": "台北市大安區建安街21號",
     "phone": "02-2700-8885", "lat": 25.0256, "lng": 121.5398,
     "status": "營運中", "hours": "週一至五 06:00-22:00，週六日 06:00-21:00",
     "facilities": "游泳池、健身房、羽球場、桌球室", "website": ""},
    {"name": "台北市立信義運動中心", "county": "台北市", "county_code": "01",
     "district": "信義區", "category": "運動中心",
     "address": "台北市信義區莊敬路340號",
     "phone": "02-2722-1305", "lat": 25.0452, "lng": 121.5671,
     "status": "營運中", "hours": "週一至五 06:00-22:00，週六日 06:00-21:00",
     "facilities": "游泳池、健身房、攀岩牆、羽球場", "website": ""},
    {"name": "台北市立中山運動中心", "county": "台北市", "county_code": "01",
     "district": "中山區", "category": "運動中心",
     "address": "台北市中山區樂群二路200號",
     "phone": "02-8502-1505", "lat": 25.0789, "lng": 121.5596,
     "status": "營運中", "hours": "週一至五 06:00-22:00，週六日 06:00-21:00",
     "facilities": "游泳池、健身房、羽球場、籃球場", "website": ""},
    {"name": "新北市立板橋體育館", "county": "新北市", "county_code": "02",
     "district": "板橋區", "category": "綜合體育館",
     "address": "新北市板橋區文化路一段188號",
     "phone": "02-2952-3800", "lat": 25.0121, "lng": 121.4592,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "羽球場、籃球場、健身房", "website": ""},
    {"name": "新北市立新莊體育館", "county": "新北市", "county_code": "02",
     "district": "新莊區", "category": "綜合體育館",
     "address": "新北市新莊區中正路500號",
     "phone": "02-2998-2662", "lat": 25.0414, "lng": 121.4432,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "籃球場、羽球場、游泳池、田徑場", "website": ""},
    {"name": "基隆市立游泳池", "county": "基隆市", "county_code": "03",
     "district": "中山區", "category": "游泳池",
     "address": "基隆市中山區中山二路1號",
     "phone": "02-2422-5110", "lat": 25.1289, "lng": 121.7459,
     "status": "營運中", "hours": "週二至日 06:00-21:00",
     "facilities": "室內游泳池", "website": ""},
    {"name": "桃園市立體育館", "county": "桃園市", "county_code": "04",
     "district": "桃園區", "category": "綜合體育館",
     "address": "桃園市桃園區縣府路55號",
     "phone": "03-332-1200", "lat": 24.9936, "lng": 121.3010,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "籃球場、羽球場、桌球室", "website": ""},
    {"name": "中壢棒球場暨運動公園", "county": "桃園市", "county_code": "04",
     "district": "中壢區", "category": "運動公園",
     "address": "桃園市中壢區環中東路二段300號",
     "phone": "03-436-1237", "lat": 24.9550, "lng": 121.2260,
     "status": "營運中", "hours": "全天候開放",
     "facilities": "棒球場、田徑場、籃球場", "website": ""},
    {"name": "新竹市立游泳池", "county": "新竹市", "county_code": "06",
     "district": "北區", "category": "游泳池",
     "address": "新竹市北區經國路一段442號",
     "phone": "03-532-5000", "lat": 24.8122, "lng": 120.9696,
     "status": "營運中", "hours": "週二至日 06:00-21:00",
     "facilities": "室內游泳池、幼兒池", "website": ""},
    {"name": "台中市立體育館", "county": "台中市", "county_code": "08",
     "district": "北區", "category": "綜合體育館",
     "address": "台中市北區崇德路一段1號",
     "phone": "04-2235-5555", "lat": 24.1590, "lng": 120.6786,
     "status": "營運中", "hours": "週一至日 06:30-22:00",
     "facilities": "籃球場、游泳池、健身房", "website": ""},
    {"name": "台中市文心運動公園", "county": "台中市", "county_code": "08",
     "district": "南屯區", "category": "運動公園",
     "address": "台中市南屯區文心南路8號",
     "phone": "04-2381-5536", "lat": 24.1244, "lng": 120.6468,
     "status": "營運中", "hours": "全天候開放",
     "facilities": "田徑場、籃球場、網球場", "website": ""},
    {"name": "台南市立體育館", "county": "台南市", "county_code": "14",
     "district": "東區", "category": "綜合體育館",
     "address": "台南市東區林森路一段270號",
     "phone": "06-289-1111", "lat": 22.9888, "lng": 120.2162,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "籃球場、羽球場、健身房", "website": ""},
    {"name": "高雄市立體育館", "county": "高雄市", "county_code": "15",
     "district": "苓雅區", "category": "綜合體育館",
     "address": "高雄市苓雅區中正四路399號",
     "phone": "07-715-6888", "lat": 22.6218, "lng": 120.3139,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "籃球場、羽球場、游泳池", "website": ""},
    {"name": "高雄市立游泳池（鳳山）", "county": "高雄市", "county_code": "15",
     "district": "鳳山區", "category": "游泳池",
     "address": "高雄市鳳山區光遠路8號",
     "phone": "07-741-3622", "lat": 22.6270, "lng": 120.3568,
     "status": "營運中", "hours": "週二至日 06:00-21:00",
     "facilities": "室內外游泳池、訓練池", "website": ""},
    {"name": "宜蘭縣立體育館", "county": "宜蘭縣", "county_code": "17",
     "district": "宜蘭市", "category": "綜合體育館",
     "address": "宜蘭市女中路二段360號",
     "phone": "03-936-9090", "lat": 24.7570, "lng": 121.7519,
     "status": "營運中", "hours": "週一至日 07:00-22:00",
     "facilities": "籃球場、羽球場", "website": ""},
    {"name": "花蓮縣立體育館", "county": "花蓮縣", "county_code": "18",
     "district": "花蓮市", "category": "綜合體育館",
     "address": "花蓮市國聯一路1號",
     "phone": "03-822-0060", "lat": 23.9870, "lng": 121.6059,
     "status": "營運中", "hours": "週一至日 08:00-21:00",
     "facilities": "籃球場、羽球場、溜冰場", "website": ""},
]

_SPORTS_VENUE_CACHE: list = []
_SPORTS_VENUE_LOADED: bool = False


def _load_sports_venues() -> list:
    """從教育部體育署開放資料 CSV 取得全台運動場館清單，快取於全域。"""
    global _SPORTS_VENUE_CACHE, _SPORTS_VENUE_LOADED
    if _SPORTS_VENUE_LOADED:
        return _SPORTS_VENUE_CACHE
    _SPORTS_VENUE_LOADED = True

    import csv, io, re

    # 政府縣市代碼 → (縣市名, 本系統代碼)
    _GOV_CODE_MAP = {
        "63000": ("台北市", "01"), "65000": ("新北市", "02"),
        "10017": ("基隆市", "03"), "68000": ("桃園市", "04"),
        "10004": ("新竹縣", "05"), "10018": ("新竹市", "06"),
        "10005": ("苗栗縣", "07"), "66000": ("台中市", "08"),
        "10007": ("南投縣", "09"), "10008": ("彰化縣", "10"),
        "10009": ("雲林縣", "11"), "10010": ("嘉義縣", "12"),
        "10020": ("嘉義市", "13"), "67000": ("台南市", "14"),
        "64000": ("高雄市", "15"), "10013": ("屏東縣", "16"),
        "10002": ("宜蘭縣", "17"), "10015": ("花蓮縣", "18"),
        "10014": ("台東縣", "19"), "10016": ("澎湖縣", "20"),
        "09020": ("金門縣", "21"), "09007": ("連江縣", "22"),
    }
    # 縣市名稱（含臺/台）→ 本系統代碼（從地址萃取時用）
    _NAME_TO_CODE = {
        "台北市": "01", "臺北市": "01", "新北市": "02",
        "基隆市": "03", "桃園市": "04", "新竹縣": "05",
        "新竹市": "06", "苗栗縣": "07", "台中市": "08", "臺中市": "08",
        "南投縣": "09", "彰化縣": "10", "雲林縣": "11",
        "嘉義縣": "12", "嘉義市": "13", "台南市": "14", "臺南市": "14",
        "高雄市": "15", "屏東縣": "16", "宜蘭縣": "17",
        "花蓮縣": "18", "台東縣": "19", "臺東縣": "19",
        "澎湖縣": "20", "金門縣": "21", "連江縣": "22",
    }

    _CSV_URL = (
        "https://ws.sports.gov.tw/FS01/FilePath/1/relfile/164/10269/"
        "5a511d68-e6b8-42ee-a449-acc395135268.csv"
    )
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://iplay.sports.gov.tw/",
    }

    try:
        resp = requests.get(_CSV_URL, headers=hdrs, timeout=15)
        if resp.status_code == 200 and "場館名稱" in (resp.text[:200]):
            reader = csv.DictReader(io.StringIO(resp.text))
            venues = []
            for row in reader:
                name = (row.get("場館名稱") or "").strip()
                if not name:
                    continue

                # 政府縣市代碼 → 縣市名 + 本系統代碼
                gov_code = (row.get("縣市") or "").strip()
                county_name, county_code = _GOV_CODE_MAP.get(gov_code, ("", ""))

                dist  = (row.get("行政區")             or "").strip()
                cat   = (row.get("場館分類")            or "").strip()
                phone = (row.get("場館實際管理人電話")  or "").strip()
                fac   = (row.get("設施項目")            or "").strip()
                stat  = (row.get("開放情形")            or "").strip()
                hrs   = (row.get("開放時間")            or "").strip()
                web   = (row.get("場館官方網站")        or "").strip()

                # 地址去掉前面的 [郵遞區號] 前綴
                raw_addr = (row.get("地址") or "").strip()
                addr = re.sub(r"^\[\d+\]", "", raw_addr).strip()

                # 若政府代碼查不到，嘗試從地址頭 3 字萃取縣市名
                if not county_name and addr:
                    for cn, cc in _NAME_TO_CODE.items():
                        if addr.startswith(cn):
                            county_name, county_code = cn, cc
                            break

                lat_s = (row.get("緯度") or "0").strip()
                lng_s = (row.get("經度") or "0").strip()
                try:
                    lat = float(lat_s) if lat_s and lat_s != "0" else 0.0
                    lng = float(lng_s) if lng_s and lng_s != "0" else 0.0
                except ValueError:
                    lat, lng = 0.0, 0.0

                venues.append({
                    "name":        name,
                    "county":      county_name,
                    "county_code": county_code,
                    "district":    dist,
                    "category":    cat,
                    "address":     addr or f"{county_name}{dist}",
                    "phone":       phone,
                    "lat":         lat,
                    "lng":         lng,
                    "status":      stat,
                    "hours":       hrs,
                    "facilities":  fac,
                    "website":     web,
                })
            if venues:
                _SPORTS_VENUE_CACHE = venues
                return _SPORTS_VENUE_CACHE
    except Exception:
        pass

    _SPORTS_VENUE_CACHE = list(_BUILTIN_VENUES)
    return _SPORTS_VENUE_CACHE


@mcp.tool()
def find_sports_venues(
    keyword: str = "",
    county_code: str = "",
    category: str = "",
    lat: float = 0,
    lng: float = 0,
    radius_km: float = 5.0,
    limit: int = 10,
) -> str:
    """查詢全台運動場館資訊（資料來源：教育部體育署 iPlay 全國運動場館資訊網）。

    當使用者詢問「附近有哪些運動場館」「哪裡有游泳池」「台北有哪些體育館」
    「想找健身中心」「附近有羽球場嗎」「運動場館在哪裡」「哪裡可以打籃球」
    等問題時呼叫此工具。

    參數:
        keyword:     場館名稱、設施或關鍵字，例如「游泳池」「羽球」「健身」「籃球」「田徑」
        county_code: 縣市代碼，對應本系統代碼：
                     01=台北 02=新北 03=基隆 04=桃園 05=新竹縣 06=新竹市
                     07=苗栗 08=台中 09=南投 10=彰化 11=雲林 12=嘉義縣
                     13=嘉義市 14=台南 15=高雄 16=屏東 17=宜蘭 18=花蓮
                     19=台東 20=澎湖 21=金門 22=連江（留空搜尋全台）
        category:    場館類別，例如「游泳池」「體育館」「運動中心」「運動公園」（留空不限）
        lat, lng:    用戶 GPS 座標（系統自動注入，有座標時依距離排序）
        radius_km:   有 GPS 時只回傳此半徑內的場館（公里，預設 5km）
        limit:       回傳筆數上限（預設 10）

    回傳:
        JSON 字串，含符合條件的場館清單。
    """
    import math

    venues = _load_sports_venues()
    is_builtin = (venues is _BUILTIN_VENUES or venues == _BUILTIN_VENUES)

    _CODE_TO_NAMES = {
        "01": ["台北市", "臺北市"], "02": ["新北市"],
        "03": ["基隆市"],           "04": ["桃園市"],
        "05": ["新竹縣"],           "06": ["新竹市"],
        "07": ["苗栗縣"],           "08": ["台中市", "臺中市"],
        "09": ["南投縣"],           "10": ["彰化縣"],
        "11": ["雲林縣"],           "12": ["嘉義縣"],
        "13": ["嘉義市"],           "14": ["台南市", "臺南市"],
        "15": ["高雄市"],           "16": ["屏東縣"],
        "17": ["宜蘭縣"],           "18": ["花蓮縣"],
        "19": ["台東縣", "臺東縣"], "20": ["澎湖縣"],
        "21": ["金門縣"],           "22": ["連江縣"],
    }
    county_names = _CODE_TO_NAMES.get(county_code, []) if county_code else []

    def _haversine(la1, lo1, la2, lo2):
        R, p = 6371.0, math.pi / 180
        a = (math.sin((la2 - la1) * p / 2) ** 2
             + math.cos(la1 * p) * math.cos(la2 * p)
             * math.sin((lo2 - lo1) * p / 2) ** 2)
        return 2 * R * math.asin(min(1.0, math.sqrt(a)))

    results = []
    for v in venues:
        if county_names:
            if v.get("county") not in county_names and v.get("county_code") != county_code:
                continue
        if category:
            if category.lower() not in (v.get("category", "") + " " + v.get("facilities", "")).lower():
                continue
        if keyword:
            haystack = " ".join([
                v.get("name", ""), v.get("category", ""),
                v.get("facilities", ""), v.get("address", ""), v.get("district", ""),
            ]).lower()
            if keyword.lower() not in haystack:
                continue
        dist_km = None
        if lat and lng and v.get("lat") and v.get("lng"):
            dist_km = _haversine(lat, lng, v["lat"], v["lng"])
            if dist_km > radius_km:
                continue
        v_copy = dict(v)
        if dist_km is not None:
            v_copy["distance_km"] = round(dist_km, 2)
        results.append(v_copy)

    if lat and lng:
        results.sort(key=lambda x: x.get("distance_km", 9999))

    # 依 (name, county, district) 去重，合併設施說明
    seen: dict = {}
    for v in results:
        key = (v["name"], v.get("county", ""), v.get("district", ""))
        if key not in seen:
            seen[key] = dict(v)
        else:
            # 合併設施
            existing_fac = seen[key].get("facilities", "")
            new_fac = v.get("facilities", "")
            if new_fac and new_fac not in existing_fac:
                seen[key]["facilities"] = f"{existing_fac}、{new_fac}" if existing_fac else new_fac
    results = list(seen.values())[:limit]

    source_note = "（資料來源：教育部體育署 iPlay 全國運動場館資訊網）"
    if is_builtin:
        source_note = "（資料來源：內建樣本，網路資料暫無法取得）"

    fp = []
    if county_code:
        fp.append(f"縣市={county_names[0] if county_names else county_code}")
    if category:
        fp.append(f"類別={category}")
    if keyword:
        fp.append(f"關鍵字={keyword}")
    if lat and lng:
        fp.append(f"GPS半徑{radius_km}km")
    filters = "、".join(fp) or "不限條件"

    return json.dumps({
        "count":             len(results),
        "venues":            results,
        "total_in_dataset":  len(venues),
        "source_is_builtin": is_builtin,
        "message": (
            f"找到 {len(results)} 個運動場館（篩選：{filters}）{source_note}。"
            if results else
            f"查無符合「{filters}」的運動場館，請嘗試調整關鍵字或放寬條件。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 測試使用
# ---------------------------------------------------------------------------
def _selftest():
    """不啟動 server，直接呼叫三個工具，確認邏輯正確。"""
    print("① search_grocery('雞胸')")
    r = json.loads(search_grocery("雞胸"))
    for p in r["products"]:
        print(f"   [{p['vendor']}] {p['name']}  蛋白質{p['protein_g']}g  ${p['price']}  庫存{p['stock']}")

    print("\n② recommend_high_protein(goal='增肌', budget=300)")
    r = json.loads(recommend_high_protein("增肌", 300))
    print(f"   → {r['message']}")
    for p in r["products"]:
        print(f"      {p['name']} ({p['vendor']})  蛋白質{p['protein_g']}g  ${p['price']}")

    print("\n③ recommend_high_protein(goal='減脂', budget=200)")
    r = json.loads(recommend_high_protein("減脂", 200))
    print(f"   → {r['message']}")
    for p in r["products"]:
        print(f"      {p['name']} ({p['vendor']})  ${p['price']}")

    print("\n④ check_inventory('豆漿')")
    r = json.loads(check_inventory("豆漿"))
    print(f"   → {r['message']}")
    for i in r["items"]:
        print(f"      [{i['vendor']}] {i['name']}  庫存{i['stock']}  ${i['price']}")

    print("\n⑤ submit_inquiry(goal='增肌', contact_name='測試用戶', contact_phone='0912345678', budget=300)")
    r5 = json.loads(submit_inquiry(
        goal="增肌", contact_name="測試用戶",
        contact_phone="0912345678", budget=300, note="selftest",
        products_json="[]"))
    print(f"   → {r5['message']}")

    _r5_no = r5.get('feedback_no', r5.get('inquiry_no'))
    print(f"\n⑥ dispatch_delivery(inquiry_no='{_r5_no}', vendor_name='萬家福信義店', estimated_minutes=45)")
    r6 = json.loads(dispatch_delivery(
        inquiry_no=_r5_no,
        vendor_name="萬家福信義店",
        estimated_minutes=45,
        reply_message="已為您準備商品，預計45分鐘內送達。"))
    print(f"   → {r6['message']}")
    print(f"   外送單號：{r6['delivery_no']}")

    print("\n✅ 五個工具皆正常。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()
