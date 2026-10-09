"""全站外觀：大卡片、按鈕大小這些 CSS 樣式。"""
import streamlit as st

CSS = """
<style>
/* 首頁兩張大卡片 */
.choice-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 28px;
    margin-top: 12px;
}
.choice-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 58vh;
    padding: 36px 34px 30px 34px;
    border: 2px solid rgba(255, 255, 255, 0.12);
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.03);
    text-decoration: none !important;
    color: inherit !important;
    transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.choice-card:hover {
    transform: translateY(-4px);
    border-color: #ff4b4b;
    background: rgba(255, 75, 75, 0.08);
}
.choice-icon { font-size: 76px; line-height: 1; }
.choice-title { font-size: 38px; font-weight: 800; margin: 18px 0 14px 0; }
.choice-text { font-size: 18px; line-height: 1.9; color: #bbb; }
.choice-cta {
    margin-top: 26px;
    padding: 20px 0;
    border-radius: 14px;
    background: #ff4b4b;
    color: #fff;
    font-size: 24px;
    font-weight: 700;
    text-align: center;
}
@media (max-width: 768px) {
    .choice-grid { grid-template-columns: 1fr; }
    .choice-card { min-height: auto; }
}

/* 內頁的「回上一頁」連結 */
.back-link {
    display: inline-block;
    padding: 12px 22px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 10px;
    text-decoration: none !important;
    color: inherit !important;
    font-size: 17px;
}
.back-link:hover { border-color: #ff4b4b; }

/* 所有 Streamlit 主要按鈕（生成推薦）放大 */
div.stButton > button[kind="primary"] {
    min-height: 64px;
    border-radius: 14px;
}
div.stButton > button[kind="primary"] p {
    font-size: 22px;
    font-weight: 700;
}
</style>
"""


def inject_styles() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
