# -*- coding: utf-8 -*-
"""健身採買助手 — 登入 + Claude API + MCP Tools（含寫入確認）"""
import os
import json
import sqlite3
import streamlit as st
import anthropic
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB_PATH):
    import seed as _seed
    _seed.main()

from mcp_server import (
    search_grocery, recommend_high_protein,
    check_inventory, submit_inquiry,
)

# ── DB / 帳號 helpers ─────────────────────────────────────────────────────────
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

def register_user(username, password):
    try:
        con = _db()
        con.execute(
            "INSERT INTO users (username,password,created_at) VALUES (?,?,?)",
            (username, password, datetime.now().isoformat()),
        )
        con.commit(); con.close(); return True
    except Exception:
        return False

# ── Claude 工具定義 ───────────────────────────────────────────────────────────
CLAUDE_TOOLS = [
    {
        "name": "search_grocery",
        "description": (
            "在統一集團各業務（7-11、家樂福、康是美、統一生機）搜尋健身商品。"
            "當用戶詢問特定商品在哪裡可以買到，或想瀏覽某類商品時使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜尋關鍵字，如：雞胸肉、乳清蛋白"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "recommend_high_protein",
        "description": (
            "根據健身目標（增肌或減脂）與採買預算，推薦高蛋白商品組合。"
            "只有在確認用戶的目標（增肌/減脂）AND 預算金額後才呼叫；"
            "若預算不明，必須先詢問。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal":   {"type": "string",  "description": "健身目標：增肌 或 減脂"},
                "budget": {"type": "integer", "description": "採買預算（台幣），如：500"},
            },
            "required": ["goal", "budget"],
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
            "【寫入工具】建立健身採買諮詢單，將用戶需求記錄到後台。"
            "這是寫入操作，必須嚴格遵守：\n"
            "1. 展示完商品後，主動詢問用戶是否需要建立諮詢單\n"
            "2. 用戶明確同意後，收集聯絡姓名和電話\n"
            "3. 收集完後再次告知「即將建立諮詢單」並確認\n"
            "4. 獲得最終確認後才呼叫此工具\n"
            "嚴禁在用戶未同意的情況下呼叫。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal":          {"type": "string",  "description": "健身目標"},
                "contact_name":  {"type": "string",  "description": "聯絡人姓名"},
                "contact_phone": {"type": "string",  "description": "聯絡電話"},
                "budget":        {"type": "integer", "description": "採買預算（選填）"},
                "keyword":       {"type": "string",  "description": "搜尋關鍵字（選填）"},
                "note":          {"type": "string",  "description": "備註（選填）"},
            },
            "required": ["goal", "contact_name", "contact_phone"],
        },
    },
]

TOOL_FNS = {
    "search_grocery":         search_grocery,
    "recommend_high_protein": recommend_high_protein,
    "check_inventory":        check_inventory,
    "submit_inquiry":         submit_inquiry,
}

SYSTEM_PROMPT = """\
你是「健身採買助手」，協助用戶在統一集團旗下各業務採買適合健身的食品與補給品。

## 可用通路
- 7-11：即食舒肥雞胸、水煮蛋、鮪魚罐頭、無糖豆漿等輕食
- 家樂福：生鮮雞胸肉、鮭魚、牛腱、希臘優格等生鮮
- 康是美：乳清蛋白粉、BCAA、保健補充劑
- 統一生機：燕麥片、黑豆漿、綜合堅果等天然穀物

## 對話規則
1. 一次只問一個問題，循序了解需求
2. 用戶提到增肌/減脂但沒說預算，先問預算再呼叫工具
3. 確認目標和預算後，才呼叫 recommend_high_protein
4. 工具結果用自然語言整理，不要直接貼 JSON

## 何時詢問是否建立諮詢單
- 展示完商品推薦後，根據情況（用戶表示有興趣、想進一步了解、需要安排採購）
  主動詢問：「需要幫您建立採買諮詢單嗎？後台人員可以幫您確認庫存和安排採購。」
- 不要每次都問，只在用戶明顯有後續需求時才問

## 建立諮詢單的流程（嚴格遵守）
1. 用戶同意建立後，詢問聯絡姓名和電話
2. 收集完後告知「即將為您建立諮詢單，確認嗎？」
3. 用戶再次確認後，才呼叫 submit_inquiry
4. 未獲明確同意，絕對不能呼叫 submit_inquiry

## 語言
繁體中文，語氣親切自然，適當使用 emoji\
"""

