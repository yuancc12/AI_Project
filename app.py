# -*- coding: utf-8 -*-
"""健身採買助手 — Streamlit + Claude API + MCP Tools"""
import os
import json
import streamlit as st
import anthropic
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB_PATH):
    import seed as _seed
    _seed.main()

from mcp_server import search_grocery, recommend_high_protein, check_inventory

# ── Claude 工具定義（供 API 用）──────────────────────────────────────────────
CLAUDE_TOOLS = [
    {
        "name": "search_grocery",
        "description": (
            "在統一集團各業務（7-11、家樂福、康是美、統一生機）搜尋健身商品。"
            "當用戶詢問特定商品在哪裡可以買、或想瀏覽某類商品時使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜尋關鍵字，如：雞胸肉、乳清蛋白、豆漿"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "recommend_high_protein",
        "description": (
            "根據健身目標（增肌或減脂）與採買預算，推薦最佳高蛋白商品組合。"
            "只有在用戶明確說出目標 AND 確認預算金額後才呼叫此工具；"
            "若預算未知，請先詢問用戶。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal":   {"type": "string",  "description": "健身目標：增肌 或 減脂"},
                "budget": {"type": "integer", "description": "採買預算（台幣整數），如：500"},
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
                "product_name": {"type": "string", "description": "商品名稱或關鍵字，如：雞胸肉、乳清蛋白"},
            },
            "required": ["product_name"],
        },
    },
]

TOOL_FNS = {
    "search_grocery":         search_grocery,
    "recommend_high_protein": recommend_high_protein,
    "check_inventory":        check_inventory,
}

SYSTEM_PROMPT = """\
你是「健身採買助手」，協助用戶在統一集團旗下各業務採買適合健身的食品與補給品。

## 可用通路
- 7-11：即食舒肥雞胸、水煮蛋、鮪魚罐頭、無糖豆漿等輕食
- 家樂福：生鮮雞胸肉、鮭魚、牛腱、希臘優格等生鮮乳製品
- 康是美：乳清蛋白粉、BCAA、膠原蛋白等保健補充劑
- 統一生機：燕麥片、黑豆漿、綜合堅果等天然穀物

## 對話規則（重要）
1. 每次只問一個問題，循序了解需求
2. 若用戶提到增肌或減脂但未說明預算，一定要先問預算再呼叫工具
3. 確認目標和預算後，才呼叫 recommend_high_protein
4. 繁體中文回答，語氣親切自然，適當使用 emoji
5. 工具回傳結果後，用自然語言整理重點，不要直接輸出 JSON\
"""

VENDOR_EMOJI = {"7-11": "🟢", "家樂福": "🔵", "康是美": "🔴", "統一生機": "🟣"}
TOOL_META    = {
    "search_grocery":         ("🔍", "商品關鍵字搜尋"),
    "recommend_high_protein": ("💪", "高蛋白目標推薦"),
    "check_inventory":        ("📦", "通路庫存查詢"),
}


# ── Claude 呼叫（含 tool use 循環）──────────────────────────────────────────
def _content_to_dict(content) -> list:
    """把 SDK ContentBlock 物件轉成可序列化的 dict，存入 session_state。"""
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id,
                        "name": b.name, "input": b.input})
    return out


def chat_with_claude(claude_msgs: list, api_key: str):
    """
    執行 Claude 對話 + tool use 循環。
    回傳 (final_text: str, tool_log: list, updated_claude_msgs: list)。
    """
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

        # ── 有 tool_use：把 assistant 回應存進 msgs ──────────────────────────
        msgs.append({"role": "assistant",
                     "content": _content_to_dict(resp.content)})

        # 執行每個工具，收集結果
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
        # 繼續循環，讓 Claude 整理工具結果後給出最終回覆


