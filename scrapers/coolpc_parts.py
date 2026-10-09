"""原價屋桌機零件爬蟲：CPU、主機板、記憶體、SSD、傳統硬碟、顯卡、電源、機殼、塔扇、Windows。

從商品名稱和分組名稱拆出相容性需要的規格（腳位、DDR 世代、尺寸、長度、高度、瓦數…），
全部存成一個 CSV：data/coolpc_parts.csv，用 category 欄位區分是哪一類零件。

平常不用手動跑，網站會在資料太舊時自動呼叫 update_csv()。
想手動更新，在專案資料夾的終端機輸入：
    python -m scrapers.coolpc_parts

只能放純 Python，不准 import streamlit。
"""
import csv
import os
import re

from scrapers.coolpc_common import (
    clean_name,
    fetch_page,
    find_select,
    iter_options_full,
    now_text,
    read_id_arrays,
)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(PROJECT_DIR, "data", "coolpc_parts.csv")

# 估價單上每一類零件的選單名稱（第幾列）
SELECT_NAMES = {
    "cpu": "n4",
    "motherboard": "n5",
    "ram": "n6",
    "ssd": "n7",
    "hdd": "n8",
    "cooler": "n10",
    "gpu": "n12",
    "case": "n14",
    "psu": "n15",
    "os": "n29",
}

# 每一類至少要抓到這麼多，太少代表網頁出問題了，不要拿壞資料蓋掉舊的
MIN_EXPECTED = {
    "cpu": 15, "motherboard": 80, "ram": 40, "ssd": 40,
    "cooler": 40, "gpu": 50, "case": 150, "psu": 80,
    "hdd": 3, "os": 1,
}

FIELDS = [
    "category", "name", "model", "price", "group",
    # 原價屋內部商品編號：拿來抓圖片和詳細規格，也當作零件的固定代號
    "coolpc_gid",
    # CPU / 主機板 / 記憶體共用
    "socket", "ddr",
    # CPU
    "cores", "threads", "has_igpu", "cooler_included", "tdp_w",
    # 主機板
    "chipset", "form_factor", "wifi", "dimm_slots", "vrm_phases",
    # 記憶體
    "ram_total_gb", "ram_sticks", "ram_speed", "ram_cl",
    # SSD / 傳統硬碟
    "ssd_interface", "capacity_gb", "nand",
    # 顯卡
    "gpu_chip", "vram_gb", "length_cm",
    # 電源
    "psu_w", "psu_rating", "psu_sfx", "psu_atx3", "psu_modular",
    # 機殼
    "case_gpu_max_cm", "case_cpu_max_cm", "case_mb_max", "case_sfx_only", "case_glass", "color",
    # 塔扇
    "cooler_height_cm", "cooler_sockets", "cooler_tdp_w", "cooler_low_profile",
    # 抓取時間
    "scraped_at",
]

NUM = r"(\d+(?:\.\d+)?)"


# ============================================================
# 共用小工具
# ============================================================
def first_number(pattern: str, text: str, cast=float):
    m = re.search(pattern, text)
    return cast(m.group(1)) if m else None


def model_in_braces(text: str) -> str:
    """名稱裡第一組｛｝通常是型號（記憶體例外，那邊放料號）。"""
    m = re.search(r"｛([^｝]+)｝", text)
    return m.group(1).strip() if m else ""


def color_of(text: str) -> str:
    if re.search(r"白|White|WHITE|ICE|冰魄|雪", text):
        return "白"
    return "黑"


def form_factor_of(text: str) -> str:
    """主機板尺寸。M-ATX 要先判斷，不然會被當成 ATX。"""
    if re.search(r"E-ATX|EEB|CEB", text, re.I):
        return "E-ATX"
    if re.search(r"Mini-ITX|ITX", text, re.I):
        return "ITX"
    if re.search(r"M-ATX|mATX|Micro-ATX", text, re.I):
        return "M-ATX"
    if re.search(r"ATX", text):
        return "ATX"
    return ""


