"""自動配單：照使用者的需求（Prefs），從原價屋的零件裡挑出「保證相容、而且同預算最強」的一台。

做法（白話）：
1. 把每一種 CPU、每一種顯卡、每一種記憶體容量都試著組組看
2. 每一種組合，自動補上「最便宜又相容、品質過得去」的主機板、記憶體、硬碟、散熱器、電源、機殼
3. 超過預算的丟掉，剩下的依用途打分數，挑分數最高的
4. 「能省則省」模式：便宜很多、分數只差 3% 以內的，選便宜的
   「用好料」模式：選最強的，再把剩下的錢拿去升級 SSD、主機板、記憶體、電源、散熱器

遊戲的分數用「CPU 和顯卡取比較弱的那個」來算，所以不會配出「超強顯卡配弱 CPU」這種浪費錢的組合。

只能放純 Python，不准 import streamlit。
"""
import re
from dataclasses import dataclass, field

import pandas as pd

from core.pc.compatibility import (
    ENTRY_CHIPSETS,
    FORM_ORDER,
    check_build,
    cooler_strong_enough,
    cpu_power,
    fits_cooler_case,
    fits_cooler_cpu,
    fits_gpu_case,
    fits_psu_power,
    required_psu_w,
)
from core.pc.scores import cpu_scores, gpu_score_and_power, igpu_score

# 用途（順序跟 core/config.py 的 PC_USAGE_OPTIONS 一樣）
USAGE_3A, USAGE_ESPORTS, USAGE_DEV, USAGE_AI, USAGE_CREATOR, USAGE_OFFICE = range(6)
USAGE_DEV_AI = USAGE_DEV  # 舊名稱相容
GAME_USAGES = (USAGE_3A, USAGE_ESPORTS)
# 螢幕解析度（順序跟 PC_RESOLUTION_OPTIONS 一樣）
RES_1080, RES_2K, RES_4K, RES_UNKNOWN = range(4)
# 容量需求（順序跟 PC_STORAGE_OPTIONS 一樣）
STORAGE_NORMAL, STORAGE_GAMES, STORAGE_MEDIA = range(3)


@dataclass(frozen=True)
class Prefs:
    """使用者的需求。網頁問卷的答案會轉成這個。"""
    budget: int
    usages: tuple = (USAGE_3A,)
    resolution: int = RES_UNKNOWN
    need_wifi: bool = True       # 沒網路孔、或要藍牙，就要 Wi-Fi 主機板（藍牙跟 Wi-Fi 通常是同一張卡）
    premium: bool = False        # False＝能省則省；True＝用好料
    small: bool = False          # 小體積機殼（M-ATX / ITX）
    storage: int = STORAGE_NORMAL
    windows: bool = False        # 要不要一起買 Windows
    case_gid: str = ""           # 使用者在圖片裡挑好的機殼（原價屋商品編號）
    color: str = ""              # "黑"、"白"，或 "" 不限；挑好機殼後會帶入機殼的顏色
    rgb: object = None           # True 要燈、False 不要燈、None 不限（只在「幫我選機殼」時用）


# 每種用途要試的記憶體容量（GB），以及容量帶來的加分
RAM_OPTIONS = {
    USAGE_3A: {16: 0, 32: 4},
    USAGE_ESPORTS: {16: 0, 32: 3},
    USAGE_DEV: {16: 0, 32: 12, 64: 20},
    USAGE_AI: {16: 0, 32: 8, 64: 14},
    USAGE_CREATOR: {16: 0, 32: 12, 64: 20},
    USAGE_OFFICE: {16: 0},
}

# 遊戲時 CPU 最多能「撐住」多強的顯卡：分數 × 這個倍數
# 解析度越高越吃顯卡、越不吃 CPU；1080p 高幀數則很吃 CPU
CPU_CAP = {
    RES_1080: {USAGE_3A: 1.15, USAGE_ESPORTS: 0.95},
    RES_2K: {USAGE_3A: 1.4, USAGE_ESPORTS: 1.1},
    RES_4K: {USAGE_3A: 2.0, USAGE_ESPORTS: 1.4},
    RES_UNKNOWN: {USAGE_3A: 1.4, USAGE_ESPORTS: 1.1},
}

