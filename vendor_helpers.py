# -*- coding: utf-8 -*-
"""
vendor_helpers.py — 健康採買後台輔助模組
純 Python 函式：常數、Ollama 工具、DB helpers、Being Sport helpers、廠商驗證
匯入方式：from vendor_helpers import (DB, VENDOR_COLOR, ...)
"""
import sqlite3
import json
import os
import asyncio
import concurrent.futures
from datetime import datetime
from openai import OpenAI
from mcp import Client

DB = os.path.join(os.path.dirname(__file__), "butler.db")
if not os.path.exists(DB):
    import seed
    seed.main()

from mcp_server import mcp as _mcp  # MCP Server instance（透過 Client 真實呼叫）

VENDOR_COLOR = {
    "7-11":    "#00833D",
    "萬家福":  "#0064D2",
    "康是美":  "#E60012",
    "統一生機": "#7B5EA7",
}
CAT_ICON = {
    "蛋白質": "🥩", "主食": "🍚", "蔬果": "🥦",
    "乳製品": "🥛", "保健品": "💊", "即食": "🍱",
}
STATUS_CFG = {
    "待處理": {"color": "#FF9800", "icon": "⏳"},
    "預留中": {"color": "#7B5EA7", "icon": "📦"},
    "配送中": {"color": "#1976D2", "icon": "🚚"},
    "已拒絕": {"color": "#9E9E9E", "icon": "❌"},
    "已完成": {"color": "#43A047", "icon": "✅"},
}
DELIVERY_TYPE_CFG = {
    "外送": {"color": "#1976D2", "icon": "🚚", "label": "外送"},
    "自取": {"color": "#43A047", "icon": "🏃", "label": "自取"},
}

DELIVERY_COMPANIES = [
    "自家配送（門市自送）",
    "黑貓宅配（大和運輸）",
    "新竹物流",
    "台灣宅配通",
    "中華郵政（郵局包裹）",
    "嘉里大榮物流",
    "統一速達（宅急便）",
    "7-11 交貨便（C2C）",
    "順豐速運",
]

DELIVERY_ICON = {
    "自家配送（門市自送）":   "🏪",
    "黑貓宅配（大和運輸）":   "🐱",
    "新竹物流":               "🚛",
    "台灣宅配通":             "📦",
    "中華郵政（郵局包裹）":   "📮",
    "嘉里大榮物流":           "🚚",
    "統一速達（宅急便）":     "⚡",
    "7-11 交貨便（C2C）":    "🏬",
    "順豐速運":               "🦅",
}

