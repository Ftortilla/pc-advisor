"""自組桌機頁：三個步驟。

    第 1 步：問問題（預算、用途、螢幕、網路、進階需求）
    第 2 步：看圖挑機殼（顏色、燈光由挑的機殼決定）
    第 3 步：完整菜單，每個零件都可以「換一個」（例如換一張比較好看的顯卡）

這裡只負責「畫面」。配單邏輯在 core/pc/，讀資料、自動更新、商品圖片在 data/store.py。
"""
from dataclasses import astuple

import pandas as pd
import streamlit as st

from core.config import (
    PC_BLUETOOTH_OPTIONS,
    PC_BUDGET_DEFAULT,
    PC_BUDGET_MAX,
    PC_BUDGET_MIN,
    PC_CASE_COLOR_OPTIONS,
    PC_CASE_LIGHT_OPTIONS,
    PC_LAN_OPTIONS,
    PC_MODE_OPTIONS,
    PC_RESOLUTION_OPTIONS,
    PC_SIZE_OPTIONS,
    PC_STORAGE_OPTIONS,
    PC_USAGE_OPTIONS,
    PC_WIFI_EXTRA_OPTIONS,
    PC_WINDOWS_OPTIONS,
)
from core.pc.build import PART_LABELS, PART_ORDER, PART_ROLES, Prefs, cheapest_possible, make_build
from core.pc.compatibility import COOLER_HEIGHT_MARGIN_CM, GPU_LENGTH_MARGIN_CM, cpu_power, required_psu_w
from core.pc.swap import SWAPPABLE, alternatives, apply_swaps, case_gallery, recheck, total_price
from core.shop_links import COOLPC_URL, momo_url, shopee_url
from core.text_utils import part_display_name
from data import store
from scrapers.coolpc_details import has_argb, radiator_sizes
from ui.helpers import ensure_fresh_data, init_state, page_header, qp_int, scroll_to, show_data_source, sync_url

AUTO_CASE = "auto"          # 使用者按「幫我選就好」
GALLERY_SIZE = 9            # 圖片牆一次顯示幾個機殼
COLOR_CODES = ["", "黑", "白"]          # 跟 PC_CASE_COLOR_OPTIONS 同順序
LIGHT_CODES = [None, True, False]       # 跟 PC_CASE_LIGHT_OPTIONS 同順序
SWAP_COLOR_MATTERS = ("gpu", "cooler", "ram", "motherboard", "psu")   # 換零件時，優先列同顏色的類別

# 問卷答案存在 session_state 的名稱 → (網址參數名稱, 選項清單)
RADIO_QUESTIONS = {
    "pc_res": ("res", PC_RESOLUTION_OPTIONS),
    "pc_lan": ("lan", PC_LAN_OPTIONS),
    "pc_wifi_extra": ("wx", PC_WIFI_EXTRA_OPTIONS),
    "pc_bt": ("bt", PC_BLUETOOTH_OPTIONS),
    "pc_mode": ("m", PC_MODE_OPTIONS),
    "pc_size": ("sz", PC_SIZE_OPTIONS),
    "pc_storage": ("sto", PC_STORAGE_OPTIONS),
    "pc_windows": ("win", PC_WINDOWS_OPTIONS),
    "pc_case_color": ("cc", PC_CASE_COLOR_OPTIONS),
    "pc_case_light": ("cl", PC_CASE_LIGHT_OPTIONS),
}
RADIO_DEFAULTS = {"pc_res": 3}
ANSWER_KEYS = ["pc_budget", "pc_usages", *RADIO_QUESTIONS]


# ============================================================
# 快取：同樣的條件不用重算
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def cached_parts(data_version: float) -> pd.DataFrame:
    return store.PARTS.load()


@st.cache_data(ttl=600, show_spinner=False)
def cached_build(data_version: float, prefs_fields: tuple):
    return make_build(cached_parts(data_version), Prefs(*prefs_fields))


@st.cache_data(ttl=600, show_spinner=False)
def cached_cheapest(data_version: float, prefs_fields: tuple):
    return cheapest_possible(cached_parts(data_version), Prefs(*prefs_fields))


@st.cache_data(ttl=600, show_spinner=False)
def cached_gallery(data_version: float, prefs_fields: tuple, color: str, rgb, page: int):
    result = cached_build(data_version, prefs_fields)
    if result is None:
        return [], 0
    budget = Prefs(*prefs_fields).budget
    return case_gallery(cached_parts(data_version), result["parts"], budget, color, rgb, GALLERY_SIZE, page)


