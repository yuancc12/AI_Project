# -*- coding: utf-8 -*-
"""健身採買助手 — 登入 + 本地對話狀態機 + MCP Tools（確認後才呼叫）"""
import os
import json
import re
import sqlite3
import streamlit as st
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB_PATH):
    import seed as _seed
    _seed.main()

from mcp_server import search_grocery, recommend_high_protein, check_inventory

# ── DB / 帳號 helpers ─────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def check_login(username, password):
    con = _db()
    row = con.execute(
        "SELECT * FROM users WHERE username=? AND password=?", (username, password)
    ).fetchone()
    con.close()
    return dict(row) if row else None

def register_user(username, password):
    try:
        con = _db()
        con.execute(
            "INSERT INTO users (username,password,created_at) VALUES (?,?,?)",
            (username, password, datetime.now().isoformat()),
        )
        con.commit()
        con.close()
        return True
    except Exception:
        return False

# ── 本地意圖分類（不需要任何 API）────────────────────────────────────────────
def classify_intent(text: str) -> str:
    """回傳: 增肌 | 減脂 | 搜尋 | 庫存 | 不明"""
    if any(kw in text for kw in ["增肌", "長肌肉", "增重", "重訓", "練肌", "肌力"]):
        return "增肌"
    if any(kw in text for kw in ["減脂", "瘦身", "減肥", "燃脂", "低熱量", "切body"]):
        return "減脂"
    if any(kw in text for kw in ["庫存", "還有嗎", "有沒有", "剩多少", "有貨嗎", "還有貨"]):
        return "庫存"
    if any(kw in text for kw in ["找", "搜尋", "查", "哪裡買", "哪裡有"]):
        return "搜尋"
    if any(kw in text for kw in ["健身", "運動", "鍛鍊", "體能", "想買", "採買", "蛋白"]):
        return "不明"   # 需要再問一句釐清
    return "搜尋"

def extract_budget(text: str):
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None

# ── 本地對話狀態機 ────────────────────────────────────────────────────────────
# conv_state 狀態流：
#   ask_goal → ask_goal_detail（若不明）
#            → ask_budget（增肌/減脂）
#            → ask_keyword（搜尋/庫存）
#            → confirm（等使用者按按鈕）
#            → done（MCP 呼叫完成）

