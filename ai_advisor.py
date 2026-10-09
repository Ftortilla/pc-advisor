import os
import re
import urllib.parse
import threading
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="硬體選購引導顧問", layout="wide")

# ============================================================
# 基本設定
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAPTOP_CSV = os.path.join(BASE_DIR, "coolpc_laptop.csv")
COOLPC_URL = "https://www.coolpc.com.tw/evaluate.php"

USAGE_OPTIONS = [
    "純上課記筆記 / 追劇上網 / Office 文書",
    "寫程式 / 跑大數據 / 偶爾打打 LOL 網遊",
    "重度打 3A 大作遊戲 (如黑神話、賽博龐克)",
    "剪 4K 影片 / 3D 製圖建模",
    "我不差錢，要最頂級的旗艦移動工作站 / 頂級遊戲機",
]
WEIGHT_OPTIONS = [
    "極致輕薄 (1.3kg 內，每天揹出門肩膀不痠)",
    "主流重量 (1.5 ~ 2.0kg，上課放後背包可接受)",
    "效能大磚頭 (2.3kg 以上 + 巨大變壓器，基本上定點使用)",
]
BATTERY_OPTIONS = [
    "長效續航 (不帶充電器要能撐完半天以上課堂)",
    "普通表現 (能撐 3~4 小時文書開會即可)",
    "隨時插電 (打遊戲或重度工作必插原廠變壓器)",
]
NOISE_OPTIONS = [
    "安靜優先 (圖書館或安靜宿舍，不能忍受吹風機起飛聲)",
    "一般平衡 (平常安靜，高負載有點風扇聲可接受)",
    "效能全開 (戴耳機打遊戲，風扇全力吹沒關係，鍵盤不燙就行)",
]

# 筆電預算拉桿範圍（RTX 5090 旗艦筆電可以到 20 幾萬）
BUDGET_MIN = 10000
BUDGET_MAX = 250000

# 每種用途「至少」需要的顯卡等級（數字越大越強，見下方 GPU_LEVELS）
USAGE_MIN_GPU = [0, 0, 3, 4, 6]

# 顯卡等級表：順序很重要，5070Ti 要排在 5070 前面才不會被誤判
GPU_LEVELS = [
    ("5090", 7),
    ("5080", 6),
    ("4080", 6),
    ("5070Ti", 5),
    ("4070", 4),
    ("5070", 4),
    ("4060", 3),
    ("5060", 3),
    ("4050", 2),
    ("5050", 2),
    ("3050", 1),
]

# 顯卡等級的白話說明
GPU_PLAIN = {
    0: "內顯，文書影音足夠",
    1: "入門獨顯，LOL 順跑",
    2: "中低階，3A 低～中特效",
    3: "甜品級，3A 高特效 1080p",
    4: "高階，2K 高特效",
    5: "高階+，2K 全開",
    6: "旗艦，4K 也能跑",
    7: "頂規旗艦，筆電天花板",
}


# ============================================================
# 小工具
# ============================================================
def get_shopee_url(keyword: str) -> str:
    return "https://shopee.tw/search?keyword=" + urllib.parse.quote(keyword)


def get_momo_url(keyword: str) -> str:
    return "https://www.momoshop.com.tw/search/searchShop.jsp?keyword=" + urllib.parse.quote(keyword)


