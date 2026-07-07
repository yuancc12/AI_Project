# -*- coding: utf-8 -*-
"""7-ELEVEN AI 生活管家前端 — streamlit run app.py"""

import os, json, sqlite3
import streamlit as st
from datetime import date, datetime

# ── 0. Auto-seed ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(_HERE, "butler.db")
if not os.path.exists(DB):
    import seed as _seed
    _seed.main()

from mcp_server import get_service_form, submit_form_feedback, match_vendors

# ── 1. DB helpers ─────────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def _ensure_msg_table():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS feedback_message (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_no TEXT NOT NULL,
            sender      TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()

_ensure_msg_table()

STATUS_ICONS = {"01": "🔴", "02": "🟡", "03": "🔵", "80": "🟢"}


def _migrate_db():
    con = _db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    try:
        con.execute("ALTER TABLE pms_form_feedback ADD COLUMN user_id INTEGER")
    except Exception:
        pass
    con.commit()
    con.close()

_migrate_db()


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
            (username, password, datetime.now().isoformat())
        )
        con.commit()
        con.close()
        return True
    except Exception:
        return False


def get_user_feedbacks(user_id):
    con = _db()
    rows = con.execute("""
        SELECT f.*, c.name as category_name
        FROM pms_form_feedback f
        LEFT JOIN service_category c ON f.category_id = c.id
        WHERE f.user_id = ?
        ORDER BY f.cre_time DESC
    """, (user_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_messages(feedback_no):
    con = _db()
    rows = con.execute(
        "SELECT * FROM feedback_message WHERE feedback_no=? ORDER BY id",
        (feedback_no,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def add_consumer_message(feedback_no, content):
    con = _db()
    con.execute(
        "INSERT INTO feedback_message (feedback_no,sender,content,created_at) VALUES (?,?,?,?)",
        (feedback_no, "consumer", content, datetime.now().isoformat())
    )
    con.commit()
    con.close()

def get_feedback_info(feedback_no):
    con = _db()
    row = con.execute(
        "SELECT f.*, c.name as category_name FROM pms_form_feedback f "
        "LEFT JOIN service_category c ON f.category_id=c.id WHERE f.feedback_no=?",
        (feedback_no,)
    ).fetchone()
    con.close()
    return dict(row) if row else None

@st.cache_data
def load_counties():
    con = _db()
    rows = con.execute("SELECT code, name FROM sys_county ORDER BY code").fetchall()
    con.close()
    return [(r["code"], r["name"]) for r in rows]

@st.cache_data
def load_districts(county_code: str):
    con = _db()
    rows = con.execute(
        "SELECT code, name FROM sys_district WHERE county_code=? ORDER BY code",
        (county_code,)
    ).fetchall()
    con.close()
    return [(r["code"], r["name"]) for r in rows]

# ── 2. MCP 呼叫包裝（記錄每一次工具呼叫） ─────────────────────────────────────
def call_mcp(tool_name: str, fn, **kwargs) -> dict:
    ts  = datetime.now().strftime("%H:%M:%S")
    raw = fn(**kwargs)
    result = json.loads(raw)
    st.session_state.mcp_log.append({
        "tool":   tool_name,
        "params": kwargs,
        "result": result,
        "ts":     ts,
    })
    return result

# ── 3. Page config & CSS ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="7-ELEVEN 生活管家",
    page_icon="🏪",
    layout="wide",
)

st.markdown("""
<style>
  .main .block-container { max-width: 700px; padding-top: 2rem; }
  .t-main { color: #00833D; font-size: 2.1rem; font-weight: 900; margin-bottom: 0; }
  .t-sub  { color: #F37021; font-size: 0.9rem; margin-top: 2px; }
  .success-box {
    background: #E8F5E9; border-left: 5px solid #00833D;
    border-radius: 8px; padding: 14px 18px; margin: 12px 0;
  }
  .vendor-card {
    background: #FFF8F0; border: 1px solid #FFCCBC;
    border-radius: 8px; padding: 12px 16px; margin: 8px 0;
  }
  /* Sidebar MCP log cards */
  .mcp-card {
    background: #1E1E2E; color: #CDD6F4;
    border-radius: 8px; padding: 10px 12px; margin-bottom: 10px;
    font-size: 0.82rem; font-family: monospace;
  }
  .mcp-tool  { color: #89B4FA; font-weight: 700; font-size: 0.9rem; }
  .mcp-ts    { color: #6C7086; font-size: 0.75rem; float: right; }
  .mcp-param { color: #A6E3A1; }
  .mcp-ret   { color: #F9E2AF; }
  .badge-ai  { background:#6C7086; color:#CDD6F4; border-radius:4px; padding:1px 6px; font-size:0.7rem; }
  .badge-mcp { background:#313244; color:#89B4FA; border-radius:4px; padding:1px 6px; font-size:0.7rem; }
</style>
""", unsafe_allow_html=True)

# ── 4. Session defaults ───────────────────────────────────────────────────────
for k, v in {
    "stage": "login",
    "user_id": None,
    "username": "",
    "form_data": None,
    "user_input": "",
    "form_errors": [],
    "feedback_no": "",
    "vendors": [],
    "mcp_log": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── 5. 右側欄：MCP 工具呼叫紀錄 ───────────────────────────────────────────────
TOOL_META = {
    "get_service_form":    ("🤖", "AI 意圖分析 + 取表單"),
    "submit_form_feedback":("📋", "建立諮詢單"),
    "match_vendors":       ("🏢", "媒合廠商"),
}

def _param_summary(tool: str, params: dict) -> str:
    if tool == "get_service_form":
        return f"user_request = \"{params.get('user_request','')}\""
    if tool == "submit_form_feedback":
        return (f"form_id={params.get('form_id')}  "
                f"contact={params.get('contact_name')}  "
                f"mobile={params.get('contact_mobile')}")
    if tool == "match_vendors":
        return (f"category_id={params.get('category_id')}  "
                f"county={params.get('county_code')}  "
                f"district={params.get('district_code')}")
    return str(params)

def _result_summary(tool: str, result: dict) -> str:
    if tool == "get_service_form":
        if result.get("matched"):
            n = len(result.get("topics", []))
            return f"✅ 分類：{result.get('category')}｜表單：{result.get('form_name')}｜{n} 題"
        return f"❌ {result.get('message','無法判斷')}"
    if tool == "submit_form_feedback":
        if result.get("success"):
            return f"✅ 諮詢單：{result.get('feedback_no')}"
        return "❌ 建立失敗"
    if tool == "match_vendors":
        n = result.get("count", 0)
        names = "、".join(v["name"] for v in result.get("vendors", [])[:3])
        return f"✅ 媒合到 {n} 家｜{names}"
    return str(result)

with st.sidebar:
    # ── 使用者資訊 + 歷史記錄 ──────────────────────────────────────────────
    if st.session_state.user_id:
        col_u, col_out = st.columns([3, 1])
        col_u.markdown(f"👤 **{st.session_state.username}**")
        if col_out.button("登出", key="logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("## 📋 我的歷史諮詢單")
        history = get_user_feedbacks(st.session_state.user_id)
        if not history:
            st.caption("尚無諮詢紀錄")
        for fb in history:
            icon = STATUS_ICONS.get(fb["status"], "⚪")
            date_str = fb["cre_time"][:10] if fb["cre_time"] else ""
            label = f"{icon} {fb['category_name']}\n{fb['feedback_no'][-8:]}  {date_str}"
            is_current = fb["feedback_no"] == st.session_state.feedback_no
            if st.button(label, key=f"hist_{fb['feedback_no']}",
                         use_container_width=True,
                         type="primary" if is_current else "secondary"):
                st.session_state.feedback_no = fb["feedback_no"]
                st.session_state.vendors = []
                st.session_state.stage = "result"
                st.rerun()

        st.divider()

    # ── MCP 工具呼叫紀錄 ───────────────────────────────────────────────────
    st.markdown("## 🔌 MCP 工具呼叫紀錄")
    st.caption("每次呼叫後端工具都會即時顯示在這裡")
    st.divider()

    if not st.session_state.mcp_log:
        st.markdown(
            "<div style='color:#888;font-size:0.85rem;text-align:center;padding:20px 0'>"
            "尚未呼叫任何工具<br/>請在左側輸入需求</div>",
            unsafe_allow_html=True,
        )
    else:
        for i, entry in enumerate(reversed(st.session_state.mcp_log), 1):
            icon, label = TOOL_META.get(entry["tool"], ("🔧", entry["tool"]))
            p_summary   = _param_summary(entry["tool"], entry["params"])
            r_summary   = _result_summary(entry["tool"], entry["result"])

            st.markdown(f"""
            <div class="mcp-card">
              <span class="mcp-tool">{icon} {entry['tool']}</span>
              <span class="mcp-ts">{entry['ts']}</span><br/>
              <span style="color:#6C7086;font-size:0.75rem">{label}</span>
              <br/><br/>
              <span class="mcp-param">▶ 輸入<br/>{p_summary}</span>
              <br/><br/>
              <span class="mcp-ret">◀ 回傳<br/>{r_summary}</span>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"查看完整 JSON #{len(st.session_state.mcp_log) - i + 1}"):
                st.json({
                    "params": {k: v for k, v in entry["params"].items() if k != "answers"},
                    "result": entry["result"],
                })

    st.divider()
    if st.session_state.mcp_log:
        if st.button("清除紀錄", use_container_width=True):
            st.session_state.mcp_log = []
            st.rerun()

# ── 6. Header ─────────────────────────────────────────────────────────────────
st.markdown('<p class="t-main">🏪 7-ELEVEN 生活管家</p>', unsafe_allow_html=True)
st.markdown('<p class="t-sub">您的生活需求，我們一手包辦 ✦ 水電修繕・居家清潔・餐廳訂位・美食外送</p>',
            unsafe_allow_html=True)
st.divider()

# ── helpers ───────────────────────────────────────────────────────────────────
def _county_to_code(counties, cname):
    return next((c for c, n in counties if n == cname), counties[0][0])

def _dist_names(counties, cname):
    cc = _county_to_code(counties, cname)
    return [n for _, n in load_districts(cc)]

def _dist_code(counties, cname, dname):
    cc = _county_to_code(counties, cname)
    return next((c for c, n in load_districts(cc) if n == dname), "")

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.stage == "login":
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("### 👤 歡迎使用 7-ELEVEN 生活管家")
        st.markdown("請登入或註冊以儲存您的諮詢紀錄")
        st.markdown("")

        tab_login, tab_reg = st.tabs(["登入", "📝 新用戶註冊"])

        with tab_login:
            li_user = st.text_input("帳號", key="li_user", placeholder="請輸入帳號")
            li_pass = st.text_input("密碼", type="password", key="li_pass", placeholder="請輸入密碼")
            if st.button("登入", type="primary", use_container_width=True, key="btn_login"):
                user = check_login(li_user.strip(), li_pass.strip())
                if user:
                    st.session_state.user_id  = user["id"]
                    st.session_state.username = user["username"]
                    st.session_state.stage    = "input"
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤，請再試一次。")

        with tab_reg:
            reg_user = st.text_input("設定帳號", key="reg_user", placeholder="請輸入帳號")
            reg_pass = st.text_input("設定密碼", type="password", key="reg_pass", placeholder="至少 4 個字元")
            if st.button("註冊並登入", type="primary", use_container_width=True, key="btn_reg"):
                if len(reg_user.strip()) < 2:
                    st.error("帳號至少 2 個字元。")
                elif len(reg_pass.strip()) < 4:
                    st.error("密碼至少 4 個字元。")
                elif register_user(reg_user.strip(), reg_pass.strip()):
                    user = check_login(reg_user.strip(), reg_pass.strip())
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
    with st.expander("📋 已有諮詢單？點此查看訊息與進度"):
        lookup_no = st.text_input("輸入諮詢單編號", placeholder="例如：FB260707XXXXXX", key="lookup_no")
        if st.button("查詢", key="btn_lookup"):
            info = get_feedback_info(lookup_no.strip()) if lookup_no.strip() else None
            if info:
                st.session_state.stage = "result"
                st.session_state.feedback_no = info["feedback_no"]
                st.session_state.vendors = []
                st.rerun()
            else:
                st.error("找不到此諮詢單，請確認編號是否正確。")

    st.markdown("#### 👋 您好！請告訴我您今天有什麼需要協助的？")
    st.caption("例如：`我家大安區廚房水管漏水` ✦ `想找人打掃家裡` ✦ `幫我訂位 4 人晚餐`")

    user_text = st.text_area(
        "需求描述", placeholder="請輸入您的需求...",
        height=90, label_visibility="collapsed", key="ui_user_text",
    )
    col_go, _ = st.columns([2, 5])
    with col_go:
        go = st.button("分析需求 →", type="primary", use_container_width=True)

    if go:
        text = user_text.strip()
        if not text:
            st.warning("請輸入您的需求描述。")
        else:
            with st.spinner("🤖 呼叫 MCP 工具：get_service_form ..."):
                # ↓ 真正呼叫 MCP 工具，並記錄到側欄
                result = call_mcp("get_service_form", get_service_form,
                                  user_request=text)

            if not result.get("matched"):
                st.error("😅 " + result.get("message",
                         "無法判斷服務類型，請提供更具體的描述（如：漏水、清潔、訂位）。"))
            elif "topics" not in result:
                st.warning("⚠️ " + result.get("message", "此服務暫無可用的表單。"))
            else:
                st.session_state.form_data   = result
                st.session_state.user_input  = text
                st.session_state.form_errors = []
                st.session_state.stage       = "form"
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: FORM
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "form":  # noqa: E501
    fd      = st.session_state.form_data
    counties = load_counties()
    cnames  = [n for _, n in counties]

    if st.button("← 重新輸入需求"):
        st.session_state.stage       = "input"
        st.session_state.form_data   = None
        st.session_state.form_errors = []
        st.rerun()

    st.markdown(f"### 📋 {fd['form_name']}")
    if fd.get("intro"):
        st.caption(fd["intro"])
    st.markdown(f"**服務類型：** {fd['category']}")
    st.divider()

    for err in st.session_state.form_errors:
        st.error(f"⚠️ {err}")

    # ── render each topic ─────────────────────────────────────────────────────
    for topic in fd["topics"]:
        tid      = topic["topic_id"]
        ttype    = topic["type"]
        title    = topic["title"]
        req      = topic["required"]
        remark   = topic.get("remark") or ""
        opts     = topic.get("options", [])
        opt_names = [o["option_name"] for o in opts]

        req_tag = " <span style='color:#E53935'>*必填</span>" if req else ""
        st.markdown(f"**{title}**{req_tag}", unsafe_allow_html=True)
        if remark:
            st.caption(remark)

        if ttype == "簡答":
            st.text_input("", key=f"q_{tid}", label_visibility="collapsed")
        elif ttype in ("詳答", "備註"):
            st.text_area("", key=f"q_{tid}", height=80, label_visibility="collapsed")
        elif ttype == "單選":
            if opt_names:
                st.radio("", opt_names, key=f"q_{tid}", label_visibility="collapsed")
        elif ttype == "複選":
            if opt_names:
                st.multiselect("", opt_names, key=f"q_{tid}", label_visibility="collapsed")
        elif ttype == "地區選單":
            c1, c2 = st.columns(2)
            with c1:
                sel_c = st.selectbox("縣市", cnames, key=f"q_{tid}_county")
            with c2:
                dnames = _dist_names(counties, sel_c)
                st.selectbox("行政區", dnames or ["—"], key=f"q_{tid}_dist_{sel_c}")
        elif ttype == "上傳照片":
            st.file_uploader("", type=["jpg","jpeg","png","heic"],
                             key=f"q_{tid}", label_visibility="collapsed")
        elif ttype == "日期":
            st.date_input("", min_value=date.today(),
                          key=f"q_{tid}", label_visibility="collapsed")
        elif ttype == "聯絡資料":
            c1, c2 = st.columns(2)
            with c1:
                st.text_input("姓名", key=f"q_{tid}_name", placeholder="您的姓名")
            with c2:
                st.text_input("聯絡電話", key=f"q_{tid}_phone", placeholder="09XX-XXX-XXX")
            c3, c4 = st.columns(2)
            with c3:
                sel_c3 = st.selectbox("縣市", cnames, key=f"q_{tid}_county")
            with c4:
                dnames3 = _dist_names(counties, sel_c3)
                st.selectbox("行政區", dnames3 or ["—"], key=f"q_{tid}_dist_{sel_c3}")
        elif ttype == "聯絡資料(不含地址)":
            c1, c2 = st.columns(2)
            with c1:
                st.text_input("姓名", key=f"q_{tid}_name", placeholder="您的姓名")
            with c2:
                st.text_input("聯絡電話", key=f"q_{tid}_phone", placeholder="09XX-XXX-XXX")

        st.markdown("---")

    # ── submit ────────────────────────────────────────────────────────────────
    col_s, _ = st.columns([2, 5])
    with col_s:
        do_submit = st.button("✓ 送出需求", type="primary", use_container_width=True)

    if do_submit:
        errors         = []
        contact_name   = ""
        contact_mobile = ""
        county_code    = counties[0][0]
        district_code  = ""
        description    = st.session_state.user_input
        answers        = {}
        got_location   = False

        for topic in fd["topics"]:
            tid      = topic["topic_id"]
            ttype    = topic["type"]
            title    = topic["title"]
            req      = topic["required"]
            opts     = topic.get("options", [])
            opt_names = [o["option_name"] for o in opts]

            if ttype == "簡答":
                v = (st.session_state.get(f"q_{tid}") or "").strip()
                if req and not v: errors.append(f"「{title}」為必填")
                answers[str(tid)] = v
            elif ttype in ("詳答", "備註"):
                v = (st.session_state.get(f"q_{tid}") or "").strip()
                if req and not v: errors.append(f"「{title}」為必填")
                answers[str(tid)] = v
                if ttype == "詳答" and v:
                    description = v
            elif ttype == "單選":
                v = st.session_state.get(f"q_{tid}", opt_names[0] if opt_names else "")
                if req and not v: errors.append(f"「{title}」為必填")
                answers[str(tid)] = v
            elif ttype == "複選":
                v = st.session_state.get(f"q_{tid}", [])
                if req and not v: errors.append(f"「{title}」至少選一項")
                answers[str(tid)] = v
            elif ttype == "地區選單":
                cname = st.session_state.get(f"q_{tid}_county", cnames[0])
                cc    = _county_to_code(counties, cname)
                dname = st.session_state.get(f"q_{tid}_dist_{cname}", "")
                dc    = _dist_code(counties, cname, dname)
                county_code   = cc
                district_code = dc
                got_location  = True
                answers[str(tid)] = {"county": cname, "district": dname}
            elif ttype == "日期":
                v = st.session_state.get(f"q_{tid}", date.today())
                answers[str(tid)] = str(v)
            elif ttype == "上傳照片":
                f = st.session_state.get(f"q_{tid}")
                answers[str(tid)] = f.name if f else None
            elif ttype == "聯絡資料":
                name  = (st.session_state.get(f"q_{tid}_name") or "").strip()
                phone = (st.session_state.get(f"q_{tid}_phone") or "").strip()
                cname = st.session_state.get(f"q_{tid}_county", cnames[0])
                cc    = _county_to_code(counties, cname)
                dname = st.session_state.get(f"q_{tid}_dist_{cname}", "")
                dc    = _dist_code(counties, cname, dname)
                if req:
                    if not name:  errors.append("「聯絡資料」請填寫姓名")
                    if not phone: errors.append("「聯絡資料」請填寫聯絡電話")
                contact_name   = name
                contact_mobile = phone
                if not got_location:
                    county_code   = cc
                    district_code = dc
                answers[str(tid)] = {
                    "name": name, "phone": phone,
                    "county": cname, "district": dname,
                }
            elif ttype == "聯絡資料(不含地址)":
                name  = (st.session_state.get(f"q_{tid}_name") or "").strip()
                phone = (st.session_state.get(f"q_{tid}_phone") or "").strip()
                if req:
                    if not name:  errors.append("「聯絡資料」請填寫姓名")
                    if not phone: errors.append("「聯絡資料」請填寫聯絡電話")
                contact_name   = name
                contact_mobile = phone
                answers[str(tid)] = {"name": name, "phone": phone}

        if errors:
            st.session_state.form_errors = errors
            st.rerun()
        else:
            with st.spinner("📋 呼叫 MCP 工具：submit_form_feedback ..."):
                # ↓ MCP 工具 #2
                sub = call_mcp("submit_form_feedback", submit_form_feedback,
                    form_id        = fd["form_id"],
                    category_id    = fd["category_id"],
                    contact_name   = contact_name,
                    contact_mobile = contact_mobile,
                    county_code    = county_code,
                    district_code  = district_code,
                    description    = description,
                    answers        = json.dumps(answers, ensure_ascii=False),
                )
            with st.spinner("🏢 呼叫 MCP 工具：match_vendors ..."):
                # ↓ MCP 工具 #3
                vend = call_mcp("match_vendors", match_vendors,
                    category_id   = fd["category_id"],
                    county_code   = county_code,
                    district_code = district_code,
                )
            st.session_state.feedback_no = sub.get("feedback_no", "")
            st.session_state.vendors     = vend.get("vendors", [])
            st.session_state.form_errors = []
            # 把 user_id 寫進這筆 feedback
            if st.session_state.user_id and st.session_state.feedback_no:
                con = _db()
                con.execute("UPDATE pms_form_feedback SET user_id=? WHERE feedback_no=?",
                            (st.session_state.user_id, st.session_state.feedback_no))
                con.commit()
                con.close()
            st.session_state.stage = "result"
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# STAGE: RESULT
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.stage == "result":
    st.markdown(f"""
    <div class="success-box">
        <h3 style="color:#00833D;margin:0 0 6px">✅ 需求送出成功！</h3>
        <p style="margin:0">諮詢單編號：
          <strong style="font-family:monospace;font-size:1.05rem">
            {st.session_state.feedback_no}
          </strong>
        </p>
        <p style="color:#555;margin:4px 0 0">共呼叫了 {len(st.session_state.mcp_log)} 個 MCP 工具，廠商將主動與您聯繫。</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")
    vendors = st.session_state.vendors
    if vendors:
        st.markdown("### 🏆 媒合廠商清單（依評分排序）")
        for i, v in enumerate(vendors, 1):
            r = v.get("rating", 0)
            stars = "★" * int(round(r)) + "☆" * (5 - int(round(r)))
            st.markdown(f"""
            <div class="vendor-card">
              <span style="font-size:1.05rem;font-weight:700;color:#333">#{i}&nbsp; {v['name']}</span><br/>
              <span style="color:#F37021;letter-spacing:2px">{stars}</span>
              <span style="color:#666;font-size:0.9rem"> {r} 分</span>
              &nbsp;｜&nbsp;
              📞 <a href="tel:{v['phone']}" style="color:#00833D;font-weight:600">{v['phone']}</a>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("😔 此地區目前暫無合適的廠商，客服人員將另行安排，請留意電話聯繫。")

    st.divider()
    st.subheader("💬 與廠商溝通")
    st.caption(f"諮詢單：`{st.session_state.feedback_no}`")

    msgs = get_messages(st.session_state.feedback_no)
    if msgs:
        for m in msgs:
            if m["sender"] == "consumer":
                with st.chat_message("user", avatar="👤"):
                    st.write(m["content"])
                    st.caption(f"您 · {m['created_at'][:16]}")
            else:
                with st.chat_message("assistant", avatar="🏪"):
                    st.write(m["content"])
                    st.caption(f"廠商 · {m['created_at'][:16]}")
    else:
        st.caption("廠商確認需求後會在這裡回覆您，請稍候。")

    with st.form("consumer_msg_form", clear_on_submit=True):
        msg_text = st.text_input("輸入訊息給廠商", placeholder="例如：請問最快何時可以來？")
        col_send, col_refresh = st.columns([1, 1])
        send_ok = col_send.form_submit_button("📤 送出訊息", type="primary", use_container_width=True)
        refresh_ok = col_refresh.form_submit_button("🔄 重新整理", use_container_width=True)

    if send_ok and msg_text.strip():
        add_consumer_message(st.session_state.feedback_no, msg_text.strip())
        st.rerun()
    if refresh_ok:
        st.rerun()

    st.markdown("")
    if st.button("← 返回首頁，送出新需求", type="primary"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