# ── Claude API 呼叫（含 tool_use 循環）───────────────────────────────────────
def _content_to_dict(content) -> list:
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id,
                        "name": b.name, "input": b.input})
    return out


def chat_with_claude(claude_msgs: list, api_key: str):
    """執行完整的 Claude + tool_use 循環。
    回傳 (final_text, tool_log, updated_claude_msgs)。"""
    client = anthropic.Anthropic(api_key=api_key)
    msgs   = list(claude_msgs)
    log    = []

    while True:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=CLAUDE_TOOLS,
            messages=msgs,
        )

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            msgs.append({"role": "assistant",
                         "content": _content_to_dict(resp.content)})
            return text, log, msgs

        # ── tool_use：先把 assistant 回應存進 msgs ────────────────────────────
        msgs.append({"role": "assistant",
                     "content": _content_to_dict(resp.content)})

        tool_results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            result_str  = TOOL_FNS[b.name](**b.input)
            result_dict = json.loads(result_str)
            log.append({
                "tool":   b.name,
                "params": b.input,
                "result": result_dict,
                "ts":     datetime.now().strftime("%H:%M:%S"),
            })
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": b.id,
                "content":     result_str,
            })

        msgs.append({"role": "user", "content": tool_results})
        # 繼續循環，讓 Claude 整理工具結果後給出下一段回覆


# ── 商品 / 諮詢單結果渲染（全用原生元件，不用 unsafe_allow_html）────────────
VENDOR_EMOJI = {"7-11": "🟢", "家樂福": "🔵", "康是美": "🔴", "統一生機": "🟣"}
TOOL_META    = {
    "search_grocery":         ("🔍", "商品關鍵字搜尋"),
    "recommend_high_protein": ("💪", "高蛋白目標推薦"),
    "check_inventory":        ("📦", "通路庫存查詢"),
    "submit_inquiry":         ("📋", "建立採買諮詢單"),
}


