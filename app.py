# -*- coding: utf-8 -*-
"""統一生活管家 — 登入 + Claude API + 真實 MCP 工具呼叫"""
import os
import json
import asyncio
import streamlit as st
import anthropic
from datetime import datetime, date
from urllib.parse import quote as _url_quote
from app_helpers import (
    DB_PATH, _db,
    check_login, register_user, get_my_inquiries, update_user_reply,
    delete_conversation, rename_conversation,
    _ensure_conversation_table, _ensure_users_schema,
    get_conversations, load_conv_from_db, save_conv_to_db,
    _content_to_dict, _run_async, _strip_images, _compact_history, _sanitize_for_openai,
    CLAUDE_TOOLS, TOOL_FNS, SYSTEM_PROMPT,
    OLLAMA_MODEL, _ollama, _mcp,
    get_counties, get_districts,
)
from mcp import Client

_HERE = os.path.dirname(os.path.abspath(__file__))

# ── API 金鑰注入（優先順序：st.secrets > .env > 系統環境變數）──────────────────
# 1. Streamlit secrets（.streamlit/secrets.toml）
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

# 2. .env 檔案（手動讀，不依賴 dotenv）
_env_file = os.path.join(_HERE, ".env")
if os.path.exists(_env_file):
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

try:
    from streamlit_js_eval import streamlit_js_eval as _js_eval
    _HAS_GEO = True
except ImportError:
    _HAS_GEO = False

@st.dialog("🗑️ 確認刪除對話")
def _delete_confirm_dialog(conv_id: int, title: str):
    st.write(f"確定要刪除「**{title[:24]}**」嗎？")
    st.caption("刪除後無法復原。")
    c1, c2 = st.columns(2)
    if c1.button("刪除", type="primary", use_container_width=True, key="dlg_del_yes"):
        delete_conversation(conv_id)
        if conv_id == st.session_state.get("conversation_id"):
            st.session_state.update({
                "display_msgs": [], "ollama_history": [], "claude_msgs": [],
                "mcp_log": [], "last_products": [], "conversation_id": None,
            })
        st.session_state._pending_delete_id = None
        st.rerun()
    if c2.button("取消", use_container_width=True, key="dlg_del_no"):
        st.session_state._pending_delete_id = None
        st.rerun()


OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in CLAUDE_TOOLS
]


@st.cache_data(ttl=300, show_spinner=False)
def _reverse_geocode(lat: float, lng: float) -> str:
    """Nominatim reverse geocoding，回傳繁中地址字串，失敗回傳空字串。"""
    try:
        import requests as _req
        r = _req.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lng, "accept-language": "zh-TW"},
            headers={"User-Agent": "ai-life-butler/1.0"},
            timeout=5,
        )
        if r.ok:
            a = r.json().get("address", {})
            hn = a.get("house_number", "")
            if hn and not hn.endswith("號"):
                hn += "號"
            parts = [
                a.get("city") or a.get("county") or a.get("state"),
                a.get("city_district") or a.get("suburb") or a.get("town"),
                a.get("road") or a.get("pedestrian"),
                hn or None,
            ]
            return "".join(p for p in parts if p)
    except Exception:
        pass
    return ""


def _guess_tw_city(lat: float, lng: float) -> str:
    """根據座標粗略推算台灣城市（僅供 UI 顯示用）。"""
    if 25.05 <= lat <= 25.22 and 121.60 <= lng <= 121.95:
        return "基隆市"
    if 25.00 <= lat <= 25.10 and 121.42 <= lng <= 121.62:
        return "台北市"
    if 24.85 <= lat <= 25.22 and 121.30 <= lng <= 121.80:
        return "新北市"
    if 24.70 <= lat <= 25.00 and 120.95 <= lng <= 121.40:
        return "桃園市"
    if 24.50 <= lat <= 24.80 and 120.80 <= lng <= 121.20:
        return "新竹"
    if 24.00 <= lat <= 24.55 and 120.50 <= lng <= 121.10:
        return "台中市"
    if 23.35 <= lat <= 24.00 and 120.10 <= lng <= 120.80:
        return "彰化/雲嘉"
    if 22.90 <= lat <= 23.35 and 120.05 <= lng <= 120.60:
        return "台南市"
    if 22.40 <= lat <= 22.90 and 120.05 <= lng <= 120.55:
        return "高雄市"
    if 22.00 <= lat <= 22.60 and 120.40 <= lng <= 121.10:
        return "屏東縣"
    if 23.50 <= lat <= 24.50 and 121.30 <= lng <= 121.90:
        return "花蓮縣"
    if 22.40 <= lat <= 23.50 and 120.90 <= lng <= 121.50:
        return "台東縣"
    if 24.50 <= lat <= 24.85 and 121.60 <= lng <= 122.00:
        return "宜蘭縣"
    return ""


def _build_system() -> str:
    """動態 system prompt：基底 + 用戶體能資料 + GPS 位置。"""
    system = SYSTEM_PROMPT

    # ── 注入用戶體能資料 ──────────────────────────────────────────────────
    user_id = st.session_state.get("user_id") or 0
    gender  = st.session_state.get("user_gender", "")
    age     = st.session_state.get("user_age", 0)
    height  = st.session_state.get("user_height_cm", 0.0)
    weight  = st.session_state.get("user_weight_kg", 0.0)
    goal    = st.session_state.get("user_fitness_goal", "")

    username      = st.session_state.get("username", "")
    contact_phone = st.session_state.get("user_contact_phone", "")
    user_address  = st.session_state.get("user_address", "")

    if user_id:
        profile_parts = []
        if gender:  profile_parts.append(f"性別={gender}")
        if age:     profile_parts.append(f"年齡={age}歲")
        if height:  profile_parts.append(f"身高={height}cm")
        if weight:  profile_parts.append(f"體重={weight}kg")
        if goal:    profile_parts.append(f"目標={goal}")
        profile_str = "、".join(profile_parts) if profile_parts else "（體能資料尚未填寫）"

        system += (
            f"\n\n## 當前登入用戶（ID={user_id}）\n"
            f"帳號名稱：{username}\n"
            f"已儲存體能資料：{profile_str}\n\n"
            f"### 諮詢單聯絡資料預設值（CRITICAL）\n"
            f"呼叫 submit_inquiry 時，contact_name 預設填入「{username}」，"
            + (f"contact_phone 預設填入「{contact_phone}」，" if contact_phone
               else "contact_phone 尚未設定，需詢問用戶電話，")
            + (f"address 預設填入「{user_address}」（外送地址，詢問用戶是否更改）。\n"
               if user_address else "address 尚未設定，需詢問用戶外送地址。\n")
            + f"用戶可在確認表單中修改，AI 不需要再詢問姓名，直接用帳號名稱即可。\n\n"
            f"### 工具呼叫規則\n"
            f"- 採買場景：從對話判斷 goal（增肌/減脂）與 budget，呼叫 recommend_high_protein；"
            f"缺少任一資訊時，先向用戶詢問，禁止呼叫 calculate_tdee\n"
            f"- TDEE 場景（用戶明確問基礎代謝/每日熱量）：呼叫 calculate_tdee(user_id={user_id})，"
            f"工具自動讀取體能資料，禁止詢問身高體重年齡性別\n"
        )
        if not goal:
            system += "注意：此用戶尚未設定健康目標，需先詢問「增肌/減脂/維持」再呼叫工具。\n"

    # ── 注入健身課程快取（避免報名時重複呼叫 get_gym_courses）──────────
    gym_courses = st.session_state.get("last_gym_courses")
    if gym_courses:
        lines = []
        for c in gym_courses:
            lines.append(
                f"  course_id={c['course_id']} 《{c['course_name']}》"
                f" 類型={c['course_type']} 教練={c['coach']}"
                f" {c['weekday']} {c['time_start']} 剩餘={c['available_slots']}名額"
                f" 狀態={c.get('status','')}"
            )
        system += (
            "\n\n## 本月健身課程清單（已快取，報名時直接使用，禁止再次呼叫 get_gym_courses）\n"
            + "\n".join(lines)
            + "\n用戶說要報名某課程時：從上表找 course_id → 詢問姓名電話 → 確認 → 呼叫 enroll_gym_course\n"
        )

    # ── 注入 GPS 位置 ───────────────────────────────────────────────────
    lat = st.session_state.get("user_lat")
    lng = st.session_state.get("user_lng")
    if lat and lng:
        system += (
            f"\n\n## 用戶目前 GPS 位置\n"
            f"緯度 {lat:.5f}，經度 {lng:.5f}\n"
            f"當用戶詢問附近任何地點時，呼叫 find_nearby_stores(name=..., category=...) 工具。\n"
            f"由你根據用戶意圖決定 name（品牌名）與 category（OSM 類型），lat/lng 系統自動注入。\n"
            f"例：7-11 → name=\"7-ELEVEN\" category=\"convenience\"；餐廳 → name=\"\" category=\"restaurant\""
        )
    else:
        manual_city = st.session_state.get("manual_city", "")
        if manual_city:
            system += (
                f"\n\n## 用戶目前位置（手動設定）\n"
                f"城市：{manual_city}\n"
                f"無 GPS 座標，呼叫 get_weather 時傳入 city=\"{manual_city}\"；"
                f"呼叫 find_nearby_stores 時帶入 name/category，系統會嘗試以城市名稱定位。"
            )
    return system


# ── Claude API 呼叫（含 tool_use 循環）───────────────────────────────────────

def _sanitize_claude_msgs(msgs: list) -> list:
    """移除 history 中沒有對應 tool_result 的 dangling assistant+tool_use message。
    防止舊 session 的殘缺 history 造成 Claude API 400 錯誤。"""
    out = []
    i = 0
    while i < len(msgs):
        msg = msgs[i]
        role    = msg.get("role", "")
        content = msg.get("content", [])

        # 偵測 assistant 訊息是否含有 tool_use block
        has_tool_use = (
            role == "assistant"
            and isinstance(content, list)
            and any(b.get("type") == "tool_use" for b in content)
        )

        if has_tool_use:
            # 下一則必須是 user + tool_result 才算完整配對
            nxt = msgs[i + 1] if i + 1 < len(msgs) else None
            nxt_content = (nxt or {}).get("content", [])
            pair_ok = (
                nxt is not None
                and nxt.get("role") == "user"
                and isinstance(nxt_content, list)
                and any(b.get("type") == "tool_result" for b in nxt_content)
            )
            if pair_ok:
                out.append(msg)
                out.append(nxt)
                i += 2
            else:
                i += 1  # dangling — 跳過
            continue

        # 孤立的 tool_result user 訊息（前面沒有 assistant+tool_use）
        if (role == "user"
                and isinstance(content, list)
                and any(b.get("type") == "tool_result" for b in content)):
            i += 1
            continue

        out.append(msg)
        i += 1
    return out


def chat_with_claude(claude_msgs: list, api_key: str):
    """Claude + tool_use 循環。submit_inquiry 攔截跳表單。
    回傳 (final_text, tool_log, updated_claude_msgs)。"""
    client = anthropic.Anthropic(api_key=api_key)
    msgs   = _sanitize_claude_msgs(list(claude_msgs))   # 清除殘缺 history
    log    = []
    system = _build_system()

    while True:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system,
            tools=CLAUDE_TOOLS,
            messages=msgs,
        )

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            msgs.append({"role": "assistant",
                         "content": _content_to_dict(resp.content)})
            return text, log, msgs

        msgs.append({"role": "assistant",
                     "content": _content_to_dict(resp.content)})

        tool_results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue

            # submit_inquiry / enroll_gym_course 攔截 → 跳到確認表單
            if b.name in ("submit_inquiry", "enroll_gym_course"):
                prefill = dict(b.input)
                if b.name == "enroll_gym_course":
                    prefill["_enroll"] = True
                if not prefill.get("user_id"):
                    prefill["user_id"] = st.session_state.get("user_id") or 0
                st.session_state.inquiry_prefill  = prefill
                st.session_state.inquiry_products = _products_from_submit(prefill)
                st.session_state.stage            = "inquiry_form"
                text = "".join(bl.text for bl in resp.content if bl.type == "text")
                # 移除 dangling assistant+tool_calls（未回應就 return 會導致下次 API 400）
                if msgs and msgs[-1].get("role") == "assistant":
                    msgs.pop()
                return text or "（為您開啟報名確認表單 📋）", log, msgs

            tool_input = dict(b.input)
            # 自動注入 GPS（Claude 有時不帶 lat/lng）
            _GPS_TOOLS_C = {"find_nearby_stores", "get_weather", "find_sports_venues"}
            if b.name in _GPS_TOOLS_C and not tool_input.get("lat"):
                _lat = st.session_state.get("user_lat")
                _lng = st.session_state.get("user_lng")
                if _lat:
                    tool_input["lat"] = _lat
                    tool_input["lng"] = _lng
            result_str  = TOOL_FNS[b.name](**tool_input)
            result_dict = json.loads(result_str)
            log.append({
                "tool":   b.name,
                "params": tool_input,
                "result": result_dict,
                "ts":     datetime.now().strftime("%H:%M:%S"),
                "via":    "direct import",
            })
            if b.name == "get_gym_courses" and result_dict.get("courses"):
                st.session_state["last_gym_courses"] = result_dict["courses"]
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": b.id,
                "content":     result_str,
            })

        msgs.append({"role": "user", "content": tool_results})


# ── Ollama 本地 AI + 真實 MCP 工具呼叫 ───────────────────────────────────────

def _extract_inquiry_products() -> list:
    """從 mcp_log 或 last_products 快取取出商品清單（fallback 用）。"""
    for entry in reversed(st.session_state.get("mcp_log", [])):
        if entry["tool"] in ("recommend_high_protein", "search_grocery"):
            prods = entry["result"].get("products") or entry["result"].get("items", [])
            if prods:
                return prods
    return st.session_state.get("last_products", [])


def _products_from_submit(prefill: dict) -> list:
    """取 submit_inquiry 參數裡的 products_json（AI 應只放用戶指定商品）。
    若 AI 沒有傳或傳空，才 fallback 到 mcp_log 裡的搜尋結果。"""
    pj = prefill.get("products_json", "")
    if pj:
        try:
            products = json.loads(pj)
            if isinstance(products, list) and products:
                return products
        except Exception:
            pass
    return _extract_inquiry_products()


