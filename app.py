# -*- coding: utf-8 -*-
"""健身採買助手前端 — streamlit run app.py"""
import os
import json
import re
import sqlite3
import streamlit as st
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB):
    import seed as _seed
    _seed.main()

from mcp_server import search_grocery, recommend_high_protein, check_inventory

# ── DB helpers ────────────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB)
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

# ── Intent detection（本地關鍵字判斷，不走舊的 service_category）─────────────
def detect_intent(text: str) -> dict:
    budget_match = re.search(r"(\d+)\s*元", text)
    budget = int(budget_match.group(1)) if budget_match else 500
    keyword = re.sub(r"\d+\s*元", "", text).strip() or text

    if any(kw in text for kw in ["庫存", "還有嗎", "有沒有", "剩多少", "有貨嗎", "還有貨"]):
        return {"intent": "inventory", "keyword": keyword}
    if any(kw in text for kw in ["增肌", "長肌肉", "增重", "重訓", "肌力", "練肌"]):
        return {"intent": "recommend", "goal": "增肌", "budget": budget}
    if any(kw in text for kw in ["減脂", "減肥", "瘦身", "低熱量", "燃脂", "cut"]):
        return {"intent": "recommend", "goal": "減脂", "budget": budget}
    if any(kw in text for kw in ["健身", "運動", "高蛋白", "蛋白質", "補充", "肌肉", "鍛鍊", "體能", "採買", "買"]):
        return {"intent": "recommend", "goal": "增肌", "budget": budget}
    return {"intent": "search", "keyword": keyword}

# ── MCP 呼叫包裝（記錄每次工具呼叫）──────────────────────────────────────────
def call_mcp(tool_name: str, fn, **kwargs) -> dict:
    ts = datetime.now().strftime("%H:%M:%S")
    raw = fn(**kwargs)
    result = json.loads(raw)
    st.session_state.mcp_log.append(
        {"tool": tool_name, "params": kwargs, "result": result, "ts": ts}
    )
    return result

# ── 常數 ──────────────────────────────────────────────────────────────────────
VENDOR_COLOR = {
    "7-11":    "#00833D",
    "家樂福":  "#0064D2",
    "康是美":  "#E60012",
    "統一生機": "#7B5EA7",
}
CAT_ICON = {
    "蛋白質": "🥩", "主食": "🍚", "蔬果": "🥦",
    "乳製品": "🥛", "保健品": "💊", "即食": "🍱",
}
TOOL_META = {
    "search_grocery":        ("🔍", "商品關鍵字搜尋"),
    "recommend_high_protein": ("💪", "高蛋白目標推薦"),
    "check_inventory":       ("📦", "通路庫存查詢"),
}

# ── Page config & CSS ─────────────────────────────────────────────────────────
st.set_page_config(page_title="健身採買助手", page_icon="🏋️", layout="wide")
st.markdown("""
<style>
  .main .block-container { max-width: 720px; padding-top: 2rem; }
  .t-main { color: #1a1a2e; font-size: 2rem; font-weight: 900; margin-bottom: 0; }
  .t-sub  { color: #E60012; font-size: 0.9rem; margin-top: 2px; }
  .summary-box {
    background: #E8F5E9; border-left: 5px solid #00833D;
    border-radius: 8px; padding: 14px 18px; margin: 12px 0;
  }
  .product-card {
    background: #F8F9FA; border: 1px solid #E0E0E0;
    border-radius: 10px; padding: 14px 18px; margin: 8px 0;
  }
  .vendor-badge {
    display: inline-block; border-radius: 4px;
    padding: 2px 8px; color: white; font-size: 0.78rem; font-weight: 600;
  }
  .mcp-card {
    background: #1E1E2E; color: #CDD6F4;
    border-radius: 8px; padding: 10px 12px; margin-bottom: 10px;
    font-size: 0.82rem; font-family: monospace;
  }
  .mcp-tool { color: #89B4FA; font-weight: 700; font-size: 0.9rem; }
  .mcp-ts   { color: #6C7086; font-size: 0.75rem; float: right; }
  .mcp-label { color: #6C7086; font-size: 0.75rem; }
  .mcp-param { color: #A6E3A1; }
  .mcp-ret   { color: #F9E2AF; }
</style>
""", unsafe_allow_html=True)