def qp_int(key: str, default: int, low: int, high: int) -> int:
    # 從網址讀一個數字；讀不到或亂填就用預設值，並限制在合理範圍內
    try:
        value = int(st.query_params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def sync_url(params: dict) -> None:
    # 用「替換」目前網址的方式更新，不會在瀏覽器的上一頁紀錄裡多塞一筆，
    # 所以按瀏覽器 ← 會直接回到首頁，而不是一格一格退回剛剛調過的選項。
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


def init_state(key: str, value) -> None:
    # 只有第一次才設定，之後交給使用者操作，避免選項被蓋掉
    if key not in st.session_state:
        st.session_state[key] = value


def gpu_level(gpu: str) -> int:
    gpu = str(gpu)
    if not gpu.startswith("RTX"):
        return 0
    for key, level in GPU_LEVELS:
        if key in gpu:
            return level
    return 0


def short_name(name: str) -> str:
    name = str(name)
    # ｛型號｝後面接的通常是促銷字（萌色動人、〈IPS面板〉、搭包包…），整段切掉
    # 例外：少數商品型號寫在前面、規格在後面（例如捷元｛15N｝N100/8G/...），這種就保留
    if "｝" in name:
        head, _, tail = name.rpartition("｝")
        if not re.search(r"\d+G/", tail):
            name = head + "｝"
    name = re.sub(r"【[^】]*】", "", name)
    name = re.sub(r"｛[^｝]*｝", " ", name)
    name = re.sub(r"〈[^〉]*〉", "", name)
    name = re.sub(r"省\$\d+", "", name)
    return re.sub(r"\s+", " ", name).strip()


def weight_grams(name: str):
    # 原價屋偶爾會在名稱寫重量，例如【極致輕999克】、極致輕990g，抓得到就用
    m = re.search(r"(\d{3,4})\s*(?:克|g)(?![A-Za-z])", str(name))
    if m:
        grams = int(m.group(1))
        if 500 <= grams <= 4000:
            return grams
    return None


def search_keyword(row) -> str:
    # 用「品牌 + 型號」去電商搜尋最準；沒有型號就用商品名稱
    if row["model_code"]:
        return f"{row['brand']} {row['model_code']}"
    return short_name(row["name"])


# ============================================================
# 自動更新價格：資料超過一天，就叫爬蟲去原價屋抓一次
# ============================================================
TAIPEI = timezone(timedelta(hours=8))
REFRESH_AFTER = timedelta(hours=24)   # 資料多舊就要重抓
RETRY_COOLDOWN = 30 * 60              # 抓失敗後，30 分鐘內不再重試（秒）


def csv_scraped_at(path: str):
    # 從 CSV 的 scraped_at 欄位讀出「上次抓取時間」；舊版 CSV 沒有這欄就回傳 None
    try:
        first = pd.read_csv(path, usecols=["scraped_at"], nrows=1)
        text = str(first["scraped_at"].iloc[0])
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TAIPEI)
    except Exception:
        return None


@st.cache_resource
def refresh_state() -> dict:
    # 整個網站共用一份：同一時間只讓一個人觸發爬蟲，並記住上次失敗時間
    return {"lock": threading.Lock(), "last_fail": 0.0, "last_error": ""}


def refresh_laptops_if_stale():
    """資料太舊就自動更新。成功或不需要更新回傳 None，失敗回傳錯誤訊息。"""
    scraped_at = csv_scraped_at(LAPTOP_CSV) if os.path.exists(LAPTOP_CSV) else None
    if scraped_at and datetime.now(TAIPEI) - scraped_at < REFRESH_AFTER:
        return None

    state = refresh_state()
    if time.time() - state["last_fail"] < RETRY_COOLDOWN:
        return state["last_error"]

    if not state["lock"].acquire(blocking=False):
        return None  # 別人正在更新，這次先用舊資料

    try:
        import coolpc_laptop_scraper as scraper
        with st.spinner("📡 正在從原價屋抓今天的最新價格，大約 5～10 秒…"):
            scraper.update_csv(LAPTOP_CSV)
        return None
    except Exception as e:
        state["last_fail"] = time.time()
        state["last_error"] = str(e)[:120]
        return state["last_error"]
    finally:
        state["lock"].release()


@st.cache_data(ttl=600)
def load_laptops(path: str, file_mtime: float) -> pd.DataFrame:
    # file_mtime 只是用來讓 CSV 更新後，快取自動失效重新讀取
    df = pd.read_csv(path)
    df["gpu"] = df["gpu"].fillna("內建顯示")
    df["gpu_level"] = df["gpu"].apply(gpu_level)
    df["ram_gb"] = pd.to_numeric(df["ram_gb"], errors="coerce").fillna(0).astype(int)
    df["screen_inch"] = pd.to_numeric(df["screen_inch"], errors="coerce").fillna(15.6)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"])
    df["price"] = df["price"].astype(int)
    df["model_code"] = df["model_code"].fillna("").astype(str)
    df["storage"] = df["storage"].fillna("").astype(str)
    df["condition"] = df["condition"].fillna("新品")
    df["weight_g"] = df["name"].apply(weight_grams)
    return df


