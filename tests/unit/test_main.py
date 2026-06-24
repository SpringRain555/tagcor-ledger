import json
from pathlib import Path

from tagcor_ledger.main import main


def test_main_prints_json_startup_payload(capsys, tmp_path: Path) -> None:
    exit_code = main(["--data-dir", str(tmp_path / "ledger-data"), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["app"] == "TagCor Ledger"
    assert payload["data_dir"] == str((tmp_path / "ledger-data").resolve())
    assert payload["styles_available"] is True