@st.cache_data(ttl=600, show_spinner=False)
def cached_current(data_version: float, prefs_fields: tuple, swaps_items: tuple):
    """套用使用者「換一個」之後的菜單。回傳 (零件 dict, 找不到的類別) 或 None。"""
    result = cached_build(data_version, prefs_fields)
    if result is None:
        return None
    return apply_swaps(cached_parts(data_version), result["parts"], dict(swaps_items))


@st.cache_data(ttl=600, show_spinner=False)
def cached_alternatives(data_version: float, prefs_fields: tuple, swaps_items: tuple, category: str, color: str):
    current = cached_current(data_version, prefs_fields, swaps_items)
    if current is None:
        return []
    core = {k: v for k, v in current[0].items() if k not in ("hdd", "os")}
    return alternatives(cached_parts(data_version), core, category, count=6, color=color)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_details(gids: tuple) -> dict:
    return store.DETAILS.get(gids, max_new=len(gids))


@st.cache_data(ttl=86400, max_entries=400, show_spinner=False)
def cached_image(url: str):
    return store.image_bytes(url)


def show_image(detail) -> None:
    """有圖片就顯示；沒有（或抓不到）就放一個灰色框，排版才不會亂掉。"""
    data = cached_image(detail["image"]) if detail and detail.get("image") else None
    if data:
        st.image(data, width="stretch")
    else:
        st.markdown("<div style='height:110px;border-radius:10px;background:rgba(128,128,128,0.15);"
                    "display:flex;align-items:center;justify-content:center;color:#888'>沒有圖片</div>",
                    unsafe_allow_html=True)


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


# ============================================================
# 問卷答案 ↔ 網址
# ============================================================
def load_answers_from_url() -> None:
    """第一次打開（或重新整理）時，從網址讀回上次的答案。"""
    init_state("pc_budget", qp_int("budget", PC_BUDGET_DEFAULT, PC_BUDGET_MIN, PC_BUDGET_MAX))
    usages = []
    for piece in str(st.query_params.get("u", "0")).split("-"):
        if piece.isdigit() and int(piece) < len(PC_USAGE_OPTIONS):
            usages.append(PC_USAGE_OPTIONS[int(piece)])
    init_state("pc_usages", usages or [PC_USAGE_OPTIONS[0]])
    for key, (param, options) in RADIO_QUESTIONS.items():
        init_state(key, options[qp_int(param, RADIO_DEFAULTS.get(key, 0), 0, len(options) - 1)])
    init_state("pc_step", qp_int("step", 1, 1, 3))
    init_state("pc_case", str(st.query_params.get("case", "")))
    init_state("pc_case_page", qp_int("cp", 0, 0, 99))
    swaps = {}
    for category in SWAPPABLE:
        gid = st.query_params.get(f"sw_{category}")
        if gid:
            swaps[category] = str(gid)
    init_state("pc_swaps", swaps)
    init_state("pc_swap_open", "")
    init_state("pc_scroll_to", "")



def ask(widget, label: str, options, key: str, **kwargs):
    """畫一個問題。答案另外存一份在 key，畫面上的元件用 "w_" + key。

    為什麼要存兩份：Streamlit 會把「這次沒顯示在畫面上」的元件答案清掉，
    到第 2、3 步時第 1 步的問題沒顯示，答案就不見了。另存一份就不會被清掉，
    回到第 1 步時再用它把元件還原。
    """
    widget_key = "w_" + key
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[key]
    if options is None:
        value = widget(label, key=widget_key, **kwargs)
    else:
        value = widget(label, options, key=widget_key, **kwargs)
    st.session_state[key] = st.session_state[widget_key]
    return value


def answer_index(key: str) -> int:
    options = RADIO_QUESTIONS[key][1]
    value = st.session_state.get(key)
    return options.index(value) if value in options else RADIO_DEFAULTS.get(key, 0)


def usage_indexes() -> list:
    chosen = st.session_state.get("pc_usages") or []
    return [i for i, text in enumerate(PC_USAGE_OPTIONS) if text in chosen]


def need_wifi() -> bool:
    if answer_index("pc_lan") != 0:   # 沒有網路孔、或不確定
        return True
    if answer_index("pc_bt") == 1:    # 要藍牙：主機板的藍牙跟 Wi-Fi 是同一張卡
        return True
    return answer_index("pc_wifi_extra") == 1