def render_tool_results(tool_calls: list):
    for tc in tool_calls:
        tool   = tc["tool"]
        result = tc["result"]
        icon, label = TOOL_META.get(tool, ("🔧", tool))

        # 寫入工具：諮詢單建立成功特別顯示
        if tool == "submit_inquiry":
            if result.get("success"):
                st.success(
                    f"📋 **諮詢單已建立！**\n\n"
                    f"單號：`{result.get('inquiry_no', '')}`\n\n"
                    f"{result.get('message', '')}"
                )
            else:
                st.error("諮詢單建立失敗，請稍後再試。")
            continue

        # 讀取工具：商品列表
        products = result.get("products") or result.get("items", [])
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
    "claude_msgs":  [],
    "mcp_log":      [],
    "api_key":      os.environ.get("ANTHROPIC_API_KEY", ""),
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    if st.session_state.user_id:
        col_u, col_out = st.columns([3, 1])
        col_u.markdown(f"👤 **{st.session_state.username}**")
        if col_out.button("登出", key="logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        st.divider()

    # API Key 設定
    st.markdown("## ⚙️ 設定")
    if not st.session_state.api_key:
        entered = st.text_input(
            "Anthropic API Key", type="password", placeholder="sk-ant-api03-..."
        )
        if entered.strip():
            st.session_state.api_key = entered.strip()
            st.rerun()
    else:
        st.success("✅ API Key 已設定")
        if st.button("清除 Key"):
            st.session_state.api_key = ""
            st.rerun()

    st.divider()

    # MCP 工具呼叫紀錄
    st.markdown("## 🔌 MCP 工具呼叫紀錄")
    st.caption("Claude 決定呼叫工具時即時顯示；寫入工具需用戶確認後才會出現")
    st.divider()

    if not st.session_state.mcp_log:
        st.caption("尚未呼叫任何工具")
    else:
        for entry in reversed(st.session_state.mcp_log):
            icon, label = TOOL_META.get(entry["tool"], ("🔧", entry["tool"]))
            is_write = entry["tool"] == "submit_inquiry"
            with st.container(border=True):
                badge = " 🔴寫入" if is_write else " 🟢讀取"
                st.caption(f"{icon} **{entry['tool']}**{badge} · `{entry['ts']}`")
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
st.caption("統一集團 × Claude AI ✦ 7-11・家樂福・康是美・統一生機")
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
                    st.session_state.claude_msgs.append({
                        "role": "user",
                        "content": f"（用戶 {user['username']} 已登入，請先問好並詢問他的健身需求）",
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
                    st.session_state.claude_msgs.append({
                        "role": "user",
                        "content": f"（新用戶 {user['username']} 剛完成註冊，請歡迎他並詢問健身需求）",
                    })
                    st.rerun()
                else:
                    st.error("此帳號已被使用，請換一個帳號。")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: CHAT
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "chat":

    # API Key 未設定時攔截
    if not st.session_state.api_key:
        st.warning("⚠️ 請先在左側側欄輸入 Anthropic API Key 才能開始對話。")
        st.stop()

    col_info, col_reset = st.columns([5, 1])
    col_info.caption(f"👤 {st.session_state.username} 的對話")
    if col_reset.button("🗑️ 清空對話"):
        st.session_state.display_msgs = []
        st.session_state.claude_msgs  = []
        st.session_state.mcp_log      = []
        st.rerun()

    # ── 1. 登入後的第一次自動問好 ─────────────────────────────────────────
    if not st.session_state.display_msgs and st.session_state.claude_msgs:
        with st.chat_message("assistant", avatar="🏋️"):
            with st.spinner("🤔 思考中..."):
                try:
                    text, tool_calls, updated = chat_with_claude(
                        st.session_state.claude_msgs,
                        st.session_state.api_key,
                    )
                    st.session_state.claude_msgs = updated
                except anthropic.AuthenticationError:
                    st.error("❌ API Key 無效，請重新設定。")
                    st.stop()
            st.markdown(text)
        st.session_state.display_msgs.append({
            "role": "assistant", "content": text, "tool_calls": [],
        })
        st.rerun()

    # ── 2. 顯示歷史訊息 ───────────────────────────────────────────────────
    for msg in st.session_state.display_msgs:
        avatar = "👤" if msg["role"] == "user" else "🏋️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                render_tool_results(msg["tool_calls"])

    # ── 3. 接收新輸入 ─────────────────────────────────────────────────────
    if prompt := st.chat_input("輸入您的需求或回覆..."):
        # 顯示用戶訊息
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        # 更新 Claude 訊息列表
        st.session_state.claude_msgs.append({"role": "user", "content": prompt})

        # 呼叫 Claude（AI 決定要不要呼叫 MCP 工具）
        with st.chat_message("assistant", avatar="🏋️"):
            with st.spinner("🤔 思考中..."):
                try:
                    text, tool_calls, updated = chat_with_claude(
                        st.session_state.claude_msgs,
                        st.session_state.api_key,
                    )
                    st.session_state.claude_msgs = updated
                except anthropic.AuthenticationError:
                    st.error("❌ API Key 無效，請重新設定。")
                    st.stop()
                except Exception as exc:
                    st.error(f"❌ 發生錯誤：{exc}")
                    st.stop()

            st.markdown(text)
            if tool_calls:
                render_tool_results(tool_calls)

        # 存入 display_msgs 供下次渲染
        st.session_state.display_msgs.append({"role": "user", "content": prompt, "tool_calls": []})
        st.session_state.display_msgs.append({
            "role": "assistant", "content": text, "tool_calls": tool_calls,
        })
        st.session_state.mcp_log.extend(tool_calls)
