"""守門：每一個會冒到使用者面前的錯誤碼都要有中文說法，而且原文不准上畫面。

這一組測試守的是 2026-08-21 那次整理的三條結論：

1. **寫入層丟的碼就是這次操作的錯誤碼**，不要塌成一個籠統的 `*_FAILED`。
2. **每個碼要有自己的一句話**，寫在 `application/failures.py` 的對照表裡。
3. **`details["reason"]` 已經廢除** —— 那個 key 曾經是 `result_message()` 用括號
   接在畫面訊息後面的東西，於是英文碼與 SQLite 原文都會被印給使用者看。

第 3 條特別需要守門：它是**加一行就會回來的**錯誤。寫 `details={"reason": str(exc)}`
在 51 個地方都曾經是「這裡照著上面抄」的自然結果。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tagcor_ledger.application.failures import ERROR_MESSAGES, failure, message_for
from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.formatting import error_text, result_message


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger"

RAISED_INDIRECTLY = {
    # `_occurrence_invalid_reason()` 把它 `return` 出來，呼叫端才
    # `raise ValueError(invalid)` —— 掃 `raise` 的常數參數看不到它。
    "DESTINATION_ACCOUNT_NOT_ACTIVE",
    # `validate_backup()` 把碼放在**回傳的 dict** 裡（`{"error_code": …}`），
    # 由 `restore_backup()` 轉成 `raise ValueError(str(validation["error_code"]))`。
    # 同樣掃不到。這一組會直接印到「還原失敗」對話框上。
    "BACKUP_FILES_MISSING",
    "BACKUP_MANIFEST_INVALID",
    "BACKUP_CHECKSUM_MISMATCH",
    "BACKUP_SCHEMA_MISSING",
    "BACKUP_SCHEMA_TOO_NEW",
}

STARTUP_ONLY = {
    # 啟動階段的失敗**還沒有主視窗**，所以走不到 `Result` 也走不到
    # `result_message()`。它們的中文由 `app/startup.py` 自己寫成對話框的標題與內文
    # （`state-machines.md` §6）。收進 ERROR_MESSAGES 只會變成第二份說法。
    "ALREADY_RUNNING",
    "DATABASE_SCHEMA_TOO_NEW",
}


def _raised_codes() -> dict[str, set[str]]:
    """`raise SomeError("CODE")` 的碼 → 出現的檔案。

    只認**常數**參數。`raise ValueError(invalid)` 這種變數參數抓不到，那正是
    `RAISED_INDIRECTLY` 存在的理由。
    """
    found: dict[str, set[str]] = {}
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            if not node.exc.args:
                continue
            first = node.exc.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                text = first.value
                if text.isupper() and " " not in text and len(text) > 3:
                    found.setdefault(text, set()).add(relative)
    return found


def _reason_details() -> list[str]:
    """所有把 `reason` 當 key 塞進 `details={...}` 的地方。"""
    hits: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "details" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and key.value == "reason":
                        hits.append(f"  {relative}:{key.lineno}")
    return hits


def test_the_extractor_actually_finds_raises() -> None:
    """陽性對照：抓不到 raise 的話，底下那條「每個碼都要有說法」會空過。"""
    raised = _raised_codes()
    assert len(raised) > 40, f"只抓到 {len(raised)} 個 raise 的錯誤碼，走訪可能壞了"
    assert "ACCOUNT_IS_DEFAULT" in raised
    assert "infrastructure/stores/accounts.py" in raised["ACCOUNT_IS_DEFAULT"]


def test_every_raised_code_has_a_chinese_message() -> None:
    """底層 raise 的每一個碼都要能翻成中文。

    翻不出來的碼會走 `failure()` 的退路：使用者看到籠統的 `*_FAILED` 訊息，
    而真正發生的那件事只留在 `details["detail"]` 裡 —— 畫面上看不到。
    """
    missing = sorted(set(_raised_codes()) - set(ERROR_MESSAGES) - STARTUP_ONLY)
    if missing:
        raised = _raised_codes()
        lines = [f"  {code}  （raise 在 {', '.join(sorted(raised[code]))}）" for code in missing]
        pytest.fail(
            "以下錯誤碼會被丟出來，但 application/failures.py 沒有給它們中文說法：\n"
            + "\n".join(lines)
            + "\n每一個都要在 ERROR_MESSAGES 加一列，說法要寫「使用者接下來該做什麼」。"
        )


def test_the_startup_exemptions_really_are_handled_at_startup() -> None:
    """豁免清單不能變成垃圾桶：每一個都要真的在 `app/startup.py` 有自己的說法。"""
    startup = (SOURCE_ROOT / "app" / "startup.py").read_text(encoding="utf-8")
    for code in sorted(STARTUP_ONLY):
        assert code in startup, (
            f"{code} 掛在 STARTUP_ONLY 豁免清單裡，但 app/startup.py 沒有處理它 ——"
            "它現在沒有任何中文說法。"
        )


def test_no_message_is_orphaned() -> None:
    """對照表裡不該有沒人丟的碼 —— 那代表功能移除了但表格忘了清。"""
    orphans = sorted(set(ERROR_MESSAGES) - set(_raised_codes()) - RAISED_INDIRECTLY)
    assert not orphans, (
        "以下碼在 ERROR_MESSAGES 裡但程式沒有任何地方丟它：\n"
        + "\n".join(f"  {code}" for code in orphans)
    )


def test_no_message_is_english_or_a_bare_code() -> None:
    """每一句都要是中文句子，不能是英文，也不能只是把碼抄一遍。"""
    for code, message in ERROR_MESSAGES.items():
        assert message != code, f"{code} 的說法就是碼本身"
        assert any("一" <= char <= "鿿" for char in message), (
            f"{code} 的說法裡沒有中文：{message}"
        )
        assert message.strip() == message, f"{code} 的說法前後有空白"


def _failure_message_literals() -> list[tuple[str, int, str]]:
    """`Result.fail(碼, 訊息)` 的第二個位置參數，以及 `fallback_message=`。"""
    found: list[tuple[str, int, str]] = []

    def text_of(node: ast.expr) -> str | None:
        """常數字串，或整段都是常數的隱式相接（`"a" "b"`）。"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return None
        return None

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name == "fail" and len(node.args) >= 2:
                message = text_of(node.args[1])
                if message:
                    found.append((relative, node.args[1].lineno, message))
            for keyword in node.keywords:
                if keyword.arg == "fallback_message":
                    message = text_of(keyword.value)
                    if message:
                        found.append((relative, keyword.value.lineno, message))
    return found


