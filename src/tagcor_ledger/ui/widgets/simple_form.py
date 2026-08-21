"""一次問完的小表單。

## 為什麼需要它

「新增帳戶」與「新增項目」以前是**兩個連續的 `QInputDialog`**：先問名稱、按 OK，
再問期初餘額、再按一次 OK。那有三個問題：

1. **取消第二個，第一個輸入的東西靜靜消失。** 使用者以為自己取消的是「這一步」。
2. **看不到全貌。** 填第二格的時候，第一格填了什麼已經不在畫面上。
3. **改不了。** 發現名字打錯要整個重來。

`QInputDialog` 適合「只問一件事」。問到第二件事就該是一張表單。

## 用法

```python
values = ask_form(self, "新增項目", [
    ChoiceField("parent_id", "所屬類別", [(name, id) for ...]),
    TextField("name", "項目名稱"),
])
if values is None:      # 使用者按了取消
    return None
```

**`None` 代表取消，不是失敗。** 呼叫端要分得出這兩件事 —— 取消不該跳錯誤訊息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class TextField:
    """一格文字輸入。`required` 的欄位空白時「確定」是停用的。"""

    key: str
    label: str
    default: str = ""
    placeholder: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class ChoiceField:
    """一個下拉。`options` 是 `(顯示文字, 值)`，回傳的是**值**不是顯示文字。

    以前「新增項目」用 `QInputDialog.getItem()` 拿回顯示文字，再用
    `labels.index(selected)` 反查 id —— 名稱一重複就會挑到錯的那一個。
    """

    key: str
    label: str
    options: Sequence[tuple[str, Any]] = field(default_factory=tuple)


Field = TextField | ChoiceField


class SimpleFormDialog(QDialog):
    """幾個欄位 ＋ 確定／取消。填完按一次就好。"""

    def __init__(self, title: str, fields: Sequence[Field], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._fields = list(fields)
        self._widgets: dict[str, QLineEdit | QComboBox] = {}
        self._build()

    def _build(self) -> None:
        form = QFormLayout()
        form.setSpacing(10)
        for spec in self._fields:
            if isinstance(spec, ChoiceField):
                combo = QComboBox()
                for label, value in spec.options:
                    combo.addItem(label, value)
                self._widgets[spec.key] = combo
                form.addRow(spec.label, combo)
                continue
            line = QLineEdit(spec.default)
            if spec.placeholder:
                line.setPlaceholderText(spec.placeholder)
            line.textChanged.connect(self._sync_ok)
            # Enter 直接送出。這種對話框通常只有一兩格，手不必離開鍵盤。
            line.returnPressed.connect(self._accept_if_ready)
            self._widgets[spec.key] = line
            form.addRow(spec.label, line)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        # 第一格拿焦點，開起來就能打字。
        first = next(iter(self._widgets.values()), None)
        if first is not None:
            first.setFocus()
        self._sync_ok()

    def _sync_ok(self) -> None:
        """必填欄空白時停用「確定」。

        **不要讓使用者按下去才知道不行。** 空白名稱送到 store 會換來一個
        `..._NAME_REQUIRED` 的警告框，而那個訊息說的是使用者早就看得到的事。
        """
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.is_ready())

    def _accept_if_ready(self) -> None:
        if self.is_ready():
            self.accept()

    def is_ready(self) -> bool:
        for spec in self._fields:
            if isinstance(spec, TextField) and spec.required:
                widget = self._widgets[spec.key]
                if isinstance(widget, QLineEdit) and not widget.text().strip():
                    return False
        return True

    def values(self) -> dict[str, Any]:
        """`{key: 值}`。文字欄已經 `strip()` 過，下拉回傳的是 `userData`。"""
        result: dict[str, Any] = {}
        for spec in self._fields:
            widget = self._widgets[spec.key]
            if isinstance(widget, QComboBox):
                result[spec.key] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                result[spec.key] = widget.text().strip()
        return result


def ask_form(
    parent: QWidget, title: str, fields: Sequence[Field]
) -> dict[str, Any] | None:
    """開一張小表單。**取消回傳 `None`** —— 那不是失敗，呼叫端不要跳錯誤訊息。"""
    dialog = SimpleFormDialog(title, fields, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.values()