def score_laptop(row, budget, usage_idx, weight_idx, battery_idx, noise_idx) -> float:
    g = row["gpu_level"]
    ram = row["ram_gb"]
    screen = row["screen_inch"]

    # 越接近預算上限，通常代表規格越好
    s = 2.0 * row["price"] / budget

    # 用途
    if usage_idx in (2, 3, 4):
        s += 0.6 * g
    elif usage_idx == 1:
        s += 0.3 * min(g, 3)
    elif usage_idx == 0 and g == 0:
        s += 1

    # 記憶體
    if ram <= 8:
        s -= 3
    elif ram >= 32:
        s += 1.5 if usage_idx in (1, 3, 4) else 0.5
    else:
        s += 1

    # 重量（原價屋大多沒寫重量，用「有沒有獨顯 + 螢幕尺寸」估計；名稱有寫克數就直接用）
    grams = row["weight_g"]
    if weight_idx == 0 and pd.notna(grams):
        s += 3.5 if grams <= 1300 else -1
    elif weight_idx == 0:
        if g == 0 and screen <= 14.5:
            s += 3
        elif g == 0:
            s += 1.5
        elif g >= 3:
            s -= 3
        else:
            s -= 1
    elif weight_idx == 1:
        if screen >= 17:
            s -= 1.5
        if g >= 5:
            s -= 1

    # 續航（獨顯越強，通常越耗電）
    if battery_idx == 0:
        if g == 0:
            s += 2
        elif g >= 3:
            s -= 2
        else:
            s -= 0.5

    # 噪音（獨顯越強，風扇通常越大聲）
    if noise_idx == 0:
        if g == 0:
            s += 1.5
        elif g >= 4:
            s -= 2
        else:
            s -= 0.5
    elif noise_idx == 2:
        s += 0.3 * g

    if row["condition"] != "新品":
        s -= 0.5

    return s


def pick_laptops(df, budget, usage_idx, weight_idx, battery_idx, noise_idx, include_used):
    notes = []
    pool = df[df["price"] <= budget]
    if not include_used:
        pool = pool[pool["condition"] == "新品"]
    if pool.empty:
        return pool, notes

    need = USAGE_MIN_GPU[usage_idx]
    matched = pool[pool["gpu_level"] >= need]

    if matched.empty and need > 0:
        relaxed = max(need - 1, 0)
        matched = pool[pool["gpu_level"] >= relaxed]
        if not matched.empty:
            notes.append("這個預算內沒有完全符合用途的顯卡，先幫你放寬一級。想要更穩的體驗，建議把預算往上拉一點。")

    if matched.empty:
        matched = pool
        notes.append("這個預算內找不到適合這個用途的顯卡，下面先列出預算內最好的選擇，但跑重度工作會比較吃力。")

    scored = matched.copy()
    scored["score"] = scored.apply(
        lambda r: score_laptop(r, budget, usage_idx, weight_idx, battery_idx, noise_idx), axis=1
    )
    scored = scored.sort_values(["score", "price"], ascending=[False, True])

    # 同一個型號只留一台（原價屋有時同一台會用不同促銷方案列兩次）
    has_code = scored["model_code"] != ""
    scored = scored[~(has_code & scored.duplicated("model_code"))]
    return scored, notes


def pick_budget_saver(results, usage_idx, weight_idx):
    # 從前 3 名以外，找一台「規格一樣夠用、但便宜很多」的省錢選擇
    if len(results) <= 3:
        return None
    top_price = results.iloc[0]["price"]
    rest = results.iloc[3:]
    rest = rest[
        (rest["ram_gb"] >= 16)
        & (rest["condition"] == "新品")
        & (rest["gpu_level"] >= USAGE_MIN_GPU[usage_idx])
        & (rest["price"] <= top_price - 3000)
    ]
    if weight_idx == 0:
        rest = rest[rest["gpu_level"] <= 1]
    if rest.empty:
        return None
    return rest.sort_values("price").iloc[0]