def base_prefs(color: str = "", rgb=None, case_gid: str = "") -> Prefs:
    return Prefs(
        budget=int(st.session_state["pc_budget"]),
        usages=tuple(usage_indexes()) or (0,),
        resolution=answer_index("pc_res"),
        need_wifi=need_wifi(),
        premium=answer_index("pc_mode") == 1,
        small=answer_index("pc_size") == 1,
        storage=answer_index("pc_storage"),
        windows=answer_index("pc_windows") == 1,
        case_gid=case_gid,
        color=color,
        rgb=rgb,
    )


def write_url() -> None:
    """把目前所有答案寫回網址：重新整理不會跑掉，複製網址給朋友也會看到一樣的菜單。"""
    params = {"type": "PC", "budget": st.session_state["pc_budget"],
              "u": "-".join(str(i) for i in usage_indexes()) or "0"}
    for key, (param, _) in RADIO_QUESTIONS.items():
        params[param] = answer_index(key)
    params["step"] = st.session_state["pc_step"]
    if st.session_state["pc_case"]:
        params["case"] = st.session_state["pc_case"]
    if st.session_state["pc_case_page"]:
        params["cp"] = st.session_state["pc_case_page"]
    for category, gid in st.session_state["pc_swaps"].items():
        params[f"sw_{category}"] = gid
    # 換步驟時在瀏覽器紀錄「新增一筆」，按 ← 才會回到上一步；第一次打開頁面不算換步驟
    last_step = st.session_state.get("pc_url_step")
    step_changed = last_step is not None and last_step != st.session_state["pc_step"]
    st.session_state["pc_url_step"] = st.session_state["pc_step"]
    sync_url(params, push=step_changed)


# ============================================================
# 按鈕動作（按下去時先跑這些，再重畫畫面）
# ============================================================
def go_step(step: int) -> None:
    st.session_state["pc_step"] = step
    st.session_state["pc_swap_open"] = ""


def finish_questions() -> None:
    # 答案改了，之前挑的機殼和換過的零件就不一定適合了，全部重來
    st.session_state["pc_case"] = ""
    st.session_state["pc_case_page"] = 0
    st.session_state["pc_swaps"] = {}
    go_step(2)


def choose_case(gid: str) -> None:
    st.session_state["pc_case"] = gid
    st.session_state["pc_swaps"] = {}
    go_step(3)


def next_case_page() -> None:
    st.session_state["pc_case_page"] += 1


def reset_case_page() -> None:
    st.session_state["pc_case_page"] = 0


def toggle_swap(category: str) -> None:
    st.session_state["pc_swap_open"] = "" if st.session_state["pc_swap_open"] == category else category


def do_swap(category: str, gid: str) -> None:
    swaps = dict(st.session_state["pc_swaps"])
    if gid:
        swaps[category] = gid
    else:
        swaps.pop(category, None)   # 還原成系統配的
    st.session_state["pc_swaps"] = swaps
    st.session_state["pc_swap_open"] = ""
    st.session_state["pc_scroll_to"] = category   # 重畫後捲回這個零件，不然畫面會停在別的地方


