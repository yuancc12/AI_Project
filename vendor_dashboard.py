# -*- coding: utf-8 -*-
"""
vendor_dashboard.py — 健康採買後台 Streamlit UI
執行：streamlit run vendor_dashboard.py --server.port 8502
"""
import streamlit as st
import json
import os
import contextlib
from datetime import datetime

_null = contextlib.nullcontext()
from vendor_helpers import (
    DB, VENDOR_COLOR, CAT_ICON, STATUS_CFG, DELIVERY_TYPE_CFG,
    DELIVERY_COMPANIES, DELIVERY_ICON, MCP_TOOLS,
    _db, get_stats, get_products, update_stock, insert_product, delete_product,
    get_inquiries, reject_inquiry, reserve_inquiry,
    get_brand_stores, get_dispatches, get_active_deliveries, update_delivery_status,
    update_product,
    get_gym_id_for_store, get_being_sport_gyms, get_gym_courses_for_dashboard,
    get_enrollments_for_course, update_course_min_students, update_course_max_slots,
    open_course_and_notify, cancel_course, add_gym_course,
    check_vendor_login, _ensure_vendor_users,
    dispatch_via_mcp, admin_ollama_chat, OLLAMA_MODEL,
)
from mcp_server import _send_email

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="健康採買後台", page_icon="🏪", layout="wide")

# ── Session state init ───────────────────────────────────────────────────────

