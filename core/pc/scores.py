"""CPU / 顯卡的效能分數、顯卡耗電。用來比較「同樣的錢，哪個組合比較強」。

⚠️ 這些分數是依公開評測整理的「大概相對值」，不是精確跑分，只用來排序和避免失衡的搭配。
之後加入真實跑分資料（例如 UL Benchmark）時，替換這個檔案就好。

只能放純 Python，不准 import streamlit。
"""
import re

# ------------------------------------------------------------
# 顯卡：RTX 5070 = 100 當基準（1440p 遊戲效能的大概比例）
# key 是 (晶片, 顯示記憶體GB)；顯示記憶體填 None 代表不分版本
# ------------------------------------------------------------
GPU_TABLE = {
    # 晶片          VRAM: (效能分數, 整卡耗電W)
    ("RTX3050", 6): (28, 70),
    ("RTX3050", 8): (33, 130),
    ("RTX3060", None): (45, 170),
    ("RTX5050", None): (52, 130),
    ("RX7650GRE", None): (55, 165),
    ("RTX5060", None): (62, 145),
    ("RX9060XT", 8): (66, 160),
    ("RX9060XT", 16): (68, 160),
    ("RTX5060Ti", 8): (72, 180),
    ("RTX5060Ti", 16): (74, 180),
    ("RX9070GRE", None): (88, 220),
    ("RTX5070", None): (100, 250),
    ("RX9070", None): (110, 220),
    ("RX9070XT", None): (122, 304),
    ("RTX5070Ti", None): (125, 300),
    ("RTX5080", None): (145, 360),
    ("RTX5090", None): (200, 575),
}


def gpu_score_and_power(chip: str, vram):
    """回傳 (效能分數, 耗電W)；表上查不到回傳 (None, None)。"""
    chip = str(chip)
    try:
        vram = int(vram)
    except (TypeError, ValueError):
        vram = None
    if (chip, vram) in GPU_TABLE:
        return GPU_TABLE[(chip, vram)]
    if (chip, None) in GPU_TABLE:
        return GPU_TABLE[(chip, None)]
    return None, None


# ------------------------------------------------------------
# CPU：(遊戲分數, 多核心分數)，Ryzen 7 9800X3D 遊戲 = 100、Ryzen 9 9950X 多核心 = 100
# 規則由上往下比對，越特殊的型號要放越前面（例如 9800X3D 要在 9800 前面）
# ------------------------------------------------------------
CPU_TABLE = [
    (r"9950X3D2", 102, 108),
    (r"9950X3D", 100, 105),
    (r"9900X3D", 98, 92),
    (r"9850X3D", 102, 77),
    (r"9800X3D", 100, 75),
    (r"7800X3D", 92, 66),
    (r"5800X3D", 75, 55),
    (r"9950X", 84, 100),
    (r"9900X", 82, 90),
    (r"9700X", 80, 72),
    (r"9600X", 76, 60),
    (r"8600G", 62, 52),
    (r"8500G", 55, 45),
    (r"8400F", 60, 50),
    (r"R7 7700", 74, 68),
    (r"7500F", 70, 55),
    (r"5600X", 60, 42),
    (r"3400G", 35, 25),
    (r"Ultra 9 285K", 84, 100),
    (r"Ultra 7 270K", 82, 95),
    (r"Ultra 7 265K", 80, 90),
    (r"Ultra 5 250K", 76, 78),
    (r"Ultra 5 245K", 74, 70),
    (r"Ultra 5 225", 66, 55),
    (r"i7-14700", 80, 85),
    (r"i5-14400", 68, 58),
    (r"i5-12400", 62, 45),
    (r"i3-14100", 55, 30),
]


def cpu_power_w(model: str, socket: str, tdp, cores) -> int:
    """CPU 實際滿載時大概會吃多少瓦。

    原價屋寫的瓦數是「官方標示 TDP」，Intel 的 65W 款滿載其實會衝到 150～220W，
    挑散熱器和電源要看這個實際值，不然會買太小。
    """
    try:
        tdp = float(tdp)
    except (TypeError, ValueError):
        tdp = 65.0
    try:
        cores = int(cores)
    except (TypeError, ValueError):
        cores = 6
    model = str(model)
    if str(socket).startswith("LGA"):
        if re.search(r"\d{3}K", model):  # 例如 265K、14700K
            return 250
        if cores <= 6:
            return 117
        if cores <= 10:
            return 150
        return 220
    return int(round(tdp * 1.35))  # AMD 滿載功耗大約是 TDP 的 1.35 倍（PPT）


def igpu_score(model: str) -> int:
    """內顯的大概遊戲分數（跟顯卡表同一把尺）。G 結尾的 AMD CPU 內顯特別強。"""
    model = str(model)
    if re.search(r"8600G|8700G", model):
        return 22
    if re.search(r"8500G", model):
        return 18
    if re.search(r"\d{4}G\b", model):
        return 12
    return 8


def cpu_scores(model: str, cores=None):
    """回傳 (遊戲分數, 多核心分數)。表上沒有的型號，用核心數粗估。"""
    for pattern, game, multi in CPU_TABLE:
        if re.search(pattern, str(model), re.I):
            return game, multi
    try:
        cores = int(cores)
    except (TypeError, ValueError):
        cores = 6
    return 50 + cores * 2, cores * 5
