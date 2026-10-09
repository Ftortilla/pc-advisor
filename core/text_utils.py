"""解析商品文字的小工具：清理名稱、抓重量、判斷顯卡等級。

只能放純 Python，不准 import streamlit。
"""
import re

from core.config import GPU_LEVELS


def gpu_level(gpu: str) -> int:
    """把 'RTX5060' 這種文字換成等級數字；內顯回傳 0。"""
    gpu = str(gpu)
    if not gpu.startswith("RTX"):
        return 0
    for key, level in GPU_LEVELS:
        if key in gpu:
            return level
    return 0


def short_name(name: str) -> str:
    """拿掉【展示品】、｛型號｝、促銷字，讓卡片上的名稱乾淨一點。"""
    name = str(name)
    # ｛型號｝後面接的通常是促銷字（萌色動人、〈IPS面板〉、搭包包…），整段切掉
    # 例外：少數商品型號寫在前面、規格在後面（例如捷元｛15N｝N100/8G/...），這種就保留
    if "｝" in name:
        head, _, tail = name.rpartition("｝")
        if not re.search(r"\d+G/", tail):
            name = head + "｝"
    name = re.sub(r"【[^】]*】", "", name)
    name = re.sub(r"｛[^｝]*｝", " ", name)
    name = re.sub(r"〈[^〉]*〉", "", name)
    name = re.sub(r"省\$\d+", "", name)
    return re.sub(r"\s+", " ", name).strip()


def weight_grams(name: str):
    """原價屋偶爾會在名稱寫重量，例如【極致輕999克】、極致輕990g，抓得到就回傳克數。"""
    m = re.search(r"(\d{3,4})\s*(?:克|g)(?![A-Za-z])", str(name))
    if m:
        grams = int(m.group(1))
        if 500 <= grams <= 4000:
            return grams
    return None
