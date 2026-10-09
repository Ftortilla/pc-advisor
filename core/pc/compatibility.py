"""桌機相容性檢查。

每個 fits_* 函式回答一個「能不能一起用」的問題，配單時拿來過濾零件；
check_build() 把整台機器從頭到尾檢查一次，回傳「一定不行的問題」和「要注意的提醒」。
使用者看到的訊息全部用白話寫，不出現腳位、DDR 這種術語也看得懂。

每個零件是一個 dict（或 pandas 的一列），欄位名稱跟 data/coolpc_parts.csv 一樣。
只能放純 Python，不准 import streamlit。
"""
import math

from core.pc.scores import cpu_power_w, gpu_score_and_power

# 主機板尺寸由小到大
FORM_ORDER = {"ITX": 1, "M-ATX": 2, "ATX": 3, "E-ATX": 4}

# 入門晶片組：供電比較弱，不適合搭配高階 CPU
ENTRY_CHIPSETS = {"A520", "A620", "H610", "H810", "B840"}

GPU_LENGTH_MARGIN_CM = 1.0     # 顯卡和機殼之間至少留 1 公分，接線才插得進去
COOLER_HEIGHT_MARGIN_CM = 0.3  # 塔扇和側板之間至少留一點空間


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value) and not (isinstance(value, float) and math.isnan(value))


def _num(value, default=0.0) -> float:
    try:
        v = float(value)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


# ============================================================
# 兩兩配對的規則（配單時用來過濾）
# ============================================================
def fits_cpu_motherboard(cpu, mb) -> bool:
    return cpu["socket"] == mb["socket"]


def fits_ram_motherboard(ram, mb) -> bool:
    return int(_num(ram["ddr"])) == int(_num(mb["ddr"])) and int(_num(ram["ram_sticks"], 1)) <= int(_num(mb["dimm_slots"], 4))


def fits_motherboard_case(mb, case) -> bool:
    return FORM_ORDER.get(mb["form_factor"], 9) <= FORM_ORDER.get(case["case_mb_max"], 0)


def fits_gpu_case(gpu, case) -> bool:
    length = _num(gpu["length_cm"], 30.0)  # 沒寫長度就當 30 公分，保守一點
    return length + GPU_LENGTH_MARGIN_CM <= _num(case["case_gpu_max_cm"])


def fits_cooler_cpu(cooler, cpu) -> bool:
    return cpu["socket"] in str(cooler["cooler_sockets"]).split("/")


def fits_cooler_case(cooler, case) -> bool:
    return _num(cooler["cooler_height_cm"]) + COOLER_HEIGHT_MARGIN_CM <= _num(case["case_cpu_max_cm"])


def cpu_power(cpu) -> int:
    """CPU 滿載實際耗電（不是盒子上寫的 TDP），見 core/pc/scores.py。"""
    return cpu_power_w(cpu["model"], cpu["socket"], cpu["tdp_w"], cpu["cores"])


def cooler_strong_enough(cooler, cpu, margin: float = 1.1) -> bool:
    return _num(cooler["cooler_tdp_w"]) >= cpu_power(cpu) * margin


def fits_psu_case(psu, case) -> bool:
    return (not _bool(case["case_sfx_only"])) or _bool(psu["psu_sfx"])


def gpu_power_w(gpu) -> int:
    if gpu is None:
        return 0
    _, power = gpu_score_and_power(gpu["gpu_chip"], gpu["vram_gb"])
    return int(power or 200)


def required_psu_w(cpu, gpu) -> int:
    """整台電腦建議的電源瓦數：CPU + 顯卡 + 其他零件，再留 1.4 倍餘裕，取 50 的倍數。"""
    draw = cpu_power(cpu) + gpu_power_w(gpu) + 80
    watts = math.ceil(draw * 1.4 / 50) * 50
    return max(watts, 450 if gpu is None else 550)


