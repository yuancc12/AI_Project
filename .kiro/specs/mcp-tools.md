# MCP 工具規格 — mcp_server.py

## 概述

`mcp_server.py` 提供 19 個 MCP 工具，以 stdio transport 運行，也可直接 import 函式使用。工具分為「讀取」（不修改資料）與「寫入」（修改 DB 或發送外部請求）兩類。

---

## 工具清單

### 商品與庫存

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 1 | `search_grocery` | 讀取 | 關鍵字搜尋統一集團 9 大通路商品（56 筆） |
| 2 | `recommend_high_protein` | 讀取 | 依目標（增肌/減脂）與預算推薦高蛋白商品 |
| 3 | `check_inventory` | 讀取 | 查詢指定商品庫存數量 |

### 服務與廠商

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 4 | `submit_inquiry` | **寫入** | 建立諮詢單（採買/搬家/旅遊/保險/課程/理財等） |
| 5 | `dispatch_delivery` | **寫入** | 後台派送外送，建立 mms_order_record + 自動發 Email |
| 6 | `get_partner_vendors` | 讀取 | 查詢合作廠商（健身房/搬家/清潔/快遞/保險/金融） |

### 時間與天氣

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 7 | `get_current_time` | 讀取 | 取得台灣當前時間（Asia/Taipei） |
| 8 | `get_weather` | 讀取 | 即時天氣（Open-Meteo，免費無金鑰） |

### 飲食與健康

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 9 | `search_recipe` | 讀取 | 搜尋食譜（Spoonacular API，需 SPOONACULAR_API_KEY） |
| 10 | `analyze_meal_nutrition` | 讀取 | 分析餐食熱量與三大營養素（蛋白質/脂肪/碳水） |
| 11 | `recommend_after_meal` | 讀取 | 餐後缺口 → 推薦補充商品 |
| 12 | `calculate_tdee` | 讀取 | 個人化 TDEE / BMR 計算（Harris-Benedict 公式） |

### 健身課程

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 13 | `get_gym_courses` | 讀取 | 查詢 Being Sport 本月健身課程（名額/教練/時間） |
| 14 | `enroll_gym_course` | **寫入** | 報名健身課程，支援多課程建立一張諮詢單 |

### 地圖與路線

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 15 | `find_nearby_stores` | 讀取 | 附近地點（7-ELEVEN 用 pcsc.com.tw，其他用 OSM） |
| 16 | `find_route` | 讀取 | 路線規劃（Nominatim geocoding + 最近鄰演算法） |
| 17 | `find_sports_venues` | 讀取 | 公共運動場館（教育部體育署 iPlay API） |

### 通知與觀光

| # | 工具 | 類型 | 說明 |
|---|------|------|------|
| 18 | `send_email_notification` | **寫入** | SMTP Email 通知（接單/保險/課程均自動觸發） |
| 19 | `find_tourist_attractions` | 讀取 | 觀光景點/餐廳/住宿/活動（交通部 TDX API） |

---

## submit_inquiry 諮詢單 Schema

```python
goal: str          # 服務目標（採買 / 旅遊保險申請 / 健身課程 / 理財諮詢 等）
name: str          # 客戶姓名（AES-256-GCM 加密儲存）
phone: str         # 聯絡電話（加密儲存 + SHA-256 雜湊供查詢）
address: str       # 地址（加密儲存）
items: list[str]   # 商品/服務項目清單
note: str          # 備注
```

回傳：`feedback_no`（14 碼純數字，格式 `YYMMDDHHMM0000` 流水號）

---

## dispatch_delivery 派送 Schema

```python
feedback_no: str   # 來源諮詢單編號
driver_id: str     # 指定外送員（driver1 / driver2）
items: list[str]   # 配送商品清單
address: str       # 配送地址
```

副作用：
- 建立 `mms_order_record`（order_no: `ORDYYMMDDxxxxxx`）
- 自動呼叫 `send_email_notification` 通知用戶

---

## 外部 API 依賴

| API | 工具 | 金鑰 | 備注 |
|-----|------|------|------|
| Open-Meteo | `get_weather` | 不需要 | 免費開放 |
| Spoonacular | `search_recipe` | `SPOONACULAR_API_KEY` | 需申請 |
| pcsc.com.tw | `find_nearby_stores` | 不需要 | 7-ELEVEN 官方 XML |
| OSM Nominatim | `find_nearby_stores`, `find_route` | 不需要 | 開放地圖 |
| 教育部 iPlay | `find_sports_venues` | 不需要 | 政府開放資料 |
| 交通部 TDX | `find_tourist_attractions` | `TDX_CLIENT_ID/SECRET` | Bearer token 快取 24hr |
| Gmail SMTP | `send_email_notification` | `SMTP_USER/PASS` | 需 App Password |

---

## 自測

```bash
python mcp_server.py --selftest
```

逐一呼叫所有工具並印出結果，不啟動 HTTP 伺服器，適合 CI 快速驗證。