for _k, _v in {"vendor_id": None, "vendor_store": None, "vendor_brand": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Login guard ──────────────────────────────────────────────────────────────

if not st.session_state.vendor_id:
    st.title("🏪 健康採買後台 — 登入")
    st.divider()
    _, _center, _ = st.columns([1, 2, 1])
    with _center:
        st.markdown("### 👤 後台人員登入")
        st.caption("請使用您的門市帳號登入")
        _vu = st.text_input("帳號", key="vu", placeholder="例：7-11-A")
        _vp = st.text_input("密碼", type="password", key="vp", placeholder="請輸入密碼")
        if st.button("登入", type="primary", use_container_width=True, key="vbtn_login"):
            _vendor = check_vendor_login(_vu.strip(), _vp.strip())
            if _vendor:
                st.session_state.vendor_id    = _vendor["id"]
                st.session_state.vendor_store = _vendor["store_name"]
                st.session_state.vendor_brand = _vendor["brand"]
                st.rerun()
            else:
                st.error("帳號或密碼錯誤，請再試一次。")
        st.divider()
        st.markdown("""
**測試帳號一覽**

| 帳號 | 密碼 | 身份 | 可見內容 |
|------|------|------|---------|
| `7-11-A` | `vendor123` | 7-11 A門市 | 商品庫存、採買諮詢、AI派送 |
| `7-11-B` | `vendor123` | 7-11 B門市 | 商品庫存、採買諮詢、AI派送 |
| `wanjiafu` | `vendor123` | 萬家福信義店 | 商品庫存、採買諮詢、AI派送 |
| `cosmed` | `vendor123` | 康是美中山店 | 商品庫存、採買諮詢、AI派送 |
| `misterdonut` | `vendor123` | Mister Donut 大安店 | 商品庫存、採買諮詢、AI派送 |
| `coldstone` | `vendor123` | Cold Stone 信義店 | 商品庫存、採買諮詢、AI派送 |
| `21plus` | `vendor123` | 21plus 信義旗艦店 | 商品庫存、採買諮詢、AI派送 |
| `starbucks` | `vendor123` | 統一星巴克 信義店 | 商品庫存、採買諮詢、AI派送 |
| `sanitas` | `vendor123` | 聖德科斯 中山店 | 商品庫存、採買諮詢、AI派送 |
| `beingsport` | `gym123` | Being Sport 健身中心 | 課程報名單、課程管理 |
| `insurance` | `ins123` | 統超保險經紀人 | 旅遊保險申請單（審核→發保單→確認生效） |
| `unisec` | `sec123` | 統一證券 | 理財諮詢單 |
| `driver1` | `driver123` | 外送員 小明 | 外送派件（接單/配送/完成） |
| `driver2` | `driver123` | 外送員 小華 | 外送派件（接單/配送/完成） |
| `admin` | `admin123` | 管理員 | 全部（商品/諮詢/AI/派件/課程） |
""")
    st.stop()

# ── 標題 + 登出 ──────────────────────────────────────────────────────────────

_col_ttl, _col_usr, _col_out = st.columns([4, 2, 1])
_col_ttl.title("🏪 統一生活管家 — 後台管理")
_col_usr.markdown(
    f'<div style="padding-top:14px;color:#555">👤 <strong>{st.session_state.vendor_store}</strong></div>',
    unsafe_allow_html=True,
)
if _col_out.button("登出", key="v_logout"):
    for _k in ["vendor_id", "vendor_store", "vendor_brand"]:
        st.session_state[_k] = None
    st.rerun()
st.caption("統一集團 × MCP Server ✦ 商品庫存 · 採買諮詢 · 外送派送 ｜ 後台 AI + mcp.Client")

# ── 品牌判斷（頁籤與統計共用） ────────────────────────────────────────────────

_brand_v        = st.session_state.vendor_brand
_is_gym_only    = _brand_v == "健身房"
_is_admin_v     = _brand_v == "全部"
_is_driver      = _brand_v == "外送員"
_is_gym_vendor  = _is_gym_only or _is_admin_v
_is_insurance   = _brand_v == "保險"
_is_finance     = _brand_v == "金融"

# ── 頂部統計 ─────────────────────────────────────────────────────────────────

_stat_vendor = "" if _is_admin_v else (_brand_v if _brand_v not in ("全部", "外送員", "健身房", "保險", "金融") else "")
total, out_of_stock, low_stock_count, avg_protein, pending, delivering = get_stats(_stat_vendor)
if _is_driver:
    m1, m2 = st.columns(2)
    m1.metric("⏳ 待取件",  pending)
    m2.metric("🚚 配送中",  delivering)
elif _is_gym_only:
    m1, m2, m3 = st.columns(3)
    m1.metric("商品總數",       total)
    m2.metric("⚠️ 低庫存(≤30)", low_stock_count)
    m3.metric("⏳ 待處理諮詢",  pending)
elif _is_insurance:
    m1, m2 = st.columns(2)
    m1.metric("⏳ 待處理申請", pending)
    m2.metric("✅ 已完成",     delivering)
elif _is_finance:
    m1, m2 = st.columns(2)
    m1.metric("⏳ 待處理諮詢", pending)
    m2.metric("✅ 已完成",     delivering)
else:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("商品總數",       total)
    m2.metric("⚠️ 低庫存(≤30)", low_stock_count)
    m3.metric("❌ 售完",        out_of_stock)
    m4.metric("⏳ 待處理諮詢",  pending)
    m5.metric("🚚 配送中",      delivering)

st.divider()

# ── 頁籤 ─────────────────────────────────────────────────────────────────────

if _is_driver:
    _tab_labels = ["🚴 外送派件"]
    _tabs = st.tabs(_tab_labels)
    tab5 = _tabs[0]
    tab1 = tab2 = tab3 = tab4 = tab6 = None
elif _is_gym_only:
    _tab_labels = ["📋 採買諮詢單", "🤖 AI 派送助手", "🔌 MCP 工具總覽", "🏋️ Being Sport 課程管理"]
    _tabs = st.tabs(_tab_labels)
    tab1, tab5 = None, None
    tab2, tab3, tab4, tab6 = _tabs
elif _is_insurance:
    _tab_labels = ["📋 保險申請單"]
    _tabs = st.tabs(_tab_labels)
    tab2 = _tabs[0]
    tab1 = tab3 = tab4 = tab5 = tab6 = None
elif _is_finance:
    _tab_labels = ["📋 理財諮詢單"]
    _tabs = st.tabs(_tab_labels)
    tab2 = _tabs[0]
    tab1 = tab3 = tab4 = tab5 = tab6 = None
elif _is_admin_v:
    _tab_labels = ["🛒 商品庫存", "📋 採買諮詢單", "🤖 AI 派送助手", "🔌 MCP 工具總覽", "🚴 外送派件", "🏋️ Being Sport 課程管理"]
    _tabs = st.tabs(_tab_labels)
    tab1, tab2, tab3, tab4, tab5, tab6 = _tabs
else:
    _tab_labels = ["🛒 商品庫存", "📋 採買諮詢單", "🤖 AI 派送助手", "🔌 MCP 工具總覽", "🚴 外送派件"]
    _tabs = st.tabs(_tab_labels)
    tab1, tab2, tab3, tab4, tab5 = _tabs
    tab6 = None


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 商品庫存
# ══════════════════════════════════════════════════════════════════════════════

_RETAIL_BRANDS = [
    "7-11", "萬家福", "康是美", "統一生機",
    "Mister Donut", "Cold Stone", "21plus", "統一星巴克", "聖德科斯",
]

_ADD_CAT_OPTS = ["蛋白質", "主食", "蔬果", "乳製品", "保健品", "即食",
                 "甜食", "甜點", "飲料", "咖啡", "酒類", "有機食品"]

@st.dialog("➕ 新增商品")
def _dialog_add_product(default_vendor, is_admin):
    if is_admin:
        ap_vendor = st.selectbox("通路 *", _RETAIL_BRANDS)
    else:
        ap_vendor = default_vendor
        st.markdown(
            f'<span style="background:{VENDOR_COLOR.get(default_vendor,"#888")};color:white;'
            f'border-radius:6px;padding:3px 10px;font-weight:600">通路：{default_vendor}</span>',
            unsafe_allow_html=True,
        )
        st.markdown("")
    c1, c2 = st.columns(2)
    ap_name = c1.text_input("商品名稱 *", placeholder="例：台灣啤酒(330ml)")
    ap_cat  = c2.selectbox("分類 *", _ADD_CAT_OPTS)
    c3, c4, c5, c6 = st.columns(4)
    ap_price    = c3.number_input("售價 ($)",     min_value=0,   max_value=99999, value=50)
    ap_stock    = c4.number_input("庫存數量",      min_value=0,   max_value=99999, value=50)
    ap_protein  = c5.number_input("蛋白質 (g)",   min_value=0.0, max_value=999.0, value=0.0, step=0.1, format="%.1f")
    ap_calories = c6.number_input("熱量 (kcal)",  min_value=0,   max_value=9999,  value=100)
    st.markdown("")
    if st.button("✅ 確定新增", type="primary", use_container_width=True):
        if not ap_name.strip():
            st.warning("請輸入商品名稱。")
        else:
            insert_product(ap_name.strip(), ap_vendor, ap_cat, ap_protein, ap_calories, ap_price, ap_stock)
            st.success(f"已新增「{ap_name.strip()}」")
            st.rerun()

if tab1 is not None:
    with tab1:
        _brand = st.session_state.vendor_brand
        _is_admin = (_brand == "全部")

        with st.expander("📊 各通路商品數量"):
            _show_vendors = _RETAIL_BRANDS if _is_admin else [_brand]
            cols = st.columns(min(len(_show_vendors), 5))
            con = _db()
            for i, vendor in enumerate(_show_vendors):
                n = con.execute(
                    "SELECT COUNT(*) FROM fitness_product WHERE vendor=?", (vendor,)
                ).fetchone()[0]
                color = VENDOR_COLOR.get(vendor, "#888")
                cols[i % 5].markdown(
                    f'<div style="background:{color};color:white;border-radius:8px;'
                    f'padding:12px;text-align:center">'
                    f'<strong>{vendor}</strong><br/>'
                    f'<span style="font-size:1.5rem;font-weight:900">{n}</span> 項</div>',
                    unsafe_allow_html=True,
                )
            con.close()

        st.divider()

        # ── 篩選列 + 新增按鈕 ────────────────────────────────────────────────
        _all_cats = ["全部", "蛋白質", "主食", "蔬果", "乳製品", "保健品", "即食",
                     "甜食", "甜點", "飲料", "咖啡", "酒類", "有機食品"]
        if _is_admin:
            fc1, fc2, fc3, fc4 = st.columns([2, 2, 1, 1])
            sel_vendor = fc1.selectbox("通路", ["全部"] + _RETAIL_BRANDS, key="v_vendor", label_visibility="collapsed")
            sel_cat    = fc2.selectbox("分類", _all_cats, key="v_cat", label_visibility="collapsed")
            show_low   = fc3.checkbox("僅低庫存", key="v_low")
            _add_col   = fc4
        else:
            sel_vendor = _brand
            fc1, fc2, fc3 = st.columns([2, 1, 1])
            sel_cat  = fc1.selectbox("分類", _all_cats, key="v_cat", label_visibility="collapsed")
            show_low = fc2.checkbox("僅低庫存", key="v_low")
            _add_col = fc3

        if _add_col.button("➕ 新增", key="btn_add_product", use_container_width=True, type="primary"):
            _dialog_add_product(_brand, _is_admin)

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
                col_info, col_stock, col_btn, col_del = st.columns([5, 1, 1, 1])

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
                    if st.button("✏️ 編輯", key=f"edit_{p['id']}"):
                        st.session_state[f"editing_{p['id']}"] = True

                with col_del:
                    if st.button("🗑️", key=f"del_{p['id']}", help="刪除此商品"):
                        st.session_state[f"confirm_del_{p['id']}"] = True
                if st.session_state.get(f"confirm_del_{p['id']}"):
                    st.warning(f"確定要刪除「{p['name']}」？")
                    _dc1, _dc2 = st.columns(2)
                    if _dc1.button("確認刪除", key=f"do_del_{p['id']}", type="primary"):
                        delete_product(p["id"])
                        st.session_state.pop(f"confirm_del_{p['id']}", None)
                        st.rerun()
                    if _dc2.button("取消", key=f"cancel_del_{p['id']}"):
                        st.session_state.pop(f"confirm_del_{p['id']}", None)
                        st.rerun()

                if st.session_state.get(f"editing_{p['id']}"):
                    _all_cat_opts = ["蛋白質", "主食", "蔬果", "乳製品", "保健品", "即食",
                                     "甜食", "甜點", "飲料", "咖啡", "酒類", "有機食品"]
                    with st.form(f"form_{p['id']}"):
                        st.markdown(f"**✏️ 編輯商品：{p['name']}**")
                        e1, e2 = st.columns(2)
                        new_name  = e1.text_input("商品名稱", value=p["name"])
                        new_cat   = e2.selectbox("分類", _all_cat_opts,
                                                 index=_all_cat_opts.index(p["category"]) if p["category"] in _all_cat_opts else 0)
                        e3, e4, e5, e6 = st.columns(4)
                        new_price    = e3.number_input("售價 ($)", min_value=0, max_value=99999, value=int(p["price"]))
                        new_stock_v  = e4.number_input("庫存",     min_value=0, max_value=99999, value=int(p["stock"]))
                        new_protein  = e5.number_input("蛋白質 (g)", min_value=0.0, max_value=999.0,
                                                        value=float(p["protein_g"]), step=0.1, format="%.1f")
                        new_calories = e6.number_input("熱量 (kcal)", min_value=0, max_value=9999, value=int(p["calories"]))
                        c1, c2 = st.columns(2)
                        save   = c1.form_submit_button("✅ 儲存", type="primary")
                        cancel = c2.form_submit_button("取消")
                    if save:
                        update_product(p["id"], new_name, new_cat, new_protein, new_calories, new_price, new_stock_v)
                        st.session_state[f"editing_{p['id']}"] = False
                        st.success(f"已更新「{new_name}」")
                        st.rerun()
                    if cancel:
                        st.session_state[f"editing_{p['id']}"] = False
                        st.rerun()



# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 採買諮詢單
# ══════════════════════════════════════════════════════════════════════════════

with (tab2 if tab2 is not None else _null):
    if _is_insurance:
        st.markdown("#### 🛡️ 用戶旅遊保險申請單，在此審核、發送保單、確認生效。")
        st.caption("四步流程：收到申請 → 發送保單給用戶簽名 → 確認用戶簽名 → 確認生效")
    elif _is_finance:
        st.markdown("#### 💰 用戶理財諮詢申請單，在此回覆並安排專員聯繫。")
        st.caption(f"登入帳號：**{st.session_state.get('vendor_store','')}**　｜　顯示 goal 含「理財/投資/股票/基金/證券」的諮詢單")
    else:
        st.markdown("#### 用戶透過 AI 助手提交的採買諮詢，在此確認接單或拒絕並派送。")
        st.caption("派送操作透過 **mcp.Client** 真實呼叫 `dispatch_delivery` MCP 工具。")

    _SICON = {"全部": "📋", "待處理": "⏳", "待簽名": "✍️", "待後台確認": "🔍", "配送中": "🚚", "預留中": "📦", "已拒絕": "❌", "已完成": "✅"}
    if _is_insurance:
        status_opts = ["全部", "待處理", "待簽名", "待後台確認", "已拒絕", "已完成"]
    elif _is_finance or _is_gym_only:
        status_opts = ["全部", "待處理", "已拒絕", "已完成"]
    else:
        status_opts = ["全部", "待處理", "配送中", "預留中", "已拒絕", "已完成"]
    _rf_col, _sel_col = st.columns([1, 8])
    if _rf_col.button("🔄", key="inq_refresh", help="重新整理"):
        st.rerun()
    sel_status = _sel_col.radio(
        "狀態篩選", status_opts,
        format_func=lambda s: f"{_SICON.get(s, '')} {s}",
        horizontal=True, key="inq_status", label_visibility="collapsed",
    )

    inquiries = get_inquiries(sel_status, st.session_state.get("vendor_store"), brand=_brand_v, is_gym=_is_gym_only, is_insurance=_is_insurance, is_finance=_is_finance)
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
            inq_id   = inq["feedback_no"]

            # 卡片間距
            st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

            _is_ins_inq    = "保險" in (inq.get("goal") or "")
            _is_course_inq = inq.get("goal","").startswith("課程報名")
            _is_service_inq = _is_ins_inq or (_is_gym_only and _is_course_inq) or _is_finance
            _dtype = inq.get("delivery_type") or "外送"
            _dtcfg = DELIVERY_TYPE_CFG.get(_dtype, DELIVERY_TYPE_CFG["外送"])
            if _is_finance:
                _dtype_badge = '<span style="background:#1B5E20;color:white;border-radius:10px;padding:2px 8px;font-size:0.78rem;font-weight:700;white-space:nowrap">💰 理財諮詢</span>'
            elif _is_ins_inq:
                _dtype_badge = '<span style="background:#6A1B9A;color:white;border-radius:10px;padding:2px 8px;font-size:0.78rem;font-weight:700;white-space:nowrap">🛡️ 保險申請</span>'
            elif _is_course_inq:
                _dtype_badge = '<span style="background:#0277BD;color:white;border-radius:10px;padding:2px 8px;font-size:0.78rem;font-weight:700;white-space:nowrap">🏋️ 課程報名</span>'
            else:
                _dtype_badge = (
                    f'<span style="background:{_dtcfg["color"]};color:white;border-radius:10px;'
                    f'padding:2px 8px;font-size:0.78rem;font-weight:700;white-space:nowrap">'
                    f'{_dtcfg["icon"]} {_dtcfg["label"]}</span>'
                )

            with st.container(border=True):
                # ── 卡片 Header：顏色條 + 狀態標籤 + 單號 + 時間 ────────────
                st.markdown(
                    f'<div style="background:{s_color}22;border-left:5px solid {s_color};'
                    f'border-radius:4px;padding:8px 12px;margin-bottom:8px;'
                    f'display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
                    f'<span style="background:{s_color};color:white;border-radius:12px;'
                    f'padding:3px 10px;font-size:0.82rem;font-weight:700;white-space:nowrap">'
                    f'{s_icon} {status}</span>'
                    f'{_dtype_badge}'
                    f'<span style="font-weight:700;font-family:monospace;font-size:0.9rem">{inq_id}</span>'
                    f'<span style="margin-left:auto;color:#888;font-size:0.78rem">'
                    f'{str(inq.get("created_at",""))[:16]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── 第二行：地址資訊（服務類諮詢單不顯示）─────────────────
                if not _is_service_inq:
                    _addr = inq.get("address", "")
                    _pickup = inq.get("pickup_store", "")
                    if _dtype == "外送" and _addr:
                        st.info(f"🚚 **外送地址：** {_addr}")
                    elif _dtype == "自取":
                        _pickup_txt = f"偏好門市：**{_pickup}**" if _pickup else "門市未指定"
                        st.success(f"🏃 **自取** — {_pickup_txt}")

                # ── 第三行：目標 ｜ 聯絡人 ｜ 預算 ─────────────────────────
                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown("**🎯 目標**")
                    st.markdown(inq.get("goal") or "—")
                    _kw_disp = inq.get("keyword", "")
                    if _is_ins_inq and _kw_disp:
                        st.caption(f"身份證字號：{_kw_disp}")
                    elif _kw_disp and not _kw_disp.isdigit():
                        st.caption(f"關鍵字：{_kw_disp}")
                    if inq.get("note"):
                        st.caption(f"備註：{inq['note']}")
                with d2:
                    st.markdown("**👤 聯絡人**")
                    st.markdown(inq.get("contact_name") or "—")
                    st.caption(f"📞 {inq.get('contact_phone') or '—'}")
                with d3:
                    budget_val = inq.get("budget") or 0
                    st.markdown("**💰 預算**")
                    st.markdown(f"{'$' + str(budget_val) if budget_val else '—'}")

                # ── 推薦商品清單（依通路分組）────────────────────────────────
                pj = inq.get("products_json", "")
                if pj and not _is_service_inq:
                    try:
                        plist = json.loads(pj)
                        if plist:
                            by_v: dict = {}
                            for p in plist:
                                by_v.setdefault(p.get("vendor", "其他"), []).append(p)
                            total_items = sum(len(v) for v in by_v.values())
                            with st.expander(f"📦 推薦商品清單（{total_items} 項 / {len(by_v)} 通路）"):
                                for vendor, items in by_v.items():
                                    color = VENDOR_COLOR.get(vendor, "#888")
                                    st.markdown(
                                        f'<span style="background:{color};color:white;'
                                        f'border-radius:4px;padding:2px 8px;font-size:0.8rem;'
                                        f'font-weight:600">{vendor}</span>',
                                        unsafe_allow_html=True,
                                    )
                                    for p in items:
                                        _qty = p.get("qty", 1)
                                        _qty_badge = (
                                            f'<span style="background:#1976D2;color:white;'
                                            f'border-radius:8px;padding:1px 7px;font-size:0.8rem;'
                                            f'font-weight:700">x{_qty}</span> '
                                            if _qty > 1 else ""
                                        )
                                        st.markdown(
                                            f"&nbsp;&nbsp;• {_qty_badge}**{p.get('name','')}** — "
                                            f"${p.get('price',0)} ｜ "
                                            f"蛋白質 {p.get('protein_g',0)}g ｜ "
                                            f"庫存 {p.get('stock',0)}",
                                            unsafe_allow_html=True,
                                        )
                                    st.markdown("")
                    except Exception:
                        pass

                # ── Delivery info（外送記錄，支援多通路分批配送）──────────────
                dispatches = get_dispatches(inq_id)
                if dispatches and not _is_service_inq:
                    for _d in dispatches:
                        _dco  = _d.get("delivery_company", "")
                        _dico = DELIVERY_ICON.get(_dco, "📦") if _dco else "🚚"
                        _trk  = _d.get("tracking_no", "")
                        _mins = _d.get("estimated_minutes", 60)
                        _eta  = f"約 {_mins//1440} 天" if _mins >= 1440 else f"{_mins} 分鐘"
                        _trk_part = f"　｜　🔍 `{_trk}`" if _trk else ""
                        _dco_part = f"　｜　{_dico} {_dco}" if _dco else ""
                        st.success(
                            f"🚚 **{_d['vendor_name']}** ｜ 外送單：`{_d['order_no']}`"
                            f"{_dco_part}{_trk_part}　｜　預計 {_eta} 送達"
                        )

                # ── 用戶上傳照片 / 保險簽名 ─────────────────────────────────
                _imgs = []
                try:
                    _imgs = json.loads(inq.get("images_json", "[]") or "[]")
                except Exception:
                    pass

                if _imgs:
                    _exp_label = "✍️ 申請人簽名" if _is_ins_inq else f"📷 用戶上傳照片（{len(_imgs)} 張）"
                    with st.expander(_exp_label, expanded=_is_ins_inq):
                        _icols = st.columns(min(len(_imgs), 3))
                        for _ii, _ip in enumerate(_imgs):
                            if os.path.exists(_ip):
                                _icols[_ii % 3].image(_ip, caption="電子簽名" if _is_ins_inq else None, use_container_width=True)
                            else:
                                _icols[_ii % 3].caption(f"📎 {_ip}")

                # ── 保險申請：四步流程操作 ─────────────────────────────────
                if _is_ins_inq and _is_insurance and status not in ("已完成", "已拒絕"):
                    st.divider()
                    st.markdown("#### 📋 保單操作")

                    if status == "待處理":
                        # Step 1: 後台審核 → 發送保單給用戶簽名
                        st.info("📋 請確認申請內容後，點擊「發送保單」產生正式保單供用戶電子簽名。")
                        _ins_b1, _ins_b2 = st.columns(2)
                        if _ins_b1.button("📤 發送保單給用戶簽名", key=f"ins_send_{inq_id}", type="primary", use_container_width=True):
                            st.session_state[f"ins_act_{inq_id}"] = "send"
                        if _ins_b2.button("❌ 拒絕申請", key=f"ins_reject_{inq_id}", use_container_width=True):
                            st.session_state[f"ins_act_{inq_id}"] = "reject"

                        if st.session_state.get(f"ins_act_{inq_id}") == "send":
                            _contract_preview = f"""統超保險旅遊綜合保險保單
申請單號：{inq_id}　　申請人：{inq.get('contact_name','')}

【承保範圍】
・意外死亡及傷殘保險金（最高 NT$300 萬）
・海外突發疾病醫療費用（最高 NT$50 萬）
・旅遊行程延誤補償（逾 6 小時每次 NT$1,000，上限 NT$3,000）
・旅行文件遺失緊急協助服務

【保險期間】以申請書所載旅遊出發日起至返回日止。

【重要事項】
1. 被保險人須年滿 15 歲，未滿 75 歲。
2. 旅遊目的地不得為外交部「警告」或「不建議前往」地區。
3. 事故發生後應於 30 日內申請理賠。

【除外責任】故意行為、戰爭、核子輻射所致事故不予承保。

統超保險經紀人股份有限公司"""
                            with st.form(f"ins_send_form_{inq_id}"):
                                _edited_contract = st.text_area(
                                    "📄 保單內容（可編輯後再發送）",
                                    value=_contract_preview,
                                    height=300,
                                    key=f"ins_contract_{inq_id}",
                                )
                                _extra_note = st.text_area(
                                    "補充說明給用戶（選填）",
                                    placeholder="例：此保單已包含您提及的澎湖旅遊，請仔細閱讀後簽名。",
                                    key=f"ins_extra_{inq_id}",
                                )
                                _sc1, _sc2 = st.columns(2)
                                _do_send   = _sc1.form_submit_button("📤 確認發送，通知用戶簽名", type="primary")
                                _do_cancel = _sc2.form_submit_button("取消")
                            if _do_send:
                                _idb = _db()
                                _now_str = datetime.now().strftime('%m/%d %H:%M')
                                _msg = f"{_now_str} [統超保險]: 您好，您的旅遊保險申請已核閱完畢，請登入「統一生活管家」→「我的訂單」，找到此申請單號並點擊「✍️ 簽署保單」完成電子簽名。\n"
                                if _extra_note:
                                    _msg += f"{_now_str} [統超保險]: {_extra_note}\n"
                                _idb.execute(
                                    "UPDATE pms_form_feedback SET status='待簽名', accepted_at=?, vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                                    (datetime.now().isoformat(), _msg, inq_id),
                                )
                                _idb.commit()
                                _urow2 = _idb.execute(
                                    "SELECT email, username FROM users WHERE id=?", (inq.get("user_id", 0),)
                                ).fetchone()
                                _idb.close()
                                if _urow2 and _urow2["email"]:
                                    try:
                                        _send_email(
                                            to_email=_urow2["email"],
                                            subject=f"【統超保險】您的旅遊保險 {inq_id} 保單已產生，請簽名確認",
                                            body=(
                                                f"親愛的 {_urow2['username']} 您好，\n\n"
                                                f"您的旅遊保險申請（申請單號：{inq_id}）已由統超保險核閱完畢，"
                                                f"保單已準備就緒。\n\n"
                                                f"請登入「統一生活管家」→「我的訂單」→ 找到此申請單號 → 點擊「✍️ 簽署保單」完成電子簽名。\n\n"
                                                + (f"保險專員留言：{_extra_note}\n\n" if _extra_note else "")
                                                + f"保單摘要：\n{_edited_contract}\n\n"
                                                f"統超保險經紀人 敬上"
                                            ),
                                        )
                                    except Exception:
                                        pass
                                st.success(f"✅ 保單已發送！已通知用戶前往電子簽名。")
                                st.session_state.pop(f"ins_act_{inq_id}", None)
                                st.rerun()
                            if _do_cancel:
                                st.session_state.pop(f"ins_act_{inq_id}", None)
                                st.rerun()

                        elif st.session_state.get(f"ins_act_{inq_id}") == "reject":
                            with st.form(f"ins_rej_form_{inq_id}"):
                                st.markdown("**確認拒絕此保險申請**")
                                _rj_reason = st.text_area("拒絕原因", placeholder="例：所申請旅遊目的地列為警示地區，無法承保", key=f"ins_rj_{inq_id}")
                                _rc1, _rc2 = st.columns(2)
                                _do_rj   = _rc1.form_submit_button("確認拒絕", type="secondary")
                                _do_rjc  = _rc2.form_submit_button("取消")
                            if _do_rj:
                                _idb = _db()
                                _idb.execute(
                                    "UPDATE pms_form_feedback SET status='已拒絕', vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                                    (f"{datetime.now().strftime('%m/%d %H:%M')} [統超保險]: {_rj_reason or '申請未通過審核，如有疑問請聯繫統超保險經紀人。'}\n", inq_id),
                                )
                                _idb.commit(); _idb.close()
                                st.warning(f"申請 {inq_id} 已拒絕。")
                                st.session_state.pop(f"ins_act_{inq_id}", None)
                                st.rerun()
                            if _do_rjc:
                                st.session_state.pop(f"ins_act_{inq_id}", None)
                                st.rerun()

                    elif status == "待簽名":
                        # Step 2: Waiting for user to sign
                        st.warning("⏳ 等待用戶登入並簽署保單中...")
                        if st.button("↩️ 撤回保單（重設為待處理）", key=f"ins_recall_{inq_id}", use_container_width=True):
                            _idb = _db()
                            _idb.execute(
                                "UPDATE pms_form_feedback SET status='待處理', vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                                (f"{datetime.now().strftime('%m/%d %H:%M')} [統超保險]: 保單已撤回，請重新申請或聯繫客服。\n", inq_id),
                            )
                            _idb.commit(); _idb.close()
                            st.rerun()

                    elif status == "待後台確認":
                        # Step 3: User signed, backend confirms
                        st.success("✅ 用戶已完成電子簽名，請確認後使保單生效。")
                        _ins_c1, _ins_c2 = st.columns(2)
                        if _ins_c1.button("✅ 確認生效", key=f"ins_approve_{inq_id}", type="primary", use_container_width=True):
                            _idb = _db()
                            _idb.execute(
                                "UPDATE pms_form_feedback SET status='已完成', accepted_at=?, vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                                (datetime.now().isoformat(),
                                 f"{datetime.now().strftime('%m/%d %H:%M')} [統超保險]: 保單已確認生效，電子保單將另行寄送至您的信箱。\n",
                                 inq_id),
                            )
                            _idb.commit()
                            _urow = _idb.execute(
                                "SELECT email, username FROM users WHERE id=?", (inq.get("user_id", 0),)
                            ).fetchone()
                            _idb.close()
                            if _urow and _urow["email"]:
                                try:
                                    _send_email(
                                        to_email=_urow["email"],
                                        subject=f"【統超保險】您的旅遊保險 {inq_id} 已確認生效",
                                        body=(
                                            f"親愛的 {_urow['username']} 您好，\n\n"
                                            f"您的旅遊保險申請（申請單號：{inq_id}）已由統超保險經紀人確認生效。\n\n"
                                            f"保單詳情：\n{inq.get('note','')}\n\n"
                                            f"如有任何問題，請至「統一生活管家」我的訂單查詢，或聯繫統超保險經紀人。\n\n統超保險經紀人 敬上"
                                        ),
                                    )
                                except Exception:
                                    pass
                            st.success(f"✅ 保單 {inq_id} 已確認生效，Email 通知已發送！")
                            st.rerun()
                        if _ins_c2.button("❌ 拒絕申請", key=f"ins_reject_{inq_id}", use_container_width=True):
                            _idb = _db()
                            _idb.execute(
                                "UPDATE pms_form_feedback SET status='已拒絕', vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                                (f"{datetime.now().strftime('%m/%d %H:%M')} [統超保險]: 申請未通過審核，如有疑問請聯繫統超保險經紀人。\n", inq_id),
                            )
                            _idb.commit(); _idb.close()
                            st.warning(f"申請 {inq_id} 已拒絕。")
                            st.rerun()

                # ── 雙向訊息紀錄 ─────────────────────────────────────────────
                import re as _re
                def _parse_msg_lines(text, role):
                    out = []
                    for l in text.split("\n"):
                        l = l.strip()
                        if not l:
                            continue
                        m = _re.match(r'^(\d{2}/\d{2} \d{2}:\d{2})\s*\[.*?\]:\s*(.*)', l)
                        if m:
                            out.append((m.group(1), role, m.group(2).strip()))
                        else:
                            out.append(("", role, l))
                    return out

                _all_msgs = (
                    _parse_msg_lines(inq.get("vendor_reply", ""), "vendor") +
                    _parse_msg_lines(inq.get("user_reply",   ""), "user")
                )
                _all_msgs.sort(key=lambda x: x[0])
                _msg_total = len(_all_msgs)

                with st.expander(f"💬 訂單訊息（{_msg_total} 則）", expanded=_msg_total > 0):
                    if _all_msgs:
                        for _ts, _role, _content in _all_msgs:
                            if _role == "vendor":
                                with st.chat_message("assistant"):
                                    if status == "已拒絕" and _all_msgs.index((_ts, _role, _content)) == 0:
                                        st.error(_content)
                                    else:
                                        st.write(_content)
                                    if _ts:
                                        st.caption(f"🏪 商家　{_ts}")
                            else:
                                with st.chat_message("user"):
                                    st.write(_content)
                                    if _ts:
                                        st.caption(f"👤 用戶　{_ts}")
                        st.divider()
                    else:
                        st.caption("尚無訊息紀錄")
                    with st.form(f"msg_form_{inq_id}"):
                        new_msg = st.text_input("輸入要傳送給用戶的訊息", key=f"msg_input_{inq_id}")
                        if st.form_submit_button("📤 送出給用戶"):
                            if new_msg:
                                con = _db()
                                store = st.session_state.get("vendor_store", "商家")
                                msg_entry = f"{datetime.now().strftime('%m/%d %H:%M')} [{store}]: {new_msg}\n"
                                con.execute(
                                    "UPDATE pms_form_feedback SET vendor_reply = COALESCE(vendor_reply,'') || ? WHERE feedback_no=?",
                                    (msg_entry, inq_id),
                                )
                                con.commit(); con.close()
                                st.rerun()
                            else:
                                st.warning("請輸入訊息內容。")

                # ── 2. 派送操作（待處理=首次接單；配送中=其他通路加入分批配送）──
                _vendor_brand = st.session_state.get("vendor_brand", "全部")
                _vendor_store = st.session_state.get("vendor_store", "管理員")
                _already_this_vendor = any(
                    _vendor_store in d["vendor_name"] or d["vendor_name"] in _vendor_store
                    for d in dispatches
                )

                # ── 理財諮詢：專屬操作區 ────────────────────────────────────
                if _is_finance and status not in ("已完成", "已拒絕"):
                    st.divider()
                    st.markdown("#### 💰 理財諮詢操作")
                    _fc1, _fc2 = st.columns(2)
                    if _fc1.button("✅ 已安排專員聯繫，標記完成", key=f"fin_done_{inq_id}", type="primary", use_container_width=True):
                        _fdb = _db()
                        _fdb.execute(
                            "UPDATE pms_form_feedback SET status='已完成', accepted_at=?, vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                            (datetime.now().isoformat(),
                             f"{datetime.now().strftime('%m/%d %H:%M')} [統一證券]: 已安排專員與您聯繫，感謝您的查詢。\n",
                             inq_id),
                        )
                        _fdb.commit()
                        _urow_f = _fdb.execute("SELECT email, username FROM users WHERE id=?", (inq.get("user_id",0),)).fetchone()
                        _fdb.close()
                        if _urow_f and _urow_f["email"]:
                            try:
                                _send_email(
                                    to_email=_urow_f["email"],
                                    subject=f"【統一證券】您的理財諮詢 {inq_id} 已安排專員聯繫",
                                    body=(
                                        f"親愛的 {_urow_f['username']} 您好，\n\n"
                                        f"您的理財諮詢申請（申請單號：{inq_id}）已由統一證券專員接手，"
                                        f"將盡快以電話或 Email 與您聯繫。\n\n"
                                        f"諮詢內容：{inq.get('note','')}\n\n統一證券 敬上"
                                    ),
                                )
                            except Exception:
                                pass
                        st.success("✅ 已標記完成，Email 通知已發送！")
                        st.rerun()
                    if _fc2.button("❌ 拒絕申請", key=f"fin_rej_{inq_id}", use_container_width=True):
                        _fdb = _db()
                        _fdb.execute(
                            "UPDATE pms_form_feedback SET status='已拒絕', vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                            (f"{datetime.now().strftime('%m/%d %H:%M')} [統一證券]: 很抱歉，目前無法受理此諮詢申請。\n", inq_id),
                        )
                        _fdb.commit(); _fdb.close()
                        st.warning(f"諮詢 {inq_id} 已拒絕。")
                        st.rerun()

                if not _is_finance and status not in ("已拒絕", "已完成", "待簽名", "待後台確認") and not _already_this_vendor and not (_is_ins_inq and _is_insurance):
                    st.divider()
                    if status == "待處理":
                        if _dtype == "自取":
                            b1, b2, b3 = st.columns([2, 2, 3])
                            if b1.button("📦 預留商品", key=f"rsv_{inq['id']}", type="primary"):
                                st.session_state[f"act_{inq_id}"] = "reserve"
                            if b2.button("❌ 拒絕", key=f"rej_{inq['id']}"):
                                st.session_state[f"act_{inq_id}"] = "reject"
                        else:
                            b1, b2, _ = st.columns([2, 2, 3])
                            if b1.button("✅ 接受", key=f"acc_{inq['id']}", type="primary"):
                                st.session_state[f"act_{inq_id}"] = "accept"
                            if b2.button("❌ 拒絕", key=f"rej_{inq['id']}"):
                                st.session_state[f"act_{inq_id}"] = "reject"
                    elif status == "配送中":
                        if st.button(
                            f"📦 加入配送（{_vendor_brand} 本通路商品）",
                            key=f"join_{inq['id']}", type="secondary",
                        ):
                            st.session_state[f"act_{inq_id}"] = "accept"
                    elif status == "預留中":
                        if st.button("✅ 確認顧客已取件", key=f"done_{inq['id']}", type="primary"):
                            st.session_state[f"act_{inq_id}"] = "complete"

                    action = st.session_state.get(f"act_{inq_id}")

                    # ── 接受表單：課程報名 vs 商品派送 ──────────────────────
                    if action == "accept":
                        _is_enroll_inq = inq.get("goal", "").startswith("課程報名：")

                        if _is_enroll_inq:
                            # ── 課程報名確認（直接通知，不需派送）──
                            with st.form(f"acc_form_{inq_id}"):
                                st.markdown("**確認接受課程報名**")
                                st.info(f"📋 {inq.get('goal', '')}")
                                v_reply = st.text_area(
                                    "給用戶的通知訊息",
                                    value="感謝您的報名！您的報名已確認，待開課日期確定後，我們將主動通知您。",
                                    key=f"v_reply_{inq_id}",
                                )
                                fc1, fc2 = st.columns(2)
                                do_accept = fc1.form_submit_button("✅ 確認接受報名", type="primary")
                                do_cancel = fc2.form_submit_button("取消")

                            if do_accept:
                                _now_e = datetime.now().isoformat()
                                _kw_e  = inq.get("keyword", "")
                                _ec = _db()
                                _ec.execute(
                                    "UPDATE pms_form_feedback SET status='已完成', vendor_reply=?, accepted_at=? WHERE feedback_no=?",
                                    (v_reply, _now_e, inq_id),
                                )
                                if _kw_e:
                                    # keyword 可能是單一 id 或逗號分隔多個 id
                                    for _kid in str(_kw_e).split(","):
                                        try:
                                            _cid = int(_kid.strip())
                                            _ec.execute(
                                                "UPDATE gym_course SET enrolled = enrolled + 1 WHERE id = ?",
                                                (_cid,),
                                            )
                                        except Exception:
                                            pass
                                    _ec.execute(
                                        "UPDATE course_enrollment SET status = '已確認' WHERE feedback_no = ?",
                                        (inq_id,),
                                    )
                                _ec.commit()
                                # 發報名確認 Email
                                _fb_row = _ec.execute(
                                    "SELECT user_id, contact_name FROM pms_form_feedback WHERE feedback_no=?",
                                    (inq_id,)
                                ).fetchone()
                                if _fb_row and _fb_row["user_id"]:
                                    _urow = _ec.execute(
                                        "SELECT email, username FROM users WHERE id=?",
                                        (_fb_row["user_id"],)
                                    ).fetchone()
                                    if _urow and _urow["email"]:
                                        from mcp_server import _send_email as _se
                                        _goal = inq.get("goal", "課程")
                                        _se(
                                            to_email=_urow["email"],
                                            subject=f"【統一生活管家】{_goal} 報名已確認",
                                            body=(
                                                f"您好 {_urow['username']}，\n\n"
                                                f"✅ 您的{_goal}報名已由後台確認！\n\n"
                                                + (f"📩 後台訊息：{v_reply}\n\n" if v_reply else "")
                                                + f"感謝您使用統一生活管家，期待在課堂上見到您！"
                                            ),
                                        )
                                _ec.close()
                                st.success("✅ 報名已確認！Email 通知已發送給用戶。")
                                st.session_state.pop(f"act_{inq_id}", None)
                                st.rerun()

                            if do_cancel:
                                st.session_state.pop(f"act_{inq_id}", None)
                                st.rerun()

                        else:
                            # ── 商品採買接受並派送（mcp.Client → dispatch_delivery）──
                            _my_brand = _vendor_brand if _vendor_brand != "全部" else ""
                            _my_prods = []
                            if pj:
                                try:
                                    _all_prods = json.loads(pj)
                                    _my_prods  = [p for p in _all_prods
                                                  if not _my_brand or p.get("vendor") == _my_brand]
                                except Exception:
                                    pass
                            _store_list = get_brand_stores(_vendor_brand)

                            # ── 商品勾選（form 外，讓狀態即時反應）──
                            _chk_keys = []
                            if _my_prods:
                                st.markdown(f"**📦 勾選本通路可配送商品（共 {len(_my_prods)} 項）：**")
                                for _i, _p in enumerate(_my_prods):
                                    _ck = f"chk_{inq_id}_{_i}"
                                    _chk_keys.append((_ck, _p))
                                    st.checkbox(
                                        f"**{_p.get('name','')}** ｜ ${_p.get('price',0)} ｜ 蛋白質 {_p.get('protein_g',0)}g",
                                        value=st.session_state.get(_ck, True),
                                        key=_ck,
                                    )
                                st.divider()
                            elif not pj:
                                st.info("此諮詢單未指定商品，將直接安排配送。")

                            with st.form(f"acc_form_{inq_id}"):
                                st.markdown("**填寫配送資訊（將透過 mcp.Client 呼叫 dispatch_delivery）**")
                                if _store_list:
                                    v_name = st.selectbox("廠商 / 門市名稱", _store_list)
                                else:
                                    v_name = st.text_input("廠商 / 門市名稱", value=_vendor_store)

                                st.markdown("**配送業者**")
                                _dco_labels = [
                                    f"{DELIVERY_ICON.get(d, '📦')} {d}" for d in DELIVERY_COMPANIES
                                ]
                                _dco_idx = st.selectbox(
                                    "選擇配送業者", range(len(DELIVERY_COMPANIES)),
                                    format_func=lambda i: _dco_labels[i],
                                    key=f"dco_{inq_id}",
                                )
                                v_delivery_co = DELIVERY_COMPANIES[_dco_idx]
                                v_tracking = ""
                                if v_delivery_co != "自家配送（門市自送）":
                                    v_tracking = st.text_input(
                                        "物流追蹤單號（選填）",
                                        placeholder="例：1234567890",
                                        key=f"trk_{inq_id}",
                                    )
                                    v_mins = st.number_input("預計送達（天）", min_value=1, max_value=14, value=2,
                                                              help="第三方物流以天計算", key=f"mins_{inq_id}")
                                    v_mins = int(v_mins) * 24 * 60
                                else:
                                    v_mins = st.number_input("預計送達（分鐘）", min_value=15, max_value=300, value=60,
                                                              key=f"mins_{inq_id}")
                                    v_mins = int(v_mins)

                                v_reply = st.text_area("給用戶的回覆訊息", placeholder="例：已為您備妥商品，預計60分鐘內送達", key=f"v_reply_{inq_id}")
                                fc1, fc2 = st.columns(2)
                                do_accept = fc1.form_submit_button("✅ 確認接受（MCP 派送）", type="primary")
                                do_cancel = fc2.form_submit_button("取消")

                            if do_accept:
                                # 讀取勾選的商品
                                _sel_prods   = [p for (k, p) in _chk_keys if st.session_state.get(k, True)]
                                _unsel_prods = [p for (k, p) in _chk_keys if not st.session_state.get(k, True)]
                                _reply_final = v_reply or ""
                                if _unsel_prods:
                                    _unsel_names = "、".join(p.get("name","") for p in _unsel_prods)
                                    _reply_final += f"\n\n⚠️ 以下商品本通路暫無庫存，無法配送：{_unsel_names}"
                                if _sel_prods and _chk_keys:
                                    # 更新 DB 中的 products_json，只保留本通路接受的品項
                                    _other_prods = [p for p in json.loads(pj or "[]")
                                                    if p.get("vendor") != _my_brand]
                                    _new_pj = json.dumps(_sel_prods + _other_prods, ensure_ascii=False)
                                    _pj_con = _db()
                                    _pj_con.execute(
                                        "UPDATE pms_form_feedback SET products_json=? WHERE feedback_no=?",
                                        (_new_pj, inq_id),
                                    )
                                    _pj_con.commit(); _pj_con.close()
                                result = dispatch_via_mcp(
                                    inquiry_no=inq_id,
                                    vendor_name=v_name or _vendor_store,
                                    estimated_minutes=v_mins,
                                    reply_message=_reply_final,
                                    delivery_company=v_delivery_co,
                                    tracking_no=v_tracking,
                                )
                                if result.get("success"):
                                    _carrier = result.get("delivery_company", "")
                                    _carrier_icon = DELIVERY_ICON.get(_carrier, "📦")
                                    _trk = result.get("tracking_no", "")
                                    _carrier_line = (
                                        f"\n\n{_carrier_icon} **配送業者：** {_carrier}"
                                        + (f"　｜　🔍 **追蹤單號：** `{_trk}`" if _trk else "")
                                        if _carrier else ""
                                    )
                                    st.success(
                                        f"✅ 接單成功！已透過 **mcp.Client** 呼叫 dispatch_delivery\n\n"
                                        f"外送單號：`{result['delivery_no']}`"
                                        f"{_carrier_line}\n\n"
                                        f"{result['message']}"
                                    )
                                else:
                                    st.error(f"派送失敗：{result.get('message', '請稍後再試')}")
                                st.session_state.pop(f"act_{inq_id}", None)
                                st.rerun()

                            if do_cancel:
                                st.session_state.pop(f"act_{inq_id}", None)
                                st.rerun()

                    # ── 預留表單（自取訂單）─────────────────────────────────
                    elif action == "reserve":
                        with st.form(f"rsv_form_{inq_id}"):
                            st.markdown("**📦 確認預留商品（自取）**")
                            rsv_note = st.text_area(
                                "備注給顧客",
                                placeholder="例：商品已備妥，請於三日內持諮詢單號前來取件",
                                key=f"rsv_note_{inq_id}",
                            )
                            rsc1, rsc2 = st.columns(2)
                            do_reserve = rsc1.form_submit_button("📦 確認預留", type="primary")
                            do_cancel_r = rsc2.form_submit_button("取消")

                        if do_reserve:
                            reserve_inquiry(inq_id, _vendor_store, rsv_note)
                            st.success(f"✅ 已標記為預留中！等待顧客前來自取。")
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                        if do_cancel_r:
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                    # ── 確認已取件（預留中 → 已完成）──────────────────────────
                    elif action == "complete":
                        con = _db()
                        con.execute(
                            "UPDATE pms_form_feedback SET status='已完成' WHERE feedback_no=?",
                            (inq_id,),
                        )
                        con.commit(); con.close()
                        st.success("✅ 已標記為完成！")
                        st.session_state.pop(f"act_{inq_id}", None)
                        st.rerun()

                    # ── 拒絕表單（只有待處理才能拒絕）──────────────────────
                    elif action == "reject" and status == "待處理":
                        with st.form(f"rej_form_{inq_id}"):
                            st.markdown("**確認拒絕此諮詢單**")
                            r_reason = st.text_area("拒絕原因", placeholder="例：目前庫存不足，建議下週再訂", key=f"r_reason_{inq_id}")
                            rc1, rc2 = st.columns(2)
                            do_reject = rc1.form_submit_button("確認拒絕", type="secondary")
                            do_cancel2 = rc2.form_submit_button("取消")

                        if do_reject:
                            reject_inquiry(inq_id, r_reason, st.session_state.vendor_store)
                            st.info("已拒絕此諮詢單。")
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                        if do_cancel2:
                            st.session_state.pop(f"act_{inq_id}", None)
                            st.rerun()

                # ── 手動改變狀態（所有非終態訂單皆可操作）──────────────────
                if status not in ("已完成", "已拒絕"):
                    with st.expander("⚙️ 手動變更狀態", expanded=False):
                        _status_options = {
                            "待處理":   "⏳ 待處理",
                            "待簽名":   "✍️ 待簽名（等待用戶簽署）",
                            "待後台確認": "🔍 待後台確認（用戶已簽名）",
                            "預留中":   "📦 預留中（等待自取）",
                            "配送中":   "🚚 配送中",
                            "已完成":   "✅ 已完成",
                            "已拒絕":   "❌ 已拒絕",
                        }
                        _available = [s for s in _status_options if s != status]
                        with st.form(f"status_form_{inq_id}"):
                            new_status = st.selectbox(
                                "變更為",
                                _available,
                                format_func=lambda s: _status_options[s],
                                key=f"ns_{inq_id}",
                            )
                            status_note = st.text_input("備注（選填）", key=f"sn_{inq_id}")
                            if st.form_submit_button("確認變更"):
                                _con = _db()
                                _now = datetime.now().isoformat()
                                _note_entry = f"\n[{_vendor_store} {_now[:16]}] 狀態改為「{new_status}」" + (f"：{status_note}" if status_note else "")
                                _con.execute(
                                    "UPDATE pms_form_feedback SET status=?, vendor_reply=vendor_reply||? WHERE feedback_no=?",
                                    (new_status, _note_entry, inq_id),
                                )
                                _con.commit(); _con.close()
                                st.success(f"狀態已更新為「{new_status}」")
                                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AI 派送助手（真實 MCP）
