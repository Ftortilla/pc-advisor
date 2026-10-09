"""原價屋估價單共用工具：下載網頁、處理編碼、讀出每個商品的文字和價格。

筆電爬蟲和之後的零件爬蟲（CPU、顯卡…）都會用到這裡。
只能放純 Python，不准 import streamlit。
"""
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

URL = "https://www.coolpc.com.tw/evaluate.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 台灣時間（雲端主機預設是 UTC，所以要自己指定 +8）
TAIPEI = timezone(timedelta(hours=8))
TIME_FORMAT = "%Y-%m-%d %H:%M"


def now_text() -> str:
    """現在的台灣時間，存進 CSV 的 scraped_at 欄位用。"""
    return datetime.now(TAIPEI).strftime(TIME_FORMAT)


def fetch_page() -> BeautifulSoup:
    """下載整張估價單。"""
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    # big5hkscs 比一般 big5 多收錄很多字（例如「宏碁」的碁）
    resp.encoding = "big5hkscs"
    return BeautifulSoup(resp.text, "html.parser")


def find_select(soup: BeautifulSoup, select_name: str):
    """找估價單上某一列的下拉選單，例如筆電是 n2。找不到就報錯。"""
    select = soup.find("select", attrs={"name": select_name})
    if select is None:
        raise RuntimeError(f"找不到名稱為 {select_name} 的選單，原價屋網頁可能改版了")
    return select


def own_text(option) -> str:
    """只拿這個商品「自己」的文字，不要把後面黏進來的商品一起算進去。"""
    parts = option.find_all(string=True, recursive=False)
    return "".join(parts).strip()


def get_group_label(option) -> str:
    """這個商品在下拉選單裡屬於哪個分組（例如「15吋 Acer宏碁 Nitro V 電競機」）。"""
    parent = option.find_parent("optgroup")
    if parent is None:
        return ""
    return parent.get("label", "")


def get_price(text: str):
    """有折扣時長這樣：$45990↘$39999，取最後一個數字就是折扣後價格。"""
    prices = re.findall(r"\$(\d+)", text)
    if not prices:
        return None
    return int(prices[-1])


def clean_name(text: str) -> str:
    """把結尾的「, $價格 ◆ ★」拿掉，只留下商品名稱。"""
    return re.sub(r",\s*\$.*$", "", text).strip()


def get_model_code(text: str) -> str:
    """抓出｛｝裡的型號，例如｛ANV15-52-52CL｝。"""
    codes = re.findall(r"｛([^｝]+)｝", text)
    return codes[-1].strip() if codes else ""


def read_id_arrays(soup: BeautifulSoup) -> dict:
    """讀出網頁程式碼裡每一列的「商品隱藏編號」陣列，例如 {14: ["0", "0", "4527.5", ...]}。

    隱藏編號是原價屋內部的商品代號，拿它去問 eva-img.php 才拿得到圖片和詳細規格。
    選單第 k 個選項（value=k）對應陣列第 k 個編號。
    """
    script_text = "\n".join(s.get_text() for s in soup.find_all("script"))
    arrays = {}
    for m in re.finditer(r"\bg(\d+)=\[([^\]]*)\]", script_text):
        arrays[int(m.group(1))] = [x.strip() for x in m.group(2).split(",")]
    return arrays


def iter_options_full(select, ids: list):
    """跟 iter_options 一樣，但多回傳商品隱藏編號：(商品文字, 價格, 分組名稱, 隱藏編號)。"""
    for option in select.find_all("option"):
        if option.has_attr("disabled"):
            continue
        text = own_text(option)
        price = get_price(text)
        if price is None:
            continue
        value = option.get("value", "")
        gid = ""
        if value.isdigit() and int(value) < len(ids) and ids[int(value)] not in ("", "0"):
            gid = ids[int(value)]
        yield text, price, get_group_label(option), gid


def iter_options(select):
    """逐一取出選單裡的商品，回傳 (商品文字, 價格, 分組名稱)；沒有價格的跳過。"""
    for option in select.find_all("option"):
        if option.has_attr("disabled"):
            continue
        text = own_text(option)
        price = get_price(text)
        if price is None:
            continue
        yield text, price, get_group_label(option)
