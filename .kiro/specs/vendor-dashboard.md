# 廠商後台規格 — vendor_dashboard.py

## 概述

廠商後台（port 8502）提供各類廠商帳號依角色查看並處理諮詢單、管理庫存、派送外送、管理課程等功能。每個帳號登入後只看到與其角色相關的 Tab。

---

## 帳號角色與可見 Tab

| 帳號 | 密碼 | 身份 | 可見 Tab |
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
| `driver1` | `driver123` | 外送員 小明 | 外送派件 |
| `driver2` | `driver123` | 外送員 小華 | 外送派件 |
| `admin` | `admin123` | 管理員 | 全部 Tab |

---

## Tab 功能規格

### Tab 1 — 商品庫存管理

**適用帳號**：零售門市（7-11-A/B、wanjiafu、cosmed 等）、admin

功能：
- 顯示本帳號所屬商品列表（`fitness_product.vendor = 登入帳號`）
- 顯示欄位：商品名稱、類別、價格、庫存數量、蛋白質/熱量
- 可直接在表格中修改庫存數量並儲存
- 支援按類別篩選

---

### Tab 2 — 採買諮詢單

**適用帳號**：零售門市、admin

功能：
- 列出 status 為 `01待處理` 的諮詢單（`goal = "採買"`）
- 顯示個資欄位（解密後顯示）：姓名、電話、地址
- 操作按鈕：
  - 「接單」→ status 改 `02配送中`
  - 「拒絕」→ status 改 `90已拒絕`
- 接單後觸發 AI 助手（Ollama）自動呼叫 `dispatch_delivery`

---

### Tab 3 — AI 派送助手

**適用帳號**：零售門市、admin

功能：
- 呼叫後台 AI（Ollama `qwen2.5:7b`）分析諮詢單內容
- AI 自動選擇合適商品與外送員，呼叫 `dispatch_delivery` 工具
- 顯示 AI 派送決策過程與結果
- 派送完成後自動發送 Email 通知用戶

---

### Tab 4 — MCP 工具總覽

**適用帳號**：admin

功能：
- 展示全部 19 個 MCP 工具的名稱、類型、說明
- 顯示各工具的呼叫次數統計（來自 conversation 表）
- 方便展示系統能力

---

### Tab 5 — 外送派件

**適用帳號**：driver1、driver2、admin

功能：
- 列出指派給本帳號的外送單（`mms_order_record.driver_id = 登入帳號`）
- 狀態流轉：`待接單` → `配送中` → `已完成`
- 顯示配送地址（解密後）
- 呼叫 `find_route` 規劃最佳路線，在 Folium 地圖顯示

---

### Tab 6 — 健身課程管理

**適用帳號**：beingsport、admin

功能：
- 查看本月課程列表（`gym_course`）
- 查看各課程報名記錄（`course_enrollment`）
- 可調整課程名額上限
- 報名單狀態管理：確認 / 取消

---

### Tab 7 — 旅遊保險

**適用帳號**：insurance、admin

功能：
- 列出 `goal = "旅遊保險申請"` 的諮詢單
- 4 步審核流程：
  1. 查看申請資料
  2. 編輯保單內容（目的地、保障範圍、金額）
  3. 發送保單確認 Email 給用戶
  4. 等用戶電子簽名後確認生效
- 可查看用戶上傳的電子簽名圖片

---

### Tab 8 — 理財諮詢

**適用帳號**：unisec、admin

功能：
- 列出 `goal = "理財諮詢"` 的諮詢單
- 操作：「已安排專員聯繫」→ 自動發 Email 通知用戶
- 可新增備注（如專員姓名、聯絡時間）

---

## DB 操作模組（vendor_helpers.py）

| 函式 | 說明 |
|------|------|
| `get_vendor_products(vendor_id)` | 取得廠商商品列表 |
| `update_stock(product_id, qty)` | 更新庫存 |
| `get_inquiries(vendor_id, goal, status)` | 查詢諮詢單 |
| `update_inquiry_status(feedback_no, status)` | 更新諮詢單狀態 |
| `get_delivery_orders(driver_id)` | 取得外送單 |
| `decrypt_field(encrypted_value)` | AES-256-GCM 解密個資欄位 |
| `send_email(to, subject, body)` | SMTP 發送 Email |
| `authenticate_vendor(account, password)` | 廠商帳號驗證 |

---

## 安全性

- 後台帳號密碼以 SHA-256 雜湊儲存於 `vendor_users`
- 個資欄位（姓名/電話/地址）僅在後台顯示時解密，不以明文回傳前端
- 各帳號只能看到自己角色對應的 Tab 與資料（資料庫查詢加帳號條件過濾）