# ══════════════════════════════════════════════════════════════════════════════

with (tab3 if tab3 is not None else _null):
    st.markdown("#### 🤖 AI 派送助手 + mcp.Client")
    st.caption(
        "透過 AI 對話自動呼叫 `dispatch_delivery` MCP 工具完成派送。\n\n"
        "範例：「請幫諮詢單 FB260708XXXXXX 安排萬家福信義店配送，40分鐘」"
    )
    st.divider()

    # 顯示待處理諮詢單摘要（提供 AI 參考）
    pending_inqs = get_inquiries("待處理", st.session_state.get("vendor_store"), brand=_brand_v, is_gym=_is_gym_only)
    if pending_inqs:
        with st.expander(f"📋 待處理諮詢單（{len(pending_inqs)} 筆）— 提供給 AI 參考", expanded=True):
            for inq in pending_inqs[:5]:
                st.markdown(
                    f"- `{inq['feedback_no']}` ｜ **{inq.get('goal', '—')}** ｜ "
                    f"聯絡：{inq.get('contact_name', '—')} {inq.get('contact_phone', '')} ｜ "
                    f"預算：{'$' + str(inq.get('budget', 0)) if inq.get('budget') else '—'}"
                )
            if len(pending_inqs) > 5:
                st.caption(f"...還有 {len(pending_inqs) - 5} 筆，請至「採買諮詢單」頁籤查看")
    else:
        st.info("目前沒有待處理的諮詢單。")

    st.divider()

    # AI 對話區
    if "admin_ollama_history" not in st.session_state:
        st.session_state.admin_ollama_history = []
    if "admin_mcp_log" not in st.session_state:
        st.session_state.admin_mcp_log = []

    # 顯示對話歷史
    for msg in st.session_state.admin_ollama_history:
        if msg["role"] == "system":
            continue
        avatar = "👤" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # 接收後台人員輸入
    admin_prompt = st.chat_input("輸入派送指令，例如：幫 IQ260708XXXXXX 安排萬家福信義店配送", key="admin_chat")
    if admin_prompt:
        with st.chat_message("user", avatar="👤"):
            st.markdown(admin_prompt)

        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("🤖 AI 透過 MCP 處理中..."):
                reply, tool_log, updated = admin_ollama_chat(
                    admin_prompt, st.session_state.admin_ollama_history
                )
                st.session_state.admin_ollama_history = updated
                st.session_state.admin_mcp_log.extend(tool_log)
            st.markdown(reply)

            # 顯示 MCP 工具呼叫結果
            for tc in tool_log:
                if tc["tool"] == "dispatch_delivery" and tc["result"].get("success"):
                    r = tc["result"]
                    st.success(
                        f"✅ **MCP dispatch_delivery 已執行**\n\n"
                        f"外送單號：`{r.get('delivery_no', '')}`\n\n"
                        f"{r.get('message', '')}"
                    )
                    st.rerun()

    # 清空 AI 對話
    if st.session_state.admin_ollama_history:
        st.divider()
        if st.button("🗑️ 清空 AI 對話", key="clear_admin_chat"):
            st.session_state.admin_ollama_history = []
            st.session_state.admin_mcp_log = []
            st.rerun()

    # MCP 工具呼叫紀錄
    if st.session_state.admin_mcp_log:
        st.divider()
        st.markdown("#### 🔌 MCP 工具呼叫紀錄（本次 session）")
        for entry in reversed(st.session_state.admin_mcp_log):
            with st.container(border=True):
                st.caption(f"🔴 **{entry['tool']}** · `{entry['ts']}`")
                st.json({"params": entry["params"], "result": entry["result"]})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MCP 工具總覽