MCP_TOOLS = [
    {
        "no": 1, "name": "search_grocery",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "依關鍵字搜尋統一集團各業務（7-11、萬家福、康是美、統一生機）的健康商品，回傳商品清單與蛋白質 / 熱量 / 價格 / 庫存資訊。每次只接受一個關鍵字。",
        "trigger": "用戶詢問「有沒有雞胸肉」「乳清蛋白哪裡賣」時，AI 透過 mcp.Client 真實呼叫。",
    },
    {
        "no": 2, "name": "recommend_high_protein",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "根據健康目標（增肌/減脂）與採買預算，用貪婪演算法挑選最佳高蛋白商品組合，回傳推薦清單與合計蛋白質 / 花費。AI 再依用戶飲食偏好篩選說明。",
        "trigger": "AI 確認用戶目標 AND 預算後才呼叫；若預算未知，必須先詢問。",
    },
    {
        "no": 3, "name": "check_inventory",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "查詢指定商品在各通路的即時庫存數量，回傳有無庫存及各通路庫存明細。",
        "trigger": "用戶詢問「還有庫存嗎」「哪裡還有貨」時，AI 透過 mcp.Client 真實呼叫。",
    },
    {
        "no": 4, "name": "submit_inquiry",
        "type": "🔴 寫入", "caller": "前端 AI（用戶確認後）",
        "desc": "將用戶的健康採買需求寫入後台諮詢單（pms_form_feedback 表），產生諮詢單號 FB...，讓後台人員跟進。products_json 只放用戶明確指定的商品。",
        "trigger": "用戶同意 → AI 收集姓名電話 → 再次確認 → 透過 mcp.Client 呼叫，嚴禁未確認就寫入。",
    },
    {
        "no": 5, "name": "dispatch_delivery",
        "type": "🔴 寫入", "caller": "後台 AI 助手（接單後）",
        "desc": "後台人員接受採買諮詢單後，建立外送配送訂單（DL...），更新諮詢單狀態為「配送中」，並自動扣減各商品庫存（每項 -1）。",
        "trigger": "後台 AI 助手確認廠商資訊後呼叫，或後台人員手動填寫後透過 mcp.Client 執行。",
    },
    {
        "no": 6, "name": "get_current_time",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "取得台灣當前時間、日期、星期幾與時段（清晨／早晨／下午／晚上），供 AI 判斷門市營業狀況或給出時段相關建議。",
        "trigger": "用戶詢問「現在幾點」「今天星期幾」「還有開嗎」時呼叫。",
    },
    {
        "no": 7, "name": "get_weather",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "透過 Open-Meteo 免費 API（無需 API 金鑰）查詢指定地點的即時天氣，回傳氣溫、體感溫度、天氣狀況（WMO 代碼對應繁體中文描述）、濕度、風速，並依天氣狀況給出外出採買或戶外運動的建議。",
        "trigger": "用戶詢問「現在天氣如何」「適合出門嗎」「會下雨嗎」「要帶傘嗎」時呼叫；系統自動注入 GPS 座標，無 GPS 時可傳入城市名稱。",
    },
    {
        "no": 8, "name": "search_recipe",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": (
            "依料理名稱或食材搜尋食譜，回傳食材清單、烹飪步驟、所需時間與營養資訊。"
            "優先呼叫 Spoonacular API（SPOONACULAR_API_KEY），若未設定則改用 Edamam Recipe API"
            "（EDAMAM_RECIPE_APP_ID + EDAMAM_RECIPE_APP_KEY）。"
            "支援飲食限制（vegetarian / vegan / ketogenic / low-carb）與料理類型（chinese / japanese / italian）過濾。"
        ),
        "trigger": "用戶詢問「用雞胸肉可以做什麼」「推薦低卡晚餐食譜」「蛋炒飯怎麼做」「今天吃什麼」時呼叫。",
    },
    {
        "no": 10, "name": "find_nearby_stores",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": (
            "以用戶 GPS 座標為圓心，透過 Overpass API（OpenStreetMap）搜尋附近地點，支援三種模式：\n"
            "① 品牌模式：輸入「7-11/超商/萬家福/藥妝/康是美/統一生機」→ 只搜統一集團對應門市\n"
            "② 場所模式：輸入「餐廳/健康餐廳/素食/咖啡廳/健身房/藥局/診所/早餐/麵包」→ 搜 OSM 對應 amenity/shop/leisure 標籤\n"
            "③ 關鍵字模式：輸入「拉麵/燒肉/火鍋/健康」等任意文字 → 用名稱模糊比對搜尋全 OSM\n"
            "留空時預設搜索附近所有統一集團門市。"
        ),
        "trigger": "用戶詢問「附近哪裡可以買」「最近的 7-11 在哪」「附近有健康餐廳嗎」「附近咖啡廳」「健身房在哪」時，系統自動注入 GPS 座標後呼叫。",
    },
    {
        "no": 11, "name": "find_route",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "給定多個取貨停靠點，以 OSRM（OpenStreetMap Routing Machine）計算最佳配送路線與實際道路距離；若 OSRM 無法連線，自動退回最近鄰貪婪演算法。停靠點無座標時自動呼叫 Nominatim 地理編碼。",
        "trigger": "用戶詢問「最佳外送路線」「要先去哪家取貨」或後台安排多點取貨時使用。",
    },
    {
        "no": 12, "name": "analyze_meal_nutrition",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "根據食物名稱與攝取克數，查詢並計算該份量的熱量與三大營養素。每次只查一種食物；用戶說出多種食物時，AI 應逐項呼叫並將結果加總。優先使用 Edamam API（需設定環境變數），無金鑰時自動改用 Open Food Facts。",
        "trigger": "用戶描述今天吃了什麼（「我吃了雞胸肉 150g 和白飯 400g」）時，AI 逐項呼叫，再將加總結果傳給 recommend_after_meal。",
    },
    {
        "no": 13, "name": "recommend_after_meal",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "根據今日已攝取的總熱量與總蛋白質，對比健康目標（增肌 2500 kcal / 減脂 1800 kcal）的每日建議量，從庫存商品中推薦應補充採買的品項（最多 5 項）。",
        "trigger": "analyze_meal_nutrition 多次呼叫後，將 calories 與 protein_g 加總，傳入此工具取得個人化採買建議。",
    },
    {
        "no": 14, "name": "calculate_tdee",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "依 Mifflin-St Jeor 公式計算基礎代謝率（BMR）與每日總能量消耗（TDEE），並依目標給出建議熱量與三大營養素配比。已登入用戶只需傳入 user_id，工具自動從 DB 讀取身高、體重、年齡、性別。",
        "trigger": "用戶詢問「TDEE」「每日需要吃多少卡」「基礎代謝是多少」時才呼叫；採買推薦場景不呼叫此工具。",
    },
    {
        "no": 15, "name": "get_gym_courses",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": "查詢合作健身房（Being Sport）本月全部開課課程，回傳課程名稱、教練、時間、剩餘名額與月費。工具回傳所有課程，由 AI 依用戶需求推薦。",
        "trigger": "用戶詢問「有什麼運動課程」「健身課怎麼報名」「找附近健身課程」時呼叫，不傳篩選參數直接取全部。",
    },
    {
        "no": 16, "name": "enroll_gym_course",
        "type": "🔴 寫入", "caller": "前端 AI（用戶確認後）",
        "desc": "報名 Being Sport 健身課程，同時建立諮詢單（FB...）與報名紀錄（course_enrollment），並更新課程已報名人數。人數達最低開課門檻時回傳提示。",
        "trigger": "用戶確認要報名某課程，AI 收集姓名與電話後呼叫；嚴禁未確認就寫入。",
    },
    {
        "no": 17, "name": "find_sports_venues",
        "type": "🟢 讀取", "caller": "前端 AI（Ollama / Claude）",
        "desc": (
            "查詢全台公共運動場館資訊（游泳池、體育館、運動中心、運動公園等），"
            "資料來源：教育部體育署 iPlay 全國運動場館資訊網，涵蓋全台 22 縣市。"
            "支援依縣市代碼、類別、關鍵字過濾，有 GPS 座標時自動依距離排序。"
            "若開放資料 CSV 暫無法取得，自動退回內建樣本場館清單。"
        ),
        "trigger": "用戶詢問「附近有哪些運動場館」「哪裡有游泳池」「台北有體育館嗎」"
                   "「哪裡可以打羽球/籃球」「運動場館在哪」等問題時呼叫。"
                   "私人商業健身房改用 find_nearby_stores；Being Sport 課程改用 get_gym_courses。",
    },
]


