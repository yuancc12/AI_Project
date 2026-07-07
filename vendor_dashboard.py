# -*- coding: utf-8 -*-
"""
vendor_dashboard.py — 健身採買助手商品庫存後台
執行：streamlit run vendor_dashboard.py --server.port 8502
"""
import streamlit as st
import sqlite3
import json
import os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "butler.db")
if not os.path.exists(DB):
    import seed
    seed.main()

from mcp_server import dispatch_delivery  # MCP 工具 #5

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
STATUS_CFG = {
    "待處理": {"color": "#FF9800", "icon": "⏳"},
    "配送中": {"color": "#1976D2", "icon": "🚚"},
    "已拒絕": {"color": "#9E9E9E", "icon": "❌"},
    "已完成": {"color": "#43A047", "icon": "✅"},
}

MCP_TOOLS = [
    {
        "no": 1, "name": "search_grocery",
        "type": "🟢 讀取", "caller": "前端 AI",
        "desc": "依關鍵字搜尋統一集團各業務（7-11、家樂福、康是美、統一生機）的健身商品，回傳商品清單與蛋白質 / 熱量 / 價格 / 庫存資訊。",
        "trigger": "用戶詢問「有沒有雞胸肉」「乳清蛋白哪裡賣」時，Claude AI 自動呼叫。",
    },
    {
        "no": 2, "name": "recommend_high_protein",
        "type": "🟢 讀取", "caller": "前端 AI",
        "desc": "根據健身目標（增肌/減脂）與採買預算，用貪婪演算法挑選最佳高蛋白商品組合，回傳推薦清單與合計蛋白質 / 花費。",
        "trigger": "Claude 確認用戶目標 AND 預算後才呼叫，避免資訊不完整。",
    },
    {
        "no": 3, "name": "check_inventory",
        "type": "🟢 讀取", "caller": "前端 AI",
        "desc": "查詢指定商品在各通路的即時庫存數量，回傳有無庫存及各通路庫存明細。",
        "trigger": "用戶詢問「還有庫存嗎」「哪裡還有貨」時，Claude AI 自動呼叫。",
    },
    {
        "no": 4, "name": "submit_inquiry",
        "type": "🔴 寫入", "caller": "前端 AI（用戶確認後）",
        "desc": "將用戶的健身採買需求寫入後台諮詢單（inquiry 表），產生諮詢單號 IQ...，讓後台人員跟進。",
        "trigger": "用戶同意 → Claude 收集姓名電話 → 再次確認 → 才呼叫，嚴禁未確認就寫入。",
    },
    {
        "no": 5, "name": "dispatch_delivery",
        "type": "🔴 寫入", "caller": "後台人員（接單後）",
        "desc": "後台人員接受採買諮詢單後，建立外送配送訂單（DL...），更新諮詢單狀態為「配送中」，記錄廠商名稱、回覆訊息與接單時間。",
        "trigger": "後台人員在採買諮詢單頁面點「接受訂單並派送」，確認廠商資訊後自動呼叫。",
    },
]


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
    pending      = con.execute("SELECT COUNT(*) FROM inquiry WHERE status='待處理'").fetchone()[0]
    delivering   = con.execute("SELECT COUNT(*) FROM inquiry WHERE status='配送中'").fetchone()[0]
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


def get_inquiries(status_filter=None):
    con = _db()
    sql = "SELECT * FROM inquiry"
    params = []
    if status_filter and status_filter != "全部":
        sql += " WHERE status=?"
        params.append(status_filter)
    sql += " ORDER BY created_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def reject_inquiry(inquiry_no, reason):
    con = _db()
    con.execute(
        "UPDATE inquiry SET status='已拒絕', vendor_reply=? WHERE inquiry_no=?",
        (reason, inquiry_no),
    )
    con.commit()
    con.close()


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="健身採買後台", page_icon="🏪", layout="wide")
st.title("🏪 健身採買助手 — 後台管理")
st.caption("統一集團 × MCP Server ✦ 商品庫存 · 採買諮詢 · 外送派送")

