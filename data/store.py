"""資料倉庫：讀取筆電資料、判斷資料是不是太舊、太舊就叫爬蟲更新。

之後把 CSV 換成 SQLite 資料庫時，只需要改這個檔案，其他地方不用動。
只能放純 Python，不准 import streamlit。
"""
import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd

from core.laptop.recommend import prepare_laptops
from scrapers import coolpc_laptop
from scrapers.coolpc_common import TAIPEI, TIME_FORMAT

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
LAPTOP_CSV = os.path.join(DATA_DIR, "coolpc_laptop.csv")

REFRESH_AFTER = timedelta(hours=24)   # 資料多舊就要重抓
RETRY_COOLDOWN = 30 * 60              # 抓失敗後，30 分鐘內不再重試（秒）

# 整個網站共用一份：同一時間只讓一個人觸發爬蟲，並記住上次失敗的時間和原因
_refresh_lock = threading.Lock()
_last_fail = {"time": 0.0, "error": ""}


def laptop_data_exists() -> bool:
    return os.path.exists(LAPTOP_CSV)


def laptop_data_version() -> float:
    """資料檔的修改時間。網站拿它當快取的鑰匙：檔案一更新，快取就自動失效。"""
    return os.path.getmtime(LAPTOP_CSV)


def laptop_scraped_at():
    """上次從原價屋抓資料的時間；舊版 CSV 沒有記錄就回傳 None。"""
    try:
        first = pd.read_csv(LAPTOP_CSV, usecols=["scraped_at"], nrows=1)
        text = str(first["scraped_at"].iloc[0])
        return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=TAIPEI)
    except Exception:
        return None


def laptop_needs_refresh() -> bool:
    scraped_at = laptop_scraped_at() if laptop_data_exists() else None
    if scraped_at is None:
        return True
    return datetime.now(TAIPEI) - scraped_at >= REFRESH_AFTER


def refresh_laptops(force: bool = False):
    """需要的話就去原價屋重抓。force=True 時不管資料新舊都立刻重抓。

    回傳 None 代表成功或不需要更新；回傳文字代表失敗原因。
    """
    if not force and not laptop_needs_refresh():
        return None

    if not force and time.time() - _last_fail["time"] < RETRY_COOLDOWN:
        return _last_fail["error"]

    if not _refresh_lock.acquire(blocking=False):
        return None  # 別人正在更新，這次先用舊資料

    try:
        coolpc_laptop.update_csv(LAPTOP_CSV)
        return None
    except Exception as e:
        _last_fail["time"] = time.time()
        _last_fail["error"] = str(e)[:120]
        return _last_fail["error"]
    finally:
        _refresh_lock.release()


def load_laptops() -> pd.DataFrame:
    """讀出整理好的筆電資料，可以直接丟進 core.laptop.recommend 使用。"""
    return prepare_laptops(pd.read_csv(LAPTOP_CSV))