# ============================================================
# CPU
# ============================================================
def parse_cpu(text: str, group: str):
    if re.search(r"Xeon|Threadripper|TRX50|WRX90", group + text):
        return None  # 工作站等級，一般人用不到

    if "1851" in group:
        socket = "LGA1851"
    elif "1700" in group:
        socket = "LGA1700"
    elif "AM5" in group:
        socket = "AM5"
    elif "AM4" in group:
        socket = "AM4"
    else:
        return None

    model = model_in_braces(text) or clean_name(text)
    cores = first_number(r"(\d+)核", text, int)
    threads = first_number(r"(\d+)緒", text, int) or cores

    # 型號尾巴：Intel 有 F 的沒內顯；AMD 有 F 的沒內顯、有 G 的有內顯
    tail = re.sub(r"\s*(MPK|Tray盤?|盒|Plus)\s*", " ", model, flags=re.I).strip().split()[-1] if model else ""
    if "無內顯" in text:
        has_igpu = False
    elif re.search(r"內顯|UHD|Xe-core|RDNA", text):
        has_igpu = True
    elif socket.startswith("LGA"):
        has_igpu = not tail.upper().endswith(("F", "KF"))
    elif socket == "AM4":
        has_igpu = tail.upper().endswith("G")
    else:  # AM5：除了 F 結尾，幾乎都有基本內顯
        has_igpu = not tail.upper().endswith("F")

    if re.search(r"含風扇|MPK", text):
        cooler_included = True
    elif re.search(r"無風扇|Tray|盤|不含散熱", text):
        cooler_included = False
    elif socket.startswith("LGA") and "K" not in tail.upper() and "盒裝" in text:
        cooler_included = True  # Intel 非 K 盒裝附原廠風扇
    else:
        cooler_included = False  # 不確定就當沒附，配單時會另外買散熱器，比較保險

    tdp = first_number(r"(\d{2,3})\s*[Ww](?![A-Za-z0-9])", text, int)
    if tdp is None:
        if socket.startswith("LGA"):
            tdp = 125 if "K" in tail.upper() else 65
        else:
            tdp = 120 if "X3D" in model else 65

    return {
        "socket": socket, "model": model, "cores": cores, "threads": threads,
        "has_igpu": has_igpu, "cooler_included": cooler_included, "tdp_w": tdp,
    }


# ============================================================
# 主機板
# ============================================================
def parse_motherboard(text: str, group: str):
    if re.search(r"工作站|伺服器|sTR5|TRX50|WRX90", group):
        return None
    socket = None
    for key, value in [("AM5", "AM5"), ("AM4", "AM4"), ("1851", "LGA1851"), ("1700", "LGA1700")]:
        if key in group:
            socket = value
            break
    if socket is None:
        return None  # 1151、1200 這些太舊的平台不推薦

    ddr = first_number(r"DDR(\d)", group, int)
    model = model_in_braces(text) or clean_name(text)
    chipset = first_number(r"([ABHXZ]\d{3})", group, str) or ""  # 分組名稱最乾淨，例如「AMD B850 / AM5腳位」
    form = form_factor_of(text)
    if not form:
        return None

    wifi = bool(re.search(r"WIFI|Wi-Fi|WiFi|無線", text, re.I))
    dimms = 2 if ("2DIMM" in text or form == "ITX") else 4
    phases = None
    m = re.search(r"((?:\d+\+)*\d+)\s*(?:電源)?相", text)
    if m:
        phases = sum(int(x) for x in m.group(1).split("+"))

    return {
        "socket": socket, "ddr": ddr, "model": model, "chipset": chipset,
        "form_factor": form, "wifi": wifi, "dimm_slots": dimms, "vrm_phases": phases,
    }


# ============================================================
# 記憶體（只留桌上型）
# ============================================================
def parse_ram(text: str, group: str):
    if not group.startswith("桌上型"):
        return None
    ddr = first_number(r"DDR(\d)", group, int)
    if ddr not in (4, 5):
        return None

    m = re.search(r"(\d+)\s*GB?\s*\(\s*(?:雙通道?)?\s*(\d+)\s*GB?\s*[\*xX×]\s*(\d)", text)
    if m:
        total, sticks = int(m.group(1)), int(m.group(3))
    elif re.search(r"\d+\s*G[B]?\s*[\*xX×]\s*\d", text):
        # 例：256GB("雙通"四根64G*4)：容量取第一個數字，條數取「64G*4」的 4
        total = first_number(r"(\d+)\s*GB?", text.replace("DDR", ""), int)
        sticks = first_number(r"\d+\s*G[B]?\s*[\*xX×]\s*(\d)", text, int)
    else:
        total = first_number(r"(\d+)\s*GB?\b", text.replace("DDR", ""), int)
        sticks = 2 if "雙通" in group else 1
    if not total:
        return None

    speed = first_number(r"(?:DDR[45]|D[45])[-\s]?(\d{4})", text, int)
    cl = first_number(r"CL\s*(\d+)", text, int)
    return {
        "ddr": ddr, "model": clean_name(text), "ram_total_gb": total,
        "ram_sticks": sticks, "ram_speed": speed, "ram_cl": cl,
    }


