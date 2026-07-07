# -*- coding: utf-8 -*-
"""
mcp_server.py — 健身採買助手 MCP Server

把統一集團健身商品查詢功能包裝成 MCP 工具，讓 Claude / 任何 MCP Agent 調用。

啟動（stdio transport）：  python mcp_server.py
本機測試工具邏輯：         python mcp_server.py --selftest
"""
import sqlite3
import os
import sys
import json
import uuid
from datetime import datetime
from mcp.server.fastmcp import FastMCP

DB = os.path.join(os.path.dirname(__file__), "butler.db")
mcp = FastMCP("fitness-grocery")


def _ensure_schema():
    """既有 DB 缺少新欄位時自動補上（schema migration，不刪資料）。"""
    con = _db()
    cols = {row[1] for row in con.execute("PRAGMA table_info(inquiry)")}
    for col, defn in [
        ("vendor_reply", "TEXT NOT NULL DEFAULT ''"),
        ("accepted_at",  "TEXT NOT NULL DEFAULT ''"),
        ("delivery_no",  "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in cols:
            con.execute(f"ALTER TABLE inquiry ADD COLUMN {col} {defn}")
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
# 工具 1：依關鍵字搜尋健身商品
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
    products = [dict(r) for r in rows]
    return json.dumps(
        {"count": len(products), "products": products,
         "message": f"找到 {len(products)} 筆商品。" if products
                    else f"找不到含「{keyword}」的商品。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 2：依目標（增肌/減脂）與預算推薦高蛋白商品組合
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
            picked.append(dict(r))
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
# 工具 3：查詢特定商品在各業務的庫存狀況
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

    items = [dict(r) for r in rows]
    in_stock = [i for i in items if i["stock"] > 0]

    return json.dumps(
        {"query": product_name, "found": len(items), "in_stock": len(in_stock),
         "items": items,
         "message": f"找到 {len(items)} 筆，其中 {len(in_stock)} 筆有庫存。"
                    if items else f"查無「{product_name}」相關商品。"},
        ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工具 4：建立健身採買諮詢單（寫入操作，必須使用者確認後才能呼叫）
# ---------------------------------------------------------------------------
@mcp.tool()
def submit_inquiry(goal: str, contact_name: str, contact_phone: str,
                   budget: int = 0, keyword: str = "", note: str = "") -> str:
    """將使用者的健身採買需求寫入後台諮詢單，讓後台人員可以跟進與協助。

    【重要】這是寫入操作。呼叫此工具前，必須已明確告知使用者
    「我將要幫您建立採買諮詢單」並獲得其口頭確認，才能執行。

    當使用者：
    - 明確說「好」「可以」「幫我建立」「記錄一下」等同意語句後
    呼叫此工具。若使用者未明確同意，禁止呼叫。

    參數:
        goal:          健身目標，例如「增肌」「減脂」「搜尋商品」
        contact_name:  聯絡人姓名
        contact_phone: 聯絡電話
        budget:        採買預算（選填，無則為 0）
        keyword:       搜尋關鍵字（選填）
        note:          備註（選填）

    回傳:
        JSON 字串，含諮詢單編號 inquiry_no。
    """
    inquiry_no = "IQ" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:6].upper()
    con = _db()
    con.execute(
        "INSERT INTO inquiry "
        "(inquiry_no,goal,budget,keyword,contact_name,contact_phone,note,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (inquiry_no, goal, budget, keyword,
         contact_name, contact_phone, note, datetime.now().isoformat()),
    )
    con.commit()
    con.close()
    return json.dumps(
        {"success": True, "inquiry_no": inquiry_no,
         "message": f"諮詢單 {inquiry_no} 已建立！後台人員將主動與您聯繫。"},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 工具 5：後台接單並派送外送服務（寫入操作，由後台人員確認後呼叫）
# ---------------------------------------------------------------------------
@mcp.tool()
def dispatch_delivery(inquiry_no: str, vendor_name: str,
                      estimated_minutes: int = 60, reply_message: str = "") -> str:
    """後台人員確認接受採買諮詢單後，建立外送配送訂單並更新諮詢單狀態。

    【重要】這是寫入操作，必須由後台人員在後台介面確認接單後才能呼叫。
    呼叫後將：
    1. 產生外送單號（DL...）
    2. 將諮詢單狀態改為「配送中」
    3. 記錄接單廠商、回覆訊息與接單時間

    參數:
        inquiry_no:        諮詢單編號，例如「IQ260708XXXXXX」
        vendor_name:       接單廠商或門市，例如「家樂福信義店」
        estimated_minutes: 預計送達分鐘數，預設 60
        reply_message:     廠商給用戶的回覆訊息（選填）

    回傳:
        JSON 字串，含外送單號 delivery_no。
    """
    delivery_no = "DL" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:6].upper()
    now_iso     = datetime.now().isoformat()
    stored_reply = f"[{vendor_name}] {reply_message}".strip()

    con = _db()
    con.execute(
        "UPDATE inquiry "
        "SET status='配送中', accepted_at=?, delivery_no=?, vendor_reply=? "
        "WHERE inquiry_no=?",
        (now_iso, delivery_no, stored_reply, inquiry_no),
    )
    con.commit()
    con.close()

    return json.dumps(
        {
            "success":           True,
            "delivery_no":       delivery_no,
            "inquiry_no":        inquiry_no,
            "vendor_name":       vendor_name,
            "estimated_minutes": estimated_minutes,
            "message": (
                f"🚚 外送單 {delivery_no} 已建立！"
                f"{vendor_name} 預計 {estimated_minutes} 分鐘內送達。"
            ),
        },
        ensure_ascii=False,
    )


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
        contact_phone="0912345678", budget=300, note="selftest"))
    print(f"   → {r5['message']}")

    print(f"\n⑥ dispatch_delivery(inquiry_no='{r5['inquiry_no']}', vendor_name='家樂福信義店', estimated_minutes=45)")
    r6 = json.loads(dispatch_delivery(
        inquiry_no=r5["inquiry_no"],
        vendor_name="家樂福信義店",
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