# ── 商品結果渲染（純原生 Streamlit 元件，避免 unsafe_allow_html 引發 DOM 錯誤）
def render_tool_results(tool_calls: list):
    for tc in tool_calls:
        tool   = tc["tool"]
        result = tc["result"]
        icon, label = TOOL_META.get(tool, ("🔧", tool))

        with st.expander(f"{icon} {label} — {result.get('message', '')}", expanded=True):
            products = result.get("products") or result.get("items", [])
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


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="健身採買助手", page_icon="🏋️", layout="wide")

# ── Session 初始化 ─────────────────────────────────────────────────────────────
for k, v in {
    "display_msgs": [],   # 顯示用
    "claude_msgs":  [],   # 送給 Claude API 用
    "mcp_log":      [],
    "api_key":      os.environ.get("ANTHROPIC_API_KEY", ""),
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 設定")

    if not st.session_state.api_key:
        entered = st.text_input("Anthropic API Key", type="password",
                                placeholder="sk-ant-api03-...")
        if entered.strip():
            st.session_state.api_key = entered.strip()
            st.rerun()
    else:
        st.success("✅ API Key 已設定")
        if st.button("清除 Key"):
            st.session_state.api_key = ""
            st.rerun()

    st.divider()
    st.markdown("## 🔌 MCP 工具呼叫紀錄")
    st.caption("Claude 每次決定呼叫工具都顯示在此")
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
col_title, col_reset = st.columns([5, 1])
col_title.markdown("## 🏋️ 健身採買助手")
col_title.caption("統一集團 × Claude AI ✦ 7-11・家樂福・康是美・統一生機")

if col_reset.button("🗑️ 清空對話"):
    st.session_state.display_msgs = []
    st.session_state.claude_msgs  = []
    st.session_state.mcp_log      = []
    st.rerun()

st.divider()

# 未設 API Key 時擋住
if not st.session_state.api_key:
    st.warning("⚠️ 請先在左側側欄輸入 Anthropic API Key 才能開始對話。")
    st.stop()

# ── 1. 顯示歷史訊息 ────────────────────────────────────────────────────────────
for msg in st.session_state.display_msgs:
    avatar = "👤" if msg["role"] == "user" else "🏋️"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if msg.get("tool_calls"):
            render_tool_results(msg["tool_calls"])

# ── 2. 無歷史時顯示歡迎語（不存入 session，避免重複渲染）────────────────────
if not st.session_state.display_msgs:
    with st.chat_message("assistant", avatar="🏋️"):
        st.markdown(
            "你好！我是健身採買助手 💪\n\n"
            "我可以幫你在 **7-11、家樂福、康是美、統一生機** 找到適合健身的食品與補給品。\n\n"
            "請問你最近的健身目標是什麼呢？或是有想找的特定商品嗎？"
        )

# ── 3. 接收新輸入 ──────────────────────────────────────────────────────────────
if prompt := st.chat_input("輸入您的健身需求或問題..."):
    # 顯示用戶訊息
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    # 更新 claude_msgs（只供 API 用）
    st.session_state.claude_msgs.append({"role": "user", "content": prompt})

    # 呼叫 Claude（含 tool use 循環）
    with st.chat_message("assistant", avatar="🏋️"):
        with st.spinner("🤔 思考中..."):
            try:
                final_text, tool_calls, updated_msgs = chat_with_claude(
                    st.session_state.claude_msgs,
                    st.session_state.api_key,
                )
                st.session_state.claude_msgs = updated_msgs
            except anthropic.AuthenticationError:
                st.error("❌ API Key 無效，請重新設定。")
                st.stop()
            except Exception as exc:
                st.error(f"❌ 發生錯誤：{exc}")
                st.stop()

        st.markdown(final_text)
        if tool_calls:
            render_tool_results(tool_calls)

    # 存入 display_msgs（供下次渲染用）
    st.session_state.display_msgs.append({"role": "user", "content": prompt})
    st.session_state.display_msgs.append({
        "role":       "assistant",
        "content":    final_text,
        "tool_calls": tool_calls,
    })
    st.session_state.mcp_log.extend(tool_calls)
