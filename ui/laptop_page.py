"""筆電頁：問卷、推薦結果卡片、避坑指南。

這裡只負責「畫面」。篩選、算分的邏輯在 core/laptop/，讀資料、自動更新在 data/store.py。
"""
import pandas as pd
import streamlit as st

from core.config import (
    BATTERY_OPTIONS,
    GPU_PLAIN,
    LAPTOP_BUDGET_DEFAULT,
    LAPTOP_BUDGET_MAX,
    LAPTOP_BUDGET_MIN,
    NOISE_OPTIONS,
    USAGE_OPTIONS,
    WEIGHT_OPTIONS,
)
from core.laptop.guide import budget_tier
from core.laptop.recommend import card_warnings, pick_budget_saver, pick_laptops
from core.shop_links import COOLPC_URL, momo_url, search_keyword, shopee_url
from core.text_utils import short_name
from data import store
from ui.helpers import init_state, page_header, qp_int, sync_url


@st.cache_data(ttl=600)
def cached_laptops(data_version: float) -> pd.DataFrame:
    # data_version 是資料檔的修改時間：資料一更新，就會重新讀取，不會一直用舊的快取
    return store.load_laptops()


def refresh_data() -> None:
    """資料太舊就自動更新；網址有 refresh=1 就強制更新一次（測試用）。"""
    # 用 session_state 記住，避免同一個分頁重複觸發強制更新
    force = st.query_params.get("refresh") == "1" and not st.session_state.get("forced_done")
    if force or store.laptop_needs_refresh():
        with st.spinner("📡 正在從原價屋抓今天的最新價格，大約 5～10 秒…"):
            error = store.refresh_laptops(force=force)
    else:
        error = None

    if force:
        st.session_state["forced_done"] = True
        if error:
            st.error(f"強制更新失敗：{error}")
        else:
            st.success("強制更新成功，已抓到原價屋最新價格。")

    if not store.laptop_data_exists():
        st.error(f"還沒有筆電資料，自動抓取也失敗了。（原因：{error}）請稍後再重新整理一次。")
        st.stop()

    st.session_state["refresh_error"] = error


def show_laptop_card(row, weight_idx) -> None:
    g = row["gpu_level"]
    with st.container(border=True):
        col_info, col_b1, col_b2, col_b3 = st.columns([5.2, 1.6, 1.6, 1.6])
        with col_info:
            badge = "" if row["condition"] == "新品" else f"　`{row['condition']}`"
            st.markdown(f"**{short_name(row['name'])}**{badge}")
            weight_text = f"　⚖️ {int(row['weight_g'])} 克" if pd.notna(row["weight_g"]) else ""
            st.markdown(
                f"🎮 {row['gpu']}（{GPU_PLAIN.get(g, '')}）　🧠 記憶體 {row['ram_gb']}GB　"
                f"💾 {row['storage']}　🖥️ {row['screen_inch']:g} 吋{weight_text}"
            )
            st.markdown(
                f"<span style='color: #4CAF50; font-weight: bold; font-size: 18px;'>原價屋價：${row['price']:,}</span>",
                unsafe_allow_html=True,
            )
            for tip in card_warnings(row, weight_idx):
                st.caption(tip)
        keyword = search_keyword(row["brand"], row["model_code"], row["name"])
        with col_b1:
            st.link_button("🏬 原價屋", COOLPC_URL, use_container_width=True)
        with col_b2:
            st.link_button("🔍 蝦皮比價", shopee_url(keyword), use_container_width=True)
        with col_b3:
            st.link_button("📦 Momo 比價", momo_url(keyword), use_container_width=True)


def show_results(laptops_df, nb_budget, usage_idx, weight_idx, battery_idx, noise_idx, include_used) -> None:
    tier_name, experience_desc, plain_rules = budget_tier(nb_budget, usage_idx)

    st.write("")
    st.success(f"🎯 推薦定位：【{tier_name}】（設定預算：${nb_budget:,} NTD）")
    st.markdown(experience_desc)

    results, notes = pick_laptops(
        laptops_df, nb_budget, usage_idx, weight_idx, battery_idx, noise_idx, include_used
    )

    st.write("### 💻 原價屋現貨推薦")

    if results.empty:
        cheapest = laptops_df["price"].min()
        st.warning(f"這個預算內原價屋目前沒有筆電。最便宜的一台是 ${cheapest:,}，可以把預算往上拉一點試試。")
    else:
        for note in notes:
            st.info(note)

        st.caption(
            f"預算內共有 {len(results)} 台符合條件，依你的需求排出最適合的。"
            "重量、續航、噪音是用「有沒有獨顯、螢幕多大」估計的，實際以官方規格為準。"
        )

        for _, row in results.head(3).iterrows():
            show_laptop_card(row, weight_idx)

        saver = pick_budget_saver(results, usage_idx, weight_idx)
        if saver is not None:
            saving = int(results.iloc[0]["price"] - saver["price"])
            if saver["gpu_level"] < results.iloc[0]["gpu_level"]:
                st.write(f"#### 💰 省錢選擇：顯卡低一階，但一樣符合你的用途，便宜 ${saving:,}")
            else:
                st.write(f"#### 💰 省錢選擇：規格一樣夠用，比第一名便宜 ${saving:,}")
            show_laptop_card(saver, weight_idx)

        more = results.iloc[3:10]
        if saver is not None:
            more = more[more.index != saver.name]
        if not more.empty:
            with st.expander(f"👀 再看 {len(more)} 台也符合條件的機種"):
                for _, row in more.iterrows():
                    show_laptop_card(row, weight_idx)

    with st.expander("🗣️ 新手避坑人話指南（這價位買筆電注意什麼？）"):
        for r in plain_rules:
            st.markdown(f"* {r}")


