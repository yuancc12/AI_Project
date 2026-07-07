# -*- coding: utf-8 -*-
"""
vendor_dashboard.py — 廠商後台管理介面
執行：streamlit run vendor_dashboard.py
"""
import streamlit as st
import sqlite3
import json
import os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "butler.db")

if not os.path.exists(DB):
    import seed; seed.main()

STATUS_MAP = {
    "01": ("待處理", "🔴"),
    "02": ("已聯繫", "🟡"),
    "03": ("已承接", "🔵"),
    "80": ("已完成", "🟢"),
}
STATUS_NEXT = {"01": "02", "02": "03", "03": "80"}
STATUS_NEXT_LABEL = {
    "01": "標記為已聯繫",
    "02": "標記為已承接",
    "03": "標記為已完成",
}


def _db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def get_stats():
    con = _db()
    total   = con.execute("SELECT COUNT(*) FROM pms_form_feedback").fetchone()[0]
    pending = con.execute("SELECT COUNT(*) FROM pms_form_feedback WHERE status='01'").fetchone()[0]
    unread  = con.execute("SELECT COUNT(*) FROM pms_form_feedback WHERE is_read='0'").fetchone()[0]
    today   = datetime.now().strftime("%Y-%m-%d")
    today_n = con.execute(
        "SELECT COUNT(*) FROM pms_form_feedback WHERE cre_time LIKE ?",
        (today + "%",)).fetchone()[0]
    con.close()
    return total, pending, unread, today_n


def get_feedbacks(status_filter=None, category_filter=None):
    con = _db()
    sql = """
        SELECT f.*,
               c.name  AS category_name,
               co.name AS county_name,
               d.name  AS district_name,
               pf.name AS form_name
        FROM pms_form_feedback f
        LEFT JOIN service_category c  ON f.category_id   = c.id
        LEFT JOIN sys_county       co ON f.county_code   = co.code
        LEFT JOIN sys_district     d  ON f.district_code = d.code
        LEFT JOIN pms_form         pf ON f.form_id       = pf.id
        WHERE 1=1
    """
    params = []
    if status_filter:
        sql += " AND f.status = ?"
        params.append(status_filter)
    if category_filter:
        sql += " AND c.name = ?"
        params.append(category_filter)
    sql += " ORDER BY f.cre_time DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


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


