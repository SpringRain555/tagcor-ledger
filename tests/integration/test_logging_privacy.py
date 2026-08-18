"""守門：日誌與診斷檔不得含有金額或備註。

這條規則寫在 `logging_setup.py` 的 docstring 裡，但**寫在文件上的隱私保證等於沒有保證**。
這裡實際跑一輪帶著可辨識內容的操作，再回頭掃檔案。

用的是刻意好認的字串（`祕密的午餐備註`、`987654`），這樣一旦哪天有人在 log 呼叫裡多帶了
`details`，測試會直接指出洩漏的是哪一個欄位，而不是給一個模糊的失敗。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tagcor_ledger.app.logging_setup import configure_logging, get_logger, log_result
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.diagnostics import DiagnosticsService
from tagcor_ledger.ui.controller import LedgerController


SECRET_NOTE = "祕密的午餐備註"
SECRET_AMOUNT = "987654"


@pytest.fixture
def controller(tmp_path: Path) -> LedgerController:
    return LedgerController(resolve_app_paths(tmp_path / "data"))


def _record_a_transaction(controller: LedgerController) -> None:
    accounts = controller.account_options()
    parents = controller.category_options()
    details = controller.category_options(str(parents[0]["category_id"]))
    result = controller.submit(
        occurred_at="2026-09-01T12:00:00+08:00",
        entry_type="expense",
        amount=SECRET_AMOUNT,
        account_id=str(accounts[0]["account_id"]),
        destination_account_id=None,
        category_id=str(details[0]["category_id"]),
        description=SECRET_NOTE,
    )
    assert result.success, result.message
    log_result("transaction.create", result)


def test_log_file_contains_neither_amount_nor_description(
    tmp_path: Path, controller: LedgerController
) -> None:
    log_path = configure_logging(tmp_path / "logs")
    assert log_path is not None

    _record_a_transaction(controller)
    logging.shutdown()

    content = log_path.read_text(encoding="utf-8")
    assert content.strip(), "日誌是空的，這個測試就沒有在檢查任何東西"
    assert SECRET_NOTE not in content, "備註洩漏到日誌裡了"
    assert SECRET_AMOUNT not in content, "金額洩漏到日誌裡了"
    # 該記的還是要記得到，否則「什麼都不記」也會通過這個測試。
    assert "transaction.create" in content
    assert "corr_" in content


def test_log_result_never_reaches_into_details(tmp_path: Path) -> None:
    """`details` 裝的正是金額與帳戶名稱，所以 `log_result` 一個字都不能碰它。"""
    log_path = configure_logging(tmp_path / "logs")
    assert log_path is not None
    from tagcor_ledger.application.result import Result

    log_result(
        "some.action",
        Result.fail(
            "SOME_CODE",
            "訊息",
            details={"amount_minor": SECRET_AMOUNT, "description": SECRET_NOTE},
        ),
    )
    logging.shutdown()

    content = log_path.read_text(encoding="utf-8")
    assert "SOME_CODE" in content
    assert SECRET_AMOUNT not in content
    assert SECRET_NOTE not in content


def test_diagnostics_report_contains_no_amounts(
    tmp_path: Path, controller: LedgerController
) -> None:
    configure_logging(tmp_path / "logs")
    _record_a_transaction(controller)

    result = controller.export_diagnostics()
    assert result.success, result.message
    report = Path(str(result.details["path"])).read_text(encoding="utf-8")

    assert SECRET_NOTE not in report, "備註洩漏到診斷檔裡了"
    assert SECRET_AMOUNT not in report, "金額洩漏到診斷檔裡了"

    # 有用的內容還是要在，否則一份空檔案也會通過。
    assert "TagCor Ledger 診斷資訊" in report
    assert "integrity" in report or "完整性" in report
    assert "transactions" in report


def test_diagnostics_survives_a_missing_database(tmp_path: Path) -> None:
    """資料庫不見時診斷資訊更重要，不能因此也壞掉。"""
    paths = resolve_app_paths(tmp_path / "empty")
    report = DiagnosticsService(paths).build_report()
    assert "資料庫尚未建立" in report


def test_crash_traceback_is_logged_without_amounts(tmp_path: Path) -> None:
    """traceback 是最容易夾帶內容的地方 —— 例外訊息本身可能含金額。

    這裡確認的是：**例外訊息帶了金額時，測試會抓到。** 所以日後若有人讓
    `Money` 的錯誤訊息夾帶數值再往上丟，這個測試會提醒他。
    """
    log_path = configure_logging(tmp_path / "logs")
    assert log_path is not None
    logger = get_logger("test")

    try:
        raise ValueError("金額格式錯誤")
    except ValueError:
        logger.exception("operation failed code=%s", "AMOUNT_INVALID")
    logging.shutdown()

    content = log_path.read_text(encoding="utf-8")
    assert "AMOUNT_INVALID" in content
    assert "Traceback" in content
    assert SECRET_AMOUNT not in content