# ══════════════════════════════════════════════════════════════════════════════

with (tab4 if tab4 is not None else _null):
    st.markdown("#### 本系統共整合 19 個 MCP 工具，由 FastMCP（fitness-grocery）提供。")
    st.caption(
        "前端 AI（Claude claude-sonnet-4-6）透過 **mcp.Client** 真實呼叫工具；"
        "後台 AI 助手也使用相同機制呼叫 dispatch_delivery 與 send_email_notification。"
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
                    f'<div style="background:#FFF3E0;color:#7F3B00;border-left:4px solid #FF9800;'
                    f'padding:6px 10px;border-radius:4px;font-size:0.85rem">'
                    f'⚠️ <strong>寫入工具</strong> — 調用方：{caller_label}</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="background:#E8F5E9;color:#1B5E20;border-left:4px solid #43A047;'
                    f'padding:6px 10px;border-radius:4px;font-size:0.85rem">'
                    f'✅ <strong>唯讀工具</strong> — 調用方：{t["caller"]}</div>',
                    unsafe_allow_html=True,
                )

    st.divider()
    st.markdown("#### 資料流程示意（真實 MCP 呼叫）")
    st.markdown("""
```
用戶輸入需求
  └─▶ Claude claude-sonnet-4-6（前端 AI）
        ├─▶ [工具01] search_grocery           🟢 依關鍵字搜尋健康商品
        ├─▶ [工具02] recommend_high_protein   🟢 目標+預算 → 最佳商品組合
        ├─▶ [工具03] check_inventory          🟢 查詢商品各通路庫存
        ├─▶ [工具06] get_current_time         🟢 取得台灣當前時間
        ├─▶ [工具07] get_weather              🟢 Open-Meteo 即時天氣 + 外出建議
        ├─▶ [工具08] search_recipe            🟢 Spoonacular/Edamam 食譜搜尋
        │               └─▶ [工具01] search_grocery  🟢 食譜相關商品推薦（AI 自動關聯）
        ├─▶ [工具10] find_nearby_stores       🟢 Overpass API 搜尋附近統一門市
        ├─▶ [工具12] analyze_meal_nutrition   🟢 指定克數計算熱量與三大營養素
        ├─▶ [工具13] recommend_after_meal     🟢 餐後缺口 → 推薦補充商品
        ├─▶ [工具14] calculate_tdee           🟢 BMR / TDEE / 三大營養素目標
        └─▶ [工具04] submit_inquiry           🔴 建立生活服務諮詢單（用戶雙重確認後）
                        │
                        ▼
              pms_form_feedback 表（butler.db）
                        │
              後台管理員 → AI 派送助手（Tab 3）
                        │
              後台 AI 助手
                        │
                        └─▶ [工具05] dispatch_delivery  🔴 建立外送單 + 扣庫存
                                        │
                                        ├─▶ [工具18] send_email_notification 🔴 自動發接單通知 Email
                                        │
                                        ▼
                              外送單 YYMMDDxxxxxxxx 建立（status=01 待取件）
                              inquiry.status = 配送中
                                        │
                              外送員 → Tab 5 接單（status=02 配送中）
                                        │
                                        └─▶ [工具09] find_route  🟢 OSRM 最佳配送路線
                                        │
                              外送員確認送達（status=03 已完成）
```
    """)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — 外送派件（外送員接單與路線規劃）
