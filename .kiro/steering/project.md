# 統一生活管家 — AI Life Butler

## 專案概述

**2026 雲湧智生黑客松（統一資訊命題）** 參賽作品。

消費者透過自然語言對話，由 AI 呼叫 19 個 MCP 工具完成採買、旅遊規劃、旅遊保險申請、健身課程報名、外送派件、理財諮詢等一站式生活服務。廠商透過後台依帳號角色接單處理。

---

## 技術架構

| 層次 | 技術 |
|------|------|
| 前端 UI | Streamlit（`app.py`，port 8501） |
| 後台 UI | Streamlit（`vendor_dashboard.py`，port 8502） |
| AI 前端 | Anthropic Claude `claude-sonnet-4-6`（雲端）/ Ollama `qwen2.5:7b`（本地） |
| AI 後台 | Ollama `qwen2.5:7b`（固定本地） |
| MCP 工具層 | `mcp_server.py`（19 個工具，stdio transport，也可直接 import） |
| 資料庫 | SQLite `butler.db`（由 `seed.py` 初始化） |
| 套件管理 | `uv`（Python 3.11+） |
| 加密 | AES-256-GCM（姓名/電話/地址/Email 欄位） |

---

## 檔案職責

| 檔案 | 職責 |
|------|------|
| `seed.py` | 建立 SQLite `butler.db`（商品 56 筆、縣市/行政區/廠商假資料） |
| `mcp_server.py` | 19 個 MCP 工具函式 |
| `app.py` | 消費者前端（AI 對話 / 諮詢單 / 保險簽名 / 地圖 / 我的訂單） |
| `app_helpers.py` | SYSTEM_PROMPT、CLAUDE_TOOLS 清單、TOOL_FNS 對應、工具 Schema |
| `vendor_dashboard.py` | 廠商後台（庫存 / 諮詢單 / AI 派送 / MCP 總覽 / 外送 / 課程） |
| `vendor_helpers.py` | 後台 DB 操作、廠商帳號管理、Email 輔助、MCP_TOOLS 定義 |
| `butler.db` | SQLite 資料庫（`seed.py` 執行後產生） |
| `.env` | API 金鑰（SMTP / Spoonacular / TDX / ENCRYPT_KEY） |
| `requirements.txt` | 全部依賴 |

---

## 資料庫主要表格

```
fitness_product          — 統一集團商品（56 筆，9 大通路）
cms_homepage_service_vendor — 服務通路
partner_vendor           — 合作廠商（Being Sport / 統一速達 / 統超保險 / 統一證券等）
pms_form_feedback        — 諮詢單
  feedback_no: 14 碼純數字（格式 2607060000XXXX）
  status: 01待處理 / 02配送中 / 03預留中 / 04待簽名 / 05待後台確認 / 80已完成 / 90已拒絕
  個資欄位（姓名/電話/地址/Email）使用 AES-256-GCM 加密儲存
mms_order_record         — 外送派件單（order_no: ORDYYMMDDxxxxxx）
users                    — 消費者帳號（含 uuid、county_code、district_code）
vendor_users             — 廠商/後台帳號（15 個預設帳號）
conversation             — AI 對話歷史（app 啟動時自建）
gym_course               — 健身課程
course_enrollment        — 課程報名記錄
sys_county / sys_district — 全台 22 縣市 / 367 行政區
```

---

## 開發慣例

### 啟動順序
```bash
uv pip install -r requirements.txt
python seed.py
streamlit run app.py                              # 消費者前端 :8501
streamlit run vendor_dashboard.py --server.port 8502  # 廠商後台 :8502
python mcp_server.py --selftest                   # 工具測試
```

### 重要限制
- **競品品牌禁止推薦**：全家、萊爾富、全聯等競品，AI 及工具回傳均須過濾
- **seed.py 會 DROP 所有表重建**，執行後需重啟 app 或手動重建 `conversation`/`vendor_users`
- MCP Server 為 stdio transport；直接 import 工具函式不會啟動 server
- 7-ELEVEN 門市查詢優先用 `pcsc.com.tw` 官方 XML API，回傳座標需除以 1,000,000
- TDX 觀光 API Bearer token 自動快取 24 小時，未填金鑰回傳明確提示

### 安全性慣例
- 個資寫入 DB 前一律 AES-256-GCM 加密（`ENCRYPT_KEY` 環境變數）
- `contact_phone` 同時保存 SHA-256 雜湊版本供快速查詢，不儲存明文
- `users.uuid` 使用 RFC 4122 UUID，與真實帳號資料解耦
- 生產環境務必設定 `ENCRYPT_KEY`，勿使用展示用預設值

### 環境變數（.env）
```
SPOONACULAR_API_KEY=      # 食譜搜尋
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your_app_password
TDX_CLIENT_ID=            # 交通部 TDX 觀光 API
TDX_CLIENT_SECRET=
ENCRYPT_KEY=              # AES-256-GCM 金鑰（64 位十六進位或 base64-32byte）
```

---

## AI 模型設定

| 模式 | 模型 | 說明 |
|------|------|------|
| 前端（雲端） | `claude-sonnet-4-6` | 登入頁輸入 Anthropic API Key |
| 前端（本地） | Ollama `qwen2.5:7b` | 自動偵測 `http://localhost:11434` |
| 後台 AI 助手（主要） | Amazon Bedrock `us.anthropic.claude-haiku-4-5` | EC2 IAM Role 授予 `bedrock:InvokeModel`，環境變數 `BEDROCK_ADMIN_MODEL` 可覆寫 |
| 後台 AI 助手（備援） | Ollama `qwen2.5:7b` | Bedrock 無法連線時自動降級 |

---

## 廠商後台帳號角色

| 帳號類型 | 代表帳號 | 可見功能 |
|---------|---------|---------|
| 零售門市 | `7-11-A`, `wanjiafu`, `cosmed` 等 | 商品庫存、採買諮詢、AI派送 |
| 健身房 | `beingsport` | 課程報名單、課程管理 |
| 保險 | `insurance` | 旅遊保險申請單（4 步審核流程） |
| 券商 | `unisec` | 理財諮詢單 |
| 外送員 | `driver1`, `driver2` | 外送派件（接單/配送/完成） |
| 管理員 | `admin` | 全部功能 |
