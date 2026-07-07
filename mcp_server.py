# -*- coding: utf-8 -*-
"""
mcp_server.py — AI 生活管家 MCP Server

把「智慧社區服務」的後端操作包裝成 MCP 工具，讓 Claude / LumineOne 等
任何 MCP Agent 都能調用。這支檔案是整個作品的技術核心。

啟動（給 Agent 連線用，stdio）：  python mcp_server.py
本機測試工具邏輯：               python mcp_server.py --selftest
"""
import sqlite3
import os
import sys
import json
import uuid
from datetime import datetime
from mcp.server.fastmcp import FastMCP

DB = os.path.join(os.path.dirname(__file__), "butler.db")
mcp = FastMCP("ai-life-butler")


def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _classify(text: str):
    """用關鍵字把使用者描述對應到服務分類。
    （MCP Server 是架構核心，供外部 Agent 調用；意圖辨識由 Agent 層負責。）"""
    con = _db()
    rows = con.execute("SELECT * FROM service_category").fetchall()
    con.close()
    best, hits = None, 0
    for r in rows:
        c = sum(1 for kw in r["keywords"].split(",") if kw and kw in text)
        if c > hits:
            best, hits = r, c
    return dict(best) if best else None


# ---------------------------------------------------------------------------
# 工具 1：判斷服務類型，回傳對應的動態表單
# ---------------------------------------------------------------------------
@mcp.tool()
def get_service_form(user_request: str) -> str:
    """根據使用者用自然語言描述的生活需求，判斷屬於哪一種服務（水電修繕、
    家事清潔、餐廳訂位、商城購物、美食外送），並回傳對應的彈性留資表單，
    包含所有題目與選項。當使用者描述任何居家、生活、修繕、訂位、購物需求時呼叫此工具。

    參數:
        user_request: 使用者的需求描述，例如「我家廚房水管漏水，想找人來修」

    回傳:
        JSON 字串，含 form_id、表單名稱、服務分類，以及題目清單（含題型與選項）。
    """
    cat = _classify(user_request)
    if not cat:
        return json.dumps(
            {"matched": False,
             "message": "無法判斷服務類型，請提供更多描述（例如修繕、清潔、訂位）。"},
            ensure_ascii=False)

    con = _db()
    form = con.execute(
        "SELECT * FROM pms_form WHERE category_id=? AND is_enable='1' LIMIT 1",
        (cat["id"],)).fetchone()
    if not form:
        con.close()
        return json.dumps(
            {"matched": True, "category": cat["name"],
             "message": "此分類尚無啟用的表單。"}, ensure_ascii=False)

    type_map = {"1": "簡答", "2": "詳答", "3": "單選", "4": "複選",
                "5": "地區選單", "6": "上傳照片", "7": "備註",
                "8": "聯絡資料", "9": "日期", "10": "聯絡資料(不含地址)"}
    topics = []
    for t in con.execute(
            "SELECT * FROM pms_form_topic WHERE form_id=? ORDER BY sort",
            (form["id"],)).fetchall():
        opts = [
            {"option_name": o["option_name"], "unit_price": o["unit_price"],
             "unit": o["unit"]}
            for o in con.execute(
                "SELECT * FROM pms_topic_option WHERE topic_id=? ORDER BY sort",
                (t["id"],)).fetchall()
        ]
        topics.append({
            "topic_id": t["id"], "title": t["title"],
            "type": type_map.get(t["type"], t["type"]),
            "required": t["is_required"] == "1",
            "remark": t["remark"], "options": opts,
        })
    con.close()
    return json.dumps({
        "matched": True, "form_id": form["id"], "form_name": form["name"],
        "category_id": cat["id"], "category": cat["name"],
        "intro": form["intro_content"], "topics": topics,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 2：消費者填完表單後送出，建立留資/諮詢單
# ---------------------------------------------------------------------------
@mcp.tool()
def submit_form_feedback(form_id: int, category_id: int, contact_name: str,
                         contact_mobile: str, county_code: str,
                         district_code: str, description: str,
                         answers: str = "{}") -> str:
    """消費者填寫完留資表單後送出，建立一筆諮詢單（留資單）存入後台。
    當使用者已提供聯絡資訊與需求細節、準備送出表單時呼叫此工具。

    參數:
        form_id:        get_service_form 回傳的表單 ID
        category_id:    服務分類 ID
        contact_name:   聯絡人姓名
        contact_mobile: 聯絡電話
        county_code:    縣市代碼（例如台北市=01）
        district_code:  行政區代碼（例如大安區=001）
        description:    需求描述
        answers:        其餘表單答案的 JSON 字串（選填）

    回傳:
        JSON 字串，含建立成功的諮詢單編號 feedback_no。
    """
    feedback_no = "FB" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:6].upper()
    con = _db()
    con.execute(
        "INSERT INTO pms_form_feedback "
        "(feedback_no,form_id,category_id,contact_name,contact_mobile,"
        "county_code,district_code,description,answers_json,status,is_read,cre_time) "
        "VALUES (?,?,?,?,?,?,?,?,?,'01','0',?)",
        (feedback_no, form_id, category_id, contact_name, contact_mobile,
         county_code, district_code, description, answers,
         datetime.now().isoformat()))
    con.commit()
    con.close()
    return json.dumps(
        {"success": True, "feedback_no": feedback_no,
         "message": f"諮詢單 {feedback_no} 已建立，正在為您媒合廠商。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 3：依服務分類 + 地區媒合合適的廠商
# ---------------------------------------------------------------------------
@mcp.tool()
def match_vendors(category_id: int, county_code: str,
                  district_code: str = "") -> str:
    """根據服務分類與消費者所在地區，媒合可服務該地區的廠商，依評分排序。
    當需要為某個服務需求推薦廠商時呼叫此工具。

    參數:
        category_id:   服務分類 ID
        county_code:   縣市代碼
        district_code: 行政區代碼（選填；給定時優先精準比對該區）

    回傳:
        JSON 字串，含媒合到的廠商清單（名稱、評分、電話、服務地區）。
    """
    con = _db()
    if district_code:
        sql = ("SELECT DISTINCT v.* FROM service_vendor v "
               "JOIN vendor_service_area a ON v.id=a.vendor_id "
               "WHERE v.category_id=? AND a.county_code=? AND a.district_code=? "
               "ORDER BY v.rating DESC")
        rows = con.execute(sql, (category_id, county_code, district_code)).fetchall()
        if not rows:  # 該區沒有就放寬到同縣市
            district_code = ""
    if not district_code:
        sql = ("SELECT DISTINCT v.* FROM service_vendor v "
               "JOIN vendor_service_area a ON v.id=a.vendor_id "
               "WHERE v.category_id=? AND a.county_code=? "
               "ORDER BY v.rating DESC")
        rows = con.execute(sql, (category_id, county_code)).fetchall()

    vendors = [{"vendor_id": r["id"], "name": r["name"],
                "rating": r["rating"], "phone": r["phone"]} for r in rows]
    con.close()
    return json.dumps(
        {"count": len(vendors), "vendors": vendors,
         "message": f"媒合到 {len(vendors)} 家廠商。" if vendors
                    else "此地區暫無可服務的廠商。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
def _selftest():
    """不啟動 server，直接呼叫三個工具，確認邏輯正確。"""
    print("① get_service_form('我家廚房水管漏水，想找人來修')")
    r = json.loads(get_service_form("我家廚房水管漏水，想找人來修"))
    print("   →", r["form_name"], "| 分類:", r["category"],
          "| 題目數:", len(r["topics"]))

    print("\n② submit_form_feedback(...)")
    s = json.loads(submit_form_feedback(
        form_id=r["form_id"], category_id=r["category_id"],
        contact_name="王小明", contact_mobile="0912345678",
        county_code="01", district_code="001",
        description="廚房水槽下方持續滴水"))
    print("   →", s["message"])

    print("\n③ match_vendors(category_id=1, 台北市 大安區)")
    m = json.loads(match_vendors(category_id=1, county_code="01",
                                 district_code="001"))
    for v in m["vendors"]:
        print(f"   → {v['name']} ⭐{v['rating']} {v['phone']}")
    print("\n✅ 三個工具皆正常。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()   # 預設 stdio transport，供 Claude Desktop / Agent 連線
