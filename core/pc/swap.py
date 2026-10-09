"""「換一個」：讓使用者自己換掉菜單裡的某個零件（例如換一張比較好看的顯卡）。

alternatives() 找出「換上去之後整台還是相容」的替代品，挑幾個不同價位的給使用者選；
apply_swaps() 把使用者換過的零件套回菜單，並重新檢查相容性。

只能放純 Python，不准 import streamlit。
"""
import pandas as pd

from core.pc.compatibility import check_build

# 每一類零件，先用最基本的條件縮小範圍，再逐一做完整相容性檢查
SWAPPABLE = ["gpu", "cooler", "case", "motherboard", "ram", "ssd", "psu", "cpu"]


def _prefilter(parts: pd.DataFrame, build: dict, category: str) -> pd.DataFrame:
    pool = parts[parts["category"] == category]
    current = build.get(category)
    if category == "cpu":
        pool = pool[pool["socket"] == build["motherboard"]["socket"]]
    elif category == "motherboard":
        pool = pool[(pool["socket"] == build["cpu"]["socket"]) & (pool["ddr"] == build["ram"]["ddr"])]
    elif category == "ram":
        pool = pool[(pool["ddr"] == build["motherboard"]["ddr"]) & (pool["ram_sticks"] == 2)]
    elif category == "gpu":
        pool = pool.dropna(subset=["gpu_score"])
    elif category == "cooler":
        pool = pool[~pool["cooler_low_profile"] | (build["case"]["case_cpu_max_cm"] < 14)]
    elif category == "ssd":
        pool = pool[pool["ssd_interface"].isin(["Gen3", "Gen4", "Gen5"])]
    if current is not None and "coolpc_gid" in pool:
        pool = pool[pool["coolpc_gid"] != current["coolpc_gid"]]
    return pool


def alternatives(parts: pd.DataFrame, build: dict, category: str, count: int = 6, color: str = "") -> list:
    """回傳最多 count 個相容的替代品（由便宜到貴），價位盡量分散；想要某個顏色就優先放同顏色的。

    同一類零件，CPU、顯卡會優先列「同等級」的不同品牌款式，避免換了之後效能落差太大。
    """
    current = build.get(category)
    pool = _prefilter(parts, build, category)
    if category == "gpu" and current is not None:
        pool = pool[(pool["gpu_chip"] == current["gpu_chip"]) | (pool["gpu_score"].between(current["gpu_score"] * 0.85, current["gpu_score"] * 1.3))]
    if category == "cpu" and current is not None:
        pool = pool[pool["cpu_game"].between(current["cpu_game"] * 0.85, current["cpu_game"] * 1.25)]

    ok = []
    for _, item in pool.sort_values("price").iterrows():
        trial = dict(build)
        trial[category] = item
        problems, _ = check_build(trial)
        if not problems:
            ok.append(item)
        if len(ok) >= 80:
            break
    if not ok:
        return []

    if color:
        same = [x for x in ok if x["color"] == color]
        others = [x for x in ok if x["color"] != color]
        ok = same + others

    # 從整個價格範圍平均抽樣，讓使用者看到便宜、中間、貴的選擇
    if len(ok) <= count:
        picked = ok
    else:
        by_price = sorted(ok, key=lambda x: x["price"])
        step = (len(by_price) - 1) / (count - 1)
        picked = [by_price[round(i * step)] for i in range(count)]
        if color:
            colored = [x for x in ok if x["color"] == color][: count // 2]
            picked = colored + [x for x in picked if x["coolpc_gid"] not in {c["coolpc_gid"] for c in colored}]
            picked = picked[:count]
    return sorted(picked, key=lambda x: x["price"])


# ============================================================
# 挑機殼（圖片牆）
# ============================================================
CASE_LIGHT_PATTERN = r"RGB|燈"


def case_gallery(parts: pd.DataFrame, build: dict, budget: int, color: str = "", rgb=None,
                 count: int = 9, page: int = 0):
    """列出「放得下這台電腦」的機殼給使用者看圖挑。回傳 (這一頁的機殼清單, 符合條件的總數)。

    build 是先用預設機殼配好的菜單，拿它的主機板尺寸、顯卡長度、散熱器高度來檢查放不放得下。
    價格從便宜到貴平均抽樣；page 加 1 就換一批不同的機殼（價位分布一樣）。
    """
    cases = parts[parts["category"] == "case"]
    floor = 1190 if budget >= 25000 else 790
    ceiling = max(2500, budget * 0.07)
    cases = cases[cases["price"].between(floor, ceiling)]
    if color:
        cases = cases[cases["color"] == color]
    if rgb is True:
        cases = cases[cases["name"].str.contains(CASE_LIGHT_PATTERN, case=False, regex=True)]
    elif rgb is False:
        cases = cases[~cases["name"].str.contains(CASE_LIGHT_PATTERN, case=False, regex=True)]

    ok = []
    for _, case in cases.sort_values("price").iterrows():
        trial = dict(build)
        trial["case"] = case
        if not check_build(trial)[0]:
            ok.append(case)
    if len(ok) <= count:
        return ok, len(ok)

    # 分成 count 個價位區間，每一區拿一個；換一批就拿每一區的下一個
    picked = []
    for i in range(count):
        bucket = ok[len(ok) * i // count: len(ok) * (i + 1) // count]
        picked.append(bucket[page % len(bucket)])
    return picked, len(ok)


def apply_swaps(parts: pd.DataFrame, build_parts: dict, swaps: dict):
    """swaps 是 {類別: 原價屋商品編號}。回傳 (新的零件 dict, 套用失敗的類別清單)。

    商品下架（今天的資料裡找不到那個編號）時，保留原本的零件。
    """
    result = dict(build_parts)
    missing = []
    for category, gid in swaps.items():
        if category not in result or not gid:
            continue
        found = parts[(parts["category"] == category) & (parts["coolpc_gid"] == gid)]
        if found.empty:
            missing.append(category)
            continue
        result[category] = found.iloc[0]
    return result, missing


def total_price(build_parts: dict) -> int:
    return int(sum(p["price"] for p in build_parts.values() if p is not None))


def recheck(build_parts: dict):
    core = {k: v for k, v in build_parts.items() if k not in ("hdd", "os")}
    return check_build(core)