def card_warnings(row, weight_idx) -> list:
    tips = []
    if row["ram_gb"] <= 8:
        tips.append("⚠️ 只有 8GB 記憶體：開十幾個網頁就可能卡頓，買之前先確認能不能自己加裝。")
    if row["condition"] == "展示品":
        tips.append("ℹ️ 展示品：在門市擺過，比較便宜，但保固可能跟新品不同，下單前先問清楚。")
    if row["condition"] == "維修品":
        tips.append("ℹ️ 維修品：修理過再賣的機器，價格最低但風險較高，保固務必問清楚。")
    if weight_idx == 0 and row["gpu_level"] >= 3:
        tips.append("⚠️ 這台有中高階獨顯，通常偏重、續航短，跟你選的「極致輕薄」不太搭。")
    return tips


def show_laptop_card(row, weight_idx):
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
        keyword = search_keyword(row)
        with col_b1:
            st.link_button("🏬 原價屋", COOLPC_URL, use_container_width=True)
        with col_b2:
            st.link_button("🔍 蝦皮比價", get_shopee_url(keyword), use_container_width=True)
        with col_b3:
            st.link_button("📦 Momo 比價", get_momo_url(keyword), use_container_width=True)


def budget_tier(nb_budget: int, usage_idx: int):
    # 用途分兩大類：輕度（文書、寫程式）走「輕薄路線」，重度（3A、剪片、旗艦）走「效能路線」
    light_usage = usage_idx in (0, 1)

    if light_usage:
        if nb_budget < 18000:
            tier_name = "超平價入門文書區間"
            experience_desc = "**體感預期：** 開多個網頁、看影片和寫 Word 很順，但不適合打中重度遊戲。機身多為塑膠質感，電池續航約 4~5 小時。"
            plain_rules = [
                "**記憶體千萬別買 8GB 焊死款**：開十幾個 Chrome 網頁就會卡頓，務必選 16GB 或能自己加裝記憶體的款式。",
                "**避開 TN 泛白螢幕**：挑選標示『IPS 面板』的款式，視角斜看才不會發灰反白傷眼睛。",
                "**處理器底線**：認準 Intel Core 3 / i3-12代以上，或 AMD Ryzen 5 (7000 系列以上)，更老的古董庫存機千萬別碰。",
            ]
        elif nb_budget < 32000:
            tier_name = "高 CP 值大學生主流區間（輕薄長續航）"
            experience_desc = "**體感預期：** 每天帶出門上課負擔小，續航可達 6~8 小時。寫程式、跑統計資料很輕鬆；打 LOL、瓦羅蘭也順，但不適合 3A 大作。"
            plain_rules = [
                "**挑 100% sRGB 色域螢幕**：顏色準確看久不累，避開平價機常偷料的 45% NTSC 偏色面板。",
                "**充電方便性**：一定要有『Type-C PD 充電』，出門只要帶一顆小豆腐頭手機筆電一起充，不用扛厚重原廠充電器。",
                "**寫程式/大數據建議**：記憶體直上 16GB～32GB，同時開很多程式和資料才不會卡。",
            ]
        elif nb_budget < 50000:
            tier_name = "高階輕薄筆電區間（金屬機身 / 好螢幕 / 一整天續航）"
            experience_desc = "**體感預期：** 全金屬機身、OLED 或高解析螢幕、重量約 1.2~1.5kg，不插電撐一整天的課沒問題。文書、寫程式非常順，偶爾打 LOL 也行。"
            plain_rules = [
                "**文書用途不用買獨顯**：多一張遊戲顯卡，機器會更重、更吵、更耗電，對上課記筆記完全沒幫助。",
                "**這個價位該要求好螢幕**：OLED 或 2.5K 以上解析度，看字更銳利；OLED 黑色很純，但長時間顯示固定畫面要注意烙印。",
                "**寫程式建議直上 32GB**：同時開 VS Code、瀏覽器、資料庫和 Docker 時，32GB 會順很多，而且輕薄機的記憶體多半焊死，買了就不能加。",
            ]
        else:
            tier_name = "頂級輕薄旗艦區間（商務 / 創作者等級）"
            experience_desc = "**體感預期：** 做工、螢幕、重量都是最頂級，很多機種不到 1.2kg。但老實說，文書和寫程式 4 萬左右就很夠用，多花的錢買的是質感與便利，不是速度。"
            plain_rules = [
                "**先想清楚錢花在哪**：預算拉到這麼高，多出來的錢主要換到更輕、更好的螢幕和更長保固，不會讓 Word 跑更快。",
                "**注意保固與到府維修**：高價機壞了修很貴，優先選有原廠到府收送或延長保固的品牌。",
                "**考慮換用途**：如果其實想偶爾玩遊戲或跑 AI，可以把用途改成「3A 遊戲」看看，同預算能買到有獨顯的機種。",
            ]
    else:
        if nb_budget < 32000:
            tier_name = "入門獨顯區間（預算偏緊）"
            experience_desc = "**體感預期：** 這個預算大多只能買到 RTX 3050 / 4050 等級的入門顯卡，3A 大作要開低特效才順。如果能再多存一點，體驗會差很多。"
            plain_rules = [
                "**記憶體至少 16GB**：遊戲加上 Discord、瀏覽器一起開，8GB 一定不夠。",
                "**看清楚顯卡型號**：同樣叫「電競筆電」，RTX 3050 和 RTX 5060 的效能差了一大截，別被外觀騙了。",
                "**建議再多存一點**：預算拉到 4 萬左右，就能買到 RTX 5060，是目前 3A 遊戲最划算的起點。",
            ]
        elif nb_budget < 50000:
            tier_name = "甜品級電競與算力遊戲本（暢玩 3A / 剪片渲染）"
            experience_desc = "**體感預期：** 玩黑神話、電馭叛客等大作在 1080p～2K 解析度下很流暢。但重量通常在 2kg 以上，高負載時風扇聲明顯，打遊戲必須插充電器。"
            plain_rules = [
                "**顯卡認準『滿血 RTX 5060』**：同一張顯卡，廠商給的電力（瓦數）不同，效能可以差到兩三成。規格表上寫 115W 以上的才算給足。",
                "**散熱不燙手重點**：注意鍵盤 WASD 區是否有避開內部發熱核心，玩兩小時鍵盤才不會變成鐵板燒。",
                "**預留升級孔**：優先選擇有『雙 M.2 硬碟槽』的機器，遊戲檔案現在動輒 100GB，之後才能自己買第二條 SSD 加裝。",
            ]
        elif nb_budget < 85000:
            tier_name = "高階電競旗艦與專業工作站（RTX 5070 / 5070 Ti）"
            experience_desc = "**體感預期：** 2.5K 解析度下 3A 特效全開、光線追蹤無壓力；高階金屬機身做工。鍵盤表面隔熱好，風扇雖有聲音但音調低沉不尖銳刺耳。"
            plain_rules = [
                "**指名『大面積均熱板』散熱**：熱導管像幾根細水管在搬熱，均熱板則像一整片銅板把熱攤平，鍵盤比較不燙，風扇也不用狂轉。",
                "**螢幕規格要到位**：都花到這預算，螢幕應該要 2.5K 240Hz 或 Mini-LED 面板，亮度要達 500 尼特以上。",
                "**供電規格**：確認原廠充電器有 240W 以上，高負載時才不會發生『一邊插電一邊掉電』的窘境。",
            ]
        else:
            tier_name = "神級旗艦電競與頂級算力怪獸（RTX 5080 / 5090 頂配級距）"
            experience_desc = "**體感預期：** 目前筆電界的天花板！4K 高畫質順跑大作、本地跑大型 AI 模型與 3D 渲染都很有餘裕。重量通常很沉，是真正的移動桌機。"
            plain_rules = [
                "**直上頂規旗艦顯卡**：鎖定 RTX 5080 或 RTX 5090，顯示記憶體越大，本地跑 AI 模型越不會卡在『裝不下』。",
                "**均熱板 + 液態金屬散熱**：旗艦晶片發熱極高，傳統散熱壓不住，必須配備高階均熱板與多風扇才能維持效能不降速。",
                "**螢幕直上 Mini-LED 或 OLED**：黑色夠純、亮度夠高，看起來跟一般筆電是不同等級。",
            ]
    return tier_name, experience_desc, plain_rules


