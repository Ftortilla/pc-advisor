"""開發用小工具：把原價屋估價單整張存下來，方便研究各類零件的名稱格式。

在專案資料夾（pc-advisor）的終端機輸入：
    python -m scrapers.explore_parts

會產生兩個檔案（都在 data/ 資料夾，不會上傳到 GitHub）：
    data/coolpc_raw.html       整張估價單原始網頁
    data/coolpc_overview.txt   每一列的選單名稱、分組、前幾個商品
"""
import os

import requests
from bs4 import BeautifulSoup

from scrapers.coolpc_common import HEADERS, URL, iter_options, now_text

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_HTML = os.path.join(DATA_DIR, "coolpc_raw.html")
OVERVIEW = os.path.join(DATA_DIR, "coolpc_overview.txt")

SAMPLES_PER_GROUP = 3


def row_title(select) -> str:
    """找出這個選單在估價單上那一列的名稱，例如「處理器 CPU」。"""
    tr = select.find_parent("tr")
    if tr is None:
        return "（找不到列名稱）"
    texts = []
    for td in tr.find_all("td", recursive=False)[:3]:
        if td.find("select") is None:
            text = td.get_text(" ", strip=True)
            if text:
                texts.append(text)
    return " ".join(texts)[:40] or "（無名稱）"


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "big5hkscs"
    page_text = resp.text

    # 原價屋是 Big5 編碼，很多軟體會誤認而把中文弄壞。
    # 這裡先正確解碼，再存成 UTF-8（最通用的編碼），用什麼打開都不會壞。
    utf8_text = page_text.replace("charset=big5", "charset=utf-8")
    with open(RAW_HTML, "w", encoding="utf-8") as f:
        f.write(utf8_text)

    # 估價單的商品圖片是由 /js/e19.js 這支程式組出來的，一起存下來研究
    js_resp = requests.get("https://www.coolpc.com.tw/js/e19.js", headers=HEADERS, timeout=30)
    js_resp.encoding = "big5hkscs"
    with open(os.path.join(DATA_DIR, "coolpc_e19.js"), "w", encoding="utf-8") as f:
        f.write(js_resp.text)

    soup = BeautifulSoup(page_text, "html.parser")

    lines = [f"抓取時間：{now_text()}", ""]
    for select in soup.find_all("select"):
        options = list(iter_options(select))
        if len(options) < 5:
            continue  # 數量選單之類的，跳過

        lines.append("=" * 70)
        lines.append(f"選單名稱={select.get('name')} ｜ 列名稱={row_title(select)} ｜ 有價格的商品={len(options)}")
        lines.append("=" * 70)

        shown = {}
        for text, price, group in options:
            if shown.get(group, 0) >= SAMPLES_PER_GROUP:
                continue
            shown[group] = shown.get(group, 0) + 1
            if shown[group] == 1:
                lines.append(f"  【{group}】")
            lines.append(f"      {price:>7} ｜ {text[:110]}")
        lines.append("")

    with open(OVERVIEW, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"已存成 {RAW_HTML}")
    print(f"已存成 {OVERVIEW}")
    print("請把 coolpc_e19.js 壓縮成 ZIP 再上傳到對話裡。")


if __name__ == "__main__":
    main()
