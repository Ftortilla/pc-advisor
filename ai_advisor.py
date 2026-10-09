"""網站入口：只負責設定頁面、套用樣式，再依網址的 type 分流到各頁。

啟動網站：在專案資料夾的終端機輸入  streamlit run ai_advisor.py
（Streamlit Cloud 部署時指定的也是這個檔名，所以不要改名）
"""
import streamlit as st

from ui import home, laptop_page, pc_page
from ui.styles import inject_styles

st.set_page_config(page_title="硬體選購引導顧問", layout="wide")
inject_styles()

page = st.query_params.get("type", None)

if page == "Laptop":
    laptop_page.render()
elif page == "PC":
    pc_page.render()
else:
    home.render()
