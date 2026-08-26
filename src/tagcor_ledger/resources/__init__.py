"""打包進安裝檔的資源：`styles.qss` 與勾選框的勾號 PNG。**不放字型檔。**

`check.png` / `check@2x.png` 是**產生出來的**，由 `tools/icons/make_check_icon.py`
畫出來 —— 要改形狀就改那支腳本再重跑，不要用繪圖軟體改，那樣兩個尺寸會對不起來。
為什麼非得是圖檔（而不是 SVG、data URI，或乾脆不覆寫）寫在那支腳本的模組說明裡。
"""
