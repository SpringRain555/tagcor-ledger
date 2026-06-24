from pathlib import Path

from tagcor_ledger.app.bootstrap import bootstrap


def test_bootstrap_returns_startup_context(tmp_path: Path) -> None:
    context = bootstrap(data_dir=tmp_path / "ledger-data")

    assert context.paths.data_dir == (tmp_path / "ledger-data").resolve()
    assert context.styles_available is True