# ── Ollama 本地 AI + 真實 MCP 呼叫（後台版）────────────────────────────────

_ollama = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
OLLAMA_MODEL = "qwen2.5:7b"

ADMIN_SYSTEM = """\
你是「後台採買管理助手」，協助後台人員處理健康採買諮詢單的派送事宜。
當後台人員提供諮詢單號（如 FB260708XXXXXX）和廠商名稱後，立即呼叫 dispatch_delivery 工具建立外送訂單，不需要再詢問確認。
語言：繁體中文，語氣專業。執行完後再回報結果。\
"""

ADMIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "dispatch_delivery",
            "description": "後台人員確認接受採買諮詢單後，建立外送配送訂單並更新諮詢單狀態為「配送中」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "inquiry_no":        {"type": "string",  "description": "諮詢單編號，例如「FB260708XXXXXX」"},
                    "vendor_name":       {"type": "string",  "description": "接單廠商或門市，例如「萬家福信義店」"},
                    "estimated_minutes": {"type": "integer", "description": "預計送達分鐘數，預設 60"},
                    "reply_message":     {"type": "string",  "description": "廠商給用戶的回覆訊息（選填）"},
                },
                "required": ["inquiry_no", "vendor_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email_notification",
            "description": "發送 Email 通知給指定收件人。適用於接單通知、訂單狀態更新、系統公告等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_email": {"type": "string", "description": "收件人 Email 地址，例如「user@example.com」"},
                    "subject":  {"type": "string", "description": "郵件主旨"},
                    "body":     {"type": "string", "description": "郵件內文（純文字）"},
                },
                "required": ["to_email", "subject", "body"],
            },
        },
    },
]


def _run_async(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _parse_text_tool_calls(text: str) -> list:
    """qwen2.5 有時把工具呼叫輸出成純文字 JSON，此函式從文字中萃取。"""
    results = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth, j = 0, i
            while j < len(text):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[i:j + 1])
                            if isinstance(obj.get("name"), str) and "arguments" in obj:
                                args = obj["arguments"]
                                if isinstance(args, str):
                                    args = json.loads(args)
                                results.append({"name": obj["name"], "arguments": args})
                        except Exception:
                            pass
                        break
                j += 1
        i += 1
    return results