async def _ollama_mcp_loop(msgs: list, prefetch_cache: dict | None = None,
                           user_lat: float | None = None,
                           user_lng: float | None = None,
                           user_id: int = 0,
                           ai_client=None, ai_model: str | None = None) -> dict:
    """
    Ollama + MCP 核心循環。
    回傳 dict，包含 text、tool_log、history（完整 messages，含工具呼叫與結果，
    排除系統 prompt）、intercepted、intercept_args。
    user_lat/user_lng 從主執行緒傳入，因 ThreadPoolExecutor 無法存取 st.session_state。
    """
    # 同一輪內這些工具只允許呼叫一次（第二次直接回傳上一次結果，不重新呼叫 MCP）
    _ONCE_PER_TURN = {
        "find_nearby_stores", "get_current_time",
        "recommend_after_meal", "recommend_high_protein", "get_all_fitness_products",
        "check_inventory", "calculate_tdee", "get_gym_courses", "enroll_gym_course",
    }

    _client = ai_client or _ollama
    _model  = ai_model  or OLLAMA_MODEL

    tool_log          = []
    messages          = list(msgs)          # msgs[0] = system prompt
    call_cache: dict[tuple, str] = dict(prefetch_cache or {})
    resolved_counts: dict[str, int] = {}   # 追蹤每個工具已回覆幾次
    tool_last_result: dict[str, str] = {}  # 每個工具最後一次的結果（用於擋重複呼叫）

    def _make_result(text: str, intercepted=False, intercept_args=None) -> dict:
        return {
            "text":           text,
            "tool_log":       tool_log,
            "history":        messages[1:],   # 排除 system prompt，其餘全保留
            "intercepted":    intercepted,
            "intercept_args": intercept_args,
        }

    async with Client(_mcp) as mcp_client:
        max_turns = 10
        for _ in range(max_turns):
            # 任何工具被回覆超過 1 次 → 強制輸出文字（不再給工具清單）
            force_text = any(v > 1 for v in resolved_counts.values())
            call_kwargs: dict = {
                "model":       _model,
                "messages":    messages,
                "temperature": 0.1,
            }
            if not force_text:
                call_kwargs["tools"] = OLLAMA_TOOLS

            _loop = asyncio.get_event_loop()
            _fn   = _client.chat.completions.create
            try:
                resp = await _loop.run_in_executor(None, lambda: _fn(**call_kwargs))
            except Exception as _api_err:
                return _make_result(f"❌ AI API 連線失敗：{_api_err}")
            msg = resp.choices[0].message

            if not msg.tool_calls:
                text_out = msg.content or ""
                # 偵測「宣告要查詢但沒呼叫工具」的幻覺（第一輪且尚未呼叫任何工具）
                _PLANNING_PHRASES = ("正在查詢", "請稍候", "馬上回來", "幫您查", "為您查", "查詢中")
                if not resolved_counts and any(p in text_out for p in _PLANNING_PHRASES):
                    print("⚠️ [幻覺] AI 說要查詢但未呼叫工具，追加一輪強制呼叫")
                    messages.append({"role": "assistant", "content": text_out})
                    messages.append({"role": "user", "content": "請立即呼叫對應的工具取得結果。"})
                    continue  # 回到迴圈頂再給模型工具清單
                # 把最終回答加入 messages，讓下次對話能讀到
                messages.append({"role": "assistant", "content": text_out})
                return _make_result(text_out)

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            _assistant_msg_idx = len(messages) - 1  # 記住 assistant message 位置，攔截時用來回退

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)
                ts        = datetime.now().strftime("%H:%M:%S")

                # 攔截表單提交 / 課程報名（history 此時已含前面所有工具結果）
                if tool_name in ("submit_inquiry", "enroll_gym_course"):
                    if tool_name == "enroll_gym_course":
                        tool_args["_enroll"] = True
                        if user_id and not tool_args.get("user_id"):
                            tool_args["user_id"] = user_id
                    elif not tool_args.get("user_id") and user_id:
                        tool_args["user_id"] = user_id
                    print(f"\n✋ [MCP] 攔截 {tool_name} args={tool_args}")
                    # 移除 dangling assistant+tool_calls 及已執行的部分 tool responses
                    del messages[_assistant_msg_idx:]
                    return _make_result("", intercepted=True, intercept_args=tool_args)

                # 自動補 user_id（Ollama 常忘記帶）
                if tool_name == "calculate_tdee" and not tool_args.get("user_id") and user_id:
                    tool_args["user_id"] = user_id
                    print(f"👤 [MCP] 自動注入 user_id={user_id} → calculate_tdee")

                # 自動補報名人姓名與電話（從 session_state 取登入用戶資料）
                if tool_name == "enroll_gym_course":
                    if not tool_args.get("contact_name") and user_id:
                        _uname = st.session_state.get("username", "")
                        if _uname:
                            tool_args["contact_name"] = _uname
                            print(f"👤 [MCP] 自動注入 contact_name={_uname} → enroll_gym_course")
                    if not tool_args.get("contact_phone") and user_id:
                        _phone = st.session_state.get("user_contact_phone", "")
                        if _phone:
                            tool_args["contact_phone"] = _phone
                            print(f"📞 [MCP] 自動注入 contact_phone → enroll_gym_course")


                # 自動補 GPS（Ollama 常忘記帶 lat/lng；用傳入的參數而非 st.session_state）
                _GPS_TOOLS = {"find_nearby_stores", "get_weather", "find_sports_venues"}
                if tool_name in _GPS_TOOLS and not tool_args.get("lat"):
                    if user_lat:
                        tool_args["lat"] = user_lat
                        tool_args["lng"] = user_lng
                        print(f"📍 [MCP] 自動注入 GPS → {tool_name} {user_lat:.5f},{user_lng:.5f}")
                    elif tool_name == "find_nearby_stores":
                        # find_nearby_stores 沒有 GPS 就無法運作，直接回錯誤
                        no_gps = json.dumps({"message": "⚠️ 尚未取得 GPS。請在側欄展開「📍 我的位置」並允許瀏覽器取得位置。"}, ensure_ascii=False)
                        resolved_counts[tool_name] = resolved_counts.get(tool_name, 0) + 1
                        tool_log.append({"tool": tool_name, "params": tool_args,
                                         "result": json.loads(no_gps), "ts": ts, "via": "mcp.Client"})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": no_gps})
                        continue
                    # get_weather / find_sports_venues 沒 GPS 時帶 city 繼續（工具自己地理編碼）

                # 同輪單次型工具：呼叫過一次即攔截，直接回上次結果（不管有無店家）
                if tool_name in _ONCE_PER_TURN and resolved_counts.get(tool_name, 0) > 0:
                    prev = tool_last_result.get(tool_name, json.dumps({"message": "（重複呼叫已攔截）"}, ensure_ascii=False))
                    print(f"\n🚫 [MCP] '{tool_name}' 本輪已呼叫 {resolved_counts[tool_name]} 次，攔截重複")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": prev})
                    continue

                cache_key = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))

                # 重複呼叫快取
                if cache_key in call_cache:
                    result_text = call_cache[cache_key]
                    print(f"\n⚡ [MCP] '{tool_name}' 命中快取，跳過重複呼叫")
                else:
                    # 執行 MCP 工具
                    print(f"\n🔌 [MCP] call_tool('{tool_name}', {tool_args})")
                    mcp_result = await mcp_client.call_tool(tool_name, tool_args)

                    if getattr(mcp_result, "is_error", False):
                        err_msg    = mcp_result.content[0].text if mcp_result.content else "工具執行錯誤"
                        print(f"❌ [MCP] '{tool_name}' 錯誤: {err_msg}")
                        result_text = json.dumps({"success": False, "message": err_msg}, ensure_ascii=False)
                    else:
                        result_text = mcp_result.content[0].text if mcp_result.content else "{}"
                        print(f"✅ [MCP] '{tool_name}' 完成")
                        call_cache[cache_key] = result_text

                # 計數；記錄最後結果（_ONCE_PER_TURN 攔截用）
                resolved_counts[tool_name] = resolved_counts.get(tool_name, 0) + 1
                tool_last_result[tool_name] = result_text

                try:
                    result_dict = json.loads(result_text)
                except Exception:
                    result_dict = {"raw": result_text}

                tool_log.append({"tool": tool_name, "params": tool_args,
                                 "result": result_dict, "ts": ts, "via": "mcp.Client"})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

        messages.append({"role": "assistant", "content": "（對話輪數過多，已停止。）"})
        return _make_result("（對話輪數過多，已停止。）")


_TDEE_TRIGGERS = {
    "tdee", "TDEE", "bmr", "BMR", "基礎代謝", "每日熱量",
    "吃多少", "熱量需求", "卡路里", "計算熱量", "計算tdee",
}


def _prefetch_tdee_for_ollama(prompt: str) -> tuple[str, dict | None]:
    """Ollama 小模型無法可靠地用 user_id 呼叫工具，改由我們代勞：
    偵測到 TDEE 相關問題時，直接呼叫 calculate_tdee，把結果嵌入 user prompt。
    注入到 prompt 而非 system，小模型對用戶訊息的遵從度遠高於系統指令。
    回傳 (augmented_prompt, tdee_log_entry | None)。
    """
    from app_helpers import calculate_tdee
    uid = st.session_state.get("user_id", 0)
    if not uid:
        return prompt, None
    if not any(kw in prompt for kw in _TDEE_TRIGGERS):
        return prompt, None

    try:
        result_str  = calculate_tdee(user_id=uid)
        result_dict = json.loads(result_str)
        if not result_dict.get("bmr"):          # 缺少體能資料 → 不注入，讓 AI 去問
            return prompt, None

        augmented_prompt = (
            f"{prompt}\n\n"
            f"[系統資料] 已根據您的個人資料計算完成：\n"
            f"{result_dict['message']}\n"
            f"請直接根據以上數據回答，不必再詢問身高、體重、年齡。"
            f"說明完畢後，詢問用戶『需要幫您推薦適合的採買商品嗎？』，等待確認再行動。"
        )
        log_entry = {
            "tool":   "calculate_tdee",
            "params": {"user_id": uid},
            "result": result_dict,
            "ts":     datetime.now().strftime("%H:%M:%S"),
            "via":    "prefetch",
        }
        return augmented_prompt, log_entry
    except Exception:
        return prompt, None


def ollama_chat(prompt: str, history: list) -> tuple:
    """OpenAI-compatible AI + MCP 同步入口（支援 Ollama / GPT-4o）。
    回傳 (text, tool_log, new_history)。"""
    history = _compact_history(history)
    history = _sanitize_for_openai(history)

    # ── 決定使用哪個 AI 後端 ─────────────────────────────────────────
    _oai_key = st.session_state.get("openai_key", "")
    if _oai_key:
        from openai import OpenAI as _OAI
        _ai_client = _OAI(api_key=_oai_key)
        _ai_model  = "gpt-4o"
        # GPT-4o 工具呼叫能力強，不需要 Qwen 專用的 prefetch
        augmented_prompt   = prompt
        tdee_prefetch_log  = None
    else:
        _ai_client = None
        _ai_model  = None
        augmented_prompt, tdee_prefetch_log = _prefetch_tdee_for_ollama(prompt)

    system = _build_system()
    msgs = [{"role": "system", "content": system}] + history + [
        {"role": "user", "content": augmented_prompt}
    ]
    try:
        _user_lat = st.session_state.get("user_lat")
        _user_lng = st.session_state.get("user_lng")
        _user_id  = st.session_state.get("user_id") or 0

        prefetch_cache: dict[tuple, str] = {}
        if tdee_prefetch_log:
            _key = ("calculate_tdee", json.dumps({"user_id": _user_id}, sort_keys=True, ensure_ascii=False))
            prefetch_cache[_key] = json.dumps(tdee_prefetch_log["result"], ensure_ascii=False)

        result = _run_async(_ollama_mcp_loop(msgs, prefetch_cache,
                                              user_lat=_user_lat, user_lng=_user_lng,
                                              user_id=_user_id,
                                              ai_client=_ai_client, ai_model=_ai_model))
    except Exception as exc:
        # 展開 anyio ExceptionGroup 取得真正的錯誤訊息
        real_exc = exc
        if hasattr(exc, "exceptions") and exc.exceptions:
            real_exc = exc.exceptions[0]
        backend = "GPT-4o" if _oai_key else f"Ollama ({OLLAMA_MODEL})"
        text = (
            f"❌ {backend} 連線失敗：{real_exc}\n\n"
            + ("請確認 OpenAI API Key 是否有效。" if _oai_key else
               f"請確認：\n1. Ollama 已啟動：`ollama serve`\n2. 已下載模型：`ollama pull {OLLAMA_MODEL}`")
        )
        fallback_history = history + [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": text},
        ]
        return text, [], fallback_history

    # 攔截到 submit_inquiry → 設定表單頁狀態
    if result["intercepted"]:
        intercepted_args = result["intercept_args"]
        st.session_state.inquiry_prefill  = intercepted_args
        st.session_state.inquiry_products = _products_from_submit(intercepted_args)
        st.session_state.stage            = "inquiry_form"
        # 把「開啟表單」訊息加入 history 讓對話連貫
        new_history = result["history"] + [
            {"role": "assistant", "content": "（為您開啟採買確認表單 📋）"}
        ]
        return "（正在開啟採買確認表單...）", result["tool_log"], new_history

    text        = result["text"]
    tool_log    = result["tool_log"]
    new_history = result["history"]

    # ── 幻覺偵測：AI 說「已建立諮詢單」但沒真的呼叫工具 → 自動跳表單 ────────
    _HALLUCINATION_KEYWORDS = ("已建立", "已為您建立", "諮詢單已", "訂單已", "採購諮詢單")
    _inquiry_called = any(e["tool"] == "submit_inquiry" for e in tool_log)
    if not _inquiry_called and any(kw in text for kw in _HALLUCINATION_KEYWORDS):
        print("⚠️ [幻覺偵測] AI 說已建立但未呼叫 submit_inquiry，自動跳表單")
        st.session_state.inquiry_prefill  = {}
        st.session_state.inquiry_products = st.session_state.get("last_products", [])
        st.session_state.stage            = "inquiry_form"
        return "（已偵測到確認意圖，為您開啟採買確認表單 📋）", tool_log, new_history

    # 把 prefetch TDEE 加到 tool_log 最前面（讓 UI 顯示 TDEE 卡片）
    # 但只在 Ollama 沒有自己呼叫 calculate_tdee 時才加，避免重複
    if tdee_prefetch_log:
        already_called = any(e["tool"] == "calculate_tdee" for e in tool_log)
        if not already_called:
            tool_log = [tdee_prefetch_log] + tool_log

    # 快取最新推薦商品
    for entry in tool_log:
        if entry["tool"] in ("recommend_high_protein", "search_grocery", "get_all_fitness_products"):
            prods = entry["result"].get("products") or entry["result"].get("items", [])
            if prods:
                st.session_state["last_products"] = prods
        # 快取健身課程（供下一輪注入 system prompt，避免重複呼叫）
        if entry["tool"] == "get_gym_courses" and entry["result"].get("courses"):
            st.session_state["last_gym_courses"] = entry["result"]["courses"]

    return text, tool_log, new_history


# ── 表單頁：透過 MCP Client 真正送出 submit_inquiry ──────────────────────────