# ============================================================
# 頁面：首頁二選一
# ============================================================
current_type = st.query_params.get("type", None)

# ============================================================
# 全站樣式：放大按鈕、做出整張可點的大卡片
# ============================================================
st.markdown("""
<style>
/* 首頁兩張大卡片 */
.choice-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 28px;
    margin-top: 12px;
}
.choice-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 58vh;
    padding: 36px 34px 30px 34px;
    border: 2px solid rgba(255, 255, 255, 0.12);
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.03);
    text-decoration: none !important;
    color: inherit !important;
    transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.choice-card:hover {
    transform: translateY(-4px);
    border-color: #ff4b4b;
    background: rgba(255, 75, 75, 0.08);
}
.choice-icon { font-size: 76px; line-height: 1; }
.choice-title { font-size: 38px; font-weight: 800; margin: 18px 0 14px 0; }
.choice-text { font-size: 18px; line-height: 1.9; color: #bbb; }
.choice-cta {
    margin-top: 26px;
    padding: 20px 0;
    border-radius: 14px;
    background: #ff4b4b;
    color: #fff;
    font-size: 24px;
    font-weight: 700;
    text-align: center;
}
@media (max-width: 768px) {
    .choice-grid { grid-template-columns: 1fr; }
    .choice-card { min-height: auto; }
}

/* 內頁的「回上一頁」連結 */
.back-link {
    display: inline-block;
    padding: 12px 22px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 10px;
    text-decoration: none !important;
    color: inherit !important;
    font-size: 17px;
}
.back-link:hover { border-color: #ff4b4b; }

/* 所有 Streamlit 主要按鈕（生成推薦）放大 */
div.stButton > button[kind="primary"] {
    min-height: 64px;
    border-radius: 14px;
}
div.stButton > button[kind="primary"] p {
    font-size: 22px;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# 頁面：首頁二選一
# 用真正的網頁連結（target="_self"）換頁，瀏覽器的 ← 返回才會有作用
# ============================================================
if current_type not in ["PC", "Laptop"]:
    st.markdown("<h1 style='text-align: center; margin-top: 10px;'>請問您這次想配置哪種設備？</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888; font-size: 18px;'>不用懂複雜參數，點選後將為您客製化配置與防呆避坑指南。</p>", unsafe_allow_html=True)

    st.markdown("""
<div class="choice-grid">
  <a class="choice-card" href="?type=PC" target="_self">
    <div>
      <div class="choice-icon">🖥️</div>
      <div class="choice-title">自組桌機 (PC)</div>
      <div class="choice-text">
        <b>優點：</b>同預算效能最高、散熱安靜、零組件未來可自由更換升級。<br>
        <b>缺點：</b>體積大佔空間、無法攜帶外出、需自備外接螢幕與鍵鼠。
      </div>
    </div>
    <div class="choice-cta">👉 進入【自組桌機】規劃</div>
  </a>
  <a class="choice-card" href="?type=Laptop" target="_self">
    <div>
      <div class="choice-icon">💻</div>
      <div class="choice-title">筆記型電腦 (Laptop)</div>
      <div class="choice-text">
        <b>優點：</b>拔掉插頭揹著就走、自帶螢幕鍵盤、外宿租屋極省空間。<br>
        <b>缺點：</b>同價位效能打折、風扇較吵、核心硬體焊死無法未來升級。
      </div>
    </div>
    <div class="choice-cta">👉 進入【筆記型電腦】挑選</div>
  </a>
</div>
""", unsafe_allow_html=True)

# ============================================================
# 頁面：桌機 / 筆電
# ============================================================
else:
    col_back, col_title = st.columns([1.5, 8.5])
    with col_back:
        st.write("")
        st.markdown('<a class="back-link" href="./" target="_self">⬅️ 回首頁</a>', unsafe_allow_html=True)

    with col_title:
        device_label = "🖥️ 自組桌機 (PC)" if current_type == "PC" else "💻 筆記型電腦 (Laptop)"
        st.title(f"目前模式：{device_label}")

    st.divider()

    # ---------------- 桌機（尚未接資料） ----------------
    if current_type == "PC":
        st.subheader("1. 選擇您的預算與需求")
        c1, c2 = st.columns(2)
        with c1:
            budget = st.slider("預算上限 (NTD)：", min_value=15000, max_value=120000, value=35000, step=1000)
            appearance = st.selectbox("機殼外觀偏好：", ["高 CP 值黑色實用款 (無光害)", "海景房側透 / RGB 燈效", "緊湊小體積 (M-ATX)", "散熱效能優先"])
        with c2:
            usage = st.selectbox("主要使用目的：", [
                "高畫質大型單機遊戲 (如黑神話、電馭叛客、法環)",
                "競技類連線網遊 (如 Apex、特戰英豪、LOL)",
                "程式開發 / 大數據處理 / AI 本地運算",
                "影音剪輯 / 3D 渲染建模",
                "一般文書上網 / 看影片"
            ])

        if st.button("🚀 生成桌機最佳配置菜單", type="primary", use_container_width=True):
            st.info("桌機配單功能開發中，之後會改成讀原價屋即時零件價格。")

    # ---------------- 筆電（讀原價屋 CSV） ----------------
    else:
        refresh_error = refresh_laptops_if_stale()

        if not os.path.exists(LAPTOP_CSV):
            st.error(
                "還沒有筆電資料，自動抓取也失敗了。"
                f"（原因：{refresh_error}）請稍後再重新整理一次。"
            )
            st.stop()

        file_mtime = os.path.getmtime(LAPTOP_CSV)
        laptops_df = load_laptops(LAPTOP_CSV, file_mtime)
        scraped_at = csv_scraped_at(LAPTOP_CSV)
        updated_text = scraped_at.strftime("%Y/%m/%d %H:%M") if scraped_at else "不明"

        st.caption(f"📡 價格來源：原價屋線上估價單，共 {len(laptops_df)} 台筆電，最後更新 {updated_text}")
        if refresh_error:
            st.caption(f"⚠️ 今天自動更新價格失敗，目前顯示的是上次抓到的價格。（{refresh_error}）")

        # 第一次打開（或重新整理）時，從網址讀回上次的選項
        init_state("nb_budget", qp_int("budget", 35000, BUDGET_MIN, BUDGET_MAX))
        init_state("nb_usage", USAGE_OPTIONS[qp_int("u", 0, 0, len(USAGE_OPTIONS) - 1)])
        init_state("weight_pref", WEIGHT_OPTIONS[qp_int("w", 0, 0, len(WEIGHT_OPTIONS) - 1)])
        init_state("battery_pref", BATTERY_OPTIONS[qp_int("b", 0, 0, len(BATTERY_OPTIONS) - 1)])
        init_state("noise_pref", NOISE_OPTIONS[qp_int("n", 0, 0, len(NOISE_OPTIONS) - 1)])
        init_state("include_used", st.query_params.get("used", "0") == "1")

        st.subheader("1. 設定您的使用習慣與生活場景")
        nb_budget = st.slider("💰 您的筆電總預算 (NTD)：", min_value=BUDGET_MIN, max_value=BUDGET_MAX, step=1000, format="$%d 元", key="nb_budget")

        col_req1, col_req2 = st.columns(2)
        with col_req1:
            nb_usage = st.selectbox("🎯 主要做什麼事：", USAGE_OPTIONS, key="nb_usage")
            weight_pref = st.selectbox("🎒 重量負擔接受度：", WEIGHT_OPTIONS, key="weight_pref")
        with col_req2:
            battery_pref = st.selectbox("🔋 不插電續航需求：", BATTERY_OPTIONS, key="battery_pref")
            noise_temp_pref = st.selectbox("❄️ 噪音與散熱體感要求：", NOISE_OPTIONS, key="noise_pref")

        include_used = st.checkbox("也顯示展示品／維修品（比較便宜，但保固可能不同）", key="include_used")

        usage_idx = USAGE_OPTIONS.index(nb_usage)
        weight_idx = WEIGHT_OPTIONS.index(weight_pref)
        battery_idx = BATTERY_OPTIONS.index(battery_pref)
        noise_idx = NOISE_OPTIONS.index(noise_temp_pref)

        init_state("show_result", st.query_params.get("go") == "1")

        clicked = st.button("🚀 生成客製化筆電選購指南與推薦", type="primary", use_container_width=True)
        if clicked:
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

                top = results.head(3)
                for _, row in top.iterrows():
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
