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
# 工具 4：依關鍵字搜尋健身商品
# ---------------------------------------------------------------------------
@mcp.tool()
def search_grocery(keyword: str) -> str:
    """在統一集團各業務（7-11、家樂福、康是美、統一生機）的健身商品庫中，
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
    products = [
        {"id": r["id"], "name": r["name"], "vendor": r["vendor"],
         "category": r["category"], "protein_g": r["protein_g"],
         "calories": r["calories"], "price": r["price"], "stock": r["stock"]}
        for r in rows
    ]
    return json.dumps(
        {"count": len(products), "products": products,
         "message": f"找到 {len(products)} 筆商品。" if products
                    else f"找不到含「{keyword}」的商品。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 5：依目標（增肌/減脂）與預算推薦高蛋白商品組合
# ---------------------------------------------------------------------------
@mcp.tool()
def recommend_high_protein(goal: str, budget: int) -> str:
    """根據使用者的健身目標與採買預算，從統一集團商品中推薦最佳高蛋白採買組合，
    回傳推薦清單、組合總蛋白質克數與總價格。
    當使用者說「幫我規劃增肌採買清單」「我有 500 元想買高蛋白食物」
    「減脂期間買什麼比較好」時，呼叫此工具。

    參數:
        goal:   健身目標，例如「增肌」或「減脂」
        budget: 採買預算（台幣整數），例如 500

    回傳:
        JSON 字串，含推薦商品清單、總蛋白質克數與總花費。
    """
    con = _db()
    if "減脂" in goal or "cut" in goal.lower():
        # 減脂：蛋白質/熱量比高（熱量效率）且庫存充足
        rows = con.execute(
            "SELECT * FROM fitness_product WHERE stock > 0 AND calories > 0 "
            "ORDER BY CAST(protein_g AS REAL)/calories DESC, price ASC"
        ).fetchall()
    else:
        # 增肌（預設）：單份蛋白質克數高
        rows = con.execute(
            "SELECT * FROM fitness_product WHERE stock > 0 "
            "ORDER BY protein_g DESC, price ASC"
        ).fetchall()
    con.close()

    picked, total_price, total_protein = [], 0, 0.0
    for r in rows:
        if total_price + r["price"] <= budget:
            picked.append({
                "name": r["name"], "vendor": r["vendor"],
                "protein_g": r["protein_g"], "calories": r["calories"],
                "price": r["price"],
            })
            total_price += r["price"]
            total_protein += r["protein_g"]

    return json.dumps(
        {"goal": goal, "budget": budget,
         "total_price": total_price, "total_protein_g": round(total_protein, 1),
         "count": len(picked), "products": picked,
         "message": f"在 {budget} 元預算內，推薦 {len(picked)} 項商品，"
                    f"合計蛋白質 {round(total_protein, 1)}g，花費 {total_price} 元。"
                    if picked else "預算不足以購買任何商品，建議提高預算。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 6：查詢特定商品在各業務的庫存狀況
# ---------------------------------------------------------------------------
@mcp.tool()
def check_inventory(product_name: str) -> str:
    """查詢某個商品在統一集團各業務（7-11、家樂福、康是美、統一生機）的庫存狀況，
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
        "SELECT name, vendor, stock, price FROM fitness_product "
        "WHERE name LIKE ? ORDER BY stock DESC",
        (f"%{product_name}%",),
    ).fetchall()
    con.close()

    items = [{"name": r["name"], "vendor": r["vendor"],
              "stock": r["stock"], "price": r["price"]} for r in rows]
    in_stock = [i for i in items if i["stock"] > 0]

    return json.dumps(
        {"query": product_name, "found": len(items), "in_stock": len(in_stock),
         "items": items,
         "message": f"找到 {len(items)} 筆，其中 {len(in_stock)} 筆有庫存。"
                    if items else f"查無「{product_name}」相關商品。"},
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
    print("\n④ search_grocery('雞胸')")
    sg = json.loads(search_grocery("雞胸"))
    for p in sg["products"]:
        print(f"   → [{p['vendor']}] {p['name']}  蛋白質{p['protein_g']}g  ${p['price']}  庫存{p['stock']}")

    print("\n⑤ recommend_high_protein(goal='增肌', budget=300)")
    rp = json.loads(recommend_high_protein("增肌", 300))
    print(f"   → {rp['message']}")
    for p in rp["products"]:
        print(f"      {p['name']} ({p['vendor']}) 蛋白質{p['protein_g']}g ${p['price']}")

    print("\n⑥ recommend_high_protein(goal='減脂', budget=200)")
    rd = json.loads(recommend_high_protein("減脂", 200))
    print(f"   → {rd['message']}")

    print("\n⑦ check_inventory('豆漿')")
    ci = json.loads(check_inventory("豆漿"))
    print(f"   → {ci['message']}")
    for i in ci["items"]:
        print(f"      [{i['vendor']}] {i['name']}  庫存{i['stock']}  ${i['price']}")

    print("\n✅ 六個工具皆正常。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        mcp.run()   # 預設 stdio transport，供 Claude Desktop / Agent 連線
