# 💻 硬體選購引導顧問

給「不懂電腦規格」的人用的選購網站。不問 CPU、顯卡型號，而是問生活化的問題：每天要不要揹去上課？不插電要撐幾節課？能不能忍受風扇聲？再從**原價屋的即時報價**裡挑出最適合的機種。

🌐 **線上試用：** https://pc-advisor-alb7tzvnye2szyqztyt4jf.streamlit.app

## ✨ 功能

- **生活化問卷**：預算、用途、重量、續航、噪音，用白話描述，新手也看得懂
- **原價屋即時價格**：自動爬取原價屋估價單，資料超過一天會自動更新
- **依需求排名**：用途決定最低顯卡等級，再依重量、續航、噪音等條件算分排序
- **省錢選擇**：額外找一台「規格一樣夠用、但便宜很多」的機種
- **自動避坑提醒**：8GB 記憶體、展示品、維修品、「想要輕薄卻推到電競機」都會標示
- **多平台比價**：每台都附原價屋、蝦皮、Momo 連結
- **可分享的結果**：選項會記在網址裡，複製網址給朋友就能看到同樣的推薦

## 🗂️ 專案架構

```
advisor_module/
├── ai_advisor.py        網站入口，依網址分流到各頁
├── core/                核心邏輯（純 Python，不依賴網頁框架）
│   ├── config.py        問卷選項、顯卡等級表等設定
│   ├── text_utils.py    商品名稱清理、重量解析
│   ├── shop_links.py    各電商連結
│   └── laptop/          筆電推薦：篩選、算分、避坑指南
├── scrapers/            爬蟲：從原價屋抓資料
├── data/                資料存取與自動更新
└── ui/                  Streamlit 畫面
```

`core/`、`scrapers/`、`data/` 都不依賴 Streamlit，之後可以直接沿用到其他框架（例如 Django）。

## 🛠️ 技術

| 用途 | 技術 |
|---|---|
| 網頁 | Streamlit |
| 爬蟲 | requests + BeautifulSoup4 |
| 資料處理 | pandas |
| 部署 | Streamlit Community Cloud |

## 🚀 在自己電腦上跑

```bash
pip install -r requirements.txt
streamlit run ai_advisor.py
```

手動更新原價屋資料（平常網站會自動更新，不需要手動跑）：

```bash
python -m scrapers.coolpc_laptop
```

## 🗺️ 接下來

- [ ] 自組桌機配單（含 CPU / 主機板腳位、記憶體世代、電源瓦數相容性檢查）
- [ ] 加入跑分資料，計算 CP 值
- [ ] AI 用白話解釋推薦理由
- [ ] 自動測試

## 📋 資料來源

[原價屋線上估價單](https://www.coolpc.com.tw/evaluate.php)。價格以原價屋官網為準。
