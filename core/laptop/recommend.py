"""筆電推薦的核心邏輯：整理資料、依需求算分、挑出推薦與省錢選擇、產生避坑警告。

只能放純 Python，不准 import streamlit（之後 Django 版直接拿去用）。
各個 *_idx 參數代表使用者在問卷選了「第幾個選項」，順序見 core/config.py。
"""
import pandas as pd

from core.config import USAGE_MIN_GPU
from core.text_utils import gpu_level, weight_grams


def prepare_laptops(df: pd.DataFrame) -> pd.DataFrame:
    """把從 CSV 讀進來的原始資料整理成推薦用的格式（補空值、轉數字、算顯卡等級和重量）。"""
    df = df.copy()
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
    """幫一台筆電打分數，分數越高越符合使用者的需求。"""
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
    """回傳 (排序好的推薦清單, 給使用者看的提醒文字清單)。"""
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
    """從前 3 名以外，找一台「規格一樣夠用、但便宜很多」的省錢選擇；找不到回傳 None。"""
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
    """這台筆電要提醒使用者注意的地方（8GB、展示品、輕薄卻有大顯卡…）。"""
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
