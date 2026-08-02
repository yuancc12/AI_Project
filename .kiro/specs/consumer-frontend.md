# 消費者前端規格 — app.py

## 概述

消費者前端（port 8501）是一個多階段 Streamlit 應用，用戶透過 AI 對話完成採買、旅遊規劃、健身課程報名等一站式服務。

---

## 頁面階段（`st.session_state.stage`）

| stage | 說明 |
|-------|------|
| `login` | 登入/註冊畫面（預設） |
| `chat` | AI 對話主畫面 |
| `inquiry_form` | 採買/報名確認表單（AI 攔截 submit_inquiry 後跳出） |
| `my_orders` | 我的訂單列表 |
| `sign_insurance` | 保單電子簽名頁面 |

---

## 登入/註冊流程

```
用戶進入 → stage = "login"
  Tab 1「登入」：
    - 帳號 + 密碼 → check_login() → 成功載入體能資料 → stage = "chat"
  Tab 2「新用戶註冊」：
    - 帳號/密碼/Email/縣市/行政區/地址/電話/體能資料
    - register_user() → 自動登入 → stage = "chat"
```

---

## AI 對話主流程

### 後端選擇優先順序
1. `USE_BEDROCK` 環境變數 → Amazon Bedrock（EC2 部署用）
2. `ANTHROPIC_API_KEY` → Claude `claude-sonnet-4-6`
3. `OPENAI_API_KEY` → GPT-4o
4. 預設 → Ollama `qwen2.5:7b`（本地）

### 訊息格式
```python
display_msgs: list[dict]   # 顯示用，含 role/content/tool_calls
claude_msgs:  list[dict]   # Claude API 格式 history
ollama_history: list[dict] # OpenAI/Ollama 格式 history
```

### submit_inquiry / enroll_gym_course 攔截機制
當 AI 呼叫這兩個工具時，不直接執行，而是：
1. 攔截參數存入 `st.session_state.inquiry_prefill`
2. 設 `stage = "inquiry_form"`
3. 跳出確認表單讓用戶填寫/確認後，再透過 `mcp.Client` 真正送出

---

## Sidebar 功能

| 功能 | 說明 |
|------|------|
| 用戶名稱 + 登出 | 顯示當前帳號，登出清除所有 session state |
| 新對話按鈕 | 清空 display_msgs/history/cart，保留登入狀態 |
| 我的訂單 / 對話切換 | 快速在兩個 stage 間切換 |
| 快速訂單狀態 | 最近 3 筆訂單預覽，保險待簽名單獨提示 |
| 對話歷史列表 | 從 DB 載入，支援重新命名/刪除 |
| 📍 我的位置 | GPS 偵測（streamlit-js-eval）或手動輸入城市 |
| ⚙️ AI 設定 | 切換 AI 後端 / 輸入 API Key |
| 🔌 MCP 紀錄 | 工具呼叫歷史，可清除 |

---

## 採買確認表單（inquiry_form stage）

表單欄位由 `inquiry_prefill` 預填，用戶可修改：
- 聯絡人姓名、電話、地址
- 商品選擇（Checkbox 多選）
- 備注

特殊場景：
- **健身課程報名**：`prefill._enroll = True` → 顯示課程報名表
- **旅遊保險申請**：`goal = "旅遊保險申請"` → 顯示保險申請表（含電子簽名 canvas）

---

## 我的訂單頁面（my_orders stage）

- 從 `pms_form_feedback` 查詢當前用戶所有訂單
- 按狀態分組顯示（待處理/配送中/已完成等）
- 保單 status=04/05 顯示「電子簽名」按鈕
- 可點入保單詳情頁

---

## GPS 位置偵測

```python
# 使用 streamlit-js-eval 取得瀏覽器 GPS
_loc = streamlit_js_eval(js_expressions="new Promise(resolve => navigator.geolocation.getCurrent...)")
# 成功 → user_lat / user_lng 存入 session_state
# 失敗 → 提示手動輸入城市名稱
```

GPS 注入時機：find_nearby_stores / get_weather / find_sports_venues 工具呼叫前自動注入。

---

## 商品卡片 carousel

商品以橫向捲動 carousel 顯示，每張卡片包含：
- 品牌色 banner + 商品 emoji
- 商品名稱、廠商、蛋白質/熱量、價格、庫存
- 「加入」按鈕（data-ph="__add_cart__" 觸發 JS postMessage）

課程卡片類似，另有「選課/取消」按鈕。

---

## 地圖顯示

使用 `folium` + `streamlit-folium`：
- 紅色 home marker：用戶位置
- 各品牌顏色 marker：門市位置（7-11=綠、萬家福=藍、康是美=橘等）
- popup 顯示門市名稱、地址、電話、距離

---

## PWA 支援

- `static/manifest.json`、`static/icon-192.png`、`static/icon-512.png`
- `enableStaticServing = true` in config.toml
- 手機可「加入主畫面」作為 PWA app