# ============================================================
# SSD（只留 2280 尺寸，2230/2242 是掌機用的）
# ============================================================
def parse_ssd(text: str, group: str):
    if re.search(r"2230|2242", group):
        return None
    if "Gen5" in group or "5.0" in group:
        interface = "Gen5"
    elif "Gen4" in group or "4.0" in group:
        interface = "Gen4"
    elif "Gen3" in group or "3.0" in group:
        interface = "Gen3"
    elif "SATA" in group:
        interface = "SATA"
    else:
        return None

    m = re.search(NUM + r"\s*(TB|T|GB|G)\b", text)
    if not m:
        return None
    size = float(m.group(1))
    capacity = int(size * 1000) if m.group(2).startswith("T") else int(size)
    nand = "QLC" if "QLC" in text else ("TLC" if "TLC" in text else "")
    return {
        "model": model_in_braces(text) or clean_name(text),
        "ssd_interface": interface, "capacity_gb": capacity, "nand": nand,
    }


# ============================================================
# 顯卡
# ============================================================
def parse_gpu(text: str, group: str):
    if re.search(r"周邊|專業|工作站|Arc Pro|GeForce 210|GT710|GT730|GT1030", group):
        return None
    if re.search(r"外接式|AI BOX", text):
        return None
    m = re.search(r"(RTX\s?\d{4}(?:\s?Ti)?|RX\s?\d{4}(?:\s?(?:XT|GRE))?)", group, re.I)
    if not m:
        return None
    chip = m.group(1).replace(" ", "").upper().replace("TI", "Ti")
    vram = first_number(r"-(\d+)\s*G", group, int)
    length = first_number(NUM + r"\s*cm", text)
    return {
        "model": model_in_braces(text) or clean_name(text), "gpu_chip": chip,
        "vram_gb": vram, "length_cm": length, "color": color_of(text),
    }


# ============================================================
# 電源
# ============================================================
def parse_psu(text: str, group: str):
    watt = first_number(r"(\d{3,4})\s*W\b", text, int)
    if not watt:
        return None
    rating = ""
    for word in ["鈦金", "白金", "金牌", "銅牌", "白牌"]:
        if word in text:
            rating = word
            break
    return {
        "model": model_in_braces(text) or clean_name(text), "psu_w": watt, "psu_rating": rating,
        "psu_sfx": bool(re.search(r"SFX", text + group)),
        "psu_atx3": bool(re.search(r"ATX\s?3|PCIe\s?5", text)),
        "psu_modular": "全模" if "全模" in text else ("半模" if "半模" in text else "直出"),
        "color": color_of(text),
    }


# ============================================================
# 機殼
# ============================================================
def parse_case(text: str, group: str):
    # 注意：品牌「聯力工業」也有「工業」兩個字，所以要比對「工業機殼」「機架式」
    if re.search(r"工業機|機架式|NAS", group + text) or "開放式" in text:
        return None
    if re.search(r"\+.*(\d{3,4}W|水冷|風扇|扇\*|反向扇)", text):
        return None  # 機殼+電源/水冷的組合包，先不處理

    gpu_max = first_number(r"(?:顯卡長|顯卡|卡長|卡)\s*約?\s*\(?" + NUM, text)
    cpu_max = first_number(r"(?:CPU限高|CPU高|U高|U)\s*約?\s*\(?" + NUM, text)
    if gpu_max is None or cpu_max is None:
        return None  # 沒寫空間大小的就不推薦，避免買了裝不進去

    # 主機板尺寸：取名稱裡寫的最大支援尺寸
    mb_max = form_factor_of(text)
    if not mb_max:
        return None

    return {
        "model": model_in_braces(text) or clean_name(text),
        "case_gpu_max_cm": gpu_max, "case_cpu_max_cm": cpu_max, "case_mb_max": mb_max,
        "case_sfx_only": bool(re.search(r"【SFX】|SFX電供|SFX電源", text)),
        "case_glass": bool(re.search(r"玻璃|透側|海景", text)),
        "color": color_of(text),
    }


