"""預設路徑必須走 session 假資料，不能受每年更新的公開資料影響。"""

from pathlib import Path

from tagcor_ledger.application.tax.loader import default_tax_dataset_path, load_tax_dataset
from tagcor_ledger.domain.tax.freshness import assess_freshness
from tagcor_ledger.infrastructure.clock import today_taipei


def test_default_tax_dataset_uses_the_quiet_session_fixture() -> None:
    repo_dataset = (
        Path(__file__).resolve().parents[2] / "reference" / "tax" / "dataset.json"
    ).resolve()
    path = default_tax_dataset_path().resolve()
    assert path != repo_dataset
    load = load_tax_dataset(path)
    assert load.state.value == "ok"
    assert assess_freshness(
        today=today_taipei(),
        load=load,
        law_oldest_reviewed_at=None,
    ) == ()
