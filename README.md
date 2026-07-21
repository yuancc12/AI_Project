# 統一生活管家 — AI Life Butler

**2026 雲湧智生黑客松（統一資訊命題）** 參賽作品。

消費者用自然語言處理一切生活需求：採買、旅遊規劃、旅遊保險申請、健身課程報名、外送派件、理財諮詢。系統由 AI 呼叫 19 個 MCP 工具完成服務，廠商後台依帳號類型接單處理。

---

## 系統需求

- Python 3.11+，套件管理器：**uv**
- [Ollama](https://ollama.com/) 本地執行（模型：`qwen2.5:7b`，後台 AI 助手使用）
- Anthropic API Key（前端 AI 使用 Claude claude-sonnet-4-6）

---

## 安裝

```bash
uv venv
uv pip install -r requirements.txt

# 建立資料庫（重建會清空所有資料，重新塞入假資料）
python seed.py
```

> **注意**：每次 `seed.py` 之後需重啟 app，或手動執行：
> ```bash
> python -c "from app_helpers import _ensure_conversation_table, _ensure_users_schema; _ensure_conversation_table(); _ensure_users_schema()"
> ```

---

## 啟動

```bash
# 消費者前端（http://localhost:8501）
streamlit run app.py

# 廠商後台（http://localhost:8502）
streamlit run vendor_dashboard.py --server.port 8502

# 測試 MCP 工具（不啟動網頁）
python mcp_server.py --selftest
```

---

## 檔案說明

| 檔案 | 職責 |
|------|------|
| `seed.py` | 建立 SQLite `butler.db`（商品 56 筆、縣市/行政區/廠商假資料） |
| `mcp_server.py` | 19 個 MCP 工具函式（stdio transport，也可直接 import） |
| `app.py` | 消費者前端（AI 對話 / 諮詢單 / 保險簽名 / 地圖 / 我的訂單） |
| `app_helpers.py` | SYSTEM_PROMPT、CLAUDE_TOOLS 清單、TOOL_FNS 對應、工具 Schema |
| `vendor_dashboard.py` | 廠商後台（庫存 / 諮詢單 / AI 派送 / MCP 總覽 / 外送 / 課程） |
| `vendor_helpers.py` | 後台 DB 操作、廠商帳號管理、Email 輔助、MCP_TOOLS 定義 |
| `butler.db` | SQLite 資料庫（`seed.py` 執行後產生） |
| `.env` | API 金鑰（SMTP / Spoonacular / TDX / Edamam） |

---

## MCP 工具（mcp_server.py，共 19 個）

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 1 | `search_grocery` | 讀取 | 關鍵字搜尋統一集團 9 大通路商品（56 筆） |
| 2 | `recommend_high_protein` | 讀取 | 依目標（增肌/減脂）與預算推薦高蛋白商品 |
| 3 | `check_inventory` | 讀取 | 查詢商品庫存 |
| 4 | `submit_inquiry` | **寫入** | 建立諮詢單（採買/搬家/旅遊/保險/課程/理財等） |
| 5 | `dispatch_delivery` | **寫入** | 後台派送外送，建立 mms_order_record + 自動發 Email |
| 6 | `get_partner_vendors` | 讀取 | 查詢合作廠商（健身房/搬家/清潔/快遞/保險/金融） |
| 7 | `get_current_time` | 讀取 | 取得台灣當前時間 |
| 8 | `get_weather` | 讀取 | 即時天氣（Open-Meteo，免費無金鑰） |
| 9 | `search_recipe` | 讀取 | 搜尋食譜（Spoonacular API） |
| 10 | `analyze_meal_nutrition` | 讀取 | 分析餐食熱量與三大營養素 |
| 11 | `recommend_after_meal` | 讀取 | 餐後缺口 → 推薦補充商品 |
| 12 | `calculate_tdee` | 讀取 | 個人化 TDEE / BMR 計算 |
| 13 | `get_gym_courses` | 讀取 | 查詢 Being Sport 本月健身課程（名額/教練/時間） |
| 14 | `enroll_gym_course` | **寫入** | 報名健身課程（支援多課程一張諮詢單） |
| 15 | `find_nearby_stores` | 讀取 | 附近地點搜尋（7-ELEVEN 用 pcsc 官方 API，其他用 OSM） |
| 16 | `find_route` | 讀取 | 路線規劃（Nominatim + 最近鄰演算法） |
| 17 | `find_sports_venues` | 讀取 | 公共運動場館查詢（教育部體育署 iPlay） |
| 18 | `send_email_notification` | **寫入** | SMTP Email 通知（接單/保險/課程均自動觸發） |
| 19 | `find_tourist_attractions` | 讀取 | 觀光景點/餐廳/住宿/活動（交通部 TDX API） |

---

## 商品通路（fitness_product，共 56 筆）

| 通路 | 類別 | 帳號 |
|------|------|------|
| 7-11 | 即食 / 蛋白質 / 主食 / 乳製品 | `7-11-A`、`7-11-B` |
| 萬家福 | 蛋白質 / 蔬果 / 乳製品 / 主食 | `wanjiafu` |
| 康是美 | 保健品 / 即食 | `cosmed` |
| 統一生機 | 主食 / 保健品 / 乳製品 | — |
| Mister Donut | 甜食 | `misterdonut` |
| Cold Stone | 甜點 / 飲料 | `coldstone` |
| 21plus | 酒類 | `21plus` |
| 統一星巴克 | 咖啡 | `starbucks` |
| 聖德科斯 | 有機食品 | `sanitas` |

---

## 後台帳號（vendor_users）

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
| `insurance` | `ins123` | 統超保險經紀人 | 旅遊保險申請單（4 步審核流程） |
| `unisec` | `sec123` | 統一證券 | 理財諮詢單 |
| `driver1` | `driver123` | 外送員 小明 | 外送派件（接單/配送/完成） |
| `driver2` | `driver123` | 外送員 小華 | 外送派件（接單/配送/完成） |
| `admin` | `admin123` | 管理員 | 全部（庫存/諮詢/AI/派件/課程） |

---

## 主要服務流程

### 採買外送
1. 用戶描述需求 → AI 呼叫 `search_grocery` / `recommend_high_protein`
2. 確認後呼叫 `submit_inquiry` 建立諮詢單
3. 後台接單 → AI 助手呼叫 `dispatch_delivery` 派送
4. 自動發 Email 通知用戶；外送員在 Tab 5 接單並規劃路線

### 旅遊保險（4 步流程）
1. 用戶詢問旅遊 → AI 呼叫 `find_tourist_attractions` 推薦景點
2. AI 主動詢問是否投保 → 前端跳出保險申請表（身分證/日期/人數等）
3. `insurance` 後台審核 → 編輯並發送正式保單 → Email 通知用戶簽名
4. 用戶前端電子簽名 → 後台確認生效 → 自動發 Email

### 健身課程
1. 用戶詢問課程 → AI 呼叫 `get_gym_courses`
2. 確認後呼叫 `enroll_gym_course` 建立報名單
3. 系統自動發報名確認 Email；`beingsport` 後台可查看報名單

### 理財諮詢
1. 用戶提出理財/投資需求 → AI 呼叫 `submit_inquiry(goal="理財諮詢")`
2. `unisec` 後台查看諮詢單 → 點「已安排專員聯繫」→ 自動發 Email

---

## 資料庫主要表格

```
fitness_product          — 統一集團商品（56 筆，9 大通路）
cms_homepage_service_vendor — 服務通路（7-ELEVEN 等 9 個）
partner_vendor           — 合作廠商（Being Sport / 統一速達 / 統超保險 / 統一證券等）
pms_form_feedback        — 諮詢單（status: 待處理/待簽名/待後台確認/預留中/配送中/已拒絕/已完成）
mms_order_record         — 外送派件單（order_no: ORDYYMMDDxxxxxx）
users                    — 消費者帳號（含 email, county_code, district_code, address）
vendor_users             — 廠商/後台帳號（15 個預設帳號）
conversation             — AI 對話歷史（app 啟動時自建）
gym_course               — 健身課程
course_enrollment        — 課程報名記錄
sys_county / sys_district — 全台 22 縣市 / 367 行政區
```

---

## .env 金鑰設定

```env
SPOONACULAR_API_KEY=      # 食譜搜尋 API（spoonacular.com）
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your_app_password
TDX_CLIENT_ID=            # 交通部 TDX 觀光 API（tdx.transportdata.tw）
TDX_CLIENT_SECRET=
```

---

## AI 模型

| 模式 | 模型 | 設定 |
|------|------|------|
| 雲端（前端預設） | Claude `claude-sonnet-4-6` | 登入頁輸入 Anthropic API Key |
| 本地 | Ollama `qwen2.5:7b` | 自動偵測 `http://localhost:11434` |
| 後台 AI 助手 | Ollama `qwen2.5:7b` | 固定本地，呼叫 `dispatch_delivery` |