# ============================================================
# 塔扇（空冷散熱器）
# ============================================================
COOLER_SOCKETS = {"W": ["LGA1200"], "X": ["AM4", "AM5"], "Z": ["LGA1700", "LGA1851"]}


def parse_cooler(text: str, group: str):
    # 只看分組名稱判斷是不是散熱膏、SSD 散熱片這類東西（商品名稱裡常出現「直觸式導熱」，不能拿來判斷）
    if re.search(r"散熱片|散熱膏|導熱|筆記型", group) or "液態金屬" in text:
        return None
    height = first_number(r"高(?:度)?\s*" + NUM, text)
    if height is None:
        return None
    code = first_number(r"【([WXYZ]+)】", text, str) or ""
    sockets = {s for letter in code for s in COOLER_SOCKETS.get(letter, [])}
    if re.search(r"AM5專用", text):
        sockets.add("AM5")
    if re.search(r"Intel專用\(1700\)|LGA1700", text):
        sockets.update(["LGA1700", "LGA1851"])
    sockets = sorted(sockets)
    if not sockets:
        return None

    tdp = first_number(r"TDP[:：]?\s*(\d+)", text, int)
    low_profile = "下吹" in text
    if tdp is None:  # 沒寫 TDP，用導管數估計
        pipes = first_number(r"(\d+)\s*(?:導)?管", text, int) or 4
        tdp = 100 if low_profile else 150 + pipes * 15 + (30 if "雙塔" in text else 0)

    return {
        "model": model_in_braces(text) or clean_name(text),
        "cooler_height_cm": height, "cooler_sockets": "/".join(sockets),
        "cooler_tdp_w": tdp, "cooler_low_profile": low_profile, "color": color_of(text),
    }


# ============================================================
# 傳統硬碟（只留一般用的「傳統碟」，監控碟、NAS 碟、企業碟一般人用不到）
# ============================================================
def parse_hdd(text: str, group: str):
    if "傳統碟" not in group:
        return None
    m = re.search(NUM + r"\s*TB", text)
    if not m:
        return None
    return {"model": model_in_braces(text) or clean_name(text), "capacity_gb": int(float(m.group(1)) * 1000)}


# ============================================================
# Windows（只留中文家用版）
# ============================================================
def parse_os(text: str, group: str):
    if "Windows 11" not in text or "中文家用" not in text or "客訂" in text:
        return None
    return {"model": clean_name(text)}


PARSERS = {
    "cpu": parse_cpu,
    "motherboard": parse_motherboard,
    "ram": parse_ram,
    "ssd": parse_ssd,
    "cooler": parse_cooler,
    "gpu": parse_gpu,
    "case": parse_case,
    "psu": parse_psu,
    "hdd": parse_hdd,
    "os": parse_os,
}


# ============================================================
# 主流程
# ============================================================
def parse_parts(soup, scraped_at: str) -> list:
    rows = []
    id_arrays = read_id_arrays(soup)
    for category, select_name in SELECT_NAMES.items():
        parser = PARSERS[category]
        ids = id_arrays.get(int(select_name[1:]), [])
        for text, price, group, gid in iter_options_full(find_select(soup, select_name), ids):
            if price < 100:
                continue
            spec = parser(text, group)
            if spec is None:
                continue
            row = {field: "" for field in FIELDS}
            row.update({
                "category": category,
                "name": clean_name(text),
                "price": price,
                "group": group,
                "coolpc_gid": gid,
                "scraped_at": scraped_at,
            })
            row.update({k: v for k, v in spec.items() if v is not None})
            rows.append(row)
    return rows


def count_by_category(rows: list) -> dict:
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    return counts


def save_csv(rows: list, filename: str = DEFAULT_CSV) -> None:
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def update_csv(filename: str = DEFAULT_CSV) -> list:
    """去原價屋抓一次所有零件，存成 CSV。網站會呼叫這個函式自動更新。"""
    soup = fetch_page()
    rows = parse_parts(soup, now_text())
    counts = count_by_category(rows)
    too_few = [f"{c}={counts.get(c, 0)}" for c, n in MIN_EXPECTED.items() if counts.get(c, 0) < n]
    if too_few:
        raise RuntimeError("零件數量異常，先不更新：" + "、".join(too_few))
    save_csv(rows, filename)
    return rows


if __name__ == "__main__":
    parts = update_csv()
    print(f"共抓到 {len(parts)} 個零件：", count_by_category(parts))
    print(f"已存成 {DEFAULT_CSV}")