def test_displayed_text_has_no_markdown() -> None:
    """畫面上的字裡不能有 `**` 或反引號 —— **沒有任何 widget 會把它們算成格式**。

    整份程式沒有一處 `setTextFormat(MarkdownText)` 或 `RichText`，所以
    `QMessageBox` 與 `QLabel` 拿到 `**不要還原它**` 就原封不動印出星號。
    寫文件的手感很容易帶到訊息字串裡 —— 那些強調語法在 `.md` 裡是對的，在這裡不是。
    """
    offenders = [
        f"  ERROR_MESSAGES[{code!r}]：{message}"
        for code, message in ERROR_MESSAGES.items()
        if "**" in message or "`" in message
    ]
    offenders += [
        f"  {relative}:{line}：{message}"
        for relative, line, message in _failure_message_literals()
        if "**" in message or "`" in message
    ]
    assert not offenders, (
        "以下要顯示給使用者的字裡有 markdown 語法，會原樣印出來：\n" + "\n".join(offenders)
    )


def test_the_message_literal_extractor_finds_something() -> None:
    """陽性對照：抽不到訊息的話，上面那條會空過。

    **兩條路徑要各驗一個只有它才抽得到的句子。** 只斷言「總數夠多」或挑一句兩邊都
    有的話，關掉其中一條路徑測試照樣會過 —— 第一版就是這樣，是陽性對照跑出來才發現的。
    """
    literals = _failure_message_literals()
    assert len(literals) > 30, f"只抽到 {len(literals)} 句訊息，AST 走訪可能壞了"
    messages = [message for _, _, message in literals]
    # 只出現在 `Result.fail(碼, 訊息)` 的第二個位置參數。
    assert any("請輸入帳戶名稱" in message for message in messages), "Result.fail 這條路徑沒抽到"
    # 只出現在 `fallback_message=`（「請匯出診斷資訊回報」兩條路徑都有，不能用它）。
    assert any("認不出原因" in message for message in messages), (
        "fallback_message 這條路徑沒抽到"
    )


def test_nothing_puts_a_reason_into_result_details() -> None:
    """`details["reason"]` 是廢除的 key。**加回來就紅。**

    它曾經有 51 個出處。`result_message()` 會把它用括號接在畫面訊息後面，於是
    `ACCOUNT_IS_DEFAULT`、`CATEGORY_HAS_ACTIVE_CHILDREN` 這些英文碼，以及
    `UNIQUE constraint failed: accounts.name` 這種 SQLite 原文，都被印給使用者看。
    要留原文就用 `details["detail"]` —— 那個 key 不會顯示。
    """
    hits = _reason_details()
    assert not hits, (
        "以下地方把原文塞進 details[\"reason\"]，它會被印在畫面上：\n"
        + "\n".join(hits)
        + '\n改用 details["detail"]，或改成 application/failures.py 的 failure()。'
    )


