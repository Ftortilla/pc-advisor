"""自組桌機頁：目前只有問卷，配單功能之後做（邏輯會放在 core/pc/）。"""
import streamlit as st

from core.config import (
    PC_APPEARANCE_OPTIONS,
    PC_BUDGET_DEFAULT,
    PC_BUDGET_MAX,
    PC_BUDGET_MIN,
    PC_USAGE_OPTIONS,
)
from ui.helpers import page_header


def render() -> None:
    page_header("目前模式：🖥️ 自組桌機 (PC)")

    st.subheader("1. 選擇您的預算與需求")
    c1, c2 = st.columns(2)
    with c1:
        st.slider("預算上限 (NTD)：", min_value=PC_BUDGET_MIN, max_value=PC_BUDGET_MAX,
                  value=PC_BUDGET_DEFAULT, step=1000)
        st.selectbox("機殼外觀偏好：", PC_APPEARANCE_OPTIONS)
    with c2:
        st.selectbox("主要使用目的：", PC_USAGE_OPTIONS)

    if st.button("🚀 生成桌機最佳配置菜單", type="primary", use_container_width=True):
        st.info("桌機配單功能開發中，之後會改成讀原價屋即時零件價格。")