def process_input(text: str) -> str:
    """依目前 conv_state 更新狀態並回傳 bot 文字。"""
    state = st.session_state.conv_state

    # ── 1. 第一句話：判斷意圖 ────────────────────────────────────────────────
    if state == "ask_goal":
        intent = classify_intent(text)
        if intent == "不明":
            st.session_state.conv_state = "ask_goal_detail"
            return (
                "了解你有健身需求！請問你的主要目標是哪一種？\n\n"
                "- **增肌**（增加肌肉量、補充蛋白質）\n"
                "- **減脂**（降低體脂、控制熱量）\n"
                "- 或者你想**搜尋特定商品**也可以直接說 😊"
            )
        elif intent in ("增肌", "減脂"):
            st.session_state.conv_goal  = intent
            st.session_state.conv_state = "ask_budget"
            return f"**{intent}** 是個很棒的目標 💪\n\n請問你的採買預算大約是多少元呢？\n（直接輸入數字，例如 `500`）"
        elif intent == "庫存":
            st.session_state.conv_goal  = "庫存"
            st.session_state.conv_state = "ask_keyword"
            return "好的！請問你想查詢哪個商品的庫存狀況呢？\n（例如：雞胸肉、乳清蛋白）"
        else:
            st.session_state.conv_goal  = "搜尋"
            st.session_state.conv_state = "ask_keyword"
            return "好的！請問你想搜尋什麼商品或食材呢？\n（例如：雞胸肉、燕麥、豆漿）"

    # ── 2. 釐清增肌/減脂 ────────────────────────────────────────────────────
    elif state == "ask_goal_detail":
        t = text
        if any(kw in t for kw in ["增肌", "增重", "長肌", "肌肉", "增"]):
            intent = "增肌"
        elif any(kw in t for kw in ["減脂", "減肥", "瘦", "減"]):
            intent = "減脂"
        elif any(kw in t for kw in ["找", "搜尋", "查", "哪裡"]):
            st.session_state.conv_goal  = "搜尋"
            st.session_state.conv_state = "ask_keyword"
            return "好的，請問你想搜尋什麼商品呢？"
        else:
            return "請輸入「增肌」或「減脂」告訴我你的目標，或直接說你想找哪種商品 😊"
        st.session_state.conv_goal  = intent
        st.session_state.conv_state = "ask_budget"
        return f"**{intent}** 好！🔥\n\n請問你的採買預算大約是多少元呢？（例如 `500`）"

    # ── 3. 輸入預算 ─────────────────────────────────────────────────────────
    elif state == "ask_budget":
        budget = extract_budget(text)
        if not budget:
            return "😅 請輸入數字金額，例如「500」或「500元」"
        st.session_state.conv_budget = budget
        st.session_state.conv_state  = "confirm"
        goal = st.session_state.conv_goal
        return (
            "好的，幫你確認一下 👇\n\n"
            f"| 項目 | 內容 |\n|------|------|\n"
            f"| 目標 | **{goal}** |\n"
            f"| 預算 | **{budget} 元** |\n\n"
            "確認後按下方按鈕，我就呼叫 MCP 幫你找最適合的商品組合！"
        )

    # ── 4. 輸入關鍵字 ────────────────────────────────────────────────────────
    elif state == "ask_keyword":
        kw = text.strip()
        if not kw:
            return "請輸入想搜尋的商品名稱 😊"
        st.session_state.conv_keyword = kw
        st.session_state.conv_state   = "confirm"
        goal   = st.session_state.conv_goal
        action = "查詢庫存" if goal == "庫存" else "搜尋商品"
        return (
            "好的，幫你確認一下 👇\n\n"
            f"| 項目 | 內容 |\n|------|------|\n"
            f"| 操作 | **{action}** |\n"
            f"| 關鍵字 | **{kw}** |\n\n"
            "確認後按下方按鈕開始查詢！"
        )

    # ── 其他（confirm / done）─────────────────────────────────────────────────
    else:
        return "請點「✅ 確認查詢」按鈕，或點「🔄 重新開始」重新提問。"


def execute_mcp():
    """按下確認後才在這裡呼叫 MCP 工具（唯一的 MCP 呼叫點）。"""
    goal    = st.session_state.conv_goal
    budget  = st.session_state.get("conv_budget", 500)
    keyword = st.session_state.get("conv_keyword", "")
    ts      = datetime.now().strftime("%H:%M:%S")

    if goal in ("增肌", "減脂"):
        raw    = recommend_high_protein(goal=goal, budget=budget)
        result = json.loads(raw)
        log    = {"tool": "recommend_high_protein",
                  "params": {"goal": goal, "budget": budget},
                  "result": result, "ts": ts}
        text   = (
            f"✅ 查詢完成！\n\n"
            f"在 **{budget} 元**預算內，推薦 **{result.get('count', 0)}** 項{goal}商品，"
            f"合計蛋白質 **{result.get('total_protein_g', 0)} g**，"
            f"花費 **{result.get('total_price', 0)} 元**。"
        )
    elif goal == "庫存":
        raw    = check_inventory(product_name=keyword)
        result = json.loads(raw)
        log    = {"tool": "check_inventory",
                  "params": {"product_name": keyword},
                  "result": result, "ts": ts}
        text   = (
            f"✅ 查詢完成！\n\n"
            f"「{keyword}」共找到 **{result.get('found', 0)}** 筆，"
            f"其中 **{result.get('in_stock', 0)}** 筆有庫存。"
        )
    else:
        raw    = search_grocery(keyword=keyword)
        result = json.loads(raw)
        log    = {"tool": "search_grocery",
                  "params": {"keyword": keyword},
                  "result": result, "ts": ts}
        text   = f"✅ 搜尋完成！「{keyword}」共找到 **{result.get('count', 0)}** 筆商品。"

    return text, [log]


def reset_conv():
    st.session_state.conv_state   = "ask_goal"
    st.session_state.conv_goal    = ""
    st.session_state.conv_budget  = 0
    st.session_state.conv_keyword = ""


