# 找出專案 conda 環境的 python.exe，供各個 git hook `.` 進來共用。
#
# PowerShell 那一側的同一件事在 tools/Resolve-TagcorPython.ps1（Launch.ps1 與
# Verify.ps1 共用）。這裡是 POSIX shell，用不到那一份，但**認的是同一個環境變數
# `$TAGCOR_PYTHON`** —— 使用者設一次就四個地方都吃得到。
#
# 抽出來是因為 pre-commit 與 pre-push 都要用：各寫一份的話，改了一邊沒改另一邊
# 會變成「commit 擋得住但 push 擋不住」，而那種不一致很難聯想到根因。
#
# 找不到就回傳空字串，由呼叫端決定要停下來還是放行。

resolve_tagcor_python() {
	if [ -n "$TAGCOR_PYTHON" ] && [ -x "$TAGCOR_PYTHON" ]; then
		printf '%s' "$TAGCOR_PYTHON"
		return 0
	fi

	for base in "$USERPROFILE/miniconda3" "$USERPROFILE/anaconda3" \
	            "$LOCALAPPDATA/miniconda3" "$LOCALAPPDATA/anaconda3" \
	            "$HOME/miniconda3" "$HOME/anaconda3" \
	            "/c/miniconda3" "/c/anaconda3"; do
		if [ -x "$base/envs/tagcor-ledger/python.exe" ]; then
			printf '%s' "$base/envs/tagcor-ledger/python.exe"
			return 0
		fi
	done

	printf ''
	return 0
}