# ============================================================
# 第 1 步：問問題
# ============================================================
def step_questions() -> None:
    st.subheader("第 1 步：告訴我你的預算和需求")

    ask(st.slider, "💰 整台主機的預算（新台幣，不含螢幕、鍵盤滑鼠）：", None, "pc_budget",
        min_value=PC_BUDGET_MIN, max_value=PC_BUDGET_MAX, step=1000, format="$%d 元")

    ask(st.pills, "🎯 主要拿來做什麼？（可以複選）", PC_USAGE_OPTIONS, "pc_usages", selection_mode="multi")
    if not st.session_state.get("pc_usages"):
        st.caption("👆 至少選一個用途")

    ask(st.radio, "🖥️ 你的螢幕是哪一種？（決定顯示卡要多強）", PC_RESOLUTION_OPTIONS, "pc_res")
    st.caption("不知道的話：一般 24 吋螢幕大多是 1080p；27 吋電競螢幕大多是 2K。")

    c1, c2 = st.columns(2)
    with c1:
        ask(st.radio, "🌐 電腦要放的位置，旁邊有網路孔（可以插網路線）嗎？", PC_LAN_OPTIONS, "pc_lan")
        if answer_index("pc_lan") == 0:
            ask(st.radio, "📶 有網路線的話，還要 Wi-Fi 嗎？", PC_WIFI_EXTRA_OPTIONS, "pc_wifi_extra")
            st.caption("網路線比 Wi-Fi 穩定、延遲低，打遊戲最推薦。有 Wi-Fi 的主機板大約貴 $500～1,500。")
    with c2:
        ask(st.radio, "🎧 需要藍牙嗎？", PC_BLUETOOTH_OPTIONS, "pc_bt")
        if answer_index("pc_bt") == 1:
            st.caption("主機板上的無線網卡幾乎都是「Wi-Fi + 藍牙」二合一，所以會自動幫你配有 Wi-Fi 的主機板；"
                       "買的時候可以再跟店員確認一次有藍牙。只想要藍牙、不要 Wi-Fi 的話，"
                       "也可以另外買約 $300 的 USB 藍牙接收器。")

    with st.expander("⚙️ 進階需求（不懂可以不用改）"):
        ask(st.radio, "💎 預算怎麼花？", PC_MODE_OPTIONS, "pc_mode")
        st.caption("「用好料」會把預算盡量花完：更高級的主機板、更大更快的記憶體、PCIe 5.0 SSD、白金電源。")
        ask(st.radio, "📦 主機大小", PC_SIZE_OPTIONS, "pc_size")
        ask(st.radio, "💾 要存多少東西？", PC_STORAGE_OPTIONS, "pc_storage")
        ask(st.radio, "🪟 要一起買 Windows 嗎？", PC_WINDOWS_OPTIONS, "pc_windows")

    if st.session_state["pc_budget"] >= 80000 and answer_index("pc_mode") == 0:
        st.info("💡 預算 8 萬以上，建議打開上面的「進階需求」選「用好料」，才會把預算花在高級主機板、"
                "大容量記憶體、PCIe 5.0 SSD 這些地方；不然系統會「效能夠用就好」，幫你省下很多錢。")

    st.button("下一步：挑機殼外觀 ➡️", type="primary", width="stretch",
              disabled=not st.session_state.get("pc_usages"), on_click=finish_questions)


def budget_too_low(version: float, prefs: Prefs) -> None:
    with st.spinner("計算最低需要多少預算…"):
        minimum = cached_cheapest(version, astuple(prefs))
    if minimum:
        st.warning(f"這個預算配不出相容的整台電腦。照你的需求，預算至少要約 **${minimum:,}**，回上一步把預算調高試試看。")
    else:
        st.warning("目前原價屋的零件配不出符合這些條件的電腦，回上一步換個條件試試看。")
    st.button("⬅️ 回上一步改問題", key="low_back", on_click=go_step, args=(1,))


# ============================================================
# 第 2 步：看圖挑機殼
# ============================================================
def case_tags(case, detail) -> str:
    tags = []
    if isinstance(case["color"], str) and case["color"]:
        tags.append(f"{case['color']}色")
    if _truthy(case["case_glass"]):
        tags.append("玻璃側透")
    if has_argb(detail or {}, case["name"]):
        tags.append("✨ 有燈光")
    radiators = radiator_sizes(detail or {})
    if radiators:
        tags.append(f"可裝 {radiators[0]} 水冷")
    tags.append(f"顯卡最長 {case['case_gpu_max_cm']:g}cm")
    return "　·　".join(tags)