# ── 商品結果渲染（純原生元件，不用 unsafe_allow_html）────────────────────────
VENDOR_EMOJI = {"7-11": "🟢", "家樂福": "🔵", "康是美": "🔴", "統一生機": "🟣"}
TOOL_META    = {
    "search_grocery":         ("🔍", "商品關鍵字搜尋"),
    "recommend_high_protein": ("💪", "高蛋白目標推薦"),
    "check_inventory":        ("📦", "通路庫存查詢"),
}

def render_tool_results(tool_calls: list):
    for tc in tool_calls:
        tool   = tc["tool"]
        result = tc["result"]
        icon, label = TOOL_META.get(tool, ("🔧", tool))
        products    = result.get("products") or result.get("items", [])

        with st.expander(f"{icon} {label} — {result.get('message', '')}", expanded=True):
            if not products:
                st.info(result.get("message", "無結果"))
                continue

            if tool == "recommend_high_protein":
                c1, c2, c3 = st.columns(3)
                c1.metric("推薦商品數", f"{result.get('count', 0)} 項")
                c2.metric("合計蛋白質", f"{result.get('total_protein_g', 0)} g")
                c3.metric("花費",       f"${result.get('total_price', 0)}")
                st.divider()

            for p in products:
                vendor = p.get("vendor", "")
                stock  = p.get("stock", 0)
                emoji  = VENDOR_EMOJI.get(vendor, "⚪")
                status = f"庫存 {stock}" if stock > 0 else "❌ 售完"
                st.markdown(
                    f"**{emoji} {p.get('name', '')}** &nbsp;`{vendor}`  \n"
                    f"🥩 {p.get('protein_g', 0)} g蛋白質 ｜ "
                    f"🔥 {p.get('calories', 0)} kcal ｜ "
                    f"💰 **${p.get('price', 0)}** ｜ "
                    f"📦 {status}"
                )


# ═════════════════════════════════════════════════════════════════════════════
# Page config & session init
# ═════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="健身採買助手", page_icon="🏋️", layout="wide")