def _strip_raw_tool_calls(text: str) -> str:
    """移除回覆文字中殘留的 <tool_call> 標籤與 JSON 片段。"""
    import re
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    text = re.sub(r'</?tool_call>', '', text)
    text = re.sub(r'\s*piring\s*', ' ', text)
    text = re.sub(r'\{"name":\s*"[^"]+",\s*"arguments":\s*\{[^{}]*\}\}', '', text)
    return text.strip()


async def _dispatch_via_mcp_async(inquiry_no, vendor_name, estimated_minutes,
                                   reply_message, delivery_company="", tracking_no=""):
    """透過 mcp.Client 真實呼叫 dispatch_delivery 工具。"""
    print(f"\n🔌 [手動派送 MCP] mcp.Client.call_tool('dispatch_delivery', inquiry_no={inquiry_no}, vendor={vendor_name}, carrier={delivery_company})")
    async with Client(_mcp) as c:
        result = await c.call_tool("dispatch_delivery", {
            "inquiry_no":        inquiry_no,
            "vendor_name":       vendor_name,
            "estimated_minutes": estimated_minutes,
            "reply_message":     reply_message,
            "delivery_company":  delivery_company,
            "tracking_no":       tracking_no,
        })
        text = result.content[0].text if result.content else "{}"
        print(f"✅ [手動派送 MCP] dispatch_delivery 回傳: {text[:120]}")
        return json.loads(text)


def dispatch_via_mcp(inquiry_no, vendor_name, estimated_minutes=60,
                     reply_message="", delivery_company="", tracking_no=""):
    """同步包裝：透過 MCP Client 派送，回傳 dict。"""
    try:
        return _run_async(
            _dispatch_via_mcp_async(inquiry_no, vendor_name, estimated_minutes,
                                    reply_message, delivery_company, tracking_no)
        )
    except Exception as exc:
        return {"success": False, "message": f"MCP 呼叫失敗：{exc}"}