# ══════════════════════════════════════════════════════════════════════════════

if tab5 is not None:
    with tab5:
        st.markdown("#### 🚴 外送派件管理")
        st.caption(
            "外送員在此查看待取件訂單、接單後規劃最佳配送路線，完成後標記「已完成」。\n\n"
            "路線規劃透過 **find_route MCP 工具**（OSRM 最佳化演算法）計算最短路徑。"
        )

        DELIVERY_STATUS = {
            "01": {"label": "⏳ 待取件", "color": "#FF9800"},
            "02": {"label": "🚴 配送中", "color": "#1976D2"},
            "03": {"label": "✅ 已完成", "color": "#43A047"},
        }

        col_dr, col_rr = st.columns([3, 1])
        _driver_default = st.session_state.vendor_store if _is_driver else ""
        _driver_name = col_dr.text_input("外送員姓名", value=_driver_default, placeholder="輸入您的姓名以接單", key="driver_name")
        if col_rr.button("🔄 重新整理", use_container_width=True, key="del_refresh"):
            st.rerun()

        active_deliveries = get_active_deliveries()
        if not active_deliveries:
            st.info("目前沒有待配送的訂單。")
        else:
            st.caption(f"共 {len(active_deliveries)} 筆待處理外送單")
            st.divider()

            for dl in active_deliveries:
                dl_status = dl.get("status", "01")
                ds_cfg    = DELIVERY_STATUS.get(dl_status, {"label": dl_status, "color": "#888"})
                order_no  = dl["order_no"]

                with st.container(border=True):
                    h1, h2, h3 = st.columns([2, 3, 2])
                    h1.markdown(
                        f'<span style="background:{ds_cfg["color"]};color:white;border-radius:12px;'
                        f'padding:3px 10px;font-size:0.82rem;font-weight:700">{ds_cfg["label"]}</span>',
                        unsafe_allow_html=True,
                    )
                    h2.markdown(f"**`{order_no}`**")
                    h3.caption(str(dl.get("created_at", ""))[:16])

                    # 配送資訊
                    info1, info2 = st.columns(2)
                    with info1:
                        st.markdown(f"**取貨門市：** {dl.get('vendor_name','—')}")
                        st.markdown(f"**諮詢單：** `{dl.get('feedback_no','')}`")
                        if dl.get("driver_name"):
                            st.markdown(f"**外送員：** {dl['driver_name']}")
                        _dco = dl.get("delivery_company", "")
                        if _dco:
                            _dico = DELIVERY_ICON.get(_dco, "📦")
                            st.markdown(f"**配送業者：** {_dico} {_dco}")
                        _trk = dl.get("tracking_no", "")
                        if _trk:
                            st.markdown(f"**追蹤單號：** `{_trk}`")
                    with info2:
                        st.markdown(f"**收件人：** {dl.get('contact_name','—')}")
                        st.markdown(f"**電話：** {dl.get('contact_phone','—')}")
                        st.markdown(f"**目標：** {dl.get('goal','—')}")

                    # 配送地址
                    addr = dl.get("address", "")
                    if addr:
                        st.info(f"📍 **配送地址：** {addr}")
                    else:
                        st.warning("⚠️ 此訂單未填寫配送地址")

                    # 商品清單
                    pj = dl.get("products_json", "")
                    if pj:
                        try:
                            plist = json.loads(pj)
                            vendor_br = dl.get("vendor_name", "")
                            # Show only products from this vendor
                            brand_key = next((b for b in ["7-11", "萬家福", "康是美", "統一生機"] if b in vendor_br), "")
                            my_items  = [p for p in plist if not brand_key or p.get("vendor") == brand_key]
                            if my_items:
                                total_qty = sum(p.get("qty", 1) for p in my_items)
                                with st.expander(f"📦 取貨商品（{len(my_items)} 項 / 共 {total_qty} 件）"):
                                    for p in my_items:
                                        _q = p.get("qty", 1)
                                        st.markdown(f"• **{p.get('name','')}** × {_q} — ${p.get('price',0) * _q}")
                        except Exception:
                            pass

                    # 路線規劃
                    if addr:
                        with st.expander("🗺️ 查看配送路線（OSRM）", expanded=_is_driver):
                            if st.button("📍 計算最佳路線", key=f"btn_route_{order_no}", type="primary" if _is_driver else "secondary"):
                                with st.spinner("正在呼叫 find_route MCP 工具計算路線..."):
                                    try:
                                        from mcp_server import find_route as _find_route
                                        _vname = dl.get("vendor_name", "")
                                        _vkey  = _vname.split("門市")[0].split("信義")[0].split("中山")[0].strip()
                                        _con = _db()
                                        _vu = _con.execute(
                                            "SELECT address FROM vendor_users "
                                            "WHERE store_name=? AND address!='' LIMIT 1",
                                            (_vname,)
                                        ).fetchone()
                                        _sv = _con.execute(
                                            "SELECT address FROM cms_homepage_service_vendor "
                                            "WHERE name LIKE ? AND is_enable=1 AND address!='' LIMIT 1",
                                            (f"%{_vkey}%",)
                                        ).fetchone()
                                        _pv = _con.execute(
                                            "SELECT address FROM partner_vendor "
                                            "WHERE name LIKE ? AND is_enable=1 AND address!='' LIMIT 1",
                                            (f"%{_vkey}%",)
                                        ).fetchone()
                                        _con.close()
                                        _vaddr = (
                                            (_vu["address"] if _vu else None)
                                            or (_sv["address"] if _sv else None)
                                            or (_pv["address"] if _pv else None)
                                            or f"{_vname} 台灣"
                                        )
                                        stops = [{"name": _vname, "address": _vaddr}]
                                        # 組合完整地址（縣市＋區＋街道），提升 Nominatim 命中率
                                        _county = dl.get("county_name", "")
                                        _dist   = dl.get("district_name", "")
                                        _full_addr = (
                                            (_county + _dist + addr) if (_county and addr)
                                            else (addr + " 台灣" if addr else "")
                                        )
                                        _rr = json.loads(_find_route(
                                            stops_json=json.dumps(stops, ensure_ascii=False),
                                            dest_address=_full_addr,
                                        ))
                                        st.session_state[f"route_{order_no}"] = _rr
                                    except Exception as e:
                                        st.error(f"路線計算失敗：{e}")
                                        st.session_state.pop(f"route_{order_no}", None)

                            # 顯示路線結果 + 地圖（從 session_state 讀取，跨 rerun 保持）
                            _rr = st.session_state.get(f"route_{order_no}")
                            if _rr:
                                if _rr.get("success"):
                                    _src = _rr.get("source", "")
                                    st.success(f"{'🌐 OSRM' if _src=='OSRM' else '📐 近鄰演算法'} — {_rr.get('message','')}")
                                    for _step in _rr.get("route", []):
                                        st.markdown(
                                            f"**{_step['order']}.** {_step['name']}"
                                            + (f"  \n&nbsp;&nbsp;&nbsp;📍 {_step['address']}" if _step.get('address') else "")
                                        )
                                    if _rr.get("total_distance_km"):
                                        _mc1, _mc2 = st.columns(2)
                                        _mc1.metric("總距離", f"{_rr['total_distance_km']} km")
                                        _mc2.metric("預計時間", f"{_rr['estimated_minutes']} 分鐘")

                                    # 地圖
                                    _route_pts = _rr.get("route", [])
                                    _geometry  = _rr.get("geometry", [])
                                    if _route_pts:
                                        import folium
                                        from streamlit_folium import st_folium
                                        _clat = sum(s["lat"] for s in _route_pts) / len(_route_pts)
                                        _clng = sum(s["lng"] for s in _route_pts) / len(_route_pts)
                                        _fm = folium.Map(location=[_clat, _clng], zoom_start=13)
                                        for _step in _route_pts:
                                            _is_dest = _step["order"] == len(_route_pts)
                                            folium.Marker(
                                                [_step["lat"], _step["lng"]],
                                                popup=folium.Popup(
                                                    f"{_step['order']}. {_step['name']}<br>{_step.get('address','')}",
                                                    max_width=200,
                                                ),
                                                icon=folium.Icon(
                                                    color="red" if _is_dest else "blue",
                                                    icon="flag" if _is_dest else "shopping-cart",
                                                    prefix="fa",
                                                ),
                                            ).add_to(_fm)
                                        if _geometry:
                                            _poly = [[c[1], c[0]] for c in _geometry]
                                            folium.PolyLine(_poly, color="#1976D2", weight=5, opacity=0.8).add_to(_fm)
                                        else:
                                            _straight = [[s["lat"], s["lng"]] for s in _route_pts]
                                            folium.PolyLine(_straight, color="#888", weight=3, dash_array="10").add_to(_fm)
                                        st_folium(_fm, use_container_width=True, height=420, key=f"map_{order_no}")
                                else:
                                    st.warning(_rr.get("message", "路線計算失敗"))

                    # 操作按鈕
                    st.divider()
                    if dl_status == "01":
                        if st.button("🚴 接單並出發", key=f"accept_dl_{order_no}", type="primary"):
                            update_delivery_status(order_no, "02", driver_name=_driver_name or "外送員")
                            st.success(f"已接單！外送單 `{order_no}` 配送中。")
                            st.rerun()
                    elif dl_status == "02":
                        if st.button("✅ 確認送達完成", key=f"done_dl_{order_no}", type="primary"):
                            update_delivery_status(order_no, "03")
                            st.success(f"外送單 `{order_no}` 已完成！")
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — Being Sport 課程管理（健身房帳號 + 管理員可見）
# ══════════════════════════════════════════════════════════════════════════════

