"""Streamlit 畫面共用的小工具：讀寫網址參數、記住選項、內頁標題列。"""
import time
import urllib.parse

import streamlit as st

try:
    # 舊版的「放一小段網頁程式」功能。新版 Streamlit 宣布之後會移除，所以要包一層：
    # 有就用，沒有就跳過（只是網址不會自動更新，網站其他功能照常）
    import streamlit.components.v1 as components
except ImportError:  # pragma: no cover
    components = None


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


def sync_url(params: dict, push: bool = False) -> None:
    """把目前選項寫進網址。

    平常用「替換」目前網址（push=False），調選項不會在瀏覽器的上一頁紀錄裡多塞一堆。
    換到下一個步驟時用「新增」（push=True），按瀏覽器 ← 才會回到上一步，而不是直接回首頁。
    按 ← 之後網址變了，但 Streamlit 不會自己發現，所以監聽「上一頁」事件，重新載入一次，
    頁面就會照網址裡記的步驟和選項重畫。
    """
    query = urllib.parse.urlencode(params)
    method = "pushState" if push else "replaceState"
    script = f"""<script>
        const w = window.parent;
        const url = new URL(w.location.href);
        if (url.search !== "?{query}") {{
            url.search = "?{query}";
            w.history.{method}(w.history.state, "", url.toString());
        }}
        if (!w.__advisorBackHooked) {{
            w.__advisorBackHooked = true;
            w.addEventListener("popstate", () => w.location.reload());
        }}
        </script>"""
    run_script(script)


def scroll_to(element_id: str) -> None:
    """畫面重畫之後，捲到指定的位置（例如剛剛換掉的那個零件）。"""
    run_script(f"""<script>
        // {time.time()}  每次內容不同，Streamlit 才會重新執行
        setTimeout(() => {{
            const el = window.parent.document.getElementById("{element_id}");
            if (el) el.scrollIntoView({{behavior: "smooth", block: "start"}});
        }}, 400);
        </script>""")


def run_script(script: str) -> None:
    """在網頁裡跑一小段 JavaScript。Streamlit 改版拿掉舊功能時，安靜地跳過，不讓整個網站壞掉。"""
    html = getattr(components, "html", None) if components else None
    if html is None:
        return
    try:
        html(script, height=0)
    except Exception:
        pass


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


def ensure_fresh_data(dataset, what: str):
    """資料太舊就自動更新；網址有 refresh=1 就強制更新一次（測試用）。

    dataset 是 data/store.py 裡的 LAPTOPS 或 PARTS。回傳失敗原因（成功或不用更新回傳 None）。
    """
    done_key = f"forced_done_{what}"
    # 用 session_state 記住，避免同一個分頁重複觸發強制更新
    force = st.query_params.get("refresh") == "1" and not st.session_state.get(done_key)
    error = None
    if force or dataset.needs_refresh():
        with st.spinner("📡 正在從原價屋抓今天的最新價格，大約 5～10 秒…"):
            error = dataset.refresh(force=force)

    if force:
        st.session_state[done_key] = True
        if error:
            st.error(f"強制更新失敗：{error}")
        else:
            st.success("強制更新成功，已抓到原價屋最新價格。")

    if not dataset.exists():
        st.error(f"還沒有{what}資料，自動抓取也失敗了。（原因：{error}）請稍後再重新整理一次。")
        st.stop()
    return error


def show_data_source(dataset, count_text: str, error) -> None:
    """頁面上方那行「價格來源、最後更新時間」。"""
    scraped_at = dataset.scraped_at()
    updated_text = scraped_at.strftime("%Y/%m/%d %H:%M") if scraped_at else "不明"
    st.caption(f"📡 價格來源：原價屋線上估價單，{count_text}，最後更新 {updated_text}")
    if error:
        st.caption(f"⚠️ 今天自動更新價格失敗，目前顯示的是上次抓到的價格。（{error}）")
