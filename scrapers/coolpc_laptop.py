"""原價屋筆電爬蟲：抓估價單第 2 列（筆電｜平板｜穿戴配件），拆出規格，存成 CSV。

平常不用手動跑，網站會在資料太舊時自動呼叫 update_csv()。
想手動更新，在專案資料夾（advisor_module）的終端機輸入：
    python -m scrapers.coolpc_laptop

只能放純 Python，不准 import streamlit。
"""
import csv
import os
import re

from scrapers.coolpc_common import (
    clean_name,
    fetch_page,
    find_select,
    get_model_code,
    iter_options,
    now_text,
)

# 估價單第 2 列「筆電｜平板｜穿戴配件」的選單名稱
LAPTOP_SELECT_NAME = "n2"

# 預設存檔位置：專案資料夾裡的 data/coolpc_laptop.csv
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(PROJECT_DIR, "data", "coolpc_laptop.csv")

# 抓到少於這個數量，通常代表網頁出問題了，不要拿壞資料蓋掉舊的好資料
MIN_EXPECTED = 50

# 品牌關鍵字：左邊是網頁上可能出現的字，右邊是統一後的品牌名
BRAND_KEYWORDS = [
    ("Acer", "Acer"), ("宏碁", "Acer"),
    ("Lenovo", "Lenovo"),
    ("華碩", "ASUS"), ("ASUS", "ASUS"),
    ("DELL", "Dell"), ("戴爾", "Dell"),
    ("Genuine", "Genuine 捷元"), ("捷元", "Genuine 捷元"),
    ("技嘉", "GIGABYTE"), ("GIGABYTE", "GIGABYTE"),
    ("微星", "MSI"), ("MSI", "MSI"),
    ("LG", "LG"),
    ("HP", "HP"),
]

FIELDS = ["brand", "name", "price", "gpu", "ram_gb", "storage",
          "screen_inch", "condition", "model_code", "group", "raw_text", "scraped_at"]


def is_laptop(text: str, group: str, price: int) -> bool:
    """這一格混了平板、掌機、充電器，只留下「有記憶體規格 + 有螢幕尺寸 + 1 萬以上」的。"""
    if price < 10000:
        return False
    if any(w in group for w in ["平板", "掌機", "周邊", "充電", "行動電源"]):
        return False
    has_ram = re.search(r"\d+G(\+\d+G)?/", text) is not None
    has_screen = ("吋" in text) or ("吋" in group)
    return has_ram and has_screen


def get_brand(text: str, group: str) -> str:
    for keyword, brand in BRAND_KEYWORDS:
        if keyword in text or keyword in group:
            return brand
    return "其他"


def get_gpu(text: str) -> str:
    m = re.search(r"RTX\s?\d{4}\s?(Ti)?", text)
    if m:
        return m.group(0).replace(" ", "")
    return "內建顯示"


def get_ram_gb(text: str):
    m = re.search(r"(\d+)G(?:\+(\d+)G)?/", text)
    if not m:
        return None
    total = int(m.group(1))
    if m.group(2):
        total += int(m.group(2))
    return total


def get_storage(text: str) -> str:
    m = re.search(r"\d+G(?:\+\d+G)?/(\d+(?:G|T))", text)
    return m.group(1) if m else ""


def get_screen(text: str, group: str):
    for source in [text, group]:
        m = re.search(r"(\d+(?:\.\d+)?)\s?吋", source)
        if m:
            return float(m.group(1))
    return None


def get_condition(text: str) -> str:
    if "展示品" in text:
        return "展示品"
    if "維修品" in text:
        return "維修品"
    return "新品"


def parse_laptops(laptop_select, scraped_at: str) -> list:
    rows = []
    for text, price, group in iter_options(laptop_select):
        if not is_laptop(text, group, price):
            continue
        rows.append({
            "brand": get_brand(text, group),
            "name": clean_name(text),
            "price": price,
            "gpu": get_gpu(text),
            "ram_gb": get_ram_gb(text),
            "storage": get_storage(text),
            "screen_inch": get_screen(text, group),
            "condition": get_condition(text),
            "model_code": get_model_code(text),
            "group": group,
            "raw_text": text,
            "scraped_at": scraped_at,
        })
    return rows


def save_csv(rows: list, filename: str = DEFAULT_CSV) -> None:
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def update_csv(filename: str = DEFAULT_CSV) -> list:
    """去原價屋抓一次，存成 CSV，回傳抓到的筆電清單。網站會呼叫這個函式自動更新。"""
    soup = fetch_page()
    laptop_select = find_select(soup, LAPTOP_SELECT_NAME)
    laptops = parse_laptops(laptop_select, now_text())

    if len(laptops) < MIN_EXPECTED:
        raise RuntimeError(f"只抓到 {len(laptops)} 台，數量異常，先不更新")

    save_csv(laptops, filename)
    return laptops


if __name__ == "__main__":
    laptops = update_csv()
    print(f"共抓到 {len(laptops)} 台筆電")

    brand_counts = {}
    for item in laptops:
        brand_counts[item["brand"]] = brand_counts.get(item["brand"], 0) + 1
    print("各品牌數量：", brand_counts)
    print("--------------------------------------------")

    for item in laptops[:15]:
        print(f"{item['price']:>7} ｜ {item['brand']:<8} ｜ {item['gpu']:<9} ｜ "
              f"{item['ram_gb']}G ｜ {item['storage']} ｜ {item['screen_inch']}吋 ｜ "
              f"{item['condition']} ｜ {item['name']}")

    print(f"已存成 {DEFAULT_CSV}")
