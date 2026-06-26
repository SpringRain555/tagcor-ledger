from pathlib import Path

from tagcor_ledger.app.path_settings import (
    PathSettingsError,
    PathSettingsService,
    SystemPathSettings,
)
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
)
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore
from tagcor_ledger.ui.controller import LedgerController


def test_path_settings_validate_separate_writable_directories(tmp_path: Path) -> None:
    service = PathSettingsService(tmp_path / "system_paths.json")
    saved = service.save(
        SystemPathSettings(
            ledger_dir=tmp_path / "ledger",
            backup_dir=tmp_path / "backups",
        )
    )

    assert saved.ledger_dir.is_dir()
    assert saved.backup_dir.is_dir()
    assert service.load() == saved

    try:
        service.save(
            SystemPathSettings(
                ledger_dir=tmp_path / "same",
                backup_dir=tmp_path / "same",
            )
        )
    except PathSettingsError as exc:
        assert str(exc) == "LEDGER_BACKUP_PATH_SAME"
    else:
        raise AssertionError("same ledger/backup path should be rejected")


def test_controller_moves_data_and_manual_backup_goes_to_backup_dir(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "app")
    controller = LedgerController(paths)
    controller.path_settings = PathSettingsService(tmp_path / "system_paths.json")
    assert controller.submit(
        occurred_at="2026-06-01T10:00:00+08:00",
        entry_type="expense",
        amount="10",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="搬移前資料",
    ).success

    result = controller.save_path_settings(
        ledger_dir=tmp_path / "ledger-dir",
        backup_dir=tmp_path / "backup-dir",
        move_current=True,
    )

    assert result.success
    assert controller.paths.database_path == tmp_path / "ledger-dir" / "ledger.sqlite3"
    assert controller.paths.database_path.is_file()
    backup = controller.create_backup()
    assert backup.parent == tmp_path / "backup-dir"
    assert (backup / "backup_manifest.json").is_file()


def test_reset_reinitializes_ledger_without_deleting_backups(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "app")
    controller = LedgerController(paths)
    assert controller.submit(
        occurred_at="2026-06-01T10:00:00+08:00",
        entry_type="expense",
        amount="10",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="重製前",
    ).success
    backup = controller.create_backup()

    controller.reset_ledger(create_backup_first=False)

    assert backup.is_dir()
    assert LedgerStore(controller.paths).account_balance_minor("acct_cash") == 0


def test_delete_only_unused_accounts_and_categories(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "app")
    store = LedgerStore(paths)
    accounts = AccountService(paths, store)
    categories = CategoryService(paths, store)

    unused_account = str(accounts.create(name="未使用帳戶").details["account_id"])
    assert accounts.delete(unused_account).success
    assert not accounts.delete("acct_cash").success

    parent = str(categories.create(name="測試類別").details["category_id"])
    child = str(categories.create(name="測試項目", parent_id=parent).details["category_id"])
    assert not categories.delete(parent).success
    assert categories.delete(child).success
    assert categories.delete(parent).success

    assert AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-01T10:00:00+08:00",
            entry_type="expense",
            amount="10",
            category_id="cat_food_711",
        )
    ).success
    assert not categories.delete("cat_food_711").success
