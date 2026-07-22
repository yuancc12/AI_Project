# AI 生活管家 — CLAUDE.md

## 專案概述

**2026 雲湧智生黑客松**（統一資訊命題）參賽作品。
「7-ELEVEN 生活管家」—— 讓消費者用自然語言處理一切生活需求，
系統由 AI 呼叫 MCP 工具完成採買、旅遊規劃、保險申請、健身課程、外送派件等服務。

## 檔案結構

| 檔案 | 職責 |
|------|------|
| `seed.py` | 建立 SQLite 資料庫 `butler.db`（含縣市/行政區/商品/廠商/課程假資料） |
| `mcp_server.py` | 19 個 MCP 工具函式（可直接 import，也可作為 stdio MCP Server 啟動） |
| `app.py` | Streamlit 消費者前端（AI 對話 + 諮詢單表單 + 保險簽名 + 地圖） |
| `app_helpers.py` | SYSTEM_PROMPT、CLAUDE_TOOLS 清單、TOOL_FNS 對應、工具 Schema |
| `vendor_dashboard.py` | 後台管理（商品庫存、諮詢單接單、課程管理、保險生效確認） |
| `vendor_helpers.py` | 後台 DB 操作、廠商帳號管理（vendor_users）、Email 輔助 |
| `butler.db` | SQLite 資料庫（seed.py 執行後產生，conversation/vendor_users 由 app 啟動時自建） |
| `.env` | API 金鑰（SMTP、Spoonacular、TDX、Edamam） |
| `requirements.txt` | 全部依賴（含 streamlit-drawable-canvas、folium 等） |

## 啟動方式

```bash
# 安裝依賴
uv pip install -r requirements.txt

# 建資料庫
python seed.py

# 消費者前端（http://localhost:8501）
streamlit run app.py

# 後台管理（http://localhost:8502）
streamlit run vendor_dashboard.py --server.port 8502

# 測試 MCP 工具
python mcp_server.py --selftest
```

> **注意**：每次執行 `seed.py` 後，需重啟 app（或執行
> `python -c "from app_helpers import _ensure_conversation_table, _ensure_users_schema; _ensure_conversation_table(); _ensure_users_schema()"`）
> 以重建 `conversation` 和 `vendor_users` 表。

## MCP 工具清單（mcp_server.py，共 19 個）

| # | 工具名稱 | 功能 |
|---|---------|------|
| 1 | `search_grocery` | 關鍵字搜尋統一集團商品庫（7-11/萬家福/康是美/統一生機等） |
| 2 | `recommend_high_protein` | 依目標（增肌/減脂）與預算推薦高蛋白商品 |
| 3 | `check_inventory` | 查詢商品庫存 |
| 4 | `submit_inquiry` | 建立諮詢單（採買/搬家/旅遊/保險等任何服務） |
| 5 | `dispatch_delivery` | 後台派送外送，建立 mms_order_record |
| 6 | `get_partner_vendors` | 查詢合作廠商（健身房/搬家/清潔/快遞/保險/金融） |
| 7 | `get_current_time` | 取得台灣當前時間 |
| 8 | `get_weather` | 即時天氣（Open-Meteo，免費無金鑰） |
| 9 | `search_recipe` | 搜尋食譜（Spoonacular API） |
| 10 | `analyze_meal_nutrition` | 分析餐食營養 |
| 11 | `recommend_after_meal` | 餐後補充品推薦 |
| 12 | `calculate_tdee` | 個人化 TDEE 計算 |
| 13 | `get_gym_courses` | 查詢 Being Sport 本月健身課程 |
| 14 | `enroll_gym_course` | 報名健身課程（支援多課程一張諮詢單） |
| 15 | `find_nearby_stores` | 附近地點搜尋（7-ELEVEN 用 pcsc.com.tw 官方 API，其他用 OSM） |
| 16 | `find_route` | 路線規劃（Nominatim + 最近鄰演算法） |
| 17 | `find_sports_venues` | 公共運動場館查詢（教育部體育署 iPlay） |
| 18 | `send_email_notification` | SMTP Email 通知 |
| 19 | `find_tourist_attractions` | 觀光景點/餐廳/住宿/活動（交通部 TDX API） |

## 資料庫重要表格

```
fitness_product          — 統一集團商品（name, vendor, protein_g, calories, price, stock）
cms_homepage_service_vendor — 服務通路（7-ELEVEN/萬家福/康是美/統一生機/Mister Donut/Cold Stone/21plus/統一星巴克/聖德科斯）
partner_vendor           — 合作廠商（Being Sport健身房/統一速達/統超保險/統一證券/清潔等）
pms_form_feedback        — 諮詢單（feedback_no 格式: 2607060000XXXX 純數字14碼，status: 01待處理/02配送中/03預留中/04待簽名/05待後台確認/80已完成/90已拒絕）
mms_order_record         — 外送派件單（order_no 格式: ORD260706XXXXXX）
sys_county               — 縣市（22個，code 01~22）
sys_district             — 行政區（360個，含全台22縣市完整行政區）
users                    — 消費者帳號（含 email, county_code, district_code, address, uuid）
vendor_users             — 廠商/後台帳號
conversation             — AI 對話歷史
gym_course / course_enrollment — 健身課程與報名記錄
```

## 後台帳號（vendor_users）

| 帳號 | 密碼 | 身份 |
|------|------|------|
| `7-11-A` | `vendor123` | 7-11 門市 A |
| `wanjiafu` | `vendor123` | 萬家福信義店 |
| `cosmed` | `vendor123` | 康是美中山店 |
| `beingsport` | `gym123` | Being Sport 健身中心 |
| `insurance` | `ins123` | **統超保險經紀人**（只看保險申請單） |
| `unisec` | `sec123` | 統一證券 |
| `driver1/2` | `driver123` | 外送員 |
| `admin` | `admin123` | 管理員（看全部） |

## 旅遊保險申請流程

1. 用戶問旅遊 → AI 呼叫 `find_tourist_attractions` 搜尋景點
2. 展示後 AI 主動問：「需要投保旅遊險嗎？」
3. 用戶同意 → AI 收集目的地/日期/人數 → 呼叫 `submit_inquiry(goal="旅遊保險申請")`
4. 前端跳出 **🛡️ 旅遊保險申請表**（無電話欄位，有手寫電子簽名）
5. 用戶簽名送出 → 後台 `insurance` 帳號可見
6. 後台點「✅ 確認生效」→ 狀態改已完成 + 自動發 Email

## .env 金鑰說明

```
SPOONACULAR_API_KEY=   # 食譜 API
SMTP_HOST/PORT/USER/PASS=  # Gmail SMTP（發送 Email 通知）
TDX_CLIENT_ID=         # 交通部 TDX 觀光 API（https://tdx.transportdata.tw 申請）
TDX_CLIENT_SECRET=
```

## 開發注意事項

- `seed.py` 會 DROP 所有表重建，`conversation`/`vendor_users` 需 app 啟動後才自建
- MCP Server 本身是 stdio transport；直接 import 函式不會啟動 server，`@mcp.tool()` 不影響直接呼叫
- 7-ELEVEN 門市查詢優先用 `pcsc.com.tw` 官方 API（XML 格式，座標為 X/Y 整數需除以 1,000,000），pcsc 回 0 時自動只帶 city 重查
- TDX 觀光 API 需要 Bearer token（填入 .env 後自動快取 24hr）；未填金鑰回傳明確提示
- 競品品牌（全家/萊爾富/全聯等）AI 不得推薦，工具回傳有競品時直接過濾