for k, v in {
    "stage":        "login",
    "user_id":      None,
    "username":     "",
    "display_msgs": [],
    "mcp_log":      [],
    "conv_state":   "ask_goal",
    "conv_goal":    "",
    "conv_budget":  0,
    "conv_keyword": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar：MCP 呼叫紀錄 ──────────────────────────────────────────────────────
with st.sidebar:
    if st.session_state.user_id:
        col_u, col_out = st.columns([3, 1])
        col_u.markdown(f"👤 **{st.session_state.username}**")
        if col_out.button("登出", key="logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        st.divider()

    st.markdown("## 🔌 MCP 工具呼叫紀錄")
    st.caption("使用者確認後才呼叫，紀錄顯示於此")
    st.divider()

    if not st.session_state.mcp_log:
        st.caption("尚未呼叫任何工具")
    else:
        for entry in reversed(st.session_state.mcp_log):
            icon, label = TOOL_META.get(entry["tool"], ("🔧", entry["tool"]))
            with st.container(border=True):
                st.caption(f"{icon} **{entry['tool']}** · `{entry['ts']}`")
                st.caption(label)
                params_str = "  ".join(f"{k}={v}" for k, v in entry["params"].items())
                st.code(params_str, language=None)
                with st.expander("完整 JSON"):
                    st.json({"params": entry["params"], "result": entry["result"]})
        st.divider()
        if st.button("清除紀錄", use_container_width=True):
            st.session_state.mcp_log = []
            st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("## 🏋️ 健身採買助手")
st.caption("統一集團 × AI ✦ 7-11・家樂福・康是美・統一生機")
st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: LOGIN
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.stage == "login":
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("### 👤 歡迎使用健身採買助手")
        st.markdown("登入後即可開始與 AI 對話採買 💪")
        st.markdown("")
        tab_login, tab_reg = st.tabs(["登入", "📝 新用戶註冊"])

        with tab_login:
            u = st.text_input("帳號", key="li_u", placeholder="請輸入帳號")
            p = st.text_input("密碼", type="password", key="li_p", placeholder="請輸入密碼")
            if st.button("登入", type="primary", use_container_width=True, key="btn_login"):
                user = check_login(u.strip(), p.strip())
                if user:
                    st.session_state.user_id  = user["id"]
                    st.session_state.username = user["username"]
                    st.session_state.stage    = "chat"
                    # 登入後的第一句歡迎語
                    st.session_state.display_msgs.append({
                        "role": "assistant",
                        "content": (
                            f"你好，**{user['username']}**！歡迎使用健身採買助手 💪\n\n"
                            "我可以幫你在 **7-11、家樂福、康是美、統一生機** 找到適合的健身食品與補給品。\n\n"
                            "請問你最近有什麼健身需求呢？"
                        ),
                        "tool_calls": [],
                    })
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤，請再試一次。")

        with tab_reg:
            ru = st.text_input("設定帳號", key="reg_u", placeholder="請輸入帳號")
            rp = st.text_input("設定密碼", type="password", key="reg_p", placeholder="至少 4 個字元")
            if st.button("註冊並登入", type="primary", use_container_width=True, key="btn_reg"):
                if len(ru.strip()) < 2:
                    st.error("帳號至少 2 個字元。")
                elif len(rp.strip()) < 4:
                    st.error("密碼至少 4 個字元。")
                elif register_user(ru.strip(), rp.strip()):
                    user = check_login(ru.strip(), rp.strip())
                    st.session_state.user_id  = user["id"]
                    st.session_state.username = user["username"]
                    st.session_state.stage    = "chat"
                    st.session_state.display_msgs.append({
                        "role": "assistant",
                        "content": (
                            f"歡迎加入，**{user['username']}**！🎉\n\n"
                            "我是健身採買助手，請問你的健身目標是什麼呢？\n"
                            "（例如：增肌、減脂、或直接告訴我你想找的商品）"
                        ),
                        "tool_calls": [],
                    })
                    st.rerun()
                else:
                    st.error("此帳號已被使用，請換一個帳號。")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: CHAT（登入後的主畫面）
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "chat":
    col_info, col_reset = st.columns([5, 1])
    col_info.caption(f"👤 {st.session_state.username} 的對話")
    if col_reset.button("🗑️ 清空"):
        st.session_state.display_msgs = []
        reset_conv()
        st.session_state.display_msgs.append({
            "role": "assistant",
            "content": "對話已清空，請問你有什麼健身需求呢？",
            "tool_calls": [],
        })
        st.rerun()

    # ── 1. 渲染歷史訊息 ────────────────────────────────────────────────────
    for msg in st.session_state.display_msgs:
        avatar = "👤" if msg["role"] == "user" else "🏋️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                render_tool_results(msg["tool_calls"])

    # ── 2. 確認按鈕（state == confirm 時顯示，讓使用者決定是否呼叫 MCP）──
    if st.session_state.conv_state == "confirm":
        st.markdown("")
        c1, c2 = st.columns(2)
        if c1.button("✅ 確認查詢", type="primary", use_container_width=True):
            # ↓ 唯一呼叫 MCP 的地方
            text, tool_calls = execute_mcp()
            st.session_state.display_msgs.append({
                "role": "assistant", "content": text, "tool_calls": tool_calls,
            })
            st.session_state.mcp_log.extend(tool_calls)
            st.session_state.conv_state = "done"
            st.rerun()
        if c2.button("🔄 重新開始", use_container_width=True):
            reset_conv()
            st.session_state.display_msgs.append({
                "role": "assistant",
                "content": "好的，重新來過 😊 請問你有什麼健身需求呢？",
                "tool_calls": [],
            })
            st.rerun()

    # ── 3. 查詢完成後的「再查一次」按鈕 ───────────────────────────────────
    elif st.session_state.conv_state == "done":
        st.markdown("")
        if st.button("🔍 再查詢一次", type="primary"):
            reset_conv()
            st.session_state.display_msgs.append({
                "role": "assistant",
                "content": "沒問題！請問還有什麼健身採買需求呢？",
                "tool_calls": [],
            })
            st.rerun()

    # ── 4. Chat input（confirm 和 done 狀態不接受文字輸入）────────────────
    else:
        if prompt := st.chat_input("輸入您的需求或回覆..."):
            # 加入用戶訊息
            st.session_state.display_msgs.append({
                "role": "user", "content": prompt, "tool_calls": [],
            })
            # 本地狀態機產生 bot 回覆（不呼叫任何 API）
            bot_reply = process_input(prompt)
            st.session_state.display_msgs.append({
                "role": "assistant", "content": bot_reply, "tool_calls": [],
            })
            st.rerun()
