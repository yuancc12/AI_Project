# 健康採買助手 — AI Life Butler

2026 雲湧智生黑客松（統一資訊命題）參賽作品。
消費者用自然語言描述健身目標與預算，系統透過 MCP 工具搜尋商品、推薦高蛋白品項、建立採買諮詢單，廠商後台接單並安排外送。

---

## 系統需求

- Python 3.11+，套件管理器：**uv**
- [Ollama](https://ollama.com/) 本地執行（模型：`qwen2.5:7b`）
- Anthropic API Key（選填，設 `ANTHROPIC_API_KEY` 環境變數）

---

## 安裝

```bash
# 建立虛擬環境並安裝套件
uv venv
uv pip install -r requirements.txt

# 建立資料庫（只需做一次；app.py 啟動時也會自動執行）
.venv/Scripts/python.exe seed.py
```

---

## 啟動

### 消費者前端（port 8501）

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

瀏覽器開 [http://localhost:8501](http://localhost:8501)

使用流程：
1. 登入後在聊天框輸入需求，例如「我想增肌，預算 500 元」
2. AI 自動推薦高蛋白商品、查詢庫存
3. 確認後建立採買諮詢單（填寫姓名與電話）
4. 在「我的訂單」頁追蹤配送狀態，並可回覆商家訊息

### 廠商後台（port 8502）

另開一個終端機視窗：

```bash
.venv/Scripts/python.exe -m streamlit run vendor_dashboard.py --server.port 8502
```

瀏覽器開 [http://localhost:8502](http://localhost:8502)

後台功能：
- **Tab 1** — 商品庫存管理（修改 stock）
- **Tab 2** — 採買諮詢單（接單 / 拒絕；顯示推薦商品與用戶回覆）
- **Tab 3** — AI 派送助手（Ollama 自動呼叫 `dispatch_delivery`）
- **Tab 4** — MCP 工具總覽

### 測試 MCP 工具（不啟動網頁）

```bash
.venv/Scripts/python.exe mcp_server.py --selftest
```

---

## 檔案說明

| 檔案 | 職責 |
|---|---|
| `app.py` | 消費者前端（Streamlit，聊天 + 表單 + 訂單） |
| `vendor_dashboard.py` | 廠商後台（Streamlit，`--server.port 8502`） |
| `mcp_server.py` | MCP Server，5 個工具，stdio transport |
| `seed.py` | 建立 `butler.db` 並塞入假資料 |
| `butler.db` | SQLite 資料庫（自動產生） |
| `requirements.txt` | `mcp[cli]`, `streamlit`, `anthropic`, `openai` |

---

## MCP 工具（mcp_server.py）

| 工具 | 類型 | 說明 |
|---|---|---|
| `search_grocery` | 讀取 | 依關鍵字搜尋商品 |
| `recommend_high_protein` | 讀取 | 依目標與預算推薦高蛋白品項 |
| `check_inventory` | 讀取 | 查詢指定商品庫存數量 |
| `submit_inquiry` | 寫入 | 建立採買諮詢單（含聯絡資料） |
| `dispatch_delivery` | 寫入 | 廠商接單並安排外送派送 |
| `find_route` | 讀取 | 多站點路線規劃（含距離與預估時間） |
| `get_current_time` | 讀取 | 取得目前日期與時間 |
| `get_weather` | 讀取 | 查詢指定城市或座標的天氣 |
| `find_nearby_stores` | 讀取 | 搜尋附近 7-ELEVEN 或合作門市 |
| `search_recipe` | 讀取 | 依關鍵字或食材搜尋食譜 |
| `analyze_meal_nutrition` | 讀取 | 分析食物的熱量與蛋白質含量 |
| `recommend_after_meal` | 讀取 | 根據已攝取熱量推薦餐後補充品 |
| `calculate_tdee` | 讀取 | 依體重、身高、年齡、活動量計算每日熱量需求 |
| `get_gym_courses` | 讀取 | 查詢健身課程時刻表 |
| `get_partner_vendors` | 讀取 | 查詢合作廠商清單（可依分類與地區篩選） |
| `enroll_gym_course` | 寫入 | 報名健身課程 |
| `find_sports_venues` | 讀取 | 搜尋附近運動場地 |

---

## AI 模型

| 模式 | 模型 | 設定 |
|---|---|---|
| 本地（預設） | Ollama `qwen2.5:7b` | 自動偵測 `http://localhost:11434` |
| 雲端 — Anthropic | Claude `claude-sonnet-4-6` | 登入頁輸入 Anthropic API Key |
| 雲端 — OpenAI | GPT-4o | 登入頁輸入 OpenAI API Key |

三種模式在登入頁以 API Key 欄位切換，不需修改程式碼。優先順序：Claude > GPT-4o > Ollama（本地）。

---

## 資料庫主要表格

```
fitness_product   — 商品（name, vendor, category, protein_g, calories, price, stock）
users             — 用戶帳號
inquiry           — 採買諮詢單（含配送欄位、user_reply 雙向訊息）
conversation      — 對話記錄（由 app.py 自動建立，不在 seed.py）
```
