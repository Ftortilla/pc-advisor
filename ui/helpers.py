"""Streamlit 畫面共用的小工具：讀寫網址參數、記住選項、內頁標題列。"""
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components


def qp_int(key: str, default: int, low: int, high: int) -> int:
    """從網址讀一個數字；讀不到或亂填就用預設值，並限制在合理範圍內。"""
    try:
        value = int(st.query_params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def init_state(key: str, value) -> None:
    """只有第一次才設定，之後交給使用者操作，避免選項被蓋掉。"""
    if key not in st.session_state:
        st.session_state[key] = value


def sync_url(params: dict) -> None:
    """把目前選項寫進網址。

    用「替換」目前網址的方式更新，不會在瀏覽器的上一頁紀錄裡多塞一筆，
    所以按瀏覽器 ← 會直接回到首頁，而不是一格一格退回剛剛調過的選項。
    """
    query = urllib.parse.urlencode(params)
    components.html(
        f"""<script>
        const w = window.parent;
        const url = new URL(w.location.href);
        if (url.search !== "?{query}") {{
            url.search = "?{query}";
            w.history.replaceState(w.history.state, "", url.toString());
        }}
        </script>""",
        height=0,
    )


def page_header(title: str) -> None:
    """內頁最上面那排：左邊「回首頁」連結、右邊標題、下面一條分隔線。"""
    col_back, col_title = st.columns([1.5, 8.5])
    with col_back:
        st.write("")
        # 用真正的網頁連結換頁，瀏覽器的 ← 返回才會有作用
        st.markdown('<a class="back-link" href="./" target="_self">⬅️ 回首頁</a>', unsafe_allow_html=True)
    with col_title:
        st.title(title)
    st.divider()
