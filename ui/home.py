"""首頁：自組桌機 / 筆記型電腦 二選一的大卡片。"""
import streamlit as st

CARDS_HTML = """
<div class="choice-grid">
  <a class="choice-card" href="?type=PC" target="_self">
    <div>
      <div class="choice-icon">🖥️</div>
      <div class="choice-title">自組桌機 (PC)</div>
      <div class="choice-text">
        <b>優點：</b>同預算效能最高、散熱安靜、零組件未來可自由更換升級。<br>
        <b>缺點：</b>體積大佔空間、無法攜帶外出、需自備外接螢幕與鍵鼠。
      </div>
    </div>
    <div class="choice-cta">👉 進入【自組桌機】規劃</div>
  </a>
  <a class="choice-card" href="?type=Laptop" target="_self">
    <div>
      <div class="choice-icon">💻</div>
      <div class="choice-title">筆記型電腦 (Laptop)</div>
      <div class="choice-text">
        <b>優點：</b>拔掉插頭揹著就走、自帶螢幕鍵盤、外宿租屋極省空間。<br>
        <b>缺點：</b>同價位效能打折、風扇較吵、核心硬體焊死無法未來升級。
      </div>
    </div>
    <div class="choice-cta">👉 進入【筆記型電腦】挑選</div>
  </a>
</div>
"""


def render() -> None:
    st.markdown("<h1 style='text-align: center; margin-top: 10px;'>請問您這次想配置哪種設備？</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888; font-size: 18px;'>不用懂複雜參數，點選後將為您客製化配置與防呆避坑指南。</p>", unsafe_allow_html=True)
    # 卡片用真正的網頁連結（target="_self"）換頁，瀏覽器的 ← 返回才會有作用
    st.markdown(CARDS_HTML, unsafe_allow_html=True)
