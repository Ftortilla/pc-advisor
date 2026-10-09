"""原價屋商品圖片和詳細規格。

估價單選單裡只有名稱和價格；圖片和更多規格（尺寸、支援幾公分水冷、內附幾顆風扇、有沒有 A.RGB）
要拿商品隱藏編號去問 eva-img.php 才拿得到。

這裡只負責「去問一個商品」和「看懂回來的內容」；
要問哪些商品、問過的存在哪裡，由 data/store.py 管（每個商品只問一次，存起來重複用）。

只能放純 Python，不准 import streamlit。
"""
import re

import requests

from scrapers.coolpc_common import HEADERS, URL

BASE = "https://www.coolpc.com.tw"
DETAIL_URL = BASE + "/eva-img.php"


def parse_detail_html(html: str) -> dict:
    """把 eva-img.php 回傳的 HTML 整理成 {"image": 圖片網址, "specs": {規格名: 內容}}。"""
    image = ""
    m = re.search(r"<img\s+src=['\"]([^'\"]+)['\"]", html, re.I)
    if m:
        src = m.group(1)
        image = src if src.startswith("http") else BASE + src

    specs = {}
    for key, value in re.findall(r"<td>\s*([^<：:]{1,12})[：:]\s*([^<]+)", html):
        key, value = key.strip(), value.strip()
        if key and value and "價" not in key:
            specs[key] = value
    return {"image": image, "specs": specs}


def fetch_detail(gid: str, session=None) -> dict:
    """拿一個商品的圖片和詳細規格。失敗會丟出錯誤，由呼叫的人決定怎麼處理。"""
    session = session or requests.Session()
    headers = dict(HEADERS)
    headers["Referer"] = URL
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    resp = session.post(DETAIL_URL, data=f"G={gid}", headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "big5hkscs"
    return parse_detail_html(resp.text)


def fetch_image_bytes(url: str, session=None) -> bytes:
    """下載圖片。由我們的伺服器去拿（帶原價屋的 Referer），避免使用者瀏覽器直接連被擋。"""
    session = session or requests.Session()
    headers = dict(HEADERS)
    headers["Referer"] = URL
    resp = session.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.content


def has_argb(detail: dict, name: str = "") -> bool:
    """機殼有沒有燈光：名稱寫了 RGB，或詳細規格的「內附風扇」寫了 A.RGB / RGB。"""
    fans = detail.get("specs", {}).get("內附風扇", "")
    return bool(re.search(r"RGB", name + fans, re.I))


def radiator_sizes(detail: dict) -> list:
    """機殼支援的水冷排尺寸，例如 [360, 240, 120]。"""
    text = detail.get("specs", {}).get("支援水冷", "")
    return sorted({int(x) for x in re.findall(r"(120|140|240|280|360|420)", text)}, reverse=True)