async def _admin_ollama_loop(msgs: list) -> tuple:
    """後台 Ollama chat loop，透過 mcp.Client 呼叫 dispatch_delivery。
    支援 qwen2.5 fallback：當模型把工具呼叫輸出成純文字時，自動萃取並執行。
    """
    import uuid as _uuid

    tool_log = []
    messages = list(msgs)

    async with Client(_mcp) as mcp_client:
        for _ in range(6):
            resp = _ollama.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=ADMIN_TOOLS,
                temperature=0.0,
            )
            msg = resp.choices[0].message
            content = msg.content or ""

            # ── 取得工具呼叫：優先 structured，否則從文字萃取 ──
            raw_tcs = list(msg.tool_calls or [])
            if not raw_tcs and content:
                parsed = _parse_text_tool_calls(content)
                if parsed:
                    class _FakeFn:
                        def __init__(self, n, a):
                            self.name = n
                            self.arguments = json.dumps(a, ensure_ascii=False)
                    class _FakeTC:
                        def __init__(self, n, a):
                            self.id = _uuid.uuid4().hex
                            self.function = _FakeFn(n, a)
                    raw_tcs = [_FakeTC(p["name"], p["arguments"]) for p in parsed]

            if not raw_tcs:
                return _strip_raw_tool_calls(content), tool_log

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in raw_tcs
                ],
            })

            for tc in raw_tcs:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)
                ts = datetime.now().strftime("%H:%M:%S")

                print(f"\n🔌 [後台 MCP] mcp.Client.call_tool('{tool_name}', {tool_args})")

                mcp_result = await mcp_client.call_tool(tool_name, tool_args)
                result_text = (
                    mcp_result.content[0].text
                    if mcp_result.content else "{}"
                )
                try:
                    result_dict = json.loads(result_text)
                except Exception:
                    result_dict = {"raw": result_text}

                print(f"✅ [後台 MCP] '{tool_name}' 回傳: {result_text[:120]}")

                tool_log.append({
                    "tool":   tool_name,
                    "params": tool_args,
                    "result": result_dict,
                    "ts":     ts,
                    "via":    "mcp.Client",
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        return "（對話輪數過多，已停止。）", tool_log


def admin_ollama_chat(prompt: str, history: list) -> tuple:
    """後台 Ollama + 真實 MCP 對話。回傳 (reply, tool_log, updated_history)。"""
    msgs = [{"role": "system", "content": ADMIN_SYSTEM}] + history + [
        {"role": "user", "content": prompt}
    ]
    try:
        text, tool_log = _run_async(_admin_ollama_loop(msgs))
    except Exception as exc:
        text = (
            f"❌ Ollama 連線失敗：{exc}\n\n"
            f"請確認 Ollama 已啟動：`ollama serve`\n"
            f"並已下載模型：`ollama pull {OLLAMA_MODEL}`"
        )
        tool_log = []

    updated = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": text},
    ]
    return text, tool_log, updated


# ── DB helpers ──────────────────────────────────────────────────────────────

def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def get_stats():
    con = _db()
    total        = con.execute("SELECT COUNT(*) FROM fitness_product").fetchone()[0]
    out_of_stock = con.execute("SELECT COUNT(*) FROM fitness_product WHERE stock=0").fetchone()[0]
    low_stock    = con.execute("SELECT COUNT(*) FROM fitness_product WHERE stock>0 AND stock<=30").fetchone()[0]
    avg_protein  = con.execute("SELECT AVG(protein_g) FROM fitness_product").fetchone()[0] or 0
    pending      = con.execute("SELECT COUNT(*) FROM pms_form_feedback WHERE status='待處理'").fetchone()[0]
    delivering   = con.execute("SELECT COUNT(*) FROM pms_form_feedback WHERE status='配送中'").fetchone()[0]
    con.close()
    return total, out_of_stock, low_stock, round(avg_protein, 1), pending, delivering


def get_products(vendor=None, category=None, low_stock_only=False):
    con = _db()
    sql, params = "SELECT * FROM fitness_product WHERE 1=1", []
    if vendor:
        sql += " AND vendor=?"; params.append(vendor)
    if category:
        sql += " AND category=?"; params.append(category)
    if low_stock_only:
        sql += " AND stock <= 30"
    sql += " ORDER BY vendor, category, protein_g DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_stock(product_id, new_stock):
    con = _db()
    con.execute("UPDATE fitness_product SET stock=? WHERE id=?", (new_stock, product_id))
    con.commit()
    con.close()


def get_inquiries(status_filter=None, store_name=None, brand=None, is_gym=False):
    con = _db()
    conditions, params = [], []
    if status_filter and status_filter != "全部":
        conditions.append("status=?")
        params.append(status_filter)
    if is_gym:
        conditions.append("goal LIKE '課程報名：%'")
    elif store_name and store_name != "管理員":
        if brand and brand not in ("全部", "健身房"):
            # 顯示：已派給本門市 OR (待處理 AND (含本品牌商品 OR 商品無vendor欄位 OR 清單為空))
            conditions.append(
                "(vendor_reply LIKE ? OR "
                "(status='待處理' AND (products_json LIKE ? "
                "OR products_json NOT LIKE '%\"vendor\":%' "
                "OR products_json IS NULL OR products_json='' OR products_json='[]')))"
            )
            params.append(f"%{store_name}%")
            params.append(f'%"vendor": "{brand}"%')
        else:
            conditions.append("(status='待處理' OR vendor_reply LIKE ?)")
            params.append(f"%{store_name}%")
    sql = "SELECT * FROM pms_form_feedback"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def reject_inquiry(feedback_no, reason, store_name=""):
    prefix = f"[{store_name}] " if store_name else ""
    con = _db()
    con.execute(
        "UPDATE pms_form_feedback SET status='已拒絕', vendor_reply=? WHERE feedback_no=?",
        (f"{prefix}{reason}", feedback_no),
    )
    con.commit()
    con.close()


def reserve_inquiry(feedback_no, store_name, note=""):
    """標記諮詢單為「預留中」，商品已備妥等待顧客自取。"""
    con = _db()
    now_iso = datetime.now().isoformat()
    msg = f"[{store_name}] 商品已備妥，請攜帶此單號前來取件。"
    if note:
        msg += f" 備注：{note}"
    con.execute(
        "UPDATE pms_form_feedback SET status='預留中', accepted_at=?, vendor_reply=? WHERE feedback_no=?",
        (now_iso, msg, feedback_no),
    )
    con.commit()
    con.close()


def get_brand_stores(brand: str) -> list:
    """回傳該品牌所有門市名稱；admin（全部）回傳全品牌。"""
    con = _db()
    if brand == "全部":
        rows = con.execute(
            "SELECT store_name FROM vendor_users WHERE brand != '全部' ORDER BY brand, store_name"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT store_name FROM vendor_users WHERE brand=? ORDER BY store_name",
            (brand,)
        ).fetchall()
    con.close()
    return [r["store_name"] for r in rows]


def get_dispatches(feedback_no: str) -> list:
    """回傳此諮詢單的所有外送記錄（mms_order_record），支援多通路分批配送。"""
    con = _db()
    rows = con.execute(
        "SELECT * FROM mms_order_record WHERE feedback_no=? ORDER BY created_at",
        (feedback_no,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_active_deliveries():
    """取得所有待取件或配送中的外送單（status 01 或 02），含聯絡資訊與地址。"""
    con = _db()
    rows = con.execute("""
        SELECT m.*, f.contact_name, f.contact_phone, f.address,
               f.products_json, f.goal, f.contact_name as recipient
        FROM mms_order_record m
        JOIN pms_form_feedback f ON m.feedback_no = f.feedback_no
        WHERE m.status IN ('01', '02')
          AND (f.goal IS NULL OR f.goal NOT LIKE '課程報名：%')
        ORDER BY m.created_at DESC
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]


# ── Being Sport 課程管理 helpers ────────────────────────────────────────────

def get_gym_id_for_store(store_name: str) -> int:
    con = _db()
    row = con.execute(
        "SELECT id FROM partner_vendor WHERE name=? AND category='健身房' AND is_enable=1",
        (store_name,)
    ).fetchone()
    con.close()
    return row["id"] if row else 0


def get_being_sport_gyms() -> list:
    con = _db()
    rows = con.execute(
        "SELECT * FROM partner_vendor WHERE category='健身房' AND is_enable=1 ORDER BY name"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_gym_courses_for_dashboard(gym_id: int = 0, month: str = "", status_filter: str = "") -> list:
    con = _db()
    sql = """
        SELECT gc.*,
               pv.name AS gym_name, pv.address AS gym_address,
               (SELECT COUNT(*) FROM course_enrollment ce WHERE ce.course_id = gc.id) AS actual_enrolled
        FROM gym_course gc
        JOIN partner_vendor pv ON pv.id = gc.gym_id AND pv.is_enable = 1
        WHERE gc.is_enable = 1
    """
    params = []
    if gym_id:
        sql += " AND gc.gym_id = ?"
        params.append(gym_id)
    if month:
        sql += " AND gc.month = ?"
        params.append(month)
    if status_filter and status_filter != "全部":
        sql += " AND gc.status = ?"
        params.append(status_filter)
    sql += " ORDER BY gc.gym_id, gc.time_start"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_enrollments_for_course(course_id: int) -> list:
    con = _db()
    rows = con.execute(
        "SELECT * FROM course_enrollment WHERE course_id=? ORDER BY enrolled_at",
        (course_id,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def update_course_min_students(course_id: int, min_students: int):
    con = _db()
    con.execute("UPDATE gym_course SET min_students=? WHERE id=?", (min_students, course_id))
    con.commit(); con.close()


def update_course_max_slots(course_id: int, max_slots: int):
    con = _db()
    con.execute("UPDATE gym_course SET max_slots=? WHERE id=?", (max_slots, course_id))
    con.commit(); con.close()


def open_course_and_notify(course_id: int) -> int:
    """開課並通知所有已報名學員（更新 enrollment + feedback 狀態），回傳通知人數。"""
    con = _db()
    now_iso = datetime.now().isoformat()
    con.execute("UPDATE gym_course SET status='已開課' WHERE id=?", (course_id,))
    # 取所有未通知的 enrollment
    rows = con.execute(
        "SELECT * FROM course_enrollment WHERE course_id=? AND notified=0",
        (course_id,)
    ).fetchall()
    count = 0
    for row in rows:
        r = dict(row)
        con.execute(
            "UPDATE course_enrollment SET status='確認開課', notified=1 WHERE id=?",
            (r["id"],)
        )
        if r.get("feedback_no"):
            con.execute(
                "UPDATE pms_form_feedback SET vendor_reply=?, status='已完成' WHERE feedback_no=?",
                (f"🎉 恭喜！您報名的課程已確認開課！請依課程時間準時出席。（{now_iso[:16]}）",
                 r["feedback_no"]),
            )
        count += 1
    con.commit(); con.close()
    return count


def cancel_course(course_id: int):
    con = _db()
    now_iso = datetime.now().isoformat()
    con.execute("UPDATE gym_course SET status='已取消' WHERE id=?", (course_id,))
    rows = con.execute(
        "SELECT * FROM course_enrollment WHERE course_id=? AND status='報名中'",
        (course_id,)
    ).fetchall()
    for row in rows:
        r = dict(row)
        con.execute(
            "UPDATE course_enrollment SET status='已取消', notified=1 WHERE id=?",
            (r["id"],)
        )
        if r.get("feedback_no"):
            con.execute(
                "UPDATE pms_form_feedback SET vendor_reply=?, status='已拒絕' WHERE feedback_no=?",
                (f"⚠️ 很遺憾，您報名的課程因故取消，如需協助請聯繫門市。（{now_iso[:16]}）",
                 r["feedback_no"]),
            )
    con.commit(); con.close()


def add_gym_course(gym_id: int, course_name: str, coach: str, course_type: str,
                   weekday: str, time_start: str, duration_min: int,
                   max_slots: int, price_month: int, min_students: int, month: str):
    con = _db()
    con.execute(
        "INSERT INTO gym_course "
        "(gym_id,course_name,coach,course_type,weekday,time_start,duration_min,"
        " max_slots,enrolled,price_month,month,min_students,status,is_enable) "
        "VALUES (?,?,?,?,?,?,?,?,0,?,?,?,'招生中',1)",
        (gym_id, course_name, coach, course_type, weekday, time_start,
         duration_min, max_slots, price_month, month, min_students),
    )
    con.commit(); con.close()


def update_delivery_status(order_no: str, new_status: str, driver_name: str = ""):
    """更新外送單狀態：01=待取件 → 02=配送中 → 03=已完成。
    當所有外送單都完成時，自動將 pms_form_feedback.status 更新為「已完成」。"""
    con = _db()
    if driver_name:
        con.execute(
            "UPDATE mms_order_record SET status=?, driver_name=? WHERE order_no=?",
            (new_status, driver_name, order_no),
        )
    else:
        con.execute("UPDATE mms_order_record SET status=? WHERE order_no=?", (new_status, order_no))
    # Auto-complete parent feedback if all records done
    if new_status == '03':
        row = con.execute("SELECT feedback_no FROM mms_order_record WHERE order_no=?", (order_no,)).fetchone()
        if row:
            fno = row["feedback_no"]
            pending = con.execute(
                "SELECT COUNT(*) FROM mms_order_record WHERE feedback_no=? AND status != '03'",
                (fno,)
            ).fetchone()[0]
            if pending == 0:
                con.execute(
                    "UPDATE pms_form_feedback SET status='已完成' WHERE feedback_no=?",
                    (fno,)
                )
    con.commit()
    con.close()


# ── Vendor 帳號管理 ─────────────────────────────────────────────────────────

def _ensure_vendor_users():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS vendor_users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL UNIQUE,
            password    TEXT NOT NULL,
            store_name  TEXT NOT NULL,
            brand       TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    con.commit()
    for row in [
        ("7-11-A",      "vendor123", "7-11 A門市",             "7-11"),
        ("7-11-B",      "vendor123", "7-11 B門市",             "7-11"),
        ("wanjiafu",    "vendor123", "萬家福信義店",             "萬家福"),
        ("cosmed",      "vendor123", "康是美中山店",             "康是美"),
        ("beingsport",  "gym123",   "Being Sport 健身中心",    "健身房"),
        ("driver1",     "driver123", "外送員 小明",             "外送員"),
        ("driver2",     "driver123", "外送員 小華",             "外送員"),
        ("admin",       "admin123", "管理員",                  "全部"),
    ]:
        con.execute(
            "INSERT OR IGNORE INTO vendor_users "
            "(username,password,store_name,brand,created_at) VALUES (?,?,?,?,?)",
            (*row, datetime.now().isoformat()),
        )
    con.commit(); con.close()

_ensure_vendor_users()


def check_vendor_login(username: str, password: str):
    con = _db()
    row = con.execute(
        "SELECT * FROM vendor_users WHERE username=? AND password=?",
        (username, password),
    ).fetchone()
    con.close()
    return dict(row) if row else None