def fits_psu_power(psu, cpu, gpu) -> bool:
    if _num(psu["psu_w"]) < required_psu_w(cpu, gpu):
        return False
    # 高耗電新顯卡用 12V-2x6 供電接頭，要 ATX 3.x 電源才有原生線
    if gpu is not None and gpu_power_w(gpu) >= 250 and not _bool(psu["psu_atx3"]):
        return False
    return True


# ============================================================
# 整台檢查
# ============================================================
def check_build(build: dict):
    """build 是 {"cpu":…, "motherboard":…, "ram":…, "ssd":…, "gpu":…或None, "cooler":…或None, "psu":…, "case":…}

    回傳 (problems, notes)：
      problems：一定要改，不然開不了機或裝不進去
      notes：可以用，但使用者應該知道的事
    """
    problems, notes = [], []
    cpu, mb, ram = build.get("cpu"), build.get("motherboard"), build.get("ram")
    gpu, cooler, psu, case = build.get("gpu"), build.get("cooler"), build.get("psu"), build.get("case")

    if cpu is None or mb is None or ram is None or psu is None or case is None or build.get("ssd") is None:
        problems.append("零件還沒選齊：CPU、主機板、記憶體、硬碟、電源、機殼都要有。")
        return problems, notes

    if not fits_cpu_motherboard(cpu, mb):
        problems.append("CPU 和主機板的插槽形狀不同，CPU 根本插不上去。")
    if not fits_ram_motherboard(ram, mb):
        problems.append("記憶體的世代和主機板不同（DDR4 和 DDR5 不能互換），插不進去。")
    if not fits_motherboard_case(mb, case):
        problems.append("主機板比機殼能裝的尺寸還大，放不進機殼。")

    if gpu is None and not _bool(cpu["has_igpu"]):
        problems.append("這顆 CPU 沒有內建顯示功能，又沒有買顯示卡，開機會沒有畫面。")
    if gpu is not None and not fits_gpu_case(gpu, case):
        problems.append("顯示卡太長，機殼放不下。")

    if cooler is None:
        if not _bool(cpu["cooler_included"]):
            problems.append("這顆 CPU 沒有附散熱風扇，一定要另外買散熱器。")
        elif cpu_power(cpu) > 120:
            notes.append("CPU 附的原廠風扇比較小，長時間滿載會比較吵，之後可以再升級散熱器。")
    else:
        if not fits_cooler_cpu(cooler, cpu):
            problems.append("散熱器不支援這顆 CPU 的插槽，裝不上去。")
        if not fits_cooler_case(cooler, case):
            problems.append("散熱器太高，機殼側板會蓋不起來。")
        if not cooler_strong_enough(cooler, cpu):
            notes.append("散熱器偏小，CPU 全速運轉時溫度會比較高、風扇會比較吵。")

    if not fits_psu_power(psu, cpu, gpu):
        problems.append(f"電源瓦數不夠或接頭不對，建議至少 {required_psu_w(cpu, gpu)}W、而且要支援 ATX 3.x。")
    if not fits_psu_case(psu, case):
        problems.append("這個機殼只能裝小尺寸（SFX）電源，一般尺寸的電源放不進去。")

    if mb.get("chipset") in ENTRY_CHIPSETS and cpu_power(cpu) >= 150:
        notes.append("主機板是入門款，搭配高階 CPU 時供電比較吃緊，長時間滿載效能可能打折。")
    if int(_num(ram["ram_sticks"], 1)) == 1:
        notes.append("記憶體只有一條，效能會比兩條一組（雙通道）差一些，之後可以再加一條同型號的。")
    if not _bool(mb["wifi"]):
        notes.append("主機板沒有 Wi-Fi，要接網路線；宿舍或房間沒有網路孔的話，要另外買無線網卡（約 $500 起）。")
    if gpu is None:
        notes.append("沒有買獨立顯示卡，用 CPU 內建的顯示功能：上網、文書、看影片沒問題，但不適合玩 3A 遊戲。")

    return problems, notes