if tab6 is not None:
    with tab6:
        st.markdown("#### 🏋️ Being Sport 課程管理")
        st.caption("查看課程報名人數、設定開課門檻，達標後一鍵開課並通知學員。")

        # ── 篩選器 ─────────────────────────────────────────────────────────
        _all_gyms = get_being_sport_gyms()
        _gym_options = {g["name"]: g["id"] for g in _all_gyms}

        _is_admin_gym = (st.session_state.vendor_brand == "全部")
        _cur_month = datetime.now().strftime("%Y%m")

        fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
        if _is_admin_gym:
            _sel_gym_name = fc1.selectbox("門市", ["全部"] + list(_gym_options.keys()), key="gym_sel")
            _sel_gym_id = 0 if _sel_gym_name == "全部" else _gym_options[_sel_gym_name]
        else:
            # beingsport 帳號只看自己的館
            _my_gym_id = get_gym_id_for_store(st.session_state.vendor_store)
            _sel_gym_id = _my_gym_id
            _sel_gym_name = st.session_state.vendor_store
            fc1.markdown(
                f'<div style="background:#1565C0;color:white;border-radius:6px;'
                f'padding:6px 12px;font-weight:600;font-size:0.9rem">'
                f'🏋️ {_sel_gym_name}</div>',
                unsafe_allow_html=True,
            )

        _sel_month  = fc2.text_input("月份（YYYYMM）", value=_cur_month, key="gym_month")
        _sel_status = fc3.selectbox("課程狀態", ["全部", "招生中", "已開課", "已取消"], key="gym_status")
        if fc4.button("🔄 重新整理", use_container_width=True, key="gym_refresh"):
            st.rerun()

        courses = get_gym_courses_for_dashboard(
            gym_id=_sel_gym_id, month=_sel_month, status_filter=_sel_status
        )

        # ── 統計指標 ───────────────────────────────────────────────────────
        _total_c   = len(courses)
        _open_c    = sum(1 for c in courses if c["status"] == "已開課")
        _recruit_c = sum(1 for c in courses if c["status"] == "招生中")
        _ready_c   = sum(1 for c in courses if c["status"] == "招生中" and c["actual_enrolled"] >= c["min_students"])
        _total_enr = sum(c["actual_enrolled"] for c in courses)

        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        sm1.metric("課程總數",      _total_c)
        sm2.metric("✅ 已開課",     _open_c)
        sm3.metric("📢 招生中",     _recruit_c)
        sm4.metric("🔔 可開課",     _ready_c, help="報名人數 ≥ 最低開課人數")
        sm5.metric("👥 總報名人數", _total_enr)

        st.divider()

        # ── 新增課程 ───────────────────────────────────────────────────────
        with st.expander("➕ 新增課程", expanded=False):
            if _is_admin_gym:
                _add_gym_opts = list(_gym_options.keys())
                _add_gym_name = st.selectbox("選擇門市", _add_gym_opts, key="add_gym_sel")
                _add_gym_id   = _gym_options[_add_gym_name]
            else:
                _add_gym_id = _sel_gym_id

            with st.form("add_course_form"):
                ac1, ac2 = st.columns(2)
                _ac_name   = ac1.text_input("課程名稱", placeholder="例：早晨瑜珈")
                _ac_coach  = ac2.text_input("教練", placeholder="例：吳教練")
                ac3, ac4   = st.columns(2)
                _ac_type   = ac3.selectbox("課程類型", ["有氧", "重訓", "瑜珈", "格鬥", "舞蹈", "其他"])
                _ac_wd     = ac4.text_input("上課日", placeholder="例：週一,週三,週五")
                ac5, ac6   = st.columns(2)
                _ac_time   = ac5.text_input("開始時間", placeholder="例：07:30")
                _ac_dur    = ac6.number_input("每堂時長（分鐘）", min_value=30, max_value=180, value=60)
                ac7, ac8, ac9 = st.columns(3)
                _ac_max    = ac7.number_input("名額上限", min_value=1, max_value=100, value=20)
                _ac_min    = ac8.number_input("最低開課人數", min_value=1, max_value=100, value=8)
                _ac_price  = ac9.number_input("月費（元）", min_value=0, max_value=9999, value=800)
                _ac_month  = st.text_input("月份（YYYYMM）", value=_cur_month)

                if st.form_submit_button("✅ 新增課程", type="primary"):
                    if _ac_name and _ac_wd and _ac_time:
                        add_gym_course(
                            gym_id=_add_gym_id, course_name=_ac_name, coach=_ac_coach,
                            course_type=_ac_type, weekday=_ac_wd, time_start=_ac_time,
                            duration_min=int(_ac_dur), max_slots=int(_ac_max),
                            price_month=int(_ac_price), min_students=int(_ac_min),
                            month=_ac_month,
                        )
                        st.success(f"✅ 課程「{_ac_name}」已新增！")
                        st.rerun()
                    else:
                        st.warning("請填寫課程名稱、上課日與開始時間。")

        st.divider()

        # ── 課程列表 ───────────────────────────────────────────────────────
        if not courses:
            st.info("目前沒有符合條件的課程。")
        else:
            STATUS_COLOR = {"招生中": "#FF9800", "已開課": "#43A047", "已取消": "#9E9E9E"}
            STATUS_ICON  = {"招生中": "📢", "已開課": "✅", "已取消": "❌"}

            for c in courses:
                actual   = c["actual_enrolled"]
                min_s    = c["min_students"]
                max_s    = c["max_slots"]
                status   = c["status"]
                s_color  = STATUS_COLOR.get(status, "#888")
                s_icon   = STATUS_ICON.get(status, "")
                can_open = (status == "招生中" and actual >= min_s)
                cid      = c["id"]

                with st.container(border=True):
                    # ── Header ──────────────────────────────────────────────
                    h1, h2, h3, h4 = st.columns([1, 3, 2, 2])
                    h1.markdown(
                        f'<span style="background:{s_color};color:white;border-radius:12px;'
                        f'padding:3px 10px;font-size:0.8rem;font-weight:700">'
                        f'{s_icon} {status}</span>',
                        unsafe_allow_html=True,
                    )
                    h2.markdown(f"**{c['course_name']}**　`{c['course_type']}`")
                    h3.caption(f"{c['gym_name']}")
                    h4.caption(f"📅 {c['weekday']} {c['time_start']} · {c['duration_min']}分")

                    # ── 報名進度條 ─────────────────────────────────────────
                    progress_pct = min(actual / min_s, 1.0) if min_s > 0 else 1.0
                    bar_color = "#43A047" if can_open else "#FF9800"
                    st.markdown(
                        f'<div style="margin:4px 0 2px">'
                        f'<span style="font-size:0.85rem;color:#555">報名人數：</span>'
                        f'<span style="font-weight:700;color:{bar_color}">{actual}</span>'
                        f'<span style="color:#888"> / 最低 {min_s} 人（上限 {max_s}）</span>'
                        + (f'&nbsp;&nbsp;<span style="background:#E8F5E9;color:#2E7D32;border-radius:8px;'
                           f'padding:1px 8px;font-size:0.8rem;font-weight:700">🔔 達標可開課</span>'
                           if can_open else '')
                        + f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.progress(progress_pct)

                    # ── 課程資訊 ───────────────────────────────────────────
                    ci1, ci2, ci3 = st.columns(3)
                    ci1.markdown(f"👨‍🏫 教練：**{c.get('coach','—')}**")
                    ci2.markdown(f"💰 月費：**NT${c.get('price_month',0)}**")
                    ci3.markdown(f"📍 {c.get('gym_address','')[:20]}")

                    # ── 報名學員列表 ───────────────────────────────────────
                    enrollments = get_enrollments_for_course(cid)
                    with st.expander(f"👥 報名學員（{len(enrollments)} 人）", expanded=False):
                        if not enrollments:
                            st.caption("目前尚無報名記錄。")
                        else:
                            for i, e in enumerate(enrollments, 1):
                                notified_badge = (
                                    '&nbsp;<span style="background:#43A047;color:white;'
                                    'border-radius:8px;padding:1px 6px;font-size:0.75rem">已通知</span>'
                                    if e["notified"] else
                                    '&nbsp;<span style="background:#FF9800;color:white;'
                                    'border-radius:8px;padding:1px 6px;font-size:0.75rem">待通知</span>'
                                )
                                st.markdown(
                                    f"{i}. **{e['contact_name']}**　{e['contact_phone']}"
                                    + (f"　💬 {e['note']}" if e.get("note") else "")
                                    + notified_badge,
                                    unsafe_allow_html=True,
                                )

                    # ── 操作區 ────────────────────────────────────────────
                    if status != "已取消":
                        st.divider()
                        op1, op2, op3 = st.columns([2, 2, 2])

                        # 設定最低人數
                        if op1.button("⚙️ 修改設定", key=f"edit_c_{cid}"):
                            st.session_state[f"editing_course_{cid}"] = True

                        # 開課按鈕（達標才啟用）
                        if status == "招生中":
                            _open_disabled = not can_open
                            _open_label = "🎉 開課並通知學員" if can_open else f"🔔 招生中（還差 {min_s - actual} 人）"
                            if op2.button(_open_label, key=f"open_c_{cid}",
                                          type="primary" if can_open else "secondary",
                                          disabled=_open_disabled):
                                notified_n = open_course_and_notify(cid)
                                st.success(f"🎉 課程已開課！已通知 {notified_n} 位學員。")
                                st.rerun()

                        # 取消課程
                        if op3.button("❌ 取消課程", key=f"cancel_c_{cid}"):
                            st.session_state[f"cancel_confirm_{cid}"] = True

                        # ── 修改設定表單 ────────────────────────────────────
                        if st.session_state.get(f"editing_course_{cid}"):
                            with st.form(f"edit_course_{cid}"):
                                st.markdown("**修改課程設定**")
                                new_min  = st.number_input(
                                    "最低開課人數", min_value=1, max_value=max_s,
                                    value=min_s, key=f"new_min_{cid}"
                                )
                                new_max  = st.number_input(
                                    "名額上限", min_value=max(actual, 1), max_value=200,
                                    value=max_s, key=f"new_max_{cid}"
                                )
                                ec1, ec2 = st.columns(2)
                                do_save = ec1.form_submit_button("✅ 儲存", type="primary")
                                do_cancel_e = ec2.form_submit_button("取消")
                            if do_save:
                                update_course_min_students(cid, int(new_min))
                                update_course_max_slots(cid, int(new_max))
                                st.success(f"已更新設定：最低 {new_min} 人，上限 {new_max} 人。")
                                st.session_state[f"editing_course_{cid}"] = False
                                st.rerun()
                            if do_cancel_e:
                                st.session_state[f"editing_course_{cid}"] = False
                                st.rerun()

                        # ── 取消確認 ───────────────────────────────────────
                        if st.session_state.get(f"cancel_confirm_{cid}"):
                            st.warning(
                                f"⚠️ 確認取消「{c['course_name']}」？\n"
                                f"將通知 {actual} 位已報名學員，此操作無法復原。"
                            )
                            cc1, cc2 = st.columns(2)
                            if cc1.button("確認取消", key=f"confirm_cancel_{cid}", type="secondary"):
                                cancel_course(cid)
                                st.info(f"課程「{c['course_name']}」已取消並通知學員。")
                                st.session_state[f"cancel_confirm_{cid}"] = False
                                st.rerun()
                            if cc2.button("不取消", key=f"abort_cancel_{cid}"):
                                st.session_state[f"cancel_confirm_{cid}"] = False
                                st.rerun()