# ── Session defaults ───────────────────────────────────────────────────────────
for k, v in {
    "stage": "login", "user_id": None, "username": "",
    "result": None, "intent": None, "mcp_log": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar：MCP 工具呼叫紀錄 ──────────────────────────────────────────────────
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
    st.caption("每次查詢即時顯示 AI 呼叫了哪個工具")
    st.divider()

    if not st.session_state.mcp_log:
        st.markdown(
            "<div style='color:#888;font-size:0.85rem;text-align:center;padding:20px 0'>"
            "尚未呼叫任何工具<br/>請在左側輸入需求</div>",
            unsafe_allow_html=True,
        )
    else:
        for entry in reversed(st.session_state.mcp_log):
            icon, label = TOOL_META.get(entry["tool"], ("🔧", entry["tool"]))
            params_str = "  ".join(f"{k}={v}" for k, v in entry["params"].items())
            msg = entry["result"].get("message", "")
            st.markdown(f"""
            <div class="mcp-card">
              <span class="mcp-tool">{icon} {entry['tool']}</span>
              <span class="mcp-ts">{entry['ts']}</span><br/>
              <span class="mcp-label">{label}</span>
              <br/><br/>
              <span class="mcp-param">▶ 輸入<br/>{params_str}</span>
              <br/><br/>
              <span class="mcp-ret">◀ 回傳<br/>{msg}</span>
            </div>
            """, unsafe_allow_html=True)
            with st.expander("完整 JSON"):
                st.json({"params": entry["params"], "result": entry["result"]})

        if st.button("清除紀錄", use_container_width=True):
            st.session_state.mcp_log = []
            st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown('<p class="t-main">🏋️ 健身採買助手</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="t-sub">統一集團 × AI ✦ 7-11・家樂福・康是美・統一生機</p>',
    unsafe_allow_html=True,
)
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.stage == "login":
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("### 👤 歡迎使用健身採買助手")
        st.markdown("登入以使用完整功能")
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
                    st.session_state.stage    = "input"
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
                    st.session_state.stage    = "input"
                    st.rerun()
                else:
                    st.error("此帳號已被使用，請換一個帳號。")

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: INPUT
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "input":
    st.markdown("#### 💬 請告訴我您的健身目標或想找的商品")
    st.caption(
        "試試看：`我最近想健身` ✦ `增肌預算500元` ✦ `幫我規劃減脂採買` ✦ "
        "`找雞胸肉` ✦ `乳清蛋白還有庫存嗎`"
    )

    user_text = st.text_area(
        "需求描述", placeholder="輸入您的需求...",
        height=90, label_visibility="collapsed", key="ui_text",
    )
    col_go, _ = st.columns([2, 5])
    go = col_go.button("開始搜尋 →", type="primary", use_container_width=True)

    if go:
        text = user_text.strip()
        if not text:
            st.warning("請輸入您的需求描述。")
        else:
            intent = detect_intent(text)
            with st.spinner("🤖 AI 分析中，呼叫 MCP 工具..."):
                if intent["intent"] == "inventory":
                    result = call_mcp("check_inventory", check_inventory,
                                     product_name=intent["keyword"])
                elif intent["intent"] == "recommend":
                    result = call_mcp("recommend_high_protein", recommend_high_protein,
                                     goal=intent["goal"], budget=intent["budget"])
                else:
                    result = call_mcp("search_grocery", search_grocery,
                                     keyword=intent["keyword"])
            result["_intent"] = intent["intent"]
            result["_intent_meta"] = intent
            st.session_state.result = result
            st.session_state.stage  = "result"
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: RESULT
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "result":
    result = st.session_state.result
    intent_type = result.get("_intent", "search")
    meta        = result.get("_intent_meta", {})

    if st.button("← 重新查詢"):
        st.session_state.stage  = "input"
        st.session_state.result = None
        st.rerun()

    # ── 結果標題 ────────────────────────────────────────────────────────────
    if intent_type == "recommend":
        goal   = meta.get("goal", "增肌")
        budget = meta.get("budget", 500)
        st.markdown(f"""
        <div class="summary-box">
          <strong>💪 {goal} 採買推薦</strong><br/>
          預算 <strong>{budget} 元</strong> ／
          推薦 <strong>{result.get('count', 0)} 項</strong> ／
          合計蛋白質 <strong>{result.get('total_protein_g', 0)} g</strong> ／
          花費 <strong>{result.get('total_price', 0)} 元</strong>
        </div>
        """, unsafe_allow_html=True)
        products = result.get("products", [])

    elif intent_type == "inventory":
        st.markdown(f"### 📦 庫存查詢")
        st.caption(result.get("message", ""))
        products = result.get("items", [])

    else:
        st.markdown(f"### 🔍 搜尋結果")
        st.caption(result.get("message", ""))
        products = result.get("products", [])

    # ── 商品清單 ────────────────────────────────────────────────────────────
    if not products:
        st.info("😔 " + result.get("message", "找不到符合的商品，請換個關鍵字試試。"))
    else:
        for p in products:
            vendor     = p.get("vendor", "")
            color      = VENDOR_COLOR.get(vendor, "#888")
            cat_icon   = CAT_ICON.get(p.get("category", ""), "📦")
            stock      = p.get("stock", 0)
            stock_str  = f"庫存 {stock}" if stock > 0 else "❌ 已售完"
            stock_color = "#E53935" if stock == 0 else ("#FF9800" if stock <= 30 else "#43A047")

            st.markdown(f"""
            <div class="product-card">
              <span class="vendor-badge" style="background:{color}">{vendor}</span>
              &nbsp;{cat_icon}&nbsp;
              <strong style="font-size:1.05rem">{p.get('name','')}</strong>
              <br/>
              <span style="color:#555;font-size:0.9rem">
                🥩 蛋白質 <strong>{p.get('protein_g', 0)}g</strong> &nbsp;&nbsp;
                🔥 熱量 <strong>{p.get('calories', 0)} kcal</strong> &nbsp;&nbsp;
                💰 <strong>${p.get('price', 0)}</strong> &nbsp;&nbsp;
                <span style="color:{stock_color}">📦 {stock_str}</span>
              </span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("")
    if st.button("← 返回首頁", type="primary"):
        st.session_state.stage  = "input"
        st.session_state.result = None
        st.rerun()