async def _submit_inquiry_via_mcp(params: dict) -> dict:
    """從確認表單送出 submit_inquiry 或 enroll_gym_course，透過 mcp.Client 真實呼叫。"""
    is_enroll = params.pop("_enroll", False)
    # 過濾 None 值，MCP 不接受 None（只接受 string/int）
    clean = {k: (v if v is not None else "") for k, v in params.items()}

    if is_enroll:
        # 課程報名：呼叫 enroll_gym_course
        enroll_params = {
            "course_name":   clean.get("course_name", ""),
            "contact_name":  clean.get("contact_name", ""),
            "contact_phone": clean.get("contact_phone", ""),
            "note":          clean.get("note", ""),
            "user_id":       int(clean.get("user_id", 0) or 0),
        }
        print(f"\n🔌 [表單 MCP] mcp.Client.call_tool('enroll_gym_course', {enroll_params})")
        async with Client(_mcp) as c:
            result = await c.call_tool("enroll_gym_course", enroll_params)
            text = result.content[0].text if result.content else "{}"
            print(f"✅ [表單 MCP] enroll_gym_course 回傳: {text[:120]}")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"success": False, "message": text}

    print(f"\n🔌 [表單 MCP] mcp.Client.call_tool('submit_inquiry', {clean})")
    async with Client(_mcp) as c:
        result = await c.call_tool("submit_inquiry", clean)
        text = result.content[0].text if result.content else "{}"
        print(f"✅ [表單 MCP] submit_inquiry 回傳: {text[:120]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"success": False, "message": text}


# ── 商品 / 諮詢單結果渲染 ────────────────────────────────────────────────────

VENDOR_EMOJI = {
    "7-11": "🟢",
    "萬家福": "🔵",
    "樂家康": "🔵",
    "康是美": "🔴",
    "統一生機": "🟣"
}

_VENDOR_BANNER = {
    "7-11":     "#007B5E", "統一超商": "#007B5E",
    "萬家福":   "#1565C0", "樂家康":   "#1565C0",
    "康是美":   "#C62828", "Cosmed":   "#C62828",
    "統一生機": "#5E35B1",
    "Mister Donut": "#E65100",
    "Cold Stone":   "#0277BD",
    "21plus":       "#4A148C",
    "統一星巴克":   "#00704A",
    "聖德科斯":     "#2E7D32",
}

def _product_emoji(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["乳清", "蛋白粉", "protein", "whey"]): return "💪"
    if any(k in n for k in ["雞胸", "雞肉", "雞排"]): return "🍗"
    if any(k in n for k in ["鮭魚", "鮪魚", "魚排"]): return "🐟"
    if any(k in n for k in ["牛肉", "牛排", "牛", "豬"]): return "🥩"
    if any(k in n for k in ["蛋", "溫泉蛋", "茶葉蛋"]): return "🥚"
    if any(k in n for k in ["豆腐", "豆漿", "豆"]): return "🫘"
    if any(k in n for k in ["牛奶", "鮮奶", "奶粉", "乳品"]): return "🥛"
    if any(k in n for k in ["優格", "酸奶", "yogurt"]): return "🍶"
    if any(k in n for k in ["燕麥", "穀片", "麥片"]): return "🌾"
    if any(k in n for k in ["咖啡", "latte", "cappuccino"]): return "☕"
    if any(k in n for k in ["茶", "綠茶", "紅茶"]): return "🍵"
    if any(k in n for k in ["甜甜圈", "donut", "doughnut"]): return "🍩"
    if any(k in n for k in ["冰淇淋", "霜淇淋", "ice cream"]): return "🍦"
    if any(k in n for k in ["蛋白棒", "能量棒", "bar", "棒"]): return "🍫"
    if any(k in n for k in ["沙拉", "生菜", "蔬菜"]): return "🥗"
    if any(k in n for k in ["便當", "飯糰"]): return "🍱"
    if any(k in n for k in ["麵包", "吐司", "三明治"]): return "🥪"
    if any(k in n for k in ["堅果", "腰果", "花生", "核桃"]): return "🥜"
    if any(k in n for k in ["水果", "蘋果", "香蕉", "莓"]): return "🍎"
    if any(k in n for k in ["啤酒", "酒", "紅酒"]): return "🍺"
    if any(k in n for k in ["維他命", "膠原", "保健", "魚油"]): return "💊"
    return "🛒"

def _course_style(course_type: str) -> tuple:
    """回傳 (banner_color, emoji)"""
    _map = [
        (["有氧", "踏步", "HIIT"], "#E65100", "🏃"),
        (["重訓", "肌力", "槓鈴"], "#1A237E", "🏋️"),
        (["瑜伽", "冥想", "yoga"], "#7B1FA2", "🧘"),
        (["拳擊", "搏擊", "boxing"], "#B71C1C", "🥊"),
        (["飛輪", "spin", "cycling"], "#0D47A1", "🚴"),
        (["舞蹈", "舞", "dance"], "#880E4F", "💃"),
        (["TRX", "懸吊", "功能"], "#1B5E20", "🤸"),
        (["游泳", "水中", "swim"], "#006064", "🏊"),
    ]
    ct = course_type or ""
    for keys, color, emo in _map:
        if any(k in ct for k in keys):
            return color, emo
    return "#37474F", "⚡"
TOOL_META    = {
    "search_grocery":         ("🔍", "商品關鍵字搜尋"),
    "recommend_high_protein": ("💪", "高蛋白目標推薦"),
    "check_inventory":        ("📦", "通路庫存查詢"),
    "submit_inquiry":         ("📋", "建立採買諮詢單"),
    "get_current_time":       ("🕐", "當前時間"),
    "find_nearby_stores":     ("📍", "附近地點搜尋"),
    "find_route":             ("🗺️", "最佳配送路線"),
    "analyze_meal_nutrition": ("🍽️", "飲食卡路里分析"),
    "recommend_after_meal":   ("💡", "飲食後補充推薦"),
    "calculate_tdee":           ("🧮", "個人化TDEE計算"),
    "get_all_fitness_products": ("🛒", "全商品庫瀏覽"),
}

_CHAIN_MAP_COLOR = {
    "7-ELEVEN": "green", "統一超商": "green",
    "萬家福": "blue",    "樂家康": "blue",
    "康是美": "orange",  "Cosmed": "orange",
    "統一生機": "purple",
}


def _render_store_map(stores: list, user_lat, user_lng):
    """用 folium 畫門市地圖。"""
    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        st.warning("請安裝地圖套件：`uv pip install streamlit-folium folium`")
        return

    valid = [s for s in stores if s.get("lat") and s.get("lng")]
    if not valid and not (user_lat and user_lng):
        st.info("無法取得座標，無法顯示地圖。")
        return

    center_lat = user_lat or valid[0]["lat"]
    center_lng = user_lng or valid[0]["lng"]

    m = folium.Map(location=[center_lat, center_lng], zoom_start=15, tiles="OpenStreetMap")

    if user_lat and user_lng:
        folium.Marker(
            [user_lat, user_lng],
            popup="📍 您的位置",
            tooltip="您的位置",
            icon=folium.Icon(color="red", icon="home"),
        ).add_to(m)

    for s in valid:
        color = "gray"
        for chain, c in _CHAIN_MAP_COLOR.items():
            if chain in s["name"]:
                color = c
                break
        dist = s.get("distance_m")
        dist_str = f"📏 {dist}m<br>" if dist else ""
        popup_html = (
            f"<b>{s['name']}</b><br>"
            f"{dist_str}"
            f"📍 {s.get('address', '地址詳見地圖')}<br>"
            f"📞 {s.get('phone') or '—'}"
        )
        folium.Marker(
            [s["lat"], s["lng"]],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=s["name"],
            icon=folium.Icon(color=color),
        ).add_to(m)

    st_folium(m, width="100%", height=420, returned_objects=[])


def _product_card(p: dict, key_prefix: str) -> str:
    """生成單一商品的 LINE 卡片 HTML（純 HTML，用 ?add_cart= 觸發加入）"""
    name    = p.get("name", "")
    vendor  = p.get("vendor", "")
    stock   = p.get("stock", 0)
    price   = p.get("price", 0)
    protein = p.get("protein_g", 0)
    cal     = p.get("calories", 0)
    banner  = _VENDOR_BANNER.get(vendor, "#607D8B")
    emo     = _product_emoji(name)
    qty     = st.session_state.get("cart", {}).get(name, {}).get("qty", 0)
    st.session_state.setdefault("product_catalog", {})[name] = p
    dimmed  = "opacity:.45;filter:grayscale(80%);" if stock == 0 else ""
    badge   = ""
    if stock > 0:
        _na = name.replace('"', '&quot;')
        btn = (f'<button data-ph="__add_cart__" data-name="{_na}" '
               f'style="display:block;width:100%;text-align:center;'
               f'background:#00833D;color:#fff;border:none;border-radius:999px;'
               f'padding:6px 0;font-size:12px;font-weight:600;margin-top:8px;cursor:pointer;">'
               f'＋ 加入</button>')
    else:
        btn = '<div style="text-align:center;color:#bbb;font-size:11px;margin-top:8px;">❌ 售完</div>'
    return (
        f'<div style="min-width:155px;max-width:175px;border-radius:16px;overflow:hidden;'
        f'box-shadow:0 2px 10px rgba(0,0,0,.10);flex-shrink:0;background:#fff;'
        f'border:1.5px solid #e8e8e8;{dimmed}">'
        f'<div style="background:{banner};padding:22px 10px;text-align:center;'
        f'font-size:42px;line-height:1.1;">{emo}</div>'
        f'<div style="padding:10px 12px 12px;">'
        f'<div style="font-weight:700;font-size:13px;color:#111;'
        f'overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;'
        f'-webkit-box-orient:vertical;">{name}</div>'
        f'<div style="font-size:11px;color:#999;margin:2px 0;">{vendor}</div>'
        f'<div style="font-size:11px;color:#555;margin:4px 0;line-height:1.6;">'
        f'🥩 {protein}g &nbsp;·&nbsp; 🔥 {cal} kcal<br>'
        f'💰 <b style="color:#d32f2f;">${price}</b> &nbsp;·&nbsp; 📦 {stock}</div>'
        f'{badge}{btn}</div></div>'
    )


def _course_card(c: dict) -> str:
    """生成單一課程的 LINE 卡片 HTML（?tog_course= 觸發切換）"""
    cname   = c.get("course_name", "")
    avail   = c.get("available_slots", 0)
    banner, emo = _course_style(c.get("course_type", ""))
    is_sel  = cname in st.session_state.get("selected_courses", [])
    dimmed  = "" if avail > 0 else "opacity:.45;filter:grayscale(80%);"
    avail_s = f"剩 {avail} 名" if avail > 0 else "已額滿"
    badge   = ('<div style="font-size:11px;font-weight:700;color:#1565C0;margin:2px 0;">✓ 已選</div>'
               if is_sel else "")
    if avail > 0:
        btn_lbl = "取消選擇" if is_sel else "＋ 選課"
        btn_bg  = "#9E9E9E" if is_sel else "#1565C0"
        _ca = cname.replace('"', '&quot;')
        btn = (f'<button data-ph="__tog_course__" data-name="{_ca}" '
               f'style="display:block;width:100%;text-align:center;'
               f'background:{btn_bg};color:#fff;border:none;border-radius:999px;'
               f'padding:6px 0;font-size:12px;font-weight:600;margin-top:8px;cursor:pointer;">'
               f'{btn_lbl}</button>')
    else:
        btn = '<div style="text-align:center;color:#bbb;font-size:11px;margin-top:8px;">已額滿</div>'
    return (
        f'<div style="min-width:155px;max-width:175px;border-radius:16px;overflow:hidden;'
        f'box-shadow:0 2px 10px rgba(0,0,0,.10);flex-shrink:0;background:#fff;'
        f'border:1.5px solid #e8e8e8;{dimmed}">'
        f'<div style="background:{banner};padding:22px 10px;text-align:center;'
        f'font-size:42px;line-height:1.1;">{emo}</div>'
        f'<div style="padding:10px 12px 12px;">'
        f'<div style="font-weight:700;font-size:13px;color:#111;'
        f'overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;'
        f'-webkit-box-orient:vertical;">{cname}</div>'
        f'<div style="font-size:11px;color:#999;margin:2px 0;">{c.get("course_type","")}</div>'
        f'<div style="font-size:11px;color:#555;margin:4px 0;line-height:1.6;">'
        f'📅 {c.get("weekday","")} {c.get("time_start","")}<br>'
        f'🧑‍🏫 {c.get("coach","")} · ⏱ {c.get("duration_min",0)}分<br>'
        f'💰 NT${c.get("price_month",0)}/月 · 🪑 {avail_s}</div>'
        f'{badge}{btn}</div></div>'
    )


_CAROUSEL_WRAP = ('<div style="display:flex;overflow-x:auto;gap:12px;padding:8px 2px 12px;'
                  '-webkit-overflow-scrolling:touch;scrollbar-width:thin;">', '</div>')


def render_tool_results(tool_calls: list, msg_idx: int = 0):
    for tc in tool_calls:
        tool   = tc["tool"]
        result = tc["result"]
        icon, label = TOOL_META.get(tool, ("🔧", tool))

        # ── 諮詢單 ──────────────────────────────────────────────────────────
        if tool == "submit_inquiry":
            if result.get("success"):
                st.success(
                    f"📋 **諮詢單已建立！**\n\n"
                    f"單號：`{result.get('feedback_no') or result.get('inquiry_no', '')}`\n\n"
                    f"{result.get('message', '')}"
                )
            else:
                err = result.get("message") or result.get("raw") or "未知錯誤"
                st.error(f"諮詢單建立失敗：{err}")
            continue

        # ── 當前時間 ─────────────────────────────────────────────────────────
        if tool == "get_current_time":
            st.info(
                f"🕐 **{result.get('datetime', '')}**　"
                f"{result.get('weekday', '')}　{result.get('period', '')}"
            )
            continue

        # ── 附近門市地圖 ─────────────────────────────────────────────────────
        if tool == "find_nearby_stores":
            stores = result.get("stores", [])
            with st.expander(f"📍 附近門市 — {result.get('message', '')}", expanded=True):
                if not stores:
                    st.info(result.get("message", "無門市資料"))
                else:
                    _render_store_map(
                        stores,
                        st.session_state.get("user_lat"),
                        st.session_state.get("user_lng"),
                    )
                    st.divider()
                    for s in stores:
                        dist = s.get("distance_m")
                        dist_str = f"　📏 {dist}m" if dist else ""
                        phone_str = f"　📞 {s['phone']}" if s.get("phone") else ""
                        st.markdown(
                            f"**{s['name']}**{dist_str}  \n"
                            f"📍 {s.get('address', '地址詳見地圖')}{phone_str}"
                        )
            continue

        # ── TDEE 個人化計算結果 ──────────────────────────────────────────────
        if tool == "calculate_tdee":
            with st.expander(
                f"🧮 個人化 TDEE — {result.get('goal', '')} · {result.get('weight_kg', '')}kg",
                expanded=True,
            ):
                st.info(result.get("message", ""))
                st.divider()
                r1c1, r1c2, r1c3 = st.columns(3)
                r1c1.metric("🔥 基礎代謝 BMR", f"{int(result.get('bmr', 0))} kcal")
                r1c2.metric("⚡ 每日消耗 TDEE", f"{int(result.get('tdee', 0))} kcal")
                r1c3.metric("🎯 目標熱量", f"{int(result.get('target_calories', 0))} kcal")
                st.divider()
                r2c1, r2c2, r2c3 = st.columns(3)
                r2c1.metric("🥩 蛋白質",  f"{int(result.get('protein_goal_g', 0))} g/天")
                r2c2.metric("🍚 碳水化合物", f"{int(result.get('carbs_goal_g', 0))} g/天")
                r2c3.metric("🧈 脂肪",    f"{int(result.get('fat_goal_g', 0))} g/天")
                st.caption(
                    f"活動量：{result.get('activity_desc', '')}　｜　"
                    f"公式：Mifflin-St Jeor"
                )
            continue

        # ── 飲食卡路里分析（單一食物）────────────────────────────────────────
        if tool == "analyze_meal_nutrition":
            if not result.get("success"):
                st.warning(result.get("message", "無法查詢此食物的營養資料"))
                continue
            with st.expander(
                f"🍽️ {result.get('food', '')} {result.get('amount_g', 0):.0f}g"
                f" — {result.get('message', '')}",
                expanded=True,
            ):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("🔥 熱量",   f"{result.get('calories',  0)} kcal")
                c2.metric("🥩 蛋白質", f"{result.get('protein_g', 0)} g")
                c3.metric("🧈 脂肪",   f"{result.get('fat_g',     0)} g")
                c4.metric("🍚 碳水",   f"{result.get('carbs_g',   0)} g")
                if result.get("source") == "Edamam":
                    st.caption("資料來源：Edamam Nutrition API")
            continue

        # ── 飲食後補充採買推薦 ──────────────────────────────────────────────
        if tool == "recommend_after_meal":
            with st.expander(
                f"💡 {result.get('fitness_goal', '增肌')} 補充採買建議",
                expanded=True,
            ):
                st.info(result.get("message", ""))
                c1, c2 = st.columns(2)
                c1.metric("⚡ 尚需熱量",   f"{result.get('calories_gap', 0)} kcal")
                c2.metric("💪 尚需蛋白質", f"{result.get('protein_gap',  0)} g")
                st.divider()
                products_rec = result.get("recommended_products", [])
                if products_rec:
                    st.markdown("**🛒 推薦補充商品**")
                    _html = _CAROUSEL_WRAP[0]
                    for p in products_rec:
                        _html += _product_card(p, f"rec{msg_idx}")
                    _html += _CAROUSEL_WRAP[1]
                    st.markdown(_html, unsafe_allow_html=True)
            continue

        # ── 健身課程列表 ──────────────────────────────────────────────────────
        if tool == "get_gym_courses":
            courses = result.get("courses", [])
            with st.expander(f"🏋️ 健身課程 — {result.get('message', '')}", expanded=True):
                if not courses:
                    st.info(result.get("message", "暫無課程資料"))
                else:
                    _html = _CAROUSEL_WRAP[0]
                    for c in courses:
                        _html += _course_card(c)
                    _html += _CAROUSEL_WRAP[1]
                    st.markdown(_html, unsafe_allow_html=True)
            continue

        # ── 商品列表（search / recommend / inventory）────────────────────────
        if isinstance(result, list):
            result = {"products": result, "message": f"共 {len(result)} 項商品"}
        products = result.get("products") or result.get("items", [])
        with st.expander(f"{icon} {label} — {result.get('message', '')}", expanded=True):
            if not products:
                st.info(result.get("message", "無結果"))
                continue

            if tool == "recommend_high_protein":
                c1, c2, c3 = st.columns(3)
                c1.metric("推薦商品數", f"{result.get('count', 0)} 項")
                c2.metric("合計蛋白質", f"{result.get('total_protein_g', 0)} g")
                c3.metric("花費",       f"${result.get('total_price', 0)}")
                st.divider()

            _html = _CAROUSEL_WRAP[0]
            for p in products:
                _html += _product_card(p, f"{msg_idx}_{tool}")
            _html += _CAROUSEL_WRAP[1]
            st.markdown(_html, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# Page config & session init
# ═════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="統一生活管家", page_icon="🏪", layout="wide")

# ── PWA meta tags + manifest（讓手機可「加入主畫面」成為 app）────────────────
st.markdown("""
<script>
(function() {
    // manifest
    if (!document.querySelector('link[rel="manifest"]')) {
        var l = document.createElement('link');
        l.rel = 'manifest'; l.href = '/app/static/manifest.json';
        document.head.appendChild(l);
    }
    // theme color
    if (!document.querySelector('meta[name="theme-color"]')) {
        var m = document.createElement('meta');
        m.name = 'theme-color'; m.content = '#00833D';
        document.head.appendChild(m);
    }
    // iOS PWA
    ['apple-mobile-web-app-capable','mobile-web-app-capable'].forEach(function(n) {
        if (!document.querySelector('meta[name="'+n+'"]')) {
            var mi = document.createElement('meta');
            mi.name = n; mi.content = 'yes';
            document.head.appendChild(mi);
        }
    });
    var mt = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (!mt) {
        mt = document.createElement('meta');
        mt.name = 'apple-mobile-web-app-title'; mt.content = '統一生活管家';
        document.head.appendChild(mt);
    }
})();
</script>
""", unsafe_allow_html=True)

for k, v in {
    "stage":              "login",
    "user_id":            None,
    "username":           "",
    "display_msgs":       [],
    "claude_msgs":        [],
    "ollama_history":     [],
    "mcp_log":            [],
    "api_key":            os.environ.get("ANTHROPIC_API_KEY", ""),
    "openai_key":         os.environ.get("OPENAI_API_KEY", ""),
    "inquiry_prefill":    {},
    "inquiry_products":   [],
    "conversation_id":    None,
    "cart":               {},
    "selected_courses":   [],
    "product_catalog":    {},
    "last_products":      [],
    "_pending_delete_id": None,
    "insurance_sign_no": "",
    "user_lat":           None,
    "user_lng":           None,
    # 用戶體能資料
    "user_gender":         "",
    "user_age":            0,
    "user_height_cm":      0.0,
    "user_weight_kg":      0.0,
    "user_fitness_goal":   "",
    "user_address":        "",
    "user_contact_phone":  "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    if st.session_state.user_id:
        # ── 用戶資訊列 ──────────────────────────────────────────────────────
        col_u, col_out = st.columns([3, 1])
        col_u.markdown(f"👤 **{st.session_state.username}**")
        if col_out.button("登出", key="logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        # ── 操作按鈕 ────────────────────────────────────────────────────────
        if st.button("➕ 新對話", use_container_width=True, key="new_chat", type="primary"):
            st.session_state.update({
                "display_msgs":    [],
                "claude_msgs":     [],
                "ollama_history":  [],
                "mcp_log":         [],
                "cart":            {},
                "last_products":   [],
                "conversation_id": None,
                "stage":           "chat",
            })
            st.rerun()

        b1, b2 = st.columns(2)
        if b1.button("📦 我的訂單", use_container_width=True, key="goto_orders"):
            st.session_state.stage = "my_orders"
            st.rerun()
        if b2.button("💬 對話", use_container_width=True, key="goto_chat"):
            st.session_state.stage = "chat"
            st.rerun()

        # ── 快速訂單狀態（不離開對話）───────────────────────────────────
        _quick_orders = get_my_inquiries(st.session_state.user_id)[:3]
        if _quick_orders:
            _ORDER_BADGE = {
                "01": ("#FF9800", "⏳"),
                "04": ("#9C27B0", "✍️"),
                "05": ("#2196F3", "🔍"),
                "02": ("#1976D2", "🚚"),
                "80": ("#43A047", "✅"),
                "90": ("#E53935", "❌"),
                "03": ("#7B5EA7", "📦"),
            }
            _ORDER_LABEL = {
                "01": "待處理", "02": "配送中", "03": "預留中",
                "04": "待簽名", "05": "待後台確認",
                "80": "已完成", "90": "已拒絕",
            }
            # ── 保險待簽名提醒 ──────────────────────────────────────────
            _pending_sign = [o for o in _quick_orders if o.get("status") == "04" and "保險" in (o.get("goal") or "")]
            if not _pending_sign:
                _all_orders_for_sign = get_my_inquiries(st.session_state.user_id)
                _pending_sign = [o for o in _all_orders_for_sign if o.get("status") == "04" and "保險" in (o.get("goal") or "")]
            if _pending_sign:
                _ps = _pending_sign[0]
                if st.button(
                    f"✍️ 保單待簽名：{_ps['feedback_no']}",
                    key="sidebar_sign_btn",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state.insurance_sign_no = _ps["feedback_no"]
                    st.session_state.stage = "insurance_sign"
                    st.rerun()

            with st.expander("📦 最近訂單", expanded=False):
                for _qo in _quick_orders:
                    _qs = _qo.get("status", "01")
                    _qc, _qi = _ORDER_BADGE.get(_qs, ("#888", "❓"))
                    st.markdown(
                        f'<span style="background:{_qc};color:white;border-radius:8px;'
                        f'padding:1px 7px;font-size:0.72rem;font-weight:700">{_qi} {_ORDER_LABEL.get(_qs, _qs)}</span>'
                        f' <span style="font-size:0.8rem;color:#444">{_qo.get("goal","")[:14]}</span>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f'`{_qo["feedback_no"]}` · {str(_qo.get("created_at",""))[:10]}')
                if st.button("查看全部", use_container_width=True, key="sb_all_orders"):
                    st.session_state.stage = "my_orders"
                    st.rerun()

        st.divider()

        # ── 對話記錄列表 ────────────────────────────────────────────────────
        st.markdown("#### 📜 對話記錄")
        convs = get_conversations(st.session_state.user_id)
        if not convs:
            st.caption("還沒有對話記錄")
        else:
            current_id = st.session_state.get("conversation_id")

            # ── 刪除 Modal 確認 ─────────────────────────────────────────
            pending_del = st.session_state.get("_pending_delete_id")
            if pending_del:
                del_title = next((c["title"] for c in convs if c["id"] == pending_del), "?")
                _delete_confirm_dialog(pending_del, del_title)

            for conv in convs:
                is_cur   = conv["id"] == current_id
                date_str = conv["updated_at"][5:10]
                label    = f"▶ {conv['title']}" if is_cur else conv["title"]
                btn_type = "primary" if is_cur else "secondary"

                col_btn, col_menu = st.columns([5, 1])
                if col_btn.button(
                    label,
                    key=f"conv_{conv['id']}",
                    use_container_width=True,
                    type=btn_type,
                    help=f"更新：{date_str}",
                ):
                    if not is_cur:
                        rec = load_conv_from_db(conv["id"])
                        st.session_state.update({
                            "display_msgs":    json.loads(rec.get("disp_json",   "[]")),
                            "ollama_history":  json.loads(rec.get("ollama_json", "[]")),
                            "claude_msgs":     [],
                            "mcp_log":         [],
                            "last_products":   [],
                            "conversation_id": conv["id"],
                            "stage":           "chat",
                        })
                        st.rerun()

                with col_menu.popover("⋯"):
                    st.caption(conv["title"][:20])
                    new_name = st.text_input(
                        "重新命名", value=conv["title"],
                        key=f"rename_input_{conv['id']}",
                        label_visibility="collapsed",
                        placeholder="輸入新名稱",
                    )
                    if st.button("✅ 更名", key=f"rename_ok_{conv['id']}", use_container_width=True):
                        if new_name.strip():
                            rename_conversation(conv["id"], new_name)
                        st.rerun()
                    st.divider()
                    if st.button("🗑️ 刪除", key=f"del_{conv['id']}", type="secondary", use_container_width=True):
                        st.session_state._pending_delete_id = conv["id"]
                        st.rerun()

        st.divider()

    # ── 位置偵測（JS 組件必須在 expander 外呼叫才能正常執行）────────────────────
    # 自訂 JS：成功回傳 {coords}，失敗回傳 {error: code}
    # 每次重新偵測 _geo_refresh_count +1 → 新 key → 組件重新掛載 → 重跑 JS
    if _HAS_GEO:
        _geo_key = f"geo_{st.session_state.get('_geo_refresh_count', 0)}"
        _loc = _js_eval(
            js_expressions="""
                new Promise(resolve => navigator.geolocation.getCurrentPosition(
                    p => resolve({coords: {latitude: p.coords.latitude, longitude: p.coords.longitude}}),
                    e => resolve({error: e.code}),
                    {maximumAge: 0, timeout: 10000}
                ))
            """,
            key=_geo_key,
        )
        if _loc and _loc.get("coords"):
            st.session_state.user_lat = _loc["coords"]["latitude"]
            st.session_state.user_lng = _loc["coords"]["longitude"]
            st.session_state.pop("_geo_error", None)
        elif _loc and _loc.get("error"):
            st.session_state["_geo_error"] = _loc["error"]

    with st.expander("📍 我的位置", expanded=False):
        if st.session_state.get("user_lat"):
            lat, lng = st.session_state.user_lat, st.session_state.user_lng
            _addr = _reverse_geocode(round(lat, 5), round(lng, 5))
            st.success(f"已取得位置 ✅")
            if _addr:
                st.caption(_addr)
            st.caption(f"緯度 {lat:.5f}　經度 {lng:.5f}")
            if st.button("🔄 重新偵測", key="geo_refresh", use_container_width=True):
                st.session_state.user_lat = None
                st.session_state.user_lng = None
                st.session_state.pop("_geo_error", None)
                st.session_state["_geo_refresh_count"] = st.session_state.get("_geo_refresh_count", 0) + 1
                st.rerun()
        else:
            if not _HAS_GEO:
                st.warning("⚠️ GPS 不可用（未安裝 streamlit-js-eval）")
            elif st.session_state.get("_geo_error") == 1:
                st.error("位置授權遭拒，請在瀏覽器設定中允許存取位置。")
                if st.button("🔄 重新偵測", key="geo_retry", use_container_width=True):
                    st.session_state.pop("_geo_error", None)
                    st.session_state["_geo_refresh_count"] = st.session_state.get("_geo_refresh_count", 0) + 1
                    st.rerun()
            else:
                st.info("正在取得位置…請允許瀏覽器的授權請求")
                st.caption("手機用戶：若持續無法取得，請改用下方手動輸入。")
            # 手動城市輸入（手機 HTTP 下瀏覽器封鎖 GPS 時的備案）
            _manual = st.text_input(
                "或手動輸入城市",
                value=st.session_state.get("manual_city", ""),
                placeholder="例：台北市、高雄市、台中市",
                key="manual_city_input",
            )
            if st.button("✅ 設定城市", key="set_manual_city", use_container_width=True):
                st.session_state["manual_city"] = _manual.strip()
                st.rerun()

    st.divider()

    # ── AI 模式設定 ──────────────────────────────────────────────────────────
    with st.expander("⚙️ AI 設定", expanded=False):
        if st.session_state.api_key:
            st.success("🤖 Claude AI 模式（claude-sonnet-4-6）")
            entered = st.text_input("重新輸入 Anthropic Key", type="password", key="key_override")
            c1, c2 = st.columns(2)
            if c1.button("套用", key="apply_key"):
                if entered.strip():
                    st.session_state.api_key = entered.strip(); st.rerun()
            if c2.button("清除（切回 GPT-4o / Ollama）", key="clear_key"):
                st.session_state.api_key = ""; st.rerun()
        elif st.session_state.get("openai_key"):
            st.success("🤖 OpenAI GPT-4o 模式")
            entered_oai = st.text_input("重新輸入 OpenAI Key", type="password", key="oai_override")
            oc1, oc2 = st.columns(2)
            if oc1.button("套用", key="apply_oai"):
                if entered_oai.strip():
                    st.session_state.openai_key = entered_oai.strip(); st.rerun()
            if oc2.button("清除（切回 Ollama）", key="clear_oai"):
                st.session_state.openai_key = ""; st.rerun()
        else:
            st.info(f"🤖 本地 Ollama（{OLLAMA_MODEL}）+ MCP")
            st.markdown("**啟用雲端 AI：**")
            entered = st.text_input(
                "Anthropic API Key（Claude）", type="password",
                placeholder="sk-ant-api03-...", key="key_input"
            )
            if st.button("啟用 Claude AI", key="enable_claude"):
                if entered.strip():
                    st.session_state.api_key = entered.strip(); st.rerun()
            st.divider()
            entered_oai = st.text_input(
                "OpenAI API Key（GPT-4o）", type="password",
                placeholder="sk-...", key="oai_key_input"
            )
            if st.button("啟用 GPT-4o", key="enable_openai"):
                if entered_oai.strip():
                    st.session_state.openai_key = entered_oai.strip(); st.rerun()

    # ── MCP 工具呼叫紀錄（折疊）────────────────────────────────────────────
    log_label = f"🔌 MCP 紀錄（{len(st.session_state.mcp_log)} 筆）"
    with st.expander(log_label, expanded=bool(st.session_state.mcp_log)):
        if not st.session_state.mcp_log:
            st.caption("尚未呼叫任何工具")
        else:
            for entry in reversed(st.session_state.mcp_log):
                icon, _ = TOOL_META.get(entry["tool"], ("🔧", entry["tool"]))
                is_write = entry["tool"] in ("submit_inquiry", "dispatch_delivery")
                via = entry.get("via", "unknown")
                with st.container(border=True):
                    rw  = "🔴寫入" if is_write else "🟢讀取"
                    via_badge = "`mcp.Client`" if via == "mcp.Client" else "`direct`"
                    st.caption(f"{icon} **{entry['tool']}** {rw} · `{entry['ts']}`")
                    st.caption(f"路徑：{via_badge}")
                    params_str = "  ".join(f"{k}={v}" for k, v in entry["params"].items())
                    st.code(params_str, language=None)
                    st.json(entry["result"], expanded=False)
            if st.button("清除", use_container_width=True, key="clear_mcp"):
                st.session_state.mcp_log = []; st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown("## 🏪 統一生活管家")
st.caption("統一集團 × AI 助手 ✦ 7-11・萬家福・康是美・統一生機・Mister Donut・Cold Stone・21plus・統一星巴克・聖德科斯")
st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: LOGIN
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.stage == "login":
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("### 👤 歡迎使用 統一生活管家")
        st.markdown("登入後即可開始與 AI 對話採買 💪")
        st.markdown("")
        tab_login, tab_reg = st.tabs(["登入", "📝 新用戶註冊"])

        def _load_profile(user: dict):
            """登入/註冊後把體能資料存入 session_state。"""
            st.session_state.user_gender        = user.get("gender", "")
            st.session_state.user_birthday      = user.get("birthday", "")
            st.session_state.user_height_cm     = float(user.get("height_cm", 0) or 0)
            st.session_state.user_weight_kg     = float(user.get("weight_kg", 0) or 0)
            st.session_state.user_email         = user.get("email", "")
            st.session_state.user_dietary_pref  = user.get("dietary_pref", "")
            st.session_state.user_county_code   = user.get("county_code", "")
            st.session_state.user_district_code = user.get("district_code", "")
            st.session_state.user_address       = user.get("address", "")
            st.session_state.user_contact_phone = user.get("contact_phone", "")

        with tab_login:
            u = st.text_input("帳號", key="li_u", placeholder="請輸入帳號")
            p = st.text_input("密碼", type="password", key="li_p", placeholder="請輸入密碼")
            if st.button("登入", type="primary", use_container_width=True, key="btn_login"):
                user = check_login(u.strip(), p.strip())
                if user:
                    st.session_state.user_id  = user["id"]
                    st.session_state.username = user["username"]
                    st.session_state.stage    = "chat"
                    _load_profile(user)
                    st.session_state.claude_msgs.append({
                        "role": "user",
                        "content": f"（用戶 {user['username']} 已登入，請先問好並詢問他的健康需求）",
                    })
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤，請再試一次。")

        with tab_reg:
            # ── 必填：帳號 / 密碼 ────────────────────────────────────────────
            ru = st.text_input("帳號", key="reg_u", placeholder="請輸入帳號（至少 2 字元）")
            rp = st.text_input("密碼", type="password", key="reg_p",
                               placeholder="請設定密碼（至少 4 字元）")
            reg_email = st.text_input("電子郵件", key="reg_email",
                                      placeholder="example@email.com")

            # ── 選填：個人資料 ────────────────────────────────────────────────
            with st.expander("👤 個人資料（選填）"):
                rc1, rc2 = st.columns(2)
                reg_gender   = rc1.radio("性別", ["男", "女"], horizontal=True, key="reg_gender")
                reg_birthday = rc2.date_input("生日", value=None, key="reg_birthday",
                                              min_value=date(1900, 1, 1))
                rc3, rc4 = st.columns(2)
                reg_height = rc3.number_input("身高（cm）", min_value=0.0, max_value=250.0,
                                               value=0.0, step=0.5, key="reg_height")
                reg_weight = rc4.number_input("體重（kg）", min_value=0.0, max_value=300.0,
                                               value=0.0, step=0.5, key="reg_weight")
                reg_dietary = st.selectbox(
                    "飲食偏好",
                    ["無限制", "素食", "純素（Vegan）", "無麩質", "清真（Halal）"],
                    key="reg_dietary",
                )

            # ── 選填：聯絡與配送地區 ─────────────────────────────────────────
            with st.expander("📦 聯絡與配送地區（選填）"):
                reg_phone = st.text_input("聯絡電話", key="reg_phone",
                                          placeholder="例：0912345678")
                _counties = get_counties()
                _county_names = ["（不選擇）"] + [c[1] for c in _counties]
                _county_codes = [""]            + [c[0] for c in _counties]
                _reg_county_idx = st.selectbox(
                    "縣市", range(len(_county_names)),
                    format_func=lambda i: _county_names[i],
                    key="reg_county",
                )
                _reg_county_code = _county_codes[_reg_county_idx]
                if _reg_county_code:
                    _districts = get_districts(_reg_county_code)
                    if _districts:
                        _dist_names = [d[1] for d in _districts]
                        _dist_codes = [d[0] for d in _districts]
                        _reg_dist_idx = st.selectbox(
                            "行政區",
                            range(len(_dist_names)),
                            format_func=lambda i: _dist_names[i],
                            key=f"reg_dist_{_reg_county_code}",
                        )
                        _reg_district_code = _dist_codes[_reg_dist_idx]
                    else:
                        st.caption("此縣市的行政區資料尚未收錄。")
                        _reg_district_code = ""
                else:
                    _reg_district_code = ""
                reg_address = st.text_input(
                    "詳細地址",
                    key="reg_address",
                    placeholder="例：忠孝東路四段 X 號 X 樓",
                )

            # ── 送出 ─────────────────────────────────────────────────────────
            if st.button("註冊並登入", type="primary", use_container_width=True, key="btn_reg"):
                if len(ru.strip()) < 2:
                    st.error("帳號至少需要 2 個字元。")
                elif len(rp.strip()) < 4:
                    st.error("密碼至少需要 4 個字元。")
                else:
                    _bday_str = reg_birthday.isoformat() if reg_birthday else ""
                    _diet_val = "" if reg_dietary == "無限制" else reg_dietary
                    ok = register_user(
                        ru.strip(), rp.strip(),
                        gender=reg_gender,
                        birthday=_bday_str,
                        height_cm=float(reg_height),
                        weight_kg=float(reg_weight),
                        email=reg_email.strip(),
                        dietary_pref=_diet_val,
                        county_code=_reg_county_code,
                        district_code=_reg_district_code,
                        address=reg_address.strip(),
                        contact_phone=reg_phone.strip(),
                    )
                    if ok:
                        user = check_login(ru.strip(), rp.strip())
                        st.session_state.user_id  = user["id"]
                        st.session_state.username = user["username"]
                        st.session_state.stage    = "chat"
                        _load_profile(user)
                        st.session_state.claude_msgs.append({
                            "role": "user",
                            "content": f"（新用戶 {user['username']} 剛完成註冊，請歡迎他並詢問健康需求）",
                        })
                        st.rerun()
                    else:
                        st.error("此帳號已被使用，請換一個帳號。")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: INQUIRY FORM — 採買確認表單（AI 欲送出諮詢單時顯示）
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "inquiry_form":
    prefill  = st.session_state.inquiry_prefill
    products = st.session_state.inquiry_products
    is_enroll = prefill.get("_enroll", False)

    col_back, col_title = st.columns([1, 6])
    if col_back.button("← 返回對話", key="form_back"):
        st.session_state.stage = "chat"
        st.session_state.inquiry_prefill  = {}
        st.session_state.inquiry_products = []
        st.rerun()

    if is_enroll:
        col_title.markdown("## 🏋️ 課程報名確認")
        st.caption("請確認報名資訊後送出，系統將同步建立諮詢單。")
        st.divider()

        course_nm = st.text_input("📚 報名課程", value=prefill.get("course_name", ""), key="enroll_course")
        c1, c2 = st.columns(2)
        name  = c1.text_input("👤 報名人姓名 *",
                               value=prefill.get("contact_name", "") or st.session_state.get("username", ""),
                               key="enroll_name")
        phone = c2.text_input("📞 聯絡電話 *",
                               value=prefill.get("contact_phone", "") or st.session_state.get("user_contact_phone", ""),
                               key="enroll_phone")
        note  = st.text_area("📝 備註（過敏、舊傷、特殊需求）", value=prefill.get("note", ""),
                              height=80, key="enroll_note")

        st.divider()
        can_submit = bool(course_nm.strip() and name.strip() and phone.strip())
        if not can_submit:
            st.warning("⚠️ 請填寫課程名稱、姓名與電話後再送出。")

        if st.button("✅ 確認報名", type="primary", disabled=not can_submit,
                     use_container_width=True, key="form_submit"):
            with st.spinner("📡 透過 MCP 建立報名中..."):
                params = {
                    "_enroll":       True,
                    "course_name":   course_nm.strip(),
                    "contact_name":  name.strip(),
                    "contact_phone": phone.strip(),
                    "note":          note or "",
                    "user_id":       st.session_state.get("user_id") or 0,
                }
                result = _run_async(_submit_inquiry_via_mcp(params))
            st.session_state.mcp_log.append({
                "tool":   "enroll_gym_course",
                "params": {k: v for k, v in params.items() if k != "_enroll"},
                "result": result,
                "ts":     datetime.now().strftime("%H:%M:%S"),
                "via":    "mcp.Client",
            })
            if result.get("success"):
                inq_no     = result.get("feedback_no", "")
                course_ret = result.get("course_name", course_nm.strip())
                success_msg = (
                    f"✅ 已成功提交【{course_ret}】報名申請！"
                    f"諮詢單號：`{inq_no}`，後台確認後將主動通知您。"
                )
                st.session_state.ollama_history.append(
                    {"role": "assistant", "content": success_msg}
                )
                st.session_state.display_msgs.append({
                    "role": "assistant",
                    "content": success_msg,
                    "tool_calls": [{
                        "tool":   "enroll_gym_course",
                        "params": {k: v for k, v in params.items() if k != "_enroll"},
                        "result": result,
                        "ts":     datetime.now().strftime("%H:%M:%S"),
                        "via":    "mcp.Client",
                    }],
                })
                st.session_state.stage            = "chat"
                st.session_state.inquiry_prefill  = {}
                st.session_state.inquiry_products = []
                st.session_state.cart             = {}
                st.session_state.selected_courses = []
                st.rerun()
            else:
                st.error(f"❌ 報名失敗：{result.get('message', '請稍後再試')}")

    else:
        _goal_val = prefill.get("goal", "")
        _is_ins_form = "保險" in _goal_val or "旅遊險" in _goal_val

        if _is_ins_form:
            # ── 從對話 note 解析預填值 ──────────────────────────────────────
            def _parse_ins_note(note: str) -> dict:
                """從 AI 彙整的 note 字串解析保險表單預填值。
                格式範例：目的地：日本東京｜出發日：2026-08-01｜返回日：2026-08-05｜投保人數：2人｜備註：XX
                或：目的地：XX｜日期：2026-08-01~2026-08-05｜人數：2人
                """
                import re as _re
                parsed = {}
                if not note:
                    return parsed
                for seg in note.split("｜"):
                    seg = seg.strip()
                    if "：" not in seg:
                        continue
                    k, v = seg.split("：", 1)
                    k, v = k.strip(), v.strip()
                    if "目的地" in k:
                        parsed["destination"] = v
                    elif "出發日" in k or ("日期" in k and "~" in v):
                        if "~" in v:
                            parts_d = v.split("~")
                            parsed["start_str"] = parts_d[0].strip()
                            if len(parts_d) > 1:
                                parsed["end_str"] = parts_d[1].strip()
                        else:
                            parsed["start_str"] = v
                    elif "返回日" in k or "回程日" in k:
                        parsed["end_str"] = v
                    elif "人數" in k:
                        m = _re.search(r'\d+', v)
                        if m:
                            parsed["persons"] = int(m.group())
                    elif "備註" in k:
                        parsed["extra_note"] = v
                return parsed

            def _try_parse_date(s: str):
                """嘗試將字串解析為 date 物件，失敗回傳 None。"""
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
                    try:
                        return datetime.strptime(s, fmt).date()
                    except Exception:
                        pass
                return None

            _ins_parsed   = _parse_ins_note(prefill.get("note", ""))
            _ins_dest_val = _ins_parsed.get("destination", "")
            _ins_persons_val = int(_ins_parsed.get("persons", 1))
            _ins_start_val = _try_parse_date(_ins_parsed.get("start_str", ""))
            _ins_end_val   = _try_parse_date(_ins_parsed.get("end_str", ""))
            _ins_extra_val = _ins_parsed.get("extra_note", "")

            # ── 旅遊保險申請表單（第一步：送出申請，不含簽名）────────────────
            col_title.markdown("## 🛡️ 旅遊保險申請表")
            st.caption("由統超保險經紀人提供服務。送出申請後，保險人員將審核並發送正式保單供您電子簽名確認。")
            st.divider()

            st.info("📋 **申請流程：** 填寫資料送出 → 保險人員審核 → 發送正式保單 → 您電子簽名確認 → 保單生效")

            # ── 申請人基本資料 ──────────────────────────────────────────────
            st.markdown("#### 👤 申請人資料")
            _ins_c1, _ins_c2 = st.columns(2)
            ins_name = _ins_c1.text_input(
                "申請人姓名 *",
                value=prefill.get("contact_name", "") or st.session_state.get("username", ""),
                key="ins_name",
            )
            ins_id = _ins_c2.text_input(
                "身份證字號 *",
                placeholder="A123456789",
                key="ins_id",
            )
            _ins_c3, _ins_c4 = st.columns(2)
            ins_birth = _ins_c3.text_input(
                "出生日期",
                placeholder="例：1990/01/15",
                key="ins_birth",
            )
            ins_email = _ins_c4.text_input(
                "聯絡 Email",
                value=st.session_state.get("user_email", ""),
                placeholder="example@email.com",
                key="ins_email",
            )

            st.divider()
            # ── 旅遊行程資料 ──────────────────────────────────────────────
            st.markdown("#### ✈️ 旅遊行程資料")
            ins_dest = st.text_input(
                "旅遊目的地 *",
                value=_ins_dest_val,
                placeholder="例：澎湖、日本東京、泰國曼谷",
                key="ins_dest",
            )
            _ins_d1, _ins_d2, _ins_d3 = st.columns(3)
            ins_start = _ins_d1.date_input(
                "投保開始日（出發日）*",
                value=_ins_start_val,
                min_value=date.today(),
                key="ins_start",
                format="YYYY/MM/DD",
            )
            ins_end = _ins_d2.date_input(
                "投保結束日（返回日）*",
                value=_ins_end_val,
                min_value=date.today(),
                key="ins_end",
                format="YYYY/MM/DD",
            )
            ins_persons = _ins_d3.number_input(
                "投保人數 *",
                min_value=1,
                max_value=20,
                value=_ins_persons_val,
                key="ins_persons",
            )

            st.divider()
            # ── 特殊需求 ──────────────────────────────────────────────────
            st.markdown("#### 📝 其他資訊")
            ins_activities = st.multiselect(
                "是否參與高風險活動（可複選）",
                ["浮潛 / 水上活動", "攀岩 / 高空活動", "滑雪 / 單板滑雪", "租車自駕", "機車騎乘", "潛水"],
                key="ins_activities",
            )
            ins_note_extra = st.text_area(
                "備註（醫療史、特殊需求等）",
                value=_ins_extra_val,
                placeholder="例：投保人有高血壓病史｜需要緊急醫療運送保障",
                height=80,
                key="ins_note_extra",
            )

            # ── 驗證 ──────────────────────────────────────────────────────
            _date_ok = (ins_start and ins_end and ins_start <= ins_end) if (ins_start and ins_end) else False
            can_submit_ins = bool(ins_name.strip() and ins_id.strip() and ins_dest.strip() and ins_start and ins_end and _date_ok)
            if ins_start and ins_end and not _date_ok:
                st.warning("⚠️ 返回日不得早於出發日。")
            elif not can_submit_ins:
                st.warning("⚠️ 請填寫所有必填欄位（*）後再送出。")

            if st.button(
                "📋 送出保險申請",
                type="primary",
                disabled=not can_submit_ins,
                use_container_width=True,
                key="ins_submit",
            ):
                _days = (ins_end - ins_start).days + 1 if ins_start and ins_end else 0
                _acts_str = "、".join(ins_activities) if ins_activities else "無"
                _ins_note = (
                    f"目的地：{ins_dest}｜"
                    f"出發日：{ins_start}｜返回日：{ins_end}｜天數：{_days}天｜"
                    f"投保人數：{ins_persons}人｜"
                    f"高風險活動：{_acts_str}"
                    + (f"｜備註：{ins_note_extra}" if ins_note_extra else "")
                )
                with st.spinner("📡 建立保險申請中..."):
                    _ins_params = {
                        "goal":          "旅遊保險申請",
                        "contact_name":  ins_name.strip(),
                        "contact_phone": "",
                        "budget":        0,
                        "keyword":       ins_id.strip(),
                        "note":          _ins_note,
                        "address":       "",
                        "products_json": "",
                        "user_id":       st.session_state.get("user_id") or 0,
                        "images_json":   "[]",
                    }
                    result = _run_async(_submit_inquiry_via_mcp(_ins_params))

                st.session_state.mcp_log.append({
                    "tool": "submit_inquiry", "params": _ins_params,
                    "result": result, "ts": datetime.now().strftime("%H:%M:%S"), "via": "mcp.Client",
                })
                if result.get("success"):
                    inq_no = result.get("feedback_no") or result.get("inquiry_no", "")
                    st.success(
                        f"✅ **旅遊保險申請已送出！**\n\n"
                        f"申請單號：`{inq_no}`\n\n"
                        f"統超保險經紀人將於 **1 個工作天**內審核，審核完成後將通知您至「我的訂單」完成電子簽名。"
                    )
                    st.session_state.ollama_history.append(
                        {"role": "assistant", "content": f"旅遊保險申請 `{inq_no}` 已送出！統超保險審核後會通知您前往「我的訂單」完成電子簽名，保單即可生效。"}
                    )
                    st.session_state.inquiry_prefill = {}
                else:
                    st.error(f"❌ 申請失敗：{result.get('message', '請稍後再試')}")
            # 提前 return，不進入一般表單
            st.stop()

        # ── 一般服務諮詢表單 ─────────────────────────────────────────────────
        col_title.markdown("## 📋 服務諮詢確認表單")
        st.caption("AI 已根據對話幫您填入資訊，請確認或修改後再送出。")
        st.divider()

        # ── 基本資訊 ────────────────────────────────────────────────────────────
        c1, c2 = st.columns(2)
        goal   = c1.text_input("🎯 需求目標", value=prefill.get("goal", ""), key="form_goal")
        budget = c2.number_input("💰 預算／費用（元）", min_value=0, value=int(prefill.get("budget") or 0))

        c3, c4 = st.columns(2)
        name  = c3.text_input("👤 聯絡人姓名 *",
                              value=prefill.get("contact_name", "") or st.session_state.get("username", ""),
                              key="form_name")
        phone = c4.text_input("📞 聯絡電話 *",
                              value=prefill.get("contact_phone", "") or st.session_state.get("user_contact_phone", ""),
                              key="form_phone")
        note  = st.text_area("📝 備註", value=prefill.get("note", ""), height=80, key="form_note")
        uploaded_imgs = st.file_uploader(
            "📷 上傳照片（選填，可多張）",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="form_images",
        )
        address = st.text_input(
            "📍 服務／配送地址 *",
            value=prefill.get("address", "") or st.session_state.get("user_address", ""),
            placeholder="例：台北市大安區忠孝東路四段X號X樓",
            key="form_address",
        )

        # ── 商品清單（依通路分組，可取消勾選）────────────────────────────────────
        st.divider()
        st.markdown("### 📦 推薦商品清單")
        st.caption("勾選您想納入本次採買的品項；不同通路商品將分組顯示。")

        selected_products = []
        if products:
            by_vendor: dict = {}
            for p in products:
                v = p.get("vendor", "其他")
                by_vendor.setdefault(v, []).append(p)

            _chk_idx = 0
            for vendor, items in by_vendor.items():
                emoji = VENDOR_EMOJI.get(vendor, "⚪")
                st.markdown(f"#### {emoji} {vendor}")
                for p in items:
                    max_stock = int(p.get("stock", 1)) or 1
                    label = (
                        f"**{p.get('name', '')}** — "
                        f"💰 ${p.get('price', 0)} ｜ "
                        f"🥩 蛋白質 {p.get('protein_g', 0)}g ｜ "
                        f"🔥 {p.get('calories', 0)} kcal ｜ "
                        f"📦 庫存 {p.get('stock', 0)}"
                    )
                    col_chk, col_qty = st.columns([5, 1])
                    checked = col_chk.checkbox(label, value=True, key=f"chk_{_chk_idx}")
                    qty = col_qty.number_input(
                        "數量", min_value=1, max_value=max_stock,
                        value=min(p.get("qty", 1), max_stock), step=1,
                        key=f"qty_{_chk_idx}",
                        label_visibility="collapsed",
                        disabled=not checked,
                    )
                    _chk_idx += 1
                    if checked:
                        selected_products.append({**p, "qty": int(qty)})
                st.markdown("")
        else:
            st.info("本次對話未產生商品推薦清單，可直接送出諮詢單。")

        # ── 送出按鈕 ─────────────────────────────────────────────────────────────
        st.divider()
        can_submit = bool(name.strip() and phone.strip() and address.strip())
        if not can_submit:
            st.warning("⚠️ 請填寫聯絡人姓名、電話和地址後再送出。")

        if st.button(
            "✅ 確認送出諮詢單",
            type="primary",
            disabled=not can_submit,
            use_container_width=True,
            key="form_submit",
        ):
            with st.spinner("📡 透過 MCP 建立諮詢單中..."):
                products_json_str = json.dumps(selected_products, ensure_ascii=False) if selected_products else ""
                kw = prefill.get("keyword", "")

                # 儲存上傳圖片到本地 uploads/ 目錄
                import uuid as _uuid, os as _os
                _img_paths = []
                if uploaded_imgs:
                    _os.makedirs("uploads", exist_ok=True)
                    for _f in uploaded_imgs:
                        _ext = _f.name.rsplit(".", 1)[-1].lower() if "." in _f.name else "jpg"
                        _fname = f"{datetime.now().strftime('%Y%m%d')}_{_uuid.uuid4().hex[:8]}.{_ext}"
                        _fpath = f"uploads/{_fname}"
                        with open(_fpath, "wb") as _out:
                            _out.write(_f.read())
                        _img_paths.append(_fpath)

                params = {
                    "goal":          goal,
                    "contact_name":  name.strip(),
                    "contact_phone": phone.strip(),
                    "budget":        int(budget),
                    "keyword":       kw or "",
                    "note":          note or "",
                    "address":       address or "",
                    "products_json": products_json_str,
                    "user_id":       st.session_state.get("user_id") or 0,
                    "images_json":   json.dumps(_img_paths, ensure_ascii=False),
                }
                result = _run_async(_submit_inquiry_via_mcp(params))

            # 記入側欄 MCP 紀錄
            st.session_state.mcp_log.append({
                "tool":   "submit_inquiry",
                "params": {k: v for k, v in params.items() if k not in ("products_json",)},
                "result": result,
                "ts":     datetime.now().strftime("%H:%M:%S"),
                "via":    "mcp.Client",
            })

            if result.get("success"):
                inq_no = result.get("feedback_no") or result.get("inquiry_no", "")
                st.success(
                    f"✅ **諮詢單已成功建立！**\n\n"
                    f"單號：`{inq_no}`\n\n"
                    f"後台人員將主動與您聯繫。"
                )

                # 寫入 ollama 對話歷史，讓後續對話知道已送出
                success_msg = f"諮詢單 `{inq_no}` 已成功建立！後台人員將主動與您聯繫。"
                st.session_state.ollama_history.append(
                    {"role": "assistant", "content": success_msg}
                )
                # 也加入顯示訊息
                st.session_state.display_msgs.append({
                    "role": "assistant",
                    "content": success_msg,
                    "tool_calls": [{
                        "tool":   "submit_inquiry",
                        "params": params,
                        "result": result,
                        "ts":     datetime.now().strftime("%H:%M:%S"),
                        "via":    "mcp.Client",
                    }],
                })

                st.balloons()
                if st.button("← 返回對話", key="form_done"):
                    st.session_state.stage            = "chat"
                    st.session_state.inquiry_prefill  = {}
                    st.session_state.inquiry_products = []
                    st.session_state.cart             = {}
                    st.session_state.selected_courses = []
                    st.rerun()
            else:
                st.error(f"❌ 建立失敗：{result.get('message', '請稍後再試')}")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE: MY ORDERS — 用戶歷史訂單查詢
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "my_orders":
    col_back, col_title = st.columns([1, 6])
    if col_back.button("← 返回對話", key="orders_back"):
        st.session_state.stage = "chat"
        st.rerun()
    col_title.markdown("## 📦 我的採買諮詢單")

    uid = st.session_state.get("user_id", 0)
    orders = get_my_inquiries(uid)

    if col_back.button("🔄 重新整理", key="orders_refresh"):
        st.rerun()

    st.caption(f"共 {len(orders)} 筆歷史諮詢單")
    st.divider()

    STATUS_CFG = {
        "01": {"color": "#FF9800", "icon": "⏳", "label": "待處理"},
        "04": {"color": "#9C27B0", "icon": "✍️", "label": "待簽名"},
        "05": {"color": "#2196F3", "icon": "🔍", "label": "待後台確認"},
        "02": {"color": "#1976D2", "icon": "🚚", "label": "配送中"},
        "03": {"color": "#7B5EA7", "icon": "📦", "label": "預留中"},
        "90": {"color": "#9E9E9E", "icon": "❌", "label": "已拒絕"},
        "80": {"color": "#43A047", "icon": "✅", "label": "已完成"},
    }
    _STATUS_LABEL = {k: v["label"] for k, v in STATUS_CFG.items()}

    if not orders:
        st.info("您目前還沒有任何採買諮詢單。\n\n開始對話並讓 AI 幫您建立採買計劃吧！")
    else:
        for inq in orders:
            status  = inq.get("status", "01")
            scfg    = STATUS_CFG.get(status, {"color": "#888", "icon": "❓"})
            inq_id  = inq["feedback_no"]

            with st.container(border=True):
                # ── 狀態 + 單號 + 時間 ──────────────────────────────────────
                h1, h2, h3 = st.columns([2, 4, 2])
                h1.markdown(
                    f'<span style="background:{scfg["color"]};color:white;'
                    f'border-radius:12px;padding:3px 10px;font-size:0.82rem;font-weight:700">'
                    f'{scfg["icon"]} {_STATUS_LABEL.get(status, status)}</span>',
                    unsafe_allow_html=True,
                )
                h2.markdown(f"**`{inq_id}`**")
                h3.caption(str(inq.get("created_at", ""))[:16])

                # ── 進度條 ────────────────────────────────────────────────────
                _is_ins = "保險" in (inq.get("goal") or "")
                if _is_ins:
                    _steps = [("01", "待處理"), ("04", "待簽名"), ("05", "待後台確認"), ("80", "已完成")]
                else:
                    _steps = [("01", "待處理"), ("02", "配送中"), ("80", "已完成")]
                _step_idx = next((i for i, (sc, _) in enumerate(_steps) if sc == status), -1)
                if status == "90":
                    st.markdown(
                        '<div style="background:#f5f5f5;border-radius:8px;padding:6px 12px;'
                        'color:#9E9E9E;font-size:0.8rem;text-align:center">❌ 此申請已拒絕</div>',
                        unsafe_allow_html=True,
                    )
                elif _step_idx >= 0:
                    _step_html = ""
                    for _si, (_scode, _sname) in enumerate(_steps):
                        _done  = _si < _step_idx
                        _curr  = _si == _step_idx
                        _bg    = "#43A047" if _done else ("#1976D2" if _curr else "#E0E0E0")
                        _tc    = "white" if (_done or _curr) else "#9E9E9E"
                        _fw    = "700" if _curr else "400"
                        _step_html += (
                            f'<div style="flex:1;text-align:center">'
                            f'<div style="width:28px;height:28px;border-radius:50%;background:{_bg};'
                            f'color:white;font-size:0.75rem;font-weight:700;line-height:28px;'
                            f'margin:0 auto">{"✓" if _done else _si+1}</div>'
                            f'<div style="font-size:0.72rem;color:{_tc};font-weight:{_fw};margin-top:3px">{_sname}</div>'
                            f'</div>'
                        )
                        if _si < len(_steps) - 1:
                            _lc = "#43A047" if _done else "#E0E0E0"
                            _step_html += f'<div style="flex:0.3;height:2px;background:{_lc};margin-top:14px"></div>'
                    st.markdown(
                        f'<div style="display:flex;align-items:flex-start;padding:8px 4px 4px">{_step_html}</div>',
                        unsafe_allow_html=True,
                    )

                # ── 基本資訊 ──────────────────────────────────────────────────
                d1, d2 = st.columns(2)
                with d1:
                    goal_val   = inq.get("goal") or "—"
                    budget_val = inq.get("budget") or 0
                    st.markdown(f"**目標：** {goal_val}")
                    st.markdown(f"**預算：** {'$' + str(budget_val) if budget_val else '—'}")
                    if inq.get("note"):
                        st.markdown(f"**備註：** {inq['note']}")
                with d2:
                    st.markdown(f"**聯絡人：** {inq.get('contact_name_display') or inq.get('contact_name') or '—'}")
                    st.markdown(f"**電話：** {inq.get('contact_phone') or '—'}")

                # ── 採買商品清單 ────────────────────────────────────────────
                pj = inq.get("products_json", "")
                if pj:
                    try:
                        plist = json.loads(pj)
                        if plist:
                            by_v: dict = {}
                            for p in plist:
                                by_v.setdefault(p.get("vendor", "其他"), []).append(p)
                            total_items = sum(len(v) for v in by_v.values())
                            with st.expander(f"🛒 採買商品（{total_items} 項 / {len(by_v)} 通路）"):
                                for vendor, items in by_v.items():
                                    emoji = VENDOR_EMOJI.get(vendor, "⚪")
                                    st.markdown(f"**{emoji} {vendor}**")
                                    for p in items:
                                        st.markdown(
                                            f"&nbsp;&nbsp;• {p.get('name', '')} — "
                                            f"${p.get('price', 0)} ｜ "
                                            f"蛋白質 {p.get('protein_g', 0)}g"
                                        )
                    except Exception:
                        pass

                # ── 配送資訊 ──────────────────────────────────────────────────
                if inq.get("delivery_no"):
                    st.success(
                        f"🚚 **外送單號：** `{inq['delivery_no']}`　"
                        f"｜　接單時間：{str(inq.get('accepted_at', ''))[:16]}"
                    )

                # ── 雙向訊息紀錄（每筆獨立泡泡） ────────────────────────────
                _v_lines = [l.strip() for l in inq.get("vendor_reply", "").split("\n") if l.strip()]
                _u_lines = [l.strip() for l in inq.get("user_reply",   "").split("\n") if l.strip()]
                _has_msgs = bool(_v_lines or _u_lines)

                with st.expander(
                    "💬 溝通紀錄" + (f"（{len(_v_lines)+len(_u_lines)} 則）" if _has_msgs else "（尚無）"),
                    expanded=_has_msgs,
                ):
                    for _line in _v_lines:
                        if status == "90" and _v_lines.index(_line) == 0:
                            st.warning(f"🏪 商家：{_line}")
                        else:
                            st.info(f"🏪 商家：{_line}")
                    for _line in _u_lines:
                        st.success(f"👤 您：{_line}")

                    if status not in ("80",):
                        st.divider()
                        with st.form(f"user_reply_{inq_id}"):
                            reply_text = st.text_area(
                                "傳送訊息給商家",
                                value="",
                                placeholder="例：請送到一樓大廳，謝謝 / 可以換成無糖豆漿嗎？",
                                key=f"rtxt_{inq_id}",
                                height=80,
                            )
                            sent = st.form_submit_button("📨 送出", type="primary")
                        if sent:
                            if reply_text.strip():
                                update_user_reply(inq_id, reply_text.strip(), st.session_state.get("username", "用戶"))
                                st.rerun()
                            else:
                                st.warning("請輸入訊息內容。")

                # ── 保險保單簽名按鈕（待簽名狀態） ─────────────────────────
                _is_ins_order = "保險" in (inq.get("goal") or "")
                if _is_ins_order and status == "04":
                    st.divider()
                    st.warning("✍️ **保單已準備完成，請點擊下方按鈕閱讀條款並完成電子簽名。**")
                    if st.button(
                        "✍️ 前往簽署保單",
                        key=f"sign_btn_{inq_id}",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state.insurance_sign_no = inq_id
                        st.session_state.stage = "insurance_sign"
                        st.rerun()
                elif _is_ins_order and status == "05":
                    st.info("🔍 **您的簽名已送出，等待統超保險確認生效中。**")


# ═════════════════════════════════════════════════════════════════════════════
# STAGE: INSURANCE SIGN — 用戶簽署正式保單
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "insurance_sign":
    _sign_inq_id = st.session_state.get("insurance_sign_no", "")
    col_back, col_title = st.columns([1, 6])
    if col_back.button("← 返回訂單", key="sign_back"):
        st.session_state.stage = "my_orders"
        st.rerun()
    col_title.markdown("## ✍️ 旅遊保險保單簽名確認")

    if not _sign_inq_id:
        st.error("找不到申請單資訊，請返回「我的訂單」重試。")
        st.stop()

    _sign_con = _db()
    _sign_row = _sign_con.execute(
        "SELECT * FROM pms_form_feedback WHERE feedback_no=?", (_sign_inq_id,)
    ).fetchone()
    _sign_con.close()

    if not _sign_row:
        st.error(f"找不到申請單 {_sign_inq_id}。")
        st.stop()

    _sign_row = dict(_sign_row)
    if _sign_row.get("status") != "04":
        _cur_status_label = {"01":"待處理","02":"配送中","03":"預留中","04":"待簽名","05":"待後台確認","80":"已完成","90":"已拒絕"}.get(_sign_row.get("status",""), _sign_row.get("status",""))
        st.warning(f"此申請單目前狀態為「{_cur_status_label}」，不需簽名或已完成。")
        if st.button("返回我的訂單"):
            st.session_state.stage = "my_orders"
            st.rerun()
        st.stop()

    st.caption(f"申請單號：`{_sign_inq_id}`　｜　申請人：{_sign_row.get('contact_name_display') or _sign_row.get('contact_name','')}")
    st.divider()

    # ── 正式保單條款 ───────────────────────────────────────────────────────
    st.markdown("### 📄 正式保單條款")
    _note_val = _sign_row.get("note", "")
    _policy_text = f"""統超保險旅遊綜合保險保單
━━━━━━━━━━━━━━━━━━━━━━━━━━
申請單號：{_sign_inq_id}
申請人：{_sign_row.get('contact_name_display') or _sign_row.get('contact_name','')}
旅遊詳情：{_note_val or '（依申請書所載）'}

【第一條 承保範圍】
本保險承保被保險人於本保單所載旅遊期間內，因意外事故或突發疾病所致之損失：
  1. 意外死亡及傷殘保險金：最高新台幣 300 萬元
  2. 海外突發疾病醫療費用：最高新台幣 50 萬元（含急診、住院、手術費）
  3. 旅遊不便補償：
     ・行程延誤（逾 6 小時）：每次 NT$1,000，最高 NT$3,000
     ・班機取消：最高 NT$5,000
     ・行李遺失：最高 NT$10,000
  4. 旅行文件遺失緊急協助（含護照補辦協助服務）

【第二條 保險期間】
以申請書所載旅遊出發日 00:00 起，至返回日 24:00 止。

【第三條 被保險人資格】
被保險人須具備以下條件：
  ・年齡：滿 15 歲以上，未滿 75 歲
  ・健康狀況：投保時未患有嚴重疾病或身心障礙
  ・旅遊目的地：非外交部「警告」或「不建議前往」地區

【第四條 理賠申請】
發生保險事故後，請於事故發生後 30 日內聯繫本公司：
  ・Email：claim@unisuperins.com.tw
  ・需檢附：理賠申請書、醫療費用收據、事故證明文件

【第五條 除外責任】
本保險不承保下列情事所致之損失：
  1. 被保險人故意或蓄意行為
  2. 戰爭、內亂、恐怖攻擊期間所致
  3. 核子輻射或放射性污染所致
  4. 飲酒駕車或無照駕駛所致
  5. 從事危險運動（高空跳傘、攀岩等）所致（需另外加保）

【第六條 保費說明】
保費依旅遊天數、目的地及承保人數計算，詳見另行寄送之費用明細。

【第七條 爭議處理】
本保單相關爭議依中華民國保險法規解決，並以台北地方法院為第一審管轄法院。

━━━━━━━━━━━━━━━━━━━━━━━━━━
統超保險經紀人股份有限公司
統一編號：12345678
官方網站：www.unisuperins.com.tw
"""
    with st.container(border=True):
        st.text(_policy_text)

    # ── 商家留言 ───────────────────────────────────────────────────────────
    _v_reply = _sign_row.get("vendor_reply", "")
    if _v_reply:
        for _vl in [l.strip() for l in _v_reply.split("\n") if l.strip()]:
            st.info(f"🏪 保險專員：{_vl}")

    st.divider()
    st.markdown("#### ✍️ 電子簽名")
    st.caption("請仔細閱讀上方條款後，在下方空白區域手寫您的簽名。完成後點擊「確認簽名送出」。")

    _HAS_CANVAS_S = False
    try:
        from streamlit_drawable_canvas import st_canvas as _st_canvas_s
        _HAS_CANVAS_S = True
    except ImportError:
        pass

    _sig_img_data_s = None
    _sig_text_s     = ""
    if _HAS_CANVAS_S:
        _canvas_res_s = _st_canvas_s(
            fill_color="rgba(0,0,0,0)",
            stroke_width=3,
            stroke_color="#000080",
            background_color="#f5f5f5",
            height=160,
            drawing_mode="freedraw",
            key="policy_signature",
        )
        if _canvas_res_s.image_data is not None:
            _sig_img_data_s = _canvas_res_s.image_data
        _has_sig_s = _sig_img_data_s is not None and int(_sig_img_data_s.sum()) > 0
    else:
        st.warning("請安裝 streamlit-drawable-canvas 以啟用手寫簽名功能")
        _sig_text_s = st.text_input("✍️ 輸入全名作為電子簽名替代", key="policy_sig_text")
        _has_sig_s  = bool(_sig_text_s.strip())

    _agree = st.checkbox(
        "✅ 我已詳細閱讀上方保單條款，同意其內容並確認申請。",
        key="policy_agree",
    )
    _can_sign = _has_sig_s and _agree

    if not _can_sign:
        st.warning("⚠️ 請完成簽名並勾選確認同意後再送出。")

    if st.button(
        "✍️ 確認簽名送出",
        type="primary",
        disabled=not _can_sign,
        use_container_width=True,
        key="policy_sign_submit",
    ):
        with st.spinner("📡 提交簽名中..."):
            import uuid as _uuid2, os as _os2
            _os2.makedirs("uploads", exist_ok=True)
            _sig_path_s = ""
            if _HAS_CANVAS_S and _sig_img_data_s is not None:
                try:
                    from PIL import Image as _PILImage2
                    _pil2 = _PILImage2.fromarray(_sig_img_data_s.astype("uint8"), "RGBA")
                    _sig_fname2 = f"sig_{_uuid2.uuid4().hex[:8]}.png"
                    _sig_path_s = f"uploads/{_sig_fname2}"
                    _pil2.save(_sig_path_s)
                except Exception:
                    pass
            elif _sig_text_s:
                _sig_path_s = _sig_text_s

            _scon = _db()
            _scon.execute(
                "UPDATE pms_form_feedback SET status='05', images_json=?, vendor_reply=COALESCE(vendor_reply,'')||? WHERE feedback_no=?",
                (
                    json.dumps([_sig_path_s] if _sig_path_s else [], ensure_ascii=False),
                    f"{datetime.now().strftime('%m/%d %H:%M')} [用戶]: 已完成電子簽名，等待保單生效確認。\n",
                    _sign_inq_id,
                ),
            )
            _scon.commit()
            _scon.close()

        st.success(
            f"✅ **簽名已送出！**\n\n"
            f"申請單號：`{_sign_inq_id}`\n\n"
            f"統超保險經紀人將確認您的簽名並使保單正式生效，確認後將寄送 Email 通知您。"
        )
        st.balloons()
        if st.button("← 返回我的訂單", key="sign_done"):
            st.session_state.stage = "my_orders"
            st.session_state.insurance_sign_no = ""
            st.rerun()
    st.stop()


# ═════════════════════════════════════════════════════════════════════════════
# STAGE: CHAT
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "chat":

    # ── Query param handlers（卡片加入 / pill 移除）──────────────
    _qe = _url_quote  # shorthand
    _rmc = st.query_params.get("rm_cart", "")
    if _rmc:
        _c = dict(st.session_state.get("cart", {}))
        _c.pop(_rmc, None)
        st.session_state.cart = _c
        del st.query_params["rm_cart"]
        st.rerun()
    _rmg = st.query_params.get("rm_course", "")
    if _rmg:
        _sc2 = list(st.session_state.get("selected_courses", []))
        if _rmg in _sc2:
            _sc2.remove(_rmg)
        st.session_state.selected_courses = _sc2
        del st.query_params["rm_course"]
        st.rerun()
    _adc = st.session_state.get("_add_cart_sig", "")
    if _adc:
        _cat = st.session_state.get("product_catalog", {})
        _prod = _cat.get(_adc, {})
        if _prod:
            _c2 = dict(st.session_state.get("cart", {}))
            if _adc in _c2:
                _c2[_adc]["qty"] += 1
            else:
                _c2[_adc] = {
                    "name":      _adc,
                    "qty":       1,
                    "price":     _prod.get("price", 0),
                    "vendor":    _prod.get("vendor", ""),
                    "protein_g": _prod.get("protein_g", 0),
                    "calories":  _prod.get("calories", 0),
                    "stock":     _prod.get("stock", 0),
                    "emoji":     _product_emoji(_adc),
                }
            st.session_state.cart = _c2
        st.session_state["_add_cart_sig"] = ""
        st.rerun()
    _togc = st.session_state.get("_tog_course_sig", "")
    if _togc:
        _sc3 = list(st.session_state.get("selected_courses", []))
        if _togc in _sc3:
            _sc3.remove(_togc)
        else:
            _sc3.append(_togc)
        st.session_state.selected_courses = _sc3
        st.session_state["_tog_course_sig"] = ""
        st.rerun()

    using_claude = bool(st.session_state.api_key)
    using_gpt    = bool(st.session_state.get("openai_key")) and not using_claude
    _ai_badge    = (
        "🤖 Claude AI (claude-sonnet-4-6)" if using_claude else
        "🤖 GPT-4o"                        if using_gpt   else
        f"🤖 Ollama ({OLLAMA_MODEL}) + MCP"
    )

    col_info, col_reset = st.columns([5, 1])
    col_info.caption(f"👤 {st.session_state.username} 的對話　{_ai_badge}")
    with col_reset.popover("🗑️", help="清空對話"):
        st.warning("確定要清空這段對話嗎？", icon="⚠️")
        if st.button("確認清空", type="primary", use_container_width=True, key="confirm_clear"):
            st.session_state.display_msgs   = []
            st.session_state.claude_msgs    = []
            st.session_state.ollama_history = []
            st.session_state.mcp_log        = []
            st.rerun()

    # ── 1. 登入後的第一次自動問好 ──────────────────────────────────
    if not st.session_state.display_msgs and st.session_state.claude_msgs:
        if using_claude:
            with st.chat_message("assistant", avatar="🌿"):
                with st.spinner("🤔 思考中..."):
                    try:
                        text, tool_calls, updated = chat_with_claude(
                            st.session_state.claude_msgs,
                            st.session_state.api_key,
                        )
                        st.session_state.claude_msgs = updated
                    except anthropic.AuthenticationError:
                        st.error("❌ API Key 無效，已切換至 Ollama 本地 AI 模式。")
                        st.session_state.api_key = ""
                        st.rerun()
                st.markdown(_strip_images(text))
            st.session_state.display_msgs.append({
                "role": "assistant", "content": text, "tool_calls": [],
            })
        else:
            username = st.session_state.username
            _model_name = "GPT-4o" if using_gpt else OLLAMA_MODEL
            # 情境感知：取得當前時間與天氣，產生個人化推薦
            try:
                from mcp_server import get_current_time, get_weather
                import json as _j
                _time_info = _j.loads(get_current_time())
                _hour = int(_time_info.get("hour", 12))
                _greeting = "早安" if _hour < 11 else ("午安" if _hour < 14 else ("午後好" if _hour < 17 else ("晚安" if _hour >= 21 else "晚上好")))

                # 取得用戶所在縣市（有 GPS 用反地理編碼，否則用帳號設定）
                _ulat = st.session_state.get("user_lat")
                _ulng = st.session_state.get("user_lng")
                _user_city = "台北"
                if _ulat and _ulng:
                    _rev = _reverse_geocode(_ulat, _ulng)
                    if _rev:
                        _user_city = _rev.split("市")[0] + "市" if "市" in _rev else _rev.split("縣")[0] + "縣" if "縣" in _rev else "台北"
                else:
                    from app_helpers import _db as _adb
                    _ucon = _adb()
                    _urow = _ucon.execute(
                        "SELECT sc.name FROM users u JOIN sys_county sc ON sc.code=u.county_code WHERE u.id=?",
                        (st.session_state.get("user_id", 0),)
                    ).fetchone()
                    _ucon.close()
                    if _urow:
                        _user_city = _urow[0]

                _weather_raw = _j.loads(get_weather(city=_user_city))
                _wdesc = _weather_raw.get("description", "")
                _temp  = _weather_raw.get("temperature", "")
                _code  = _weather_raw.get("weather_code", 0)

                # 根據天氣 code（分類）+ 時段產生統一集團情境推薦
                _recs = []
                if 51 <= _code <= 99:   # 雨天（毛毛雨/雨/陣雨）
                    _recs.append("🌧️ 外頭下雨，可以讓我幫您安排**7-11 外送到府**，不用出門")
                elif _code <= 3:         # 晴/多雲
                    _recs.append("☀️ 天氣晴朗，適合外出運動，要不要查查附近**Being Sport 課程**或**公共運動場館**？")
                if _hour < 11:
                    _recs.append("🥐 早晨好時光，**Mister Donut** 或 **統一星巴克** 的早餐點心現在有供應")
                elif 11 <= _hour < 14:
                    _recs.append("🍱 午餐時段，**7-11 舒肥雞胸肉**搭配**萬家福新鮮蔬菜**是高蛋白好選擇")
                elif _hour >= 20:
                    _recs.append("🍺 輕鬆夜晚，**21plus 精選啤酒**或**聖德科斯天然果汁**讓您放鬆一下")

                _ctx = f"📍 {_user_city}　🌡️ {_temp}°C　{_wdesc}" if _temp else ""
                _rec_str = "\n".join(f"- {r}" for r in _recs[:2]) if _recs else ""
            except Exception:
                _greeting = "您好"
                _ctx = ""
                _rec_str = ""

            text = (
                f"{_greeting}，{username}！我是您的 統一生活管家 🏪\n\n"
                + (f"{_ctx}\n\n" if _ctx else "")
                + (_rec_str + "\n\n" if _rec_str else "")
                + f"由 **{_model_name}** 透過 **MCP 協議**真實呼叫工具，"
                f"幫您在 7-11、萬家福、康是美、統一生機、Mister Donut、Cold Stone、21plus、統一星巴克、聖德科斯 採買！\n\n"
                f"請告訴我您的需求，例如：\n"
                f"- 「我想增肌，預算 500 元」\n"
                f"- 「附近有沒有統一門市」\n"
                f"- 「幫我規劃旅遊保險」"
            )
            st.session_state.ollama_history = [
                {"role": "user",
                 "content": f"（{username} 已登入，請問有什麼需要協助的？）"},
                {"role": "assistant", "content": text},
            ]
            with st.chat_message("assistant", avatar="🌿"):
                st.markdown(text)
            st.session_state.display_msgs.append({
                "role": "assistant", "content": text, "tool_calls": [],
            })
        st.rerun()

    # ── 1.5 新對話範例提示 ─────────────────────────────────────────
    if not st.session_state.display_msgs and not st.session_state.claude_msgs:
        st.markdown("#### 💡 試試這些問題開始對話：")
        _examples = [
            ("🍗 分析今日飲食", "我今天吃了雞胸肉150g和白飯2碗，幫我分析卡路里並推薦補充食物"),
            ("💪 規劃增肌採買", "我想增肌，預算500元，幫我推薦高蛋白商品"),
            ("🛒 搜尋乳清蛋白", "各通路有沒有乳清蛋白？庫存還有多少？"),
            ("📍 找附近超商", "幫我找附近1公里內的超商或超市"),
        ]
        _ex_cols = st.columns(2)
        for _i, (_lbl, _txt) in enumerate(_examples):
            if _ex_cols[_i % 2].button(_lbl, use_container_width=True, key=f"ex_{_i}"):
                st.session_state["_pending_prompt"] = _txt
                st.rerun()
        st.divider()

    # ── 2. 顯示歷史訊息 ────────────────────────────────────────────
    for _midx, msg in enumerate(st.session_state.display_msgs):
        avatar = "👤" if msg["role"] == "user" else "🌿"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(_strip_images(msg["content"]))
            if msg.get("tool_calls"):
                render_tool_results(msg["tool_calls"], msg_idx=_midx)

    # ── 已選商品 Pills（chat_input 正上方，融入聊天區域）───────────────
    _cart = st.session_state.get("cart", {})
    # ── Pills 共用 CSS ───────────────────────────────────────────
    st.markdown("""<style>
.pill-row{display:flex;overflow-x:auto;gap:8px;padding:6px 2px 6px;
          -webkit-overflow-scrolling:touch;scrollbar-width:thin;}
.pill-row::-webkit-scrollbar{height:4px;}
.pill-row::-webkit-scrollbar-thumb{background:#c8e6c9;border-radius:9px;}
.cpill{display:inline-flex;align-items:center;gap:4px;flex-shrink:0;
       background:#e8f5e9;border:1.5px solid #00833D;border-radius:999px;
       padding:4px 10px 4px 12px;font-size:13px;color:#1a5c35;font-weight:600;
       white-space:nowrap;text-decoration:none!important;}
.cpill .rm{font-size:11px;font-weight:700;opacity:.6;line-height:1;
           padding:0 2px;text-decoration:none;color:inherit;}
.cpill .rm:hover{opacity:1;}
.cpill-gym{display:inline-flex;align-items:center;gap:4px;flex-shrink:0;
           background:#e3f2fd;border:1.5px solid #1565C0;border-radius:999px;
           padding:4px 10px 4px 12px;font-size:13px;color:#1a3a6b;font-weight:600;
           white-space:nowrap;text-decoration:none!important;}
.cpill-gym .rm{font-size:11px;font-weight:700;opacity:.6;line-height:1;
               padding:0 2px;text-decoration:none;color:inherit;}
.cpill-gym .rm:hover{opacity:1;}
div[data-testid="stTextInput"]:has(input[placeholder^="__"]){height:0!important;overflow:hidden!important;
  padding:0!important;margin:0!important;min-height:0!important;}
div[data-testid="stTextInput"]:has(input[placeholder^="__"]) input{position:absolute!important;
  left:-9999px!important;opacity:0!important;pointer-events:none!important;}
</style>""", unsafe_allow_html=True)
    st.text_input("_add", placeholder="__add_cart__",   key="_add_cart_sig",   label_visibility="collapsed")
    st.text_input("_tog", placeholder="__tog_course__", key="_tog_course_sig", label_visibility="collapsed")
    import streamlit.components.v1 as _stc
    _stc.html("""<script>
(function(){
  try {
    var p=window.parent;
    if(p._stClickHandler){p.document.removeEventListener('click',p._stClickHandler);}
    p._stClickHandler=function(e){
      var btn=e.target.closest('[data-ph]');
      if(!btn)return;
      var ph=btn.getAttribute('data-ph');
      var val=btn.getAttribute('data-name')||'';
      var el=p.document.querySelector('input[placeholder="'+ph+'"]');
      if(!el)return;
      var s=Object.getOwnPropertyDescriptor(p.HTMLInputElement.prototype,'value').set;
      s.call(el,val);
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',keyCode:13}));
      el.dispatchEvent(new KeyboardEvent('keypress',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',keyCode:13}));
      el.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',keyCode:13}));
    };
    p.document.addEventListener('click',p._stClickHandler);
  } catch(err) {}
})();
</script>""", height=1)

    # ── 已選商品 Pills（橫向滑動，✕ 內嵌，帶 emoji）────────────
    if _cart:
        _ph = '<div class="pill-row">'
        for _pn, _pi in _cart.items():
            _qty  = _pi["qty"]
            _emo  = _pi.get("emoji") or _product_emoji(_pn)
            _cnt  = f" ×{_qty}" if _qty > 1 else ""
            _ph += (f'<span class="cpill">{_emo} {_pn}{_cnt}'
                    f'<a href="?rm_cart={_qe(_pn)}" class="rm">✕</a></span>')
        _ph += '</div>'
        _total = sum(v["price"] * v["qty"] for v in _cart.values())
        _ph += f'<div style="font-size:12px;color:#555;margin:1px 0 4px;">💰 <b>${_total}</b></div>'
        st.markdown(_ph, unsafe_allow_html=True)

    # ── 已選課程 Pills（橫向滑動，✕ 內嵌）────────────────────────
    _sel_courses = st.session_state.get("selected_courses", [])
    if _sel_courses:
        _gh = '<div class="pill-row">'
        for _cn in _sel_courses:
            _gh += (f'<span class="cpill-gym">🏋️ {_cn}'
                    f'<a href="?rm_course={_qe(_cn)}" class="rm">✕</a></span>')
        _gh += '</div>'
        st.markdown(_gh, unsafe_allow_html=True)

    # ── 3. 接收新輸入 ───────────────────────────────────────────────
    _ep = st.session_state.get("_pending_prompt")
    if _ep and "_pending_prompt" in st.session_state:
        del st.session_state["_pending_prompt"]
    _ci = st.chat_input("輸入您的需求或回覆...")
    prompt = _ep or _ci
    if prompt:
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        navigating_to_form = False
        _had_error = False

        with st.chat_message("assistant", avatar="🌿"):
            if using_claude:
                _ai_content = prompt
                _cart_now = st.session_state.get("cart", {})
                if _cart_now:
                    _cart_lines = "、".join(
                        f"{n}×{v['qty']}（${v['price']*v['qty']}）"
                        for n, v in _cart_now.items()
                    )
                    _ai_content += f"\n\n[系統：使用者已透過 UI 加入購物車：{_cart_lines}，若使用者表達購買/下單意圖請呼叫 submit_inquiry 並帶入這些商品]"
                _sel = st.session_state.get("selected_courses", [])
                if _sel:
                    _ai_content += f"\n\n[系統：使用者已透過 UI 選取課程：{'、'.join(_sel)}，若使用者表達報名意圖請呼叫 enroll_gym_course]"
                st.session_state.claude_msgs.append({"role": "user", "content": _ai_content})
                text = ""
                tool_calls = []
                with st.spinner("🤔 思考中..."):
                    try:
                        text, tool_calls, updated = chat_with_claude(
                            st.session_state.claude_msgs,
                            st.session_state.api_key,
                        )
                        st.session_state.claude_msgs = updated
                    except anthropic.AuthenticationError:
                        st.error("❌ API Key 無效，已切換至 Ollama 本地 AI 模式。")
                        st.session_state.api_key = ""
                        st.rerun()
                    except Exception as exc:
                        # 清除殘缺 user message，避免 history 帶著爛資料
                        if (st.session_state.claude_msgs
                                and st.session_state.claude_msgs[-1].get("content") == prompt):
                            st.session_state.claude_msgs.pop()
                        _had_error = True
                        st.error("❌ AI 暫時無法回應，請稍後重試。")
                        st.caption(f"錯誤原因：{str(exc)[:150]}")
                        if st.button("🔄 重試上一則", key="retry_claude", type="primary"):
                            st.session_state["_pending_prompt"] = prompt
                            st.rerun()
                if not _had_error:
                    if st.session_state.stage == "inquiry_form":
                        navigating_to_form = True
                        st.info("📋 正在為您開啟採買確認表單...")
            else:
                _spin_label = "🤖 GPT-4o 透過 MCP 思考中..." if using_gpt else f"🤖 {OLLAMA_MODEL} 透過 MCP 思考中..."
                with st.spinner(_spin_label):
                    _ol_prompt = prompt
                    _cart_ol = st.session_state.get("cart", {})
                    if _cart_ol:
                        _cart_lines_ol = "、".join(
                            f"{n}×{v['qty']}（${v['price']*v['qty']}）"
                            for n, v in _cart_ol.items()
                        )
                        _ol_prompt += f"\n\n[系統：使用者已透過 UI 加入購物車：{_cart_lines_ol}，若使用者表達購買/下單意圖請呼叫 submit_inquiry 並帶入這些商品]"
                    _sel2 = st.session_state.get("selected_courses", [])
                    if _sel2:
                        _ol_prompt += f"\n\n[系統：使用者已透過 UI 選取課程：{'、'.join(_sel2)}，若使用者表達報名意圖請呼叫 enroll_gym_course]"
                    text, tool_calls, updated_history = ollama_chat(
                        _ol_prompt, st.session_state.ollama_history
                    )
                    st.session_state.ollama_history = updated_history
                if st.session_state.stage == "inquiry_form":
                    navigating_to_form = True
                    st.info("📋 正在為您開啟採買確認表單...")

            if not navigating_to_form and not _had_error:
                st.markdown(_strip_images(text))
                if tool_calls:
                    render_tool_results(tool_calls, msg_idx=9999)

        # 更新顯示訊息與 MCP 紀錄（錯誤時不寫入，讓用戶重試）
        if not _had_error:
            st.session_state.display_msgs.append({"role": "user", "content": prompt, "tool_calls": []})
            if not navigating_to_form:
                st.session_state.display_msgs.append({
                    "role": "assistant", "content": text, "tool_calls": tool_calls,
                })
            if tool_calls:
                st.session_state.mcp_log.extend(tool_calls)

            # 自動儲存對話記錄到 DB
            if st.session_state.get("user_id") and not navigating_to_form:
                conv_id = save_conv_to_db(
                    user_id       = st.session_state.user_id,
                    conv_id       = st.session_state.get("conversation_id"),
                    display_msgs  = st.session_state.display_msgs,
                    ollama_history= st.session_state.ollama_history,
                )
                st.session_state.conversation_id = conv_id

        if navigating_to_form:
            st.rerun()