def get_messages(feedback_no):
    con = _db()
    rows = con.execute(
        "SELECT * FROM feedback_message WHERE feedback_no=? ORDER BY id",
        (feedback_no,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def add_message(feedback_no, sender, content):
    con = _db()
    con.execute(
        "INSERT INTO feedback_message (feedback_no,sender,content,created_at) VALUES (?,?,?,?)",
        (feedback_no, sender, content, datetime.now().isoformat())
    )
    con.commit()
    con.close()


def get_feedback_detail(feedback_no):
    con = _db()
    row = con.execute("""
        SELECT f.*,
               c.name  AS category_name,
               co.name AS county_name,
               d.name  AS district_name,
               pf.name AS form_name
        FROM pms_form_feedback f
        LEFT JOIN service_category c  ON f.category_id   = c.id
        LEFT JOIN sys_county       co ON f.county_code   = co.code
        LEFT JOIN sys_district     d  ON f.district_code = d.code
        LEFT JOIN pms_form         pf ON f.form_id       = pf.id
        WHERE f.feedback_no = ?
    """, (feedback_no,)).fetchone()
    con.close()
    return dict(row) if row else None


def get_categories():
    con = _db()
    rows = con.execute("SELECT name FROM service_category ORDER BY id").fetchall()
    con.close()
    return [r["name"] for r in rows]


def update_status(feedback_no, new_status):
    con = _db()
    con.execute("UPDATE pms_form_feedback SET status=? WHERE feedback_no=?",
                (new_status, feedback_no))
    con.commit()
    con.close()


def mark_read(feedback_no):
    con = _db()
    con.execute("UPDATE pms_form_feedback SET is_read='1' WHERE feedback_no=?",
                (feedback_no,))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
st.set_page_config(page_title="廠商後台管理", page_icon="🏪", layout="wide")
st.title("🏪 廠商後台管理系統")

if "selected_no" not in st.session_state:
    st.session_state.selected_no = None

# ── 頂部統計 ───────────────────────────────────────────────────────────────
total, pending, unread, today_n = get_stats()
m1, m2, m3, m4 = st.columns(4)
m1.metric("總案件數", total)
m2.metric("🔴 待處理", pending)
m3.metric("🔵 未讀", unread)
m4.metric("今日新增", today_n)

st.divider()

# ── 主要區域：左＝列表，右＝詳情 ──────────────────────────────────────────
col_list, col_detail = st.columns([2, 3], gap="medium")

# ── 左欄：篩選 + 案件列表 ─────────────────────────────────────────────────
with col_list:
    st.subheader("案件列表")

    f1, f2 = st.columns(2)

    status_options = ["全部", "01", "02", "03", "80"]
    status_labels  = ["全部", "🔴 待處理", "🟡 已聯繫", "🔵 已承接", "🟢 已完成"]
    sel_status_label = f1.selectbox("狀態篩選", status_labels)
    status_filter = status_options[status_labels.index(sel_status_label)]
    if status_filter == "全部":
        status_filter = None

    cat_options = ["全部"] + get_categories()
    sel_cat = f2.selectbox("服務類型", cat_options)
    cat_filter = None if sel_cat == "全部" else sel_cat

    feedbacks = get_feedbacks(status_filter, cat_filter)

    if not feedbacks:
        st.info("目前沒有符合條件的案件。")

    for fb in feedbacks:
        status_label, status_icon = STATUS_MAP.get(fb["status"], ("未知", "⚪"))
        unread_dot = "🔵 " if fb["is_read"] == "0" else ""
        time_str = fb["cre_time"][:16] if fb["cre_time"] else ""

        with st.container(border=True):
            top_l, top_r = st.columns([3, 1])
            top_l.markdown(f"**{unread_dot}{fb['feedback_no']}**")
            top_r.markdown(f"{status_icon} {status_label}")

            st.caption(
                f"{fb['category_name']} ｜ "
                f"{fb['county_name'] or ''}{fb['district_name'] or ''}"
            )
            st.markdown(
                f"👤 **{fb['contact_name'] or '-'}**　"
                f"📱 {fb['contact_mobile'] or '-'}"
            )
            if fb["description"]:
                preview = fb["description"][:45]
                if len(fb["description"]) > 45:
                    preview += "…"
                st.caption(f"📝 {preview}")

            btn_c, time_c = st.columns([1, 1])
            time_c.caption(f"🕐 {time_str}")
            if btn_c.button("查看詳情", key=f"sel_{fb['feedback_no']}"):
                st.session_state.selected_no = fb["feedback_no"]
                mark_read(fb["feedback_no"])
                st.rerun()

# ── 右欄：案件詳情 ────────────────────────────────────────────────────────
with col_detail:
    if st.session_state.selected_no:
        fb = get_feedback_detail(st.session_state.selected_no)
        if fb:
            status_label, status_icon = STATUS_MAP.get(fb["status"], ("未知", "⚪"))

            # 標題列
            h1, h2 = st.columns([3, 1])
            h1.subheader(f"案件詳情")
            if h2.button("✖ 關閉"):
                st.session_state.selected_no = None
                st.rerun()

            # 基本資訊
            i1, i2 = st.columns(2)
            i1.markdown(f"**諮詢單號：** `{fb['feedback_no']}`")
            i1.markdown(f"**服務類型：** {fb['category_name']}")
            i1.markdown(f"**使用表單：** {fb['form_name']}")
            i2.markdown(f"**目前狀態：** {status_icon} {status_label}")
            i2.markdown(f"**建立時間：** {fb['cre_time'][:16]}")

            st.divider()

            # 消費者聯絡資訊
            st.subheader("消費者聯絡資訊")
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**👤 姓名**\n\n{fb['contact_name'] or '-'}")
            c2.markdown(f"**📱 電話**\n\n{fb['contact_mobile'] or '-'}")
            location = (fb["county_name"] or "") + (fb["district_name"] or "")
            c3.markdown(f"**📍 地區**\n\n{location or '-'}")

            st.divider()

            # 需求描述
            if fb["description"]:
                st.subheader("需求描述")
                st.info(fb["description"])

            # 表單填答
            if fb["answers_json"] and fb["answers_json"] not in ("{}", ""):
                st.subheader("表單填答內容")
                try:
                    answers = json.loads(fb["answers_json"])
                    for key, val in answers.items():
                        if val is not None and val != "":
                            if isinstance(val, list):
                                st.markdown(f"**{key}：** {'、'.join(val)}")
                            else:
                                st.markdown(f"**{key}：** {val}")
                except Exception:
                    st.code(fb["answers_json"])

            st.divider()

            # 狀態管理
            st.subheader("案件管理")
            next_status = STATUS_NEXT.get(fb["status"])
            if next_status:
                if st.button(
                    f"✅ {STATUS_NEXT_LABEL[fb['status']]}",
                    type="primary",
                    key=f"upd_{fb['feedback_no']}"
                ):
                    update_status(fb["feedback_no"], next_status)
                    ns_label, ns_icon = STATUS_MAP[next_status]
                    st.success(f"狀態已更新為 {ns_icon} {ns_label}")
                    st.session_state.selected_no = None
                    st.rerun()
            else:
                st.success("此案件已完成，無需進一步操作。")

            st.divider()

            # ── 訊息往來 ──────────────────────────────────────────────────
            st.subheader("💬 與消費者溝通")

            msgs = get_messages(fb["feedback_no"])
            if msgs:
                for m in msgs:
                    if m["sender"] == "vendor":
                        with st.chat_message("assistant", avatar="🏪"):
                            st.write(m["content"])
                            st.caption(f"廠商 · {m['created_at'][:16]}")
                    else:
                        with st.chat_message("user", avatar="👤"):
                            st.write(m["content"])
                            st.caption(f"消費者 · {m['created_at'][:16]}")
            else:
                st.caption("尚無訊息，可先傳訊息給消費者確認需求。")

            with st.form(f"vendor_msg_{fb['feedback_no']}", clear_on_submit=True):
                msg_input = st.text_input("輸入訊息", placeholder="例如：您好，請問方便今天下午到府嗎？")
                col_send, col_refresh = st.columns([1, 1])
                send_clicked = col_send.form_submit_button("📤 發送訊息", type="primary", use_container_width=True)
                refresh_clicked = col_refresh.form_submit_button("🔄 重新整理", use_container_width=True)

            if send_clicked and msg_input.strip():
                add_message(fb["feedback_no"], "vendor", msg_input.strip())
                st.rerun()
            if refresh_clicked:
                st.rerun()

    else:
        st.markdown(
            "<div style='text-align:center; padding: 80px 0; color:#888;'>"
            "<h3>👈 請從左側選擇一個案件查看詳情</h3>"
            "</div>",
            unsafe_allow_html=True,
        )
