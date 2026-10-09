"""各電商的搜尋 / 購買連結。

之後接聯盟導購（Affiliate）時，只要改這個檔案：
例如把 shopee_url() 換成帶有你推廣代碼的網址。
只能放純 Python，不准 import streamlit。
"""
import urllib.parse

from core.text_utils import short_name

COOLPC_URL = "https://www.coolpc.com.tw/evaluate.php"


def shopee_url(keyword: str) -> str:
    return "https://shopee.tw/search?keyword=" + urllib.parse.quote(keyword)


def momo_url(keyword: str) -> str:
    return "https://www.momoshop.com.tw/search/searchShop.jsp?keyword=" + urllib.parse.quote(keyword)


def search_keyword(brand: str, model_code: str, name: str) -> str:
    """用「品牌 + 型號」去電商搜尋最準；沒有型號就用整理過的商品名稱。"""
    if model_code:
        return f"{brand} {model_code}"
    return short_name(name)