FLAGSHIP_BUDGET = 300000   # 用好料又給到這麼多預算＝要頂規：記憶體、SSD 不設上限，能多大就多大
GOOD_ENOUGH_RATIO = 0.97   # 能省則省：便宜的組合分數只要有最強的 97%，就選便宜的
MIN_CORES = 6              # 4 核心的 CPU 太舊了，不推薦
AM5_BONUS = 3              # AM5 之後還能直接換新 CPU，給一點加分
STRONG_CPU_POWER = 150     # CPU 滿載超過這個瓦數，就不配入門主機板
MIN_CASE_PRICE = 1190      # 太便宜的機殼通常做工差、散熱差、邊緣會割手
MIN_CASE_PRICE_TIGHT = 790  # 預算很緊時放寬
COLOR_PREMIUM = 1.15       # 想要白色系時，白色版只要貴 15% 以內就選白色

CHIPSET_RANK = {"X870": 6, "Z890": 6, "B850": 4, "Z790": 4, "B650": 3, "B860": 3, "B760": 3,
                "B550": 3, "B840": 1, "A620": 1, "H810": 1, "H610": 1, "A520": 1}
RATING_RANK = {"鈦金": 3, "白金": 3, "金牌": 2, "銅牌": 1}  # 鈦金比白金貴很多、省電差一點點，當成同一級
FORM_RANK = {"ATX": 3, "E-ATX": 3, "M-ATX": 2, "ITX": 1}
SSD_GEN_RANK = {"Gen5": 3, "Gen4": 2, "Gen3": 1, "SATA": 0}

PART_ORDER = ["cpu", "cooler", "motherboard", "ram", "gpu", "ssd", "hdd", "psu", "case", "os"]
CORE_PARTS = ["cpu", "cooler", "motherboard", "ram", "gpu", "ssd", "psu", "case"]
PART_LABELS = {
    "cpu": "處理器 CPU",
    "cooler": "CPU 散熱器",
    "motherboard": "主機板",
    "ram": "記憶體 RAM",
    "gpu": "顯示卡",
    "ssd": "固態硬碟 SSD",
    "hdd": "傳統硬碟 HDD",
    "psu": "電源供應器",
    "case": "機殼",
    "os": "作業系統",
}
PART_ROLES = {
    "cpu": "電腦的大腦，所有運算都靠它",
    "cooler": "幫 CPU 降溫，溫度低才不會降速、比較安靜",
    "motherboard": "電腦的骨架，把所有零件接在一起",
    "ram": "工作桌，同時開越多程式、分頁，越需要大",
    "gpu": "負責畫面，遊戲畫質和流暢度主要看它",
    "ssd": "主要的倉庫，放系統和遊戲；開機和讀取速度看它",
    "hdd": "便宜的大倉庫，放影片、照片這種很佔空間但不用很快的檔案",
    "psu": "幫全部零件供電；品質差的電源可能燒壞其他零件，不能省",
    "case": "外殼，決定外觀和散熱空間",
    "os": "Windows 正版授權",
}


# ============================================================
# 整理資料
# ============================================================
def _to_bool(series):
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def _color_from_name(name: str) -> str:
    return "白" if re.search(r"白|White|WHITE|ICE|冰魄|雪", str(name)) else "黑"