def render() -> None:
    page_header("目前模式：💻 筆記型電腦 (Laptop)")

    refresh_data()
    laptops_df = cached_laptops(store.laptop_data_version())
    scraped_at = store.laptop_scraped_at()
    updated_text = scraped_at.strftime("%Y/%m/%d %H:%M") if scraped_at else "不明"

    st.caption(f"📡 價格來源：原價屋線上估價單，共 {len(laptops_df)} 台筆電，最後更新 {updated_text}")
    refresh_error = st.session_state.get("refresh_error")
    if refresh_error:
        st.caption(f"⚠️ 今天自動更新價格失敗，目前顯示的是上次抓到的價格。（{refresh_error}）")

    # 第一次打開（或重新整理）時，從網址讀回上次的選項
    init_state("nb_budget", qp_int("budget", LAPTOP_BUDGET_DEFAULT, LAPTOP_BUDGET_MIN, LAPTOP_BUDGET_MAX))
    init_state("nb_usage", USAGE_OPTIONS[qp_int("u", 0, 0, len(USAGE_OPTIONS) - 1)])
    init_state("weight_pref", WEIGHT_OPTIONS[qp_int("w", 0, 0, len(WEIGHT_OPTIONS) - 1)])
    init_state("battery_pref", BATTERY_OPTIONS[qp_int("b", 0, 0, len(BATTERY_OPTIONS) - 1)])
    init_state("noise_pref", NOISE_OPTIONS[qp_int("n", 0, 0, len(NOISE_OPTIONS) - 1)])
    init_state("include_used", st.query_params.get("used", "0") == "1")
    init_state("show_result", st.query_params.get("go") == "1")

    st.subheader("1. 設定您的使用習慣與生活場景")
    nb_budget = st.slider("💰 您的筆電總預算 (NTD)：", min_value=LAPTOP_BUDGET_MIN, max_value=LAPTOP_BUDGET_MAX,
                          step=1000, format="$%d 元", key="nb_budget")

    col_req1, col_req2 = st.columns(2)
    with col_req1:
        nb_usage = st.selectbox("🎯 主要做什麼事：", USAGE_OPTIONS, key="nb_usage")
        weight_pref = st.selectbox("🎒 重量負擔接受度：", WEIGHT_OPTIONS, key="weight_pref")
    with col_req2:
        battery_pref = st.selectbox("🔋 不插電續航需求：", BATTERY_OPTIONS, key="battery_pref")
        noise_pref = st.selectbox("❄️ 噪音與散熱體感要求：", NOISE_OPTIONS, key="noise_pref")

    include_used = st.checkbox("也顯示展示品／維修品（比較便宜，但保固可能不同）", key="include_used")

    usage_idx = USAGE_OPTIONS.index(nb_usage)
    weight_idx = WEIGHT_OPTIONS.index(weight_pref)
    battery_idx = BATTERY_OPTIONS.index(battery_pref)
    noise_idx = NOISE_OPTIONS.index(noise_pref)

    if st.button("🚀 生成客製化筆電選購指南與推薦", type="primary", use_container_width=True):
        st.session_state["show_result"] = True

    # 把目前選項寫回網址：重新整理不會跑掉，複製網址給朋友也會看到一樣的推薦
    url_params = {
        "type": "Laptop",
        "budget": nb_budget,
        "u": usage_idx,
        "w": weight_idx,
        "b": battery_idx,
        "n": noise_idx,
        "used": 1 if include_used else 0,
    }
    if st.session_state["show_result"]:
        url_params["go"] = 1
    sync_url(url_params)

    # 按過一次之後，改任何選項結果都會即時更新；重新整理也會直接顯示結果
    if st.session_state["show_result"]:
        show_results(laptops_df, nb_budget, usage_idx, weight_idx, battery_idx, noise_idx, include_used)