def step_case(version: float) -> None:
    st.subheader("第 2 步：挑一個你喜歡的機殼")
    st.caption("下面的機殼都確認過「放得下你這台電腦」。顏色和燈光就看你挑的機殼，其他零件會盡量配同色系。")

    prefs = base_prefs()
    with st.spinner("🔧 先幫你算出零件大小，挑出放得下的機殼…"):
        prelim = cached_build(version, astuple(prefs))
    if prelim is None:
        budget_too_low(version, prefs)
        return

    c1, c2 = st.columns(2)
    with c1:
        ask(st.radio, "🎨 顏色", PC_CASE_COLOR_OPTIONS, "pc_case_color", horizontal=True, on_change=reset_case_page)
    with c2:
        ask(st.radio, "💡 燈光", PC_CASE_LIGHT_OPTIONS, "pc_case_light", horizontal=True, on_change=reset_case_page)
    color = COLOR_CODES[answer_index("pc_case_color")]
    rgb = LIGHT_CODES[answer_index("pc_case_light")]

    cases, total = cached_gallery(version, astuple(prefs), color, rgb, st.session_state["pc_case_page"])
    if not cases:
        st.info("沒有符合這個顏色、燈光的機殼，換個條件試試看。")
    else:
        with st.spinner("🖼️ 正在載入機殼圖片…（第一次比較慢，之後就很快）"):
            details = cached_details(tuple(c["coolpc_gid"] for c in cases))
        default_price = prelim["parts"]["case"]["price"]
        for row_start in range(0, len(cases), 3):
            cols = st.columns(3)
            for col, case in zip(cols, cases[row_start:row_start + 3]):
                detail = details.get(case["coolpc_gid"])
                with col, st.container(border=True):
                    show_image(detail)
                    st.markdown(f"**{part_display_name(case['name'])}**")
                    diff = int(case["price"] - default_price)
                    diff_text = "" if diff == 0 else f"（比預設 {'+' if diff > 0 else '-'}${abs(diff):,}）"
                    st.markdown(f"<span style='font-size:18px;font-weight:700;color:#4CAF50'>${int(case['price']):,}</span>"
                                f" <span style='color:#888;font-size:13px'>{diff_text}</span>", unsafe_allow_html=True)
                    st.caption(case_tags(case, detail))
                    st.button("選這個", key=f"pick_{case['coolpc_gid']}", width="stretch",
                              on_click=choose_case, args=(case["coolpc_gid"],))
        st.caption(f"符合條件、放得下的機殼共 {total} 個，這裡從便宜到貴各挑幾個。機殼買比較貴的，其他零件的預算就會少一點。")

    c1, c2, c3 = st.columns(3)
    c1.button("⬅️ 回上一步改問題", width="stretch", on_click=go_step, args=(1,))
    c2.button("🔄 換一批機殼", width="stretch", on_click=next_case_page, disabled=total <= GALLERY_SIZE)
    c3.button("🎲 幫我選就好", type="primary", width="stretch", on_click=choose_case, args=(AUTO_CASE,))


# ============================================================
# 第 3 步：完整菜單
# ============================================================
def final_prefs(version: float) -> Prefs:
    gid = st.session_state["pc_case"]
    if gid and gid != AUTO_CASE:
        parts = cached_parts(version)
        found = parts[(parts["category"] == "case") & (parts["coolpc_gid"] == gid)]
        color = found.iloc[0]["color"] if not found.empty else ""
        return base_prefs(color=color if isinstance(color, str) else "", case_gid=gid)
    return base_prefs(color=COLOR_CODES[answer_index("pc_case_color")], rgb=LIGHT_CODES[answer_index("pc_case_light")])


def compatibility_checklist(parts: dict) -> list:
    """把自動檢查過的項目，用白話一條條列出來。"""
    cpu, mb, ram, gpu = parts["cpu"], parts["motherboard"], parts["ram"], parts["gpu"]
    cooler, psu, case = parts["cooler"], parts["psu"], parts["case"]
    items = [
        f"CPU 和主機板的插槽都是 **{cpu['socket']}**，插得上去",
        f"記憶體和主機板都是 **DDR{int(ram['ddr'])}**，插得上去",
        f"主機板尺寸 **{mb['form_factor']}**，機殼最大能裝 **{case['case_mb_max']}**，放得進去",
    ]
    if gpu is not None:
        length = "未標示（以 30 公分保守估算）" if pd.isna(gpu["length_cm"]) else f"{gpu['length_cm']:g} 公分"
        items.append(f"顯示卡長 **{length}**，機殼最長可放 **{case['case_gpu_max_cm']:g} 公分**"
                     f"（至少留 {GPU_LENGTH_MARGIN_CM:g} 公分插線空間）")
    else:
        items.append("沒有買顯示卡，但這顆 CPU **有內建顯示功能**，接上螢幕就有畫面")
    if cooler is not None:
        items.append(f"散熱器高 **{cooler['cooler_height_cm']:g} 公分**，機殼最高可放 **{case['case_cpu_max_cm']:g} 公分**"
                     f"（至少留 {COOLER_HEIGHT_MARGIN_CM:g} 公分）")
        items.append(f"散熱器能壓住約 **{int(cooler['cooler_tdp_w'])}W**，CPU 滿載大約 **{cpu_power(cpu)}W**")
    else:
        items.append("CPU 盒裝附原廠風扇，不用另外買散熱器")
    items.append(f"整台電腦建議電源至少 **{required_psu_w(cpu, gpu)}W**，選的是 **{int(psu['psu_w'])}W {psu['psu_rating']}**")
    return items


