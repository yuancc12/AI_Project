# Hooks 說明

本資料夾定義 Kiro 自動化 Hook，在特定事件觸發時執行對應動作。

## hooks.json 中定義的 Hooks

| Hook 名稱 | 觸發時機 | 說明 |
|-----------|---------|------|
| Python 語法檢查 | 儲存 `.py` 檔案時 | 執行 `pyflakes` 檢查語法錯誤 |
| seed.py 變更提示 | 儲存 `seed.py` 時 | 提醒需重建資料庫並重啟 app |
| 敏感金鑰保護 | git commit 前 | 阻止 `.env` 被意外提交 |
| butler.db 保護 | git commit 前 | 阻止 SQLite DB 被意外提交 |

## 重要提醒

- `seed.py` 每次執行會 DROP 並重建所有資料表，請謹慎執行
- `.env` 含 SMTP / API 金鑰，**絕對不可提交至 Git**
- `butler.db` 含假資料與加密個資，已在 `.gitignore` 中排除