def test_result_message_shows_only_the_message() -> None:
    """就算 `details` 裡有 reason 與 detail，畫面上也只有 `message`。"""
    result = Result.fail(
        "ACCOUNT_DELETE_FAILED",
        "帳戶無法刪除。",
        details={"reason": "ACCOUNT_IS_DEFAULT", "detail": "UNIQUE constraint failed"},
    )
    assert result_message(result) == "帳戶無法刪除。"


def test_failure_uses_the_specific_code_not_the_fallback() -> None:
    """認得出來的碼要**取代**退路碼，而不是被塞進 details。"""
    result = failure(
        ValueError("ACCOUNT_IS_DEFAULT"),
        fallback_code="ACCOUNT_DELETE_FAILED",
        fallback_message="帳戶無法刪除。請匯出診斷資訊回報。",
    )
    assert result.error_code == "ACCOUNT_IS_DEFAULT"
    assert "預設帳戶" in result.message
    assert result.details == {}
    # 畫面上不該再出現那串英文碼。
    assert "ACCOUNT_IS_DEFAULT" not in result_message(result)


def test_failure_keeps_unknown_text_out_of_the_message() -> None:
    """認不出來的原文走 `detail`，畫面上只有退路訊息。"""
    result = failure(
        RuntimeError("UNIQUE constraint failed: accounts.name"),
        fallback_code="ACCOUNT_DELETE_FAILED",
        fallback_message="帳戶無法刪除。請匯出診斷資訊回報。",
    )
    assert result.error_code == "ACCOUNT_DELETE_FAILED"
    assert result.details["detail"] == "UNIQUE constraint failed: accounts.name"
    assert "UNIQUE" not in result_message(result)


def test_overrides_win_over_the_default_message() -> None:
    """呼叫端能給更貼近情境的說法（恢復撞名時該處理的是**另外**那一個）。"""
    result = failure(
        ValueError("ACCOUNT_ACTIVE_NAME_CONFLICT"),
        fallback_code="ACCOUNT_RESTORE_FAILED",
        fallback_message="帳戶無法恢復。",
        overrides={"ACCOUNT_ACTIVE_NAME_CONFLICT": "請先把那一個改名或封存。"},
    )
    assert result.error_code == "ACCOUNT_ACTIVE_NAME_CONFLICT"
    assert result.message == "請先把那一個改名或封存。"


def test_a_broken_backup_explains_itself_in_chinese(tmp_path: Path) -> None:
    """還原一份壞掉的備份時，對話框上要是中文，不是 `BACKUP_CHECKSUM_MISMATCH`。

    這條路徑特別容易被忽略：碼是 `validate_backup()` **回傳**的，不是 raise 的，
    所以 `test_error_codes.py` 掃不到它，而維護頁又直接 `str(exc)` 印出來。
    """
    from tagcor_ledger.app.paths import resolve_app_paths
    from tagcor_ledger.infrastructure.maintenance import MaintenanceService
    from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

    paths = resolve_app_paths(tmp_path / "ledger")
    LedgerStore(paths)
    maintenance = MaintenanceService(paths)
    backup_dir = maintenance.create_backup(reason="test")

    # 竄改資料庫檔，讓它與清單裡的雜湊對不起來。
    (backup_dir / "ledger.sqlite3").write_bytes(b"not a database")
    assert maintenance.validate_backup(backup_dir)["error_code"] == "BACKUP_CHECKSUM_MISMATCH"

    with pytest.raises(ValueError) as caught:
        maintenance.restore_backup(backup_dir)
    shown = error_text(caught.value, fallback="不該用到這個退路")
    assert "不該用到" not in shown
    assert "不要還原" in shown
    assert "BACKUP_CHECKSUM_MISMATCH" not in shown

    # 清單檔壞掉是另一件事，說法也要不一樣。
    (backup_dir / "backup_manifest.json").write_text("{ broken", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        maintenance.restore_backup(backup_dir)
    other = error_text(caught.value, fallback="不該用到這個退路")
    assert other != shown, "兩種不同的壞法講了同一句話"


def test_money_errors_reach_the_screen_in_chinese() -> None:
    """金額打錯是最常見的操作失誤，**那句話一定要是中文**。

    以前 `MoneyError` 帶的是 `"Amount must be greater than zero."`，而待確認頁與
    模板對話框直接印 `str(exc)` —— 全中文介面裡的一句英文。
    """
    from tagcor_ledger.domain.money import Money, MoneyError

    for value, expected_code in (("0", "AMOUNT_NOT_POSITIVE"), ("1,200", "AMOUNT_FORMAT_INVALID")):
        with pytest.raises(MoneyError) as caught:
            Money.from_decimal_string(value)
        assert str(caught.value) == expected_code
        shown = error_text(caught.value, fallback="不該用到這個退路")
        assert shown == message_for(expected_code)
        assert "不該用到" not in shown
        assert not any(char.isascii() and char.isalpha() for char in shown), shown