def menu_text(parts: dict, total: int) -> str:
    """純文字菜單：可以複製去問店員、貼到原價屋估價單，或傳給朋友。"""
    lines = []
    for category in PART_ORDER:
        part = parts.get(category)
        if part is not None:
            lines.append(f"{PART_LABELS[category]}：{part_display_name(part['name'])}  ${int(part['price']):,}")
    lines.append(f"合計：${total:,}")
    return "\n".join(lines)


def show_alternatives(version, prefs_fields, swaps_items, category, current, color) -> None:
    with st.container(border=True):
        with st.spinner("找出換上去之後還是相容的選擇…"):
            alts = cached_alternatives(version, prefs_fields, swaps_items, category, color)
        if not alts:
            st.caption("沒有其他相容的選擇了。")
        else:
            st.caption("下面每一個都確認過：換上去之後整台還是相容。價格是跟目前這個比。")
            with st.spinner("🖼️ 載入圖片…"):
                details = cached_details(tuple(a["coolpc_gid"] for a in alts))
            for row_start in range(0, len(alts), 3):
                cols = st.columns(3)
                for col, alt in zip(cols, alts[row_start:row_start + 3]):
                    with col:
                        show_image(details.get(alt["coolpc_gid"]))
                        st.markdown(f"<div style='font-size:14px'>{part_display_name(alt['name'])}</div>",
                                    unsafe_allow_html=True)
                        diff = int(alt["price"] - current["price"])
                        diff_color = "#e57373" if diff > 0 else "#4CAF50"
                        st.markdown(f"**${int(alt['price']):,}**　<span style='color:{diff_color}'>"
                                    f"{'+' if diff > 0 else '-'}${abs(diff):,}</span>", unsafe_allow_html=True)
                        st.button("換這個", key=f"swap_{category}_{alt['coolpc_gid']}", width="stretch",
                                  on_click=do_swap, args=(category, alt["coolpc_gid"]))
        if category in st.session_state["pc_swaps"]:
            st.button("↩️ 換回系統原本配的", key=f"undo_{category}", on_click=do_swap, args=(category, ""))


def show_part_row(category, part, detail, swapped, can_swap) -> None:
    with st.container(border=True):
        col_img, col_info, col_price, col_btn = st.columns([1.3, 5, 1.6, 2])
        with col_img:
            show_image(detail)
        with col_info:
            badge = "　<span style='color:#ffb74d;font-size:13px'>（你換過的）</span>" if swapped else ""
            st.markdown(f"**{PART_LABELS[category]}**　<span style='color:#888;font-size:14px'>{PART_ROLES[category]}</span>{badge}",
                        unsafe_allow_html=True)
            st.markdown(part_display_name(part["name"]))
        with col_price:
            st.markdown(f"<div style='font-size:20px;font-weight:700;color:#4CAF50;padding-top:14px'>${int(part['price']):,}</div>",
                        unsafe_allow_html=True)
        with col_btn:
            model = part["model"]
            keyword = model if isinstance(model, str) and model else part_display_name(part["name"])
            b1, b2 = st.columns(2)
            b1.link_button("蝦皮", shopee_url(keyword), width="stretch")
            b2.link_button("Momo", momo_url(keyword), width="stretch")
            if can_swap:
                opened = st.session_state["pc_swap_open"] == category
                st.button("收起" if opened else "🔄 換一個", key=f"open_{category}", width="stretch",
                          on_click=toggle_swap, args=(category,))


