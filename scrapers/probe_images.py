"""開發用小工具：測試能不能從原價屋拿到商品圖片。

原價屋估價單的圖片不在網頁裡，而是：
  1. 網頁裡有一組隱藏編號（例如機殼的 g14 陣列），每個商品對應一個編號
  2. 拿編號去問 eva-img.php，伺服器才回傳圖片

這支程式拿 3 個機殼、2 張顯卡試試看，把原價屋回傳的內容存下來研究。

在專案資料夾的終端機輸入：
    python -m scrapers.probe_images
"""
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from scrapers.coolpc_common import HEADERS, URL, own_text

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(PROJECT_DIR, "data", "coolpc_img_probe.txt")
IMG_URL = "https://www.coolpc.com.tw/eva-img.php"


def read_id_array(page_text: str, row: int) -> list:
    """從網頁的程式碼裡，讀出第 row 列的隱藏編號陣列（例如 g14=[0,0,4527.5,...]）。"""
    m = re.search(rf"\bg{row}=\[([^\]]*)\]", page_text)
    if not m:
        return []
    return [x.strip() for x in m.group(1).split(",")]


def main() -> None:
    session = requests.Session()
    resp = session.get(URL, headers=HEADERS, timeout=30)
    resp.encoding = "big5hkscs"
    page_text = resp.text
    soup = BeautifulSoup(page_text, "html.parser")

    lines = []
    for row, count in [(14, 3), (12, 2)]:
        ids = read_id_array(page_text, row)
        lines.append(f"######## 第 {row} 列，隱藏編號共 {len(ids)} 個")
        select = soup.find("select", attrs={"name": f"n{row}"})
        tried = 0
        for option in select.find_all("option"):
            text = own_text(option)
            value = option.get("value", "")
            if "$" not in text or not value.isdigit() or int(value) >= len(ids):
                continue
            g = ids[int(value)]
            if g in ("", "0"):
                continue
            headers = dict(HEADERS)
            headers["Referer"] = URL
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = session.post(IMG_URL, data=f"G={g}", headers=headers, timeout=30)
            r.encoding = "big5hkscs"
            lines.append(f"--- 商品：{text[:80]}")
            lines.append(f"    選單值={value}  隱藏編號 G={g}  回應狀態={r.status_code}  長度={len(r.text)}")
            lines.append(r.text[:3000])
            lines.append("")
            tried += 1
            time.sleep(1)  # 慢慢問，不要給原價屋太大負擔
            if tried >= count:
                break

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"已存成 {OUTPUT}")
    print("請把 coolpc_img_probe.txt 壓縮成 ZIP 再上傳到對話裡。")


if __name__ == "__main__":
    main()