def prepare_parts(df: pd.DataFrame) -> pd.DataFrame:
    """把 CSV 讀進來的字串轉成正確型別，並補上效能分數、實際耗電、顏色。"""
    df = df.copy().reset_index(drop=True)
    for col in ["price", "cores", "threads", "tdp_w", "ddr", "dimm_slots", "vrm_phases",
                "ram_total_gb", "ram_sticks", "ram_speed", "ram_cl", "capacity_gb", "vram_gb",
                "length_cm", "psu_w", "case_gpu_max_cm", "case_cpu_max_cm",
                "cooler_height_cm", "cooler_tdp_w"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["has_igpu", "cooler_included", "wifi", "psu_sfx", "psu_atx3",
                "case_sfx_only", "case_glass", "cooler_low_profile"]:
        if col in df:
            df[col] = _to_bool(df[col])
    for col in ["socket", "chipset", "form_factor", "gpu_chip", "ssd_interface", "nand",
                "psu_rating", "case_mb_max", "color", "cooler_sockets", "model", "name", "coolpc_gid"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    df = df.dropna(subset=["price"])
    missing_color = df["color"] == ""
    df.loc[missing_color, "color"] = df.loc[missing_color, "name"].map(_color_from_name)

    is_cpu = df["category"] == "cpu"
    is_gpu = df["category"] == "gpu"
    for col in ["cpu_game", "cpu_multi", "cpu_power", "igpu_score", "gpu_score", "gpu_power"]:
        df[col] = None
    df.loc[is_cpu, "cpu_game"] = [cpu_scores(m, c)[0] for m, c in zip(df.loc[is_cpu, "model"], df.loc[is_cpu, "cores"])]
    df.loc[is_cpu, "cpu_multi"] = [cpu_scores(m, c)[1] for m, c in zip(df.loc[is_cpu, "model"], df.loc[is_cpu, "cores"])]
    df.loc[is_cpu, "cpu_power"] = [cpu_power(r) for _, r in df[is_cpu].iterrows()]
    df.loc[is_cpu, "igpu_score"] = [igpu_score(m) for m in df.loc[is_cpu, "model"]]
    df.loc[is_gpu, "gpu_score"] = [gpu_score_and_power(c, v)[0] for c, v in zip(df.loc[is_gpu, "gpu_chip"], df.loc[is_gpu, "vram_gb"])]
    df.loc[is_gpu, "gpu_power"] = [gpu_score_and_power(c, v)[1] for c, v in zip(df.loc[is_gpu, "gpu_chip"], df.loc[is_gpu, "vram_gb"])]
    return df


def _part(df, category):
    return df[df["category"] == category]


def _is_big_tower(cooler) -> bool:
    """雙塔、或 6 根導管以上的塔扇，壓得住高耗電 CPU。"""
    name = str(cooler["name"])
    m = re.search(r"(\d+)\s*(?:導)?管", name)
    return "雙塔" in name or (m is not None and int(m.group(1)) >= 6)


def _cheapest_per(df, keys, color=""):
    """每一組 keys 留一個最便宜的；想要白色系的話，白色版貴 15% 以內就留白色版。"""
    df = df.sort_values("price")
    picked = []
    for _, group in df.groupby(keys, sort=False, dropna=False):
        group = group.sort_values("price")
        choice = group.iloc[0]
        if color:
            same = group[(group["color"] == color) & (group["price"] <= choice["price"] * COLOR_PREMIUM)]
            if not same.empty:
                choice = same.iloc[0]
        picked.append(choice)
    return pd.DataFrame(picked) if picked else df.head(0)


def _first_ok(pool, ok, color=""):
    """從便宜到貴找第一個符合 ok() 的；想要某個顏色的話，同顏色貴 15% 以內就選同顏色。"""
    base = None
    for _, item in pool.iterrows():
        if base is not None and item["price"] > base["price"] * COLOR_PREMIUM:
            break
        if not ok(item):
            continue
        if base is None:
            base = item
            if not color or item["color"] == color:
                return item
        elif item["color"] == color:
            return item
    return base


# ============================================================
# 打分數
# ============================================================
def performance(usage, cpu, gpu, ram_gb, resolution=RES_UNKNOWN):
    g = gpu["gpu_score"] if gpu is not None else cpu["igpu_score"]
    cg, cm = cpu["cpu_game"], cpu["cpu_multi"]
    bonus = RAM_OPTIONS[usage].get(int(ram_gb), 0) + (AM5_BONUS if cpu["socket"] == "AM5" else 0)
    if usage in GAME_USAGES:
        # 遊戲：畫面流暢度取決於 CPU、顯卡比較弱的那個
        score = min(g, CPU_CAP[resolution][usage] * cg)
        if usage == USAGE_ESPORTS:
            score += 0.3 * cg  # 競技遊戲追求高幀數，CPU 強一點有感
        return score + bonus
    if usage == USAGE_DEV:
        return 0.7 * cm + 0.1 * g + bonus  # 寫程式、跑資料：多核心 CPU 和記憶體最重要
    if usage == USAGE_AI:
        # 在自己電腦跑 AI 模型：顯示卡的「顯示記憶體」決定跑得動多大的模型，NVIDIA（CUDA）支援最好
        if gpu is None:
            return 0.1 * cm + bonus
        vram = gpu["vram_gb"] or 0
        nvidia = str(gpu["gpu_chip"]).startswith("RTX")
        return (4.0 * vram + 0.4 * g) * (1.0 if nvidia else 0.5) + 0.15 * cm + bonus
    if usage == USAGE_CREATOR:
        return 0.5 * cm + 0.35 * g + bonus
    return 0.0  # 文書：夠用就好，挑最便宜的


def _main_usages(prefs):
    usages = tuple(u for u in prefs.usages if u != USAGE_OFFICE)
    return usages or (USAGE_OFFICE,)


def _ram_choices(prefs):
    """預算夠的話，記憶體不要配太小（記憶體不夠用時，再強的 CPU、顯卡都會卡）。"""
    usages = _main_usages(prefs)
    options = sorted({gb for u in usages for gb in RAM_OPTIONS[u]})
    floor = 16
    heavy = any(u in (USAGE_DEV, USAGE_AI, USAGE_CREATOR) for u in usages)
    gaming = any(u in GAME_USAGES for u in usages)
    if gaming and prefs.budget >= 50000:
        floor = 32
    if heavy:
        if prefs.budget >= 90000 or (prefs.premium and prefs.budget >= 60000):
            floor = 64
        elif prefs.budget >= 40000:
            floor = 32
    picked = [gb for gb in options if gb >= floor]
    return picked or options


def _ssd_target(prefs):
    if prefs.storage == STORAGE_GAMES:
        return 4000 if (prefs.premium and prefs.budget >= 80000) else 2000
    if prefs.budget < 25000:
        return 500
    if prefs.premium and prefs.budget >= 60000:
        return 2000
    return 1000


# ============================================================
# 配單器：把各零件的挑選規則和快取包在一起
# ============================================================
class _Builder:
    def __init__(self, parts, prefs, budget_core):
        self.parts = parts
        self.prefs = prefs
        self.budget = budget_core
        self.forms = {"ITX", "M-ATX"} if prefs.small else {"ITX", "M-ATX", "ATX"}
        self.case_pool = self._case_pool()
        self.coolers = _part(parts, "cooler").sort_values("price")
        self.psus = self._psu_pool()
        self.ssd = self._pick_ssd()
        self._platform_cache, self._case_cache, self._cooler_cache, self._psu_cache = {}, {}, {}, {}

    # ---------- 機殼 ----------
    def _case_pool(self):
        cases = _part(self.parts, "case")
        if self.prefs.case_gid:
            chosen = cases[cases["coolpc_gid"] == self.prefs.case_gid]
            if not chosen.empty:
                return chosen  # 使用者自己挑的機殼，直接用
        floor = MIN_CASE_PRICE if self.budget >= 25000 else MIN_CASE_PRICE_TIGHT
        if self.prefs.premium:
            floor = max(floor, min(3000, int(self.budget * 0.025)))
        cases = cases[cases["price"] >= floor]
        if self.prefs.small:
            cases = cases[cases["case_mb_max"].isin(["M-ATX", "ITX"])]
        elif self.prefs.premium:
            cases = cases[cases["case_mb_max"].isin(["ATX", "E-ATX"])]
        styled = cases
        if self.prefs.color:
            styled = styled[styled["color"] == self.prefs.color]
        if self.prefs.rgb is True:
            styled = styled[styled["name"].str.contains("RGB", case=False)]
        elif self.prefs.rgb is False:
            styled = styled[~styled["name"].str.contains(r"RGB|燈", case=False, regex=True)]
        return (styled if not styled.empty else cases).sort_values("price")

    def max_gpu_length(self):
        return self.case_pool["case_gpu_max_cm"].max() - 1

    def pick_case(self, mb, gpu):
        key = (mb["form_factor"], None if gpu is None else gpu.name)
        if key not in self._case_cache:
            found = None
            for _, case in self.case_pool.iterrows():
                if FORM_ORDER.get(mb["form_factor"], 9) > FORM_ORDER.get(case["case_mb_max"], 0):
                    continue
                if gpu is not None and not fits_gpu_case(gpu, case):
                    continue
                found = case
                break
            self._case_cache[key] = found
        return self._case_cache[key]

    # ---------- 主機板 + 記憶體 ----------
    def pick_platform(self, cpu, ram_gb):
        """主機板和記憶體一起挑：1700 腳位有 DDR4、DDR5 兩種板子，要比加起來的總價。"""
        strong = cpu["cpu_power"] >= STRONG_CPU_POWER
        key = (cpu["socket"], strong, ram_gb)
        if key in self._platform_cache:
            return self._platform_cache[key]

        mbs = _part(self.parts, "motherboard")
        forms = {"ATX"} if (self.prefs.premium and not self.prefs.small) else self.forms
        mbs = mbs[(mbs["socket"] == cpu["socket"]) & mbs["form_factor"].isin(forms)]
        if self.prefs.need_wifi:
            mbs = mbs[mbs["wifi"]]
        if strong:
            mbs = mbs[~mbs["chipset"].isin(ENTRY_CHIPSETS) & (mbs["vrm_phases"].fillna(0) >= 10)]

        rams = _part(self.parts, "ram")
        rams = rams[rams["ram_total_gb"] == ram_gb]
        best = None
        for ddr in sorted(mbs["ddr"].dropna().unique()):
            mb_options = mbs[mbs["ddr"] == ddr].sort_values("price")
            ram_options = rams[rams["ddr"] == ddr]
            min_speed = 5600 if ddr == 5 else 3200
            good = ram_options[(ram_options["ram_sticks"] == 2) & (ram_options["ram_speed"] >= min_speed)]
            if good.empty:
                good = ram_options[ram_options["ram_speed"] >= min_speed]
            if good.empty or mb_options.empty:
                continue
            mb = _first_ok(mb_options, lambda x: True, self.prefs.color)
            ram = _first_ok(good.sort_values("price"), lambda x: x["ram_sticks"] <= mb["dimm_slots"], self.prefs.color)
            if ram is None:
                continue
            cost = mb["price"] + ram["price"]
            if best is None or cost < best[2]:
                best = (mb, ram, cost)
        self._platform_cache[key] = best
        return best

    # ---------- 散熱器 ----------
    def pick_cooler(self, cpu, case):
        """回傳 (散熱器或 None, 是否可行)。CPU 有附風扇、耗電又不高，就不另外買。"""
        key = (cpu.name, case.name)
        if key in self._cooler_cache:
            return self._cooler_cache[key]
        if cpu["cooler_included"] and cpu["cpu_power"] <= 120 and not self.prefs.premium:
            result = (None, True)
        else:
            hot = cpu["cpu_power"] >= 150 or "X3D" in cpu["model"]

            def ok(cooler):
                if cooler["cooler_low_profile"] and cpu["cpu_power"] > 100:
                    return False  # 下吹式散熱器只適合低耗電 CPU
                if hot and not _is_big_tower(cooler):
                    return False  # 高耗電 CPU（或怕熱的 X3D）要配雙塔或 6 導管以上的散熱器
                return (fits_cooler_cpu(cooler, cpu) and fits_cooler_case(cooler, case)
                        and cooler_strong_enough(cooler, cpu, 1.1))

            found = _first_ok(self.coolers, ok, self.prefs.color)
            result = (found, found is not None)
        self._cooler_cache[key] = result
        return result

    # ---------- 電源 ----------
    def _psu_pool(self):
        psus = _part(self.parts, "psu").sort_values("price")
        ratings = ["金牌", "白金", "鈦金"] if self.budget >= 40000 else ["銅牌", "金牌", "白金", "鈦金"]
        return psus[psus["psu_rating"].isin(ratings)]

    def pick_psu(self, cpu, gpu, case):
        key = (required_psu_w(cpu, gpu), gpu is not None and gpu["gpu_power"] >= 250, bool(case["case_sfx_only"]))
        if key not in self._psu_cache:
            pool = self.psus[self.psus["psu_sfx"]] if case["case_sfx_only"] else self.psus
            self._psu_cache[key] = _first_ok(pool, lambda p: fits_psu_power(p, cpu, gpu), self.prefs.color)
        return self._psu_cache[key]

    # ---------- SSD ----------
    def _pick_ssd(self):
        ssds = _part(self.parts, "ssd")
        target = _ssd_target(self.prefs)
        for require_tlc in (True, False):
            pool = ssds[(ssds["capacity_gb"] >= target * 0.95) & ssds["ssd_interface"].isin(["Gen4", "Gen3"])]
            if require_tlc:
                pool = pool[pool["nand"] == "TLC"]
            if not pool.empty:
                return pool.sort_values("price").iloc[0]
        pool = ssds[ssds["capacity_gb"] >= target * 0.95]
        return pool.sort_values("price").iloc[0] if not pool.empty else None

    # ---------- 組一台 ----------
    def assemble(self, cpu, gpu, ram_gb):
        platform = self.pick_platform(cpu, ram_gb)
        if platform is None:
            return None
        mb, ram, _ = platform
        case = self.pick_case(mb, gpu)
        if case is None:
            return None
        cooler, ok = self.pick_cooler(cpu, case)
        if not ok:
            return None
        psu = self.pick_psu(cpu, gpu, case)
        if psu is None:
            return None
        return {"cpu": cpu, "cooler": cooler, "motherboard": mb, "ram": ram,
                "gpu": gpu, "ssd": self.ssd, "psu": psu, "case": case}


# ============================================================
# 「用好料」：把剩下的錢拿去升級
# ============================================================
def _is_flagship(prefs) -> bool:
    return prefs is not None and prefs.premium and prefs.budget >= FLAGSHIP_BUDGET


def _quality(category, item, psu_needed=0, prefs=None):
    """升級時比較「哪個比較好」。每一項都有上限，超過實際需要的規格不加分（不買用不到的東西）。

    頂規預算（_is_flagship）時，記憶體、SSD 容量不設上限。
    """
    if item is None:
        return (0, 0, 0)
    flagship = _is_flagship(prefs)
    if category == "ssd":
        return (min(item["capacity_gb"], 8000 if flagship else 4000), item["nand"] == "TLC", SSD_GEN_RANK.get(item["ssd_interface"], 0))
    if category == "motherboard":
        # 小體積機殼就不追求大板；一般機殼優先 ATX（插槽多、散熱好）
        form = 0 if (prefs is not None and prefs.small) else FORM_RANK.get(item["form_factor"], 1)
        return (CHIPSET_RANK.get(item["chipset"], 2), form, min(item["vrm_phases"] or 0, 20))
    if category == "ram":
        usages = _main_usages(prefs) if prefs is not None else ()
        heavy = any(u in (USAGE_DEV, USAGE_AI, USAGE_CREATOR) for u in usages)
        cap = (96 if prefs is not None and prefs.budget >= 150000 else 64) if heavy else 32
        if flagship:
            cap = 9999
        speed = item["ram_speed"] or 0
        return (min(item["ram_total_gb"], cap), min(speed, 6400), -(item["ram_cl"] or 99))
    if category == "psu":
        return (RATING_RANK.get(item["psu_rating"], 0), min(item["psu_w"], psu_needed + 200), not item["psu_sfx"])
    if category == "cooler":
        return (min(item["cooler_tdp_w"], 280), _is_big_tower(item), 0)
    return (0, 0, 0)


def _upgrade(parts, chosen, prefs, budget_core):
    """依序升級，每一步最多花剩下預算的 40%，升級後一定要通過相容性檢查。"""
    chosen = dict(chosen)
    usages = _main_usages(prefs)
    if any(u in (USAGE_DEV, USAGE_AI, USAGE_CREATOR) for u in usages):
        order = ["ram", "ssd", "motherboard", "psu", "cooler"]
    else:
        order = ["ssd", "ram", "motherboard", "psu", "cooler"]
    psu_needed = required_psu_w(chosen["cpu"], chosen["gpu"])
    upgraded = []
    # 每一步最多花剩下預算的幾成；頂規預算時放寬，才買得起 256GB 這種很貴的記憶體
    share = 0.75 if _is_flagship(prefs) else 0.4
    max_sticks = 4 if _is_flagship(prefs) else 2

    for category in order:
        left = budget_core - sum(p["price"] for p in chosen.values() if p is not None)
        if left < 800:
            break
        current = chosen[category]
        current_price = current["price"] if current is not None else 0
        current_q = _quality(category, current, psu_needed, prefs)
        pool = _part(parts, category)
        pool = pool[pool["price"] <= current_price + left * share]
        if category == "ram":
            pool = pool[(pool["ddr"] == chosen["ram"]["ddr"]) & pool["ram_sticks"].between(2, max_sticks)]
        if category == "motherboard":
            pool = pool[(pool["socket"] == chosen["cpu"]["socket"]) & (pool["ddr"] == chosen["ram"]["ddr"])]
            if prefs.need_wifi:
                pool = pool[pool["wifi"]]
        if category == "ssd":
            pool = pool[pool["ssd_interface"].isin(["Gen4", "Gen5"])]
        if category == "cooler":
            pool = pool[~pool["cooler_low_profile"]]

        best, best_key = None, None
        for _, item in pool.iterrows():
            q = _quality(category, item, psu_needed, prefs)
            if q <= current_q:
                continue
            trial = dict(chosen)
            trial[category] = item
            if check_build(trial)[0]:
                continue
            color_match = 1 if (prefs.color and item["color"] == prefs.color) else 0
            key = (q, color_match, -item["price"])
            if best_key is None or key > best_key:
                best, best_key = item, key
        if best is not None:
            chosen[category] = best
            upgraded.append(PART_LABELS[category])
    return chosen, upgraded


# ============================================================
# 主流程
# ============================================================
def _extras(parts, prefs):
    """預算以外要先扣掉的東西：Windows、傳統硬碟。"""
    extras = {"hdd": None, "os": None}
    if prefs.windows:
        os_pool = _part(parts, "os").sort_values("price")
        if not os_pool.empty:
            extras["os"] = os_pool.iloc[0]
    if prefs.storage == STORAGE_MEDIA:
        hdds = _part(parts, "hdd")
        hdds = hdds[hdds["capacity_gb"] >= 4000].sort_values("price")
        if not hdds.empty:
            extras["hdd"] = hdds.iloc[0]
    return extras


def make_build(parts: pd.DataFrame, prefs: Prefs):
    """配一台電腦。預算太緊配不出來時，會放寬條件（允許 4 核心 CPU）再試一次。

    回傳 dict：{"parts": {類別: 零件或 None}, "total": 總價, "problems": [...], "notes": [...],
               "tips": [...], "upgraded": [...], "psu_needed_w": 數字}
    找不到任何組合時回傳 None。
    """
    result = _make_build(parts, prefs, MIN_CORES)
    if result is None:
        result = _make_build(parts, prefs, 4)
        if result is not None:
            result["tips"].insert(0, "預算很緊，這是能開機、能用的最低配置；多存幾千元，就能換到 6 核心以上的 CPU，順很多。")
    return result


def cheapest_possible(parts: pd.DataFrame, prefs: Prefs):
    """這些需求下，最少要多少錢才配得出來（給「預算不夠」的提示用）。"""
    from dataclasses import replace
    for budget in range(15000, 300001, 5000):
        if make_build(parts, replace(prefs, budget=budget)) is not None:
            return budget
    return None


def _make_build(parts, prefs, min_cores):
    extras = _extras(parts, prefs)
    extras_cost = sum(p["price"] for p in extras.values() if p is not None)
    budget_core = prefs.budget - extras_cost

    builder = _Builder(parts, prefs, budget_core)
    if builder.ssd is None or builder.case_pool.empty:
        return None

    usages = _main_usages(prefs)
    office_only = usages == (USAGE_OFFICE,)

    cpus = _cheapest_per(_part(parts, "cpu"), ["model"])
    cpus = cpus[cpus["cores"].fillna(0) >= min_cores]
    if office_only:
        cpus = cpus[cpus["has_igpu"]]

    gpu_options = [None]
    if not office_only:
        gpus = _part(parts, "gpu").dropna(subset=["gpu_score"])
        gpus = gpus[gpus["length_cm"].fillna(30) <= builder.max_gpu_length()]
        gpu_options += [row for _, row in _cheapest_per(gpus, ["gpu_chip", "vram_gb"], prefs.color).iterrows()]

    candidates = []
    for ram_gb in _ram_choices(prefs):
        for _, cpu in cpus.iterrows():
            for gpu in gpu_options:
                if gpu is None and not cpu["has_igpu"]:
                    continue
                chosen = builder.assemble(cpu, gpu, ram_gb)
                if chosen is None:
                    continue
                total = sum(p["price"] for p in chosen.values() if p is not None)
                if total > budget_core:
                    continue
                scores = tuple(performance(u, cpu, gpu, ram_gb, prefs.resolution) for u in usages)
                candidates.append((scores, total, chosen))

    if not candidates:
        return None

    # 多種用途：每種用途的分數先除以「這次所有組合裡的最高分」，再平均，這樣不同用途的分數才能比較
    tops = [max(c[0][i] for c in candidates) or 1 for i in range(len(usages))]
    scored = [(sum(s / t for s, t in zip(c[0], tops)) / len(usages), c[1], c[2]) for c in candidates]
    top_score = max(c[0] for c in scored)
    strongest_total = min(c[1] for c in scored if c[0] == top_score)

    if office_only:
        best = min(scored, key=lambda c: c[1])
    elif prefs.premium:
        best = max(scored, key=lambda c: (round(c[0], 4), -c[1]))
    else:
        good_enough = [c for c in scored if c[0] >= top_score * GOOD_ENOUGH_RATIO]
        best = min(good_enough, key=lambda c: (c[1], -c[0]))

    _, total, chosen = best
    upgraded = []
    if prefs.premium and not office_only:
        chosen, upgraded = _upgrade(parts, chosen, prefs, budget_core)

    problems, notes = check_build(chosen)
    all_parts = dict(chosen)
    all_parts.update(extras)
    total = int(sum(p["price"] for p in all_parts.values() if p is not None))
    return {
        "parts": all_parts,
        "total": total,
        "problems": problems,
        "notes": notes,
        "tips": _tips(all_parts, prefs, total, strongest_total + extras_cost, upgraded, _strongest_gpu_chip(parts)),
        "upgraded": upgraded,
        "psu_needed_w": required_psu_w(chosen["cpu"], chosen["gpu"]),
    }


def _strongest_gpu_chip(parts) -> str:
    gpus = _part(parts, "gpu").dropna(subset=["gpu_score"])
    if gpus.empty:
        return ""
    return str(gpus.sort_values("gpu_score").iloc[-1]["gpu_chip"])


def _tips(chosen, prefs, total, strongest_total, upgraded, strongest_chip=""):
    """給使用者看的白話說明：為什麼這樣配。"""
    tips = []
    gpu_now = chosen["gpu"]
    if gpu_now is not None and strongest_chip and gpu_now["gpu_chip"] == strongest_chip and "5090" not in strongest_chip:
        tips.append(f"原價屋今天沒有單賣 RTX 5090 顯示卡（只有品牌主機、電競筆電裡有），能單買到最強的是 {strongest_chip}，"
                    "所以幫你配這張。等原價屋上架 5090，網站每天自動更新價格，就會自動配進去。")
    usages = _main_usages(prefs)
    cpu, gpu = chosen["cpu"], chosen["gpu"]
    gaming = any(u in GAME_USAGES for u in usages)
    if gaming and gpu is None:
        tips.append("這個預算買不到能玩遊戲的獨立顯示卡，先用 CPU 內建的顯示功能；之後存到錢再加顯示卡就能直接升級。")
    if USAGE_AI in usages and gpu is None:
        tips.append("跑 AI 主要靠顯示卡（尤其是顯示卡的記憶體 VRAM），這個預算買不到顯示卡，只能跑很小的模型。"
                    "預算拉到約 $35,000 以上，就配得到 16GB 的顯示卡。")
    elif USAGE_AI in usages and gpu["gpu_chip"].startswith(("RX", "Arc", "B5", "B7")):
        tips.append("AI 工具大多是為 NVIDIA 顯示卡設計的；這張不是 NVIDIA，有些 AI 軟體會跑不動或比較慢。")
    if gaming and gpu is not None:
        tips.append("CPU 和顯示卡的等級是照你的螢幕解析度搭配的，不會出現一個太強、另一個拖後腿的浪費。")
    if len(usages) > 1:
        tips.append("你勾了好幾種用途，CPU 和顯示卡是照「每一種都兼顧」來挑的。")
    if cpu["socket"] == "AM5":
        tips.append("AMD AM5 平台之後還會出新 CPU，以後想升級只要換 CPU，主機板可以繼續用。")
    if upgraded:
        tips.append("「用好料」模式：剩下的預算幫你升級了 " + "、".join(upgraded) + "。")

    left = prefs.budget - total
    if left >= 3000:
        if usages == (USAGE_OFFICE,):
            tips.append(f"文書用途這樣就很夠用了，剩下的 ${left:,} 可以留著買螢幕、鍵盤滑鼠。")
        elif prefs.budget - strongest_total >= 3000 and prefs.premium:
            tips.append(f"已經是原價屋目前買得到的頂規組合，預算還剩 ${left:,}。"
                        "想再花，可以回第 2 步挑更高級的機殼，或在菜單按「換一個」升級散熱器、記憶體。")
        elif prefs.budget - strongest_total >= 3000:
            tips.append(f"已經是原價屋目前買得到、搭配起來最強的組合，預算還剩 ${left:,}。想把主機板、電源、SSD 也換好一點，可以在進階選項選「用好料」。")
        else:
            tips.append(f"還剩 ${left:,}：再加錢換更好的零件，效能提升不到 3%，不划算，所以幫你省下來。")
    if chosen["cooler"] is None and cpu["cooler_included"]:
        tips.append("這顆 CPU 盒裝附原廠風扇，不用另外買散熱器。")
    return tips
