# UI 設計規範

## 品牌配色（統一資訊）

| 變數 | 色碼 | 用途 |
|------|------|------|
| `--blue` | `#0057A8` | 主色（按鈕、邊框、active 狀態） |
| `--blue-dark` | `#003D7A` | 深藍（hover、標題） |
| `--blue-light` | `#EBF3FF` | 淺藍背景（hover 區域、選中 tab） |
| `--orange` | `#F7941D` | 強調色（CTA 按鈕、重要標籤） |
| `--orange-dark` | `#D4780A` | 深橘（hover） |
| `--orange-light` | `#FFF4E6` | 淺橘背景 |

Hero banner 漸層：`linear-gradient(135deg, #003D7A 0%, #0057A8 55%, #F7941D 100%)`

---

## 圖示系統

| 來源 | 使用方式 | 場景 |
|------|---------|------|
| Font Awesome 6 Free | `<i class="fa-solid fa-...">` in HTML markdown | Hero banner、登入卡片、HTML 區塊 |
| Streamlit Material Icons | `icon=":material/icon_name:"` in st.button/etc. | 按鈕、Sidebar 導航 |
| Emoji | 直接文字 | Tab 標籤、狀態標記 |

### 常用 Material Icon 對照

| 按鈕文字 | Material Icon |
|---------|---------------|
| 新對話 | `:material/add_comment:` |
| 我的訂單 | `:material/receipt_long:` |
| 對話 | `:material/forum:` |
| 登入 | `:material/login:` |
| 登出 | `:material/logout:` |
| 確認 | `:material/check_circle:` |
| 刪除 | `:material/delete:` |
| 設定 | `:material/settings:` |

---

## Logo 使用方式

將 `logo.png` 放入 `static/` 資料夾，hero banner 自動載入：
```html
<img src="/app/static/logo.png"
     style="height:44px;object-fit:contain;filter:brightness(0) invert(1);"
     alt="logo">
```
未放置時自動降級顯示 Font Awesome icon。

---

## 字型

主要字型：`Noto Sans TC`（Google Fonts），回退順序：
1. Noto Sans TC
2. PingFang TC（macOS/iOS）
3. Microsoft JhengHei（Windows）
4. sans-serif

---

## 元件規範

### 按鈕
- 圓角：`border-radius: 10px`
- hover：`translateY(-2px)` + 加深陰影
- Primary：藍色漸層；Sidebar CTA：橘色漸層

### Metric 卡片
- 白底 + 頂部 4px 藍色邊框
- 右上角藍色裝飾圓角（`::before` pseudo-element）
- hover 微浮起動畫

### Tabs
- 選中狀態：淺藍背景 + 底部 3px 藍色底線
- hover：同淺藍背景

### 聊天訊息
- 用戶訊息：藍色漸層背景 + 藍色邊框
- AI 訊息：白底 + 灰色邊框 + 陰影
- 出現動畫：`fadeInUp` 0.25s

### Sidebar（消費者前端）
- 深藍漸層背景：`linear-gradient(180deg, #003D7A, #0057A8, #1A78D0)`
- 白色文字
- 一般按鈕：半透明白底
- CTA 按鈕（新對話）：橘色漸層

---

## 頁面背景
- 消費者前端：`#F2F5FA`（淺藍灰）
- 廠商後台：`#F2F5FA`（相同，統一視覺）

---

## 動畫

| 動畫名 | 用途 | 時長 |
|--------|------|------|
| `fadeInUp` | 聊天訊息出現 | 0.25s ease |
| `fadeInDown` | Metric 卡片出現 | 0.3s ease |

---

## Streamlit 版本注意事項

- **版本**：1.40.1
- Material Icons 從 Streamlit 1.27+ 支援，使用 `:material/icon_name:` 語法
- `st.dialog` 從 1.32+ 支援
- `st.chat_message` 從 1.23+ 支援
- `st.popover` 從 1.28+ 支援
