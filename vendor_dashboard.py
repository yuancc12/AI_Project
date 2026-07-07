# -*- coding: utf-8 -*-
"""
vendor_dashboard.py — 健身採買助手商品庫存後台
執行：streamlit run vendor_dashboard.py --server.port 8502
"""
import streamlit as st
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "butler.db")
if not os.path.exists(DB):
    import seed
    seed.main()

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
    con.close()
    return total, out_of_stock, low_stock, round(avg_protein, 1)


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


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="商品庫存後台", page_icon="🏪", layout="wide")
st.title("🏪 健身採買助手 — 商品庫存後台")

# ── 頂部統計 ───────────────────────────────────────────────────────────────────
total, out_of_stock, low_stock_count, avg_protein = get_stats()
m1, m2, m3, m4 = st.columns(4)
m1.metric("商品總數", total)
m2.metric("⚠️ 低庫存（≤30）", low_stock_count)
m3.metric("❌ 售完", out_of_stock)
m4.metric("平均蛋白質 (g)", avg_protein)

st.divider()

# ── 通路庫存分佈 ───────────────────────────────────────────────────────────────
with st.expander("📊 各通路商品數量"):
    cols = st.columns(4)
    con = _db()
    for i, vendor in enumerate(["7-11", "家樂福", "康是美", "統一生機"]):
        n = con.execute("SELECT COUNT(*) FROM fitness_product WHERE vendor=?", (vendor,)).fetchone()[0]
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

# ── 篩選 ───────────────────────────────────────────────────────────────────────
f1, f2, f3 = st.columns([2, 2, 1])
sel_vendor = f1.selectbox("通路篩選", ["全部", "7-11", "家樂福", "康是美", "統一生機"])
sel_cat    = f2.selectbox("分類篩選", ["全部", "蛋白質", "主食", "蔬果", "乳製品", "保健品", "即食"])
show_low   = f3.checkbox("僅低庫存")

products = get_products(
    vendor=None if sel_vendor == "全部" else sel_vendor,
    category=None if sel_cat == "全部" else sel_cat,
    low_stock_only=show_low,
)
st.caption(f"顯示 {len(products)} 筆商品")
st.divider()

# ── 商品列表 ───────────────────────────────────────────────────────────────────
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
