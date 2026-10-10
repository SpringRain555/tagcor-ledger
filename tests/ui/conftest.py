"""`tests/ui/` 共用的 fixture。

## 為什麼是 fixture 而不是繼續各寫各的

這三行

    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

在 2026-08-22 之前重複了 **49 次**，而且**每一次都一模一樣**。重複本身還好，
麻煩的是它讓「這個測試有什麼不一樣」看不出來 —— 讀者要逐字比對三行才知道
某個測試是不是刻意不 `show()`。

抽成 fixture 之後，**還在手動建視窗的地方就是真的有理由的地方**，
而那個理由現在寫在各自的註解裡。

## 什麼時候不要用它

- 需要在 `show()` 之前 `resize()`（版面測試）。
- 刻意不 `show()`。
- 一個測試裡要開第二個視窗，或用同一個 data dir 重開。

這些情況直接自己建，不要為了共用而給 fixture 加參數 —— 加到第三個參數的時候，
fixture 自己就變成另一個要讀懂的東西了。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QMessageBox

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: Any, tmp_path: Path) -> Iterator[MainWindow]:
    """一個開好、顯示中、資料在 `tmp_path` 底下的主視窗。

    **資料一律在 `tmp_path`**，不會碰到真實帳本 —— `resolve_app_paths()` 收到明確的
    路徑時就不會去讀 `%LOCALAPPDATA%` 的指標檔。
    """
    main_window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(main_window)
    main_window.show()
    yield main_window


_REAL_EXEC = QMessageBox.exec
"""換掉之前的那一個，給 `use_real_dialogs` 用。"""


@dataclass(frozen=True)
class Notice:
    """一個提示框。`kind` 照圖示：`"warning"`（`notice.warn`）、`"information"`（`notice.inform`）。"""

    kind: str
    title: str
    text: str


@dataclass
class DialogStub:
    """UI 測試裡**每一個** `QMessageBox` 都經過這裡 —— 不會真的開出一個等人按的視窗。

    確認框（`widgets.confirm`）與提示框（`widgets.notice`）都是自己建 `QMessageBox` 再 `exec()`，
    所以攔一個 `QMessageBox.exec` 就全部攔到了：

    - **確認框**（有「是」那一顆）：照 `answer_confirmations()` 給的順序回答。
    - **提示框**（只有「確定」）：記進 `notices`，回「確定」。
    - **沒有預期到的**（沒給答案的確認框、沒要 `notices` 的提示框）：先當成「否」／「確定」
      讓程式走完，**測試結束時失敗**，訊息裡就是那個對話框的內容。給了答案卻沒被問到也一樣。

    以前每一條測試各自換掉 `QMessageBox.question`／`warning`／`information` 那幾個靜態函式，
    漏換一處的代價是**整包測試掛住**（modal 對話框在 offscreen 上沒有人按），而靜態函式在 C++
    那一側呼叫 exec，這裡攔不到（2026-10-09 實測）。現在全部走 Python 這一側，漏掉的是一條紅。
    """

    answers: list[bool] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    notices_expected: bool = False
    unexpected: list[str] = field(default_factory=list)
    use_real_dialogs: bool = False
    """真的開。只給 `test_confirm.py` 那幾條要看真的對話框（按 Enter、看按鈕上的字）的測試用。"""

    def exec(self, box: QMessageBox) -> int:
        if self.use_real_dialogs:
            return int(_REAL_EXEC(box))
        if box.button(QMessageBox.StandardButton.Yes) is not None:
            self.asked.append(box.text())
            if not self.answers:
                self.unexpected.append(f"沒給答案的確認框：{box.text()}")
                return int(QMessageBox.StandardButton.No.value)
            yes = self.answers.pop(0)
            button = QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No
            return int(button.value)
        kinds = {
            QMessageBox.Icon.Warning: "warning",
            QMessageBox.Icon.Information: "information",
        }
        self.notices.append(Notice(kinds.get(box.icon(), "other"), box.windowTitle(), box.text()))
        if not self.notices_expected:
            self.unexpected.append(f"沒預期的提示框：{box.windowTitle()}｜{box.text()}")
        return int(QMessageBox.StandardButton.Ok.value)


@pytest.fixture(autouse=True)
def dialog_stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[DialogStub]:
    """每一條 UI 測試都換掉 `QMessageBox.exec`（見 `DialogStub`）。"""
    stub = DialogStub()

    def fake_exec(box: QMessageBox) -> int:
        return stub.exec(box)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    yield stub
    problems = list(stub.unexpected)
    if stub.answers:
        problems.append(f"準備了 {len(stub.answers)} 個答案，確認框卻沒有出現那麼多次")
    if problems:
        pytest.fail("對話框跟預期的不一樣：\n  " + "\n  ".join(problems))


@pytest.fixture
def answer_confirmations(dialog_stub: DialogStub) -> Callable[..., list[str]]:
    """確認框**照順序回答**，回傳問過的話（對話框裡的文字）給斷言用：

        asked = answer_confirmations(False, True)   # 第一次按「否」、第二次按「是」

    答案用完之後又被問一次、或答案沒用完，測試結束時失敗 —— 問的次數變了就是行為變了。
    """

    def install(*answers: bool) -> list[str]:
        dialog_stub.answers.extend(answers)
        return dialog_stub.asked

    return install


@pytest.fixture
def notices(dialog_stub: DialogStub) -> list[Notice]:
    """要了這個 fixture 就表示**預期會出現提示框**；回傳收到的提示框，照出現的順序。"""
    dialog_stub.notices_expected = True
    return dialog_stub.notices


@pytest.fixture
def make_deposit() -> Callable[..., str]:
    """建一份**確定會產生待確認草稿**的定存，回傳 contract_id。

    四個檔案都要「有一件待確認」當前提，而它們踩的坑一模一樣，所以收在這裡。
    **是 fixture 不是普通函式** —— `tests/` 底下沒有 `__init__.py`，
    `pythonpath` 也只有 `src`，所以 `from tests.ui.conftest import …` 匯入不到。

    **`recorded_on` 一定要跟著首次起存日往前拉。** 產生待確認草稿的下界是合約的建檔日
    （ADR-0012），預設今天 —— 首次起存日填在很久以前但建檔日是今天的話，那一期在建檔
    之前就到期了，一件項目都不會產生。而 UI 測試沒辦法像 `generate_due(today=...)`
    那樣控制「今天」，它走的是真實時鐘。

    這正是使用者照存單抄日期會遇到的情形，只是在測試裡它會讓斷言悄悄變成
    「0 件也算通過」。
    """

    def build(
        controller: Any,
        *,
        name: str = "郵局定存",
        opened_on: str = "2020-01-15",
        generate: bool = True,
    ) -> str:
        account_id = str(controller.account_options()[0]["account_id"])
        result = controller.create_deposit_contract(
            account_id=account_id,
            name=name,
            interest_method="lump_sum",
            maturity_action="renew_principal_only",
            interest_destination_account_id=account_id,
            term_months=12,
            opened_on=opened_on,
            principal="100000",
            annual_rate_ppm=16_000,
            recorded_on=opened_on,
        )
        assert result.success, result.message
        if generate:
            # **合約建好不會自己產生事件** —— 那是啟動任務或定存頁那顆按鈕做的。
            assert controller.generate_deposit_events().success
        return str(result.details["contract_id"])

    return build
