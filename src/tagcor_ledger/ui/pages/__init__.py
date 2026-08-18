"""側邊欄六個主頁，以及它們底下的分頁與對話框。

一個檔案 = 一個畫面。頁面之間不互相 import，要互動就往上發 Qt Signal，由
`tagcor_ledger.ui.main_window.MainWindow` 接起來 —— 這樣「按了 A 會影響 B」這件事
只會出現在一個地方。
"""
