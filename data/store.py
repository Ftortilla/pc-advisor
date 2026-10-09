"""資料倉庫：讀取資料、判斷資料是不是太舊、太舊就叫爬蟲更新。

目前有兩份資料：筆電（LAPTOPS）、桌機零件（PARTS），用法一模一樣：
    PARTS.exists()        有沒有資料檔
    PARTS.needs_refresh() 資料是不是超過 24 小時
    PARTS.refresh()       去原價屋重抓（失敗回傳原因文字，成功回傳 None）
    PARTS.load()          讀出整理好的資料

之後把 CSV 換成 SQLite 資料庫時，只需要改這個檔案，其他地方不用動。
只能放純 Python，不准 import streamlit。
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd

from core.laptop.recommend import prepare_laptops
from core.pc.build import prepare_parts
from scrapers import coolpc_details, coolpc_laptop, coolpc_parts
from scrapers.coolpc_common import TAIPEI, TIME_FORMAT

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

REFRESH_AFTER = timedelta(hours=24)   # 資料多舊就要重抓
RETRY_COOLDOWN = 30 * 60              # 抓失敗後，30 分鐘內不再重試（秒）


class Dataset:
    def __init__(self, filename, updater, prepare):
        self.path = os.path.join(DATA_DIR, filename)
        self._updater = updater      # 爬蟲：去原價屋抓資料、存成 CSV 的函式
        self._prepare = prepare      # 整理：把 CSV 轉成推薦邏輯要用的格式
        # 整個網站共用：同一時間只讓一個人觸發爬蟲，並記住上次失敗的時間和原因
        self._lock = threading.Lock()
        self._last_fail = {"time": 0.0, "error": ""}

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def version(self) -> float:
        """資料檔的修改時間。網站拿它當快取的鑰匙：檔案一更新，快取就自動失效。"""
        return os.path.getmtime(self.path)

    def scraped_at(self):
        """上次從原價屋抓資料的時間；舊版 CSV 沒有記錄就回傳 None。"""
        try:
            first = pd.read_csv(self.path, usecols=["scraped_at"], nrows=1)
            text = str(first["scraped_at"].iloc[0])
            return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=TAIPEI)
        except Exception:
            return None

    def needs_refresh(self) -> bool:
        scraped_at = self.scraped_at() if self.exists() else None
        if scraped_at is None:
            return True
        return datetime.now(TAIPEI) - scraped_at >= REFRESH_AFTER

    def refresh(self, force: bool = False):
        """需要的話就去原價屋重抓。force=True 時不管資料新舊都立刻重抓。

        回傳 None 代表成功或不需要更新；回傳文字代表失敗原因。
        """
        if not force and not self.needs_refresh():
            return None
        if not force and time.time() - self._last_fail["time"] < RETRY_COOLDOWN:
            return self._last_fail["error"]
        if not self._lock.acquire(blocking=False):
            return None  # 別人正在更新，這次先用舊資料
        try:
            self._updater(self.path)
            return None
        except Exception as e:
            self._last_fail["time"] = time.time()
            self._last_fail["error"] = str(e)[:120]
            return self._last_fail["error"]
        finally:
            self._lock.release()

    def load(self) -> pd.DataFrame:
        # coolpc_gid 一定要當文字讀，不然 2269 會被讀成 2269.0，就對不上原價屋的編號了
        df = pd.read_csv(self.path, dtype={"coolpc_gid": str})
        return self._prepare(df)


LAPTOPS = Dataset("coolpc_laptop.csv", coolpc_laptop.update_csv, prepare_laptops)
PARTS = Dataset("coolpc_parts.csv", coolpc_parts.update_csv, prepare_parts)

# ============================================================
# 商品圖片和詳細規格（每個商品只問原價屋一次，存起來重複用）
# ============================================================
class DetailCache:
    REQUEST_GAP = 0.3   # 每問一個商品停一下，不要給原價屋太大負擔（秒）

    def __init__(self, filename):
        self.path = os.path.join(DATA_DIR, filename)
        self._lock = threading.Lock()
        self._data = None

    def _load(self):
        if self._data is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
        except OSError:
            pass  # 存不起來就算了，下次再問一次而已

    def get(self, gids, max_new: int = 12) -> dict:
        """回傳 {編號: {"image": 網址, "specs": {...}}}。沒問過的最多新問 max_new 個，問不到的就跳過。"""
        gids = [str(g) for g in gids if g and str(g) not in ("nan", "0")]
        with self._lock:
            data = self._load()
            missing = [g for g in gids if g not in data][:max_new]
            if missing:
                session = coolpc_details.requests.Session()
                for i, gid in enumerate(missing):
                    try:
                        data[gid] = coolpc_details.fetch_detail(gid, session)
                    except Exception:
                        continue
                    if i < len(missing) - 1:
                        time.sleep(self.REQUEST_GAP)
                self._save()
            return {g: data[g] for g in gids if g in data}


DETAILS = DetailCache("coolpc_details.json")


def image_bytes(url: str):
    """下載商品圖片；失敗回傳 None（畫面上就不顯示圖片）。"""
    try:
        return coolpc_details.fetch_image_bytes(url)
    except Exception:
        return None


# 舊的寫法（筆電頁在用），保留下來讓舊程式不用改
LAPTOP_CSV = LAPTOPS.path
laptop_data_exists = LAPTOPS.exists
laptop_data_version = LAPTOPS.version
laptop_scraped_at = LAPTOPS.scraped_at
laptop_needs_refresh = LAPTOPS.needs_refresh
refresh_laptops = LAPTOPS.refresh
load_laptops = LAPTOPS.load
