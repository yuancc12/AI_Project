# AI 生活管家 — CLAUDE.md

## 专案概述

**2026 雲湧智生黑客松**（統一資訊命題）参赛作品。
这是一个「7-ELEVEN 生活管家」系统，让消费者用自然语言描述生活需求（漏水、清洁、订位），
系统自动判断服务类型、显示动态表单、送出后媒合附近厂商。

## 档案结构

| 档案 | 职责 |
|------|------|
| `seed.py` | 建立 SQLite 资料库 `butler.db`，塞入分类/表单/厂商/区域假资料 |
| `mcp_server.py` | MCP Server，含三个可直接 import 的 Python 函式 |
| `app.py` | Streamlit 消费者前端，直接 import mcp_server 的函式 |
| `butler.db` | SQLite 资料库（若不存在，app.py 会自动执行 seed.py 建立） |
| `requirements.txt` | 只有 `mcp[cli]>=1.2.0`；前端另需 `streamlit` |

## 启动方式

```bash
pip install -r requirements.txt
pip install streamlit

# 建资料库（app.py 也会自动做）
python seed.py

# 跑前端
streamlit run app.py

# 测试三个函式逻辑（不启动 server）
python mcp_server.py --selftest
```

## 核心三个函式（mcp_server.py）

### `get_service_form(user_request: str) -> str`
- 输入：自然语言需求描述
- 逻辑：关键字比对 `service_category.keywords` → 找对应的 `pms_form` + 题目
- 回传 JSON：
  ```json
  {
    "matched": true,
    "form_id": 1,
    "form_name": "水電修繕估價單",
    "category_id": 1,
    "category": "水電修繕",
    "intro": "...",
    "topics": [
      {
        "topic_id": 101,
        "title": "問題描述",
        "type": "詳答",
        "required": true,
        "remark": "...",
        "options": []
      }
    ]
  }
  ```
- 未比对到时：`{"matched": false, "message": "..."}`

### `submit_form_feedback(form_id, category_id, contact_name, contact_mobile, county_code, district_code, description, answers="{}") -> str`
- 写入 `pms_form_feedback` 表，产生 `feedback_no`（格式：`FB260706XXXXXX`）
- 回传 JSON：`{"success": true, "feedback_no": "FB...", "message": "..."}`

### `match_vendors(category_id, county_code, district_code="") -> str`
- 依分类 + 地区查 `service_vendor` JOIN `vendor_service_area`，按 `rating DESC`
- 若指定区域无结果，自动放宽到同县市
- 回传 JSON：`{"count": N, "vendors": [{"vendor_id":1, "name":"...", "rating":4.8, "phone":"..."}]}`

## 题型代码对照（pms_form_topic.type）

| 代码 | 类型 | Streamlit 元件 |
|------|------|----------------|
| 1 | 簡答 | `st.text_input` |
| 2 | 詳答 | `st.text_area` |
| 3 | 單選 | `st.radio` |
| 4 | 複選 | `st.multiselect` |
| 5 | 地區選單 | 县市 + 行政区 `st.selectbox`（联动） |
| 6 | 上傳照片 | `st.file_uploader` |
| 7 | 備註 | `st.text_area` |
| 8 | 聯絡資料 | 姓名 + 电话 + 县市 + 行政区 |
| 9 | 日期 | `st.date_input` |
| 10 | 聯絡資料(不含地址) | 姓名 + 电话 |

## 资料库重要表格

```
service_category   — 服务分类（id, name, keywords, description）
pms_form           — 表单主档（id, category_id, name, intro_content, is_enable）
pms_form_topic     — 题目（id, form_id, type, title, remark, is_required, sort）
pms_topic_option   — 选项（id, topic_id, option_name, unit_price, unit, sort）
service_vendor     — 厂商（id, name, category_id, rating, phone）
vendor_service_area— 厂商服务范围（vendor_id, county_code, district_code）
sys_county         — 县市（code, name）  台北市=01 新北市=02 桃园市=03 台中市=04 高雄市=05
sys_district       — 行政区（code, county_code, name, zip）
pms_form_feedback  — 诊询单（feedback_no, form_id, category_id, contact_name, ...）
```

## 意图判断逻辑（`_classify`）

目前是**关键字比对**，不接 LLM：
- 统计 `service_category.keywords`（逗号分隔）在用户输入中出现几个
- 取命中数最多的分类
- 正式版可替换成 LLM / Amazon Bedrock，函式介面不变

## app.py 架构（Streamlit）

三阶段状态机，用 `st.session_state.stage` 控制：
1. `input` — 文字输入框，分析需求
2. `form` — 动态渲染题目，联动县市/行政区下拉
3. `result` — 显示 feedback_no + 厂商列表

县市/行政区联动关键：district selectbox 的 key 包含所选县市名称（`q_{tid}_dist_{sel_county}`），
县市变动时 key 改变，Streamlit 自动重置为新县市的第一个行政区。

## 开发注意事项

- 不需要重写 DB 逻辑，直接 `from mcp_server import` 三个函式
- `butler.db` 不存在时 app.py 开头会自动 `import seed; seed.main()`
- MCP Server 本身是 stdio transport，`mcp.run()` 才会启动；直接 import 呼叫函式不会启动 server
- `@mcp.tool()` 装饰器不影响函式的直接调用（selftest 已验证）