# ── 頂部統計 ─────────────────────────────────────────────────────────────────

total, out_of_stock, low_stock_count, avg_protein, pending, delivering = get_stats()
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("商品總數",       total)
m2.metric("⚠️ 低庫存(≤30)", low_stock_count)
m3.metric("❌ 售完",        out_of_stock)
m4.metric("平均蛋白質(g)",  avg_protein)
m5.metric("⏳ 待處理諮詢",  pending)
m6.metric("🚚 配送中",      delivering)

st.divider()

# ── 三個頁籤 ─────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["🛒 商品庫存", "📋 採買諮詢單", "🔌 MCP 工具總覽"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 商品庫存
# ══════════════════════════════════════════════════════════════════════════════

with tab1:
    with st.expander("📊 各通路商品數量"):
        cols = st.columns(4)
        con = _db()
        for i, vendor in enumerate(["7-11", "家樂福", "康是美", "統一生機"]):
            n = con.execute(
                "SELECT COUNT(*) FROM fitness_product WHERE vendor=?", (vendor,)
            ).fetchone()[0]
            color = VENDOR_COLOR[vendor]
            cols[i].markdown(
                f'<div style="background:{color};color:white;border-radius:8px;'
                f'padding:12px;text-align:center">'
                f'<strong>{vendor}</strong><br/>'
                f'<span style="font-size:1.5rem;font-weight:900">{n}</span> 項</div>',
                unsafe_allow_html=True,
            )
        con.close()

    st.divider()

    f1, f2, f3 = st.columns([2, 2, 1])
    sel_vendor = f1.selectbox("通路篩選", ["全部", "7-11", "家樂福", "康是美", "統一生機"], key="v_vendor")
    sel_cat    = f2.selectbox("分類篩選", ["全部", "蛋白質", "主食", "蔬果", "乳製品", "保健品", "即食"], key="v_cat")
    show_low   = f3.checkbox("僅低庫存", key="v_low")

    products = get_products(
        vendor=None if sel_vendor == "全部" else sel_vendor,
        category=None if sel_cat == "全部" else sel_cat,
        low_stock_only=show_low,
    )
    st.caption(f"顯示 {len(products)} 筆商品")
    st.divider()

    for p in products:
        vendor     = p["vendor"]
        color      = VENDOR_COLOR.get(vendor, "#888")
        cat_icon   = CAT_ICON.get(p["category"], "📦")
        stock      = p["stock"]
        stock_color = "#E53935" if stock == 0 else ("#FF9800" if stock <= 30 else "#43A047")

        with st.container(border=True):
            col_info, col_stock, col_btn = st.columns([5, 1, 1])

            with col_info:
                st.markdown(
                    f'<span style="background:{color};color:white;border-radius:4px;'
                    f'padding:2px 8px;font-size:0.78rem;font-weight:600">{vendor}</span>'
                    f'&nbsp;{cat_icon}&nbsp;<strong>{p["name"]}</strong>'
                    f'&nbsp;<span style="color:#777;font-size:0.85rem">'
                    f'蛋白質 {p["protein_g"]}g ｜ {p["calories"]} kcal ｜ ${p["price"]}</span>',
                    unsafe_allow_html=True,
                )

            with col_stock:
                st.markdown(
                    f'<div style="text-align:center;color:{stock_color};font-weight:700;padding-top:4px">'
                    f'庫存 {stock}</div>',
                    unsafe_allow_html=True,
                )

            with col_btn:
                if st.button("修改庫存", key=f"edit_{p['id']}"):
                    st.session_state[f"editing_{p['id']}"] = True

            if st.session_state.get(f"editing_{p['id']}"):
                with st.form(f"form_{p['id']}"):
                    new_stock = st.number_input(
                        f"「{p['name']}」新庫存", min_value=0, max_value=9999, value=stock
                    )
                    c1, c2 = st.columns(2)
                    save   = c1.form_submit_button("✅ 儲存", type="primary")
                    cancel = c2.form_submit_button("取消")
                if save:
                    update_stock(p["id"], new_stock)
                    st.session_state[f"editing_{p['id']}"] = False
                    st.success(f"已更新「{p['name']}」庫存為 {new_stock}")
                    st.rerun()
                if cancel:
                    st.session_state[f"editing_{p['id']}"] = False
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 採買諮詢單
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("#### 用戶透過 AI 助手提交的採買諮詢，在此確認接單或拒絕並派送。")

    col_filter, col_refresh = st.columns([3, 1])
    status_opts = ["全部", "待處理", "配送中", "已拒絕", "已完成"]
    sel_status  = col_filter.selectbox("篩選狀態", status_opts, key="inq_status")
    if col_refresh.button("🔄 重新整理", use_container_width=True, key="inq_refresh"):
        st.rerun()

    inquiries = get_inquiries(sel_status)
    st.caption(f"共 {len(inquiries)} 筆{'（' + sel_status + '）' if sel_status != '全部' else ''}")
    st.divider()

    if not inquiries:
        st.info("目前沒有符合條件的諮詢單。")
    else:
        for inq in inquiries:
            status   = inq.get("status", "待處理")
            scfg     = STATUS_CFG.get(status, {"color": "#888", "icon": "❓"})
            s_icon   = scfg["icon"]
            s_color  = scfg["color"]
            inq_id   = inq["inquiry_no"]

            with st.container(border=True):
                # ── Header ──────────────────────────────────────────────────
                h1, h2, h3 = st.columns([2, 3, 2])
                h1.markdown(
                    f'<span style="background:{s_color};color:white;border-radius:12px;'
                    f'padding:3px 10px;font-size:0.82rem;font-weight:700">'
                    f'{s_icon} {status}</span>',
                    unsafe_allow_html=True,
                )
                h2.markdown(f"**`{inq_id}`**")
                h3.caption(str(inq.get("created_at", ""))[:16])

                # ── Details ─────────────────────────────────────────────────
                d1, d2 = st.columns(2)
                with d1:
                    st.markdown(f"**目標：** {inq.get('goal') or '—'}")
                    budget_val = inq.get("budget") or 0
                    st.markdown(f"**預算：** {'$' + str(budget_val) if budget_val else '—'}")
                    if inq.get("keyword"):
                        st.markdown(f"**關鍵字：** {inq['keyword']}")
                    if inq.get("note"):
                        st.markdown(f"**備註：** {inq['note']}")
                with d2:
                    st.markdown(f"**聯絡人：** {inq.get('contact_name') or '—'}")
                    st.markdown(f"**電話：** {inq.get('contact_phone') or '—'}")

                # ── Delivery info（已派送）──────────────────────────────────
                if inq.get("delivery_no"):
                    st.success(
                        f"🚚 **外送單號：** `{inq['delivery_no']}`　"
                        f"｜　接單時間：{str(inq.get('accepted_at', ''))[:16]}"
                    )
                    if inq.get("vendor_reply"):
                        st.caption(f"廠商回覆：{inq['vendor_reply']}")

                # ── 拒絕回覆 ────────────────────────────────────────────────
                if status == "已拒絕" and inq.get("vendor_reply"):
                    st.warning(f"拒絕原因：{inq['vendor_reply']}")

                # ── 操作按鈕（僅待處理） ─────────────────────────────────
                if status == "待處理":
                    st.divider()
                    b1, b2, _ = st.columns([2, 2, 3])
                    if b1.button("✅ 接受訂單並派送", key=f"acc_{inq['id']}", type="primary"):
                        st.session_state[f"act_{inq_id}"] = "accept"
                    if b2.button("❌ 拒絕", key=f"rej_{inq['id']}"):
                        st.session_state[f"act_{inq_id}"] = "reject"

                    action = st.session_state.get(f"act_{inq_id}")

                    # ── 接受表單 ──────────────────────────────────────────
                    if action == "accept":
                        with st.form(f"acc_form_{inq_id}"):
                            st.markdown("**填寫接單資訊後確認派送**")
                            v_name  = st.text_input("廠商 / 門市名稱", placeholder="例：家樂福信義店")
                            v_reply = st.text_area("給用戶的回覆訊息", placeholder="例：已為您備妥商品，預計60分鐘內送達")
                            v_mins  = st.number_input("預計送達（分鐘）", min_value=15, max_value=300, value=60)
                            fc1, fc2 = st.columns(2)
                            do_accept = fc1.form_submit_button("🚚 確認接單並呼叫 MCP 派送", type="primary")
                            do_cancel = fc2.form_submit_button("取消")

                        if do_accept:
                            result = json.loads(dispatch_delivery(
                                inquiry_no=inq_id,
                                vendor_name=v_name or "統一集團",
                                estimated_minutes=int(v_mins),
                                reply_message=v_reply,
                            ))
                            if result.get("success"):
                                st.success(
                                    f"✅ 接單成功！MCP dispatch_delivery 已執行\n\n"
                                    f"外送單號：`{result['delivery_no']}`\n\n"
                                    f"{result['message']}"
                                )
                            else:
                                st.error("派送失敗，請稍後再試。")
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                        if do_cancel:
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                    # ── 拒絕表單 ──────────────────────────────────────────
                    elif action == "reject":
                        with st.form(f"rej_form_{inq_id}"):
                            st.markdown("**確認拒絕此諮詢單**")
                            r_reason = st.text_area("拒絕原因", placeholder="例：目前庫存不足，建議下週再訂")
                            rc1, rc2 = st.columns(2)
                            do_reject = rc1.form_submit_button("確認拒絕", type="secondary")
                            do_cancel2 = rc2.form_submit_button("取消")

                        if do_reject:
                            reject_inquiry(inq_id, r_reason)
                            st.info("已拒絕此諮詢單。")
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                        if do_cancel2:
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — MCP 工具總覽
# ══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("#### 本系統共整合 5 個 MCP 工具，由 FastMCP（fitness-grocery）提供。")
    st.caption(
        "前端 AI（Claude claude-sonnet-4-6）在對話中自動判斷需求並呼叫讀取工具；"
        "寫入工具需用戶或後台人員明確確認後才執行。"
    )
    st.divider()

    for t in MCP_TOOLS:
        is_write = "寫入" in t["type"]
        border_color = "#E53935" if is_write else "#43A047"

        with st.container(border=True):
            h1, h2, h3 = st.columns([1, 2, 2])
            h1.markdown(f"### #{t['no']}")
            h2.markdown(f"**`{t['name']}`**")
            h3.markdown(t["type"])

            st.markdown(f"**功能說明：** {t['desc']}")
            st.caption(f"**觸發時機：** {t['trigger']}")

            if is_write:
                caller_label = t["caller"]
                st.markdown(
                    f'<div style="background:#FFF3E0;border-left:4px solid #FF9800;'
                    f'padding:6px 10px;border-radius:4px;font-size:0.85rem">'
                    f'⚠️ <strong>寫入工具</strong> — 調用方：{caller_label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="background:#E8F5E9;border-left:4px solid #43A047;'
                    f'padding:6px 10px;border-radius:4px;font-size:0.85rem">'
                    f'✅ <strong>唯讀工具</strong> — 調用方：{t["caller"]}</div>',
                    unsafe_allow_html=True,
                )

    st.divider()
    st.markdown("#### 資料流程示意")
    st.markdown("""
```
用戶輸入需求
  └─▶ Claude claude-sonnet-4-6（前端 AI）
        ├─▶ [工具1] search_grocery       🟢 搜尋商品
        ├─▶ [工具2] recommend_high_protein 🟢 推薦組合
        ├─▶ [工具3] check_inventory       🟢 查詢庫存
        └─▶ [工具4] submit_inquiry        🔴 建立諮詢單（用戶雙重確認後）
                        │
                        ▼
              inquiry 表（butler.db）
                        │
              後台人員 → 採買諮詢單頁面
                        │
                        └─▶ [工具5] dispatch_delivery  🔴 接單派送
                                        │
                                        ▼
                              外送單 DL... 建立
                              inquiry.status = 配送中
```
    """)
