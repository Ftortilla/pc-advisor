import re
import csv
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

URL = "https://www.coolpc.com.tw/evaluate.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 台灣時間（雲端主機預設是 UTC，所以要自己指定 +8）
TAIPEI = timezone(timedelta(hours=8))

# 估價單第 2 列「筆電｜平板｜穿戴配件」的選單名稱
LAPTOP_SELECT_NAME = "n2"

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


def fetch_page() -> BeautifulSoup:
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    # big5hkscs 比一般 big5 多收錄很多字（例如「宏碁」的碁）
    resp.encoding = "big5hkscs"
    return BeautifulSoup(resp.text, "html.parser")


def own_text(option) -> str:
    # 只拿這個商品「自己」的文字，不要把後面黏進來的商品一起算進去
    parts = option.find_all(string=True, recursive=False)
    return "".join(parts).strip()


def get_group_label(option) -> str:
    parent = option.find_parent("optgroup")
    if parent is None:
        return ""
    return parent.get("label", "")


def get_price(text: str):
    # 有折扣時長這樣：$45990↘$39999，取最後一個數字就是折扣後價格
    prices = re.findall(r"\$(\d+)", text)
    if not prices:
        return None
    return int(prices[-1])


def is_laptop(text: str, group: str, price: int) -> bool:
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


def get_model_code(text: str) -> str:
    codes = re.findall(r"｛([^｝]+)｝", text)
    return codes[-1].strip() if codes else ""


def clean_name(text: str) -> str:
    # 把結尾的「, $價格 ◆ ★」拿掉，只留下商品名稱
    return re.sub(r",\s*\$.*$", "", text).strip()


def parse_laptops(laptop_select, scraped_at: str) -> list:
    rows = []
    for option in laptop_select.find_all("option"):
        if option.has_attr("disabled"):
            continue
        text = own_text(option)
        price = get_price(text)
        if price is None:
            continue
        group = get_group_label(option)
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


def save_csv(rows: list, filename: str = "coolpc_laptop.csv") -> None:
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def update_csv(filename: str = "coolpc_laptop.csv") -> list:
    """去原價屋抓一次，存成 CSV，回傳抓到的筆電清單。網站會呼叫這個函式自動更新。"""
    soup = fetch_page()
    laptop_select = soup.find("select", attrs={"name": LAPTOP_SELECT_NAME})
    if laptop_select is None:
        raise RuntimeError(f"找不到名稱為 {LAPTOP_SELECT_NAME} 的選單，原價屋網頁可能改版了")

    scraped_at = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    laptops = parse_laptops(laptop_select, scraped_at)

    # 抓到太少台，通常代表網頁出問題了，不要拿壞資料蓋掉舊的好資料
    if len(laptops) < 50:
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

    print("已存成 coolpc_laptop.csv")