def step_result(version: float) -> None:
    st.subheader("第 3 步：你的專屬菜單")
    prefs = final_prefs(version)
    prefs_fields = astuple(prefs)
    with st.spinner("🔧 正在從幾百個零件裡，找出最適合你又保證相容的組合…"):
        result = cached_build(version, prefs_fields)
    if result is None:
        if prefs.case_gid:
            st.warning("用這個機殼配不出預算內的整台電腦（機殼太貴，或放不下需要的零件），回上一步換一個機殼試試看。")
            st.button("⬅️ 回上一步重新挑機殼", on_click=go_step, args=(2,))
        else:
            budget_too_low(version, prefs)
        return

    swaps_items = tuple(sorted(st.session_state["pc_swaps"].items()))
    parts, missing = cached_current(version, prefs_fields, swaps_items)
    for category in missing:
        st.info(f"你之前換的{PART_LABELS[category]}今天原價屋沒賣了，先換回系統配的。")
    problems, notes = recheck(parts)
    total = total_price(parts)
    budget = prefs.budget

    c1, c2, c3 = st.columns(3)
    c1.metric("整台總價", f"${total:,}")
    if total > budget:
        c2.metric("你的預算", f"${budget:,}", delta=f"超出 ${total - budget:,}", delta_color="inverse")
    else:
        c2.metric("你的預算", f"${budget:,}", delta=f"省下 ${budget - total:,}" if budget > total else None)
    c3.metric("相容性檢查", "全部通過 ✅" if not problems else "有問題 ⚠️")

    for problem in problems:
        st.error(problem)
    if not st.session_state["pc_swaps"]:
        for tip in result["tips"]:
            st.info(tip)
    elif total > budget:
        st.warning("你換過零件之後，總價超出預算了。不喜歡的話，可以按「換一個」→「換回系統原本配的」。")

    st.write("### 🧾 推薦菜單")
    st.caption("價格是原價屋今天的報價。每一項都附蝦皮、Momo 搜尋可以比價；不喜歡外觀或想升級，按「換一個」。")
    with st.spinner("🖼️ 正在載入零件圖片…（第一次比較慢）"):
        details = cached_details(tuple(p["coolpc_gid"] for p in parts.values() if p is not None))
    for category in PART_ORDER:
        part = parts.get(category)
        if part is None:
            continue
        can_swap = category in SWAPPABLE
        st.markdown(f"<div id='pc-row-{category}'></div>", unsafe_allow_html=True)
        show_part_row(category, part, details.get(part["coolpc_gid"]),
                      category in st.session_state["pc_swaps"], can_swap)
        if can_swap and st.session_state["pc_swap_open"] == category:
            if category == "case":
                with st.container(border=True):
                    st.caption("想換機殼的話，回第 2 步看圖挑，其他零件會跟著重新配。")
                    st.button("⬅️ 回去看圖挑機殼", key="case_back", on_click=go_step, args=(2,))
            else:
                swap_color = prefs.color if category in SWAP_COLOR_MATTERS else ""
                show_alternatives(version, prefs_fields, swaps_items, category, part, swap_color)

    if notes:
        st.write("### 📌 買之前要知道的事")
        for note in notes:
            st.warning(note)

    with st.expander("✅ 幫你檢查過的相容性項目（點開看）"):
        st.caption("這些是新手最常買錯的地方，系統都自動確認過了。")
        for item in compatibility_checklist(parts):
            st.markdown(f"- {item}")

    with st.expander("📋 複製整張菜單（可以傳給朋友，或拿去問店員）"):
        st.code(menu_text(parts, total), language=None)
        st.link_button("🏬 到原價屋估價單自己下單", COOLPC_URL)

    st.caption("商品圖片、價格來自原價屋。")
    c1, c2 = st.columns(2)
    c1.button("⬅️ 重新挑機殼", width="stretch", on_click=go_step, args=(2,))
    c2.button("📝 回去改問題", width="stretch", on_click=go_step, args=(1,))


# ============================================================
# 頁面
# ============================================================
def render() -> None:
    page_header("目前模式：🖥️ 自組桌機 (PC)")

    refresh_error = ensure_fresh_data(store.PARTS, "桌機零件")
    version = store.PARTS.version()
    parts_df = cached_parts(version)
    show_data_source(store.PARTS, f"共 {len(parts_df)} 個零件", refresh_error)

    load_answers_from_url()
    step = st.session_state["pc_step"]
    st.markdown("<div id='pc-top'></div>", unsafe_allow_html=True)
    st.progress(step / 3, text=["", "① 問問題　→　② 挑機殼　→　③ 完整菜單",
                                "① 問問題 ✓　→　② 挑機殼　→　③ 完整菜單",
                                "① 問問題 ✓　→　② 挑機殼 ✓　→　③ 完整菜單"][step])

    if step == 1:
        step_questions()
    elif step == 2:
        step_case(version)
    else:
        step_result(version)

    # 換了步驟就捲回最上面；換了零件就捲回那個零件
    if st.session_state.get("pc_url_step") not in (None, step):
        scroll_to("pc-top")
    elif st.session_state["pc_scroll_to"]:
        scroll_to(f"pc-row-{st.session_state['pc_scroll_to']}")
    st.session_state["pc_scroll_to"] = ""

    write_url()
