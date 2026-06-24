from tagcor_ledger.application.tags import TagCatalog
from tagcor_ledger.domain.models import TagPath
from tagcor_ledger.infrastructure.repositories import default_tags


def test_tag_catalog_resolves_default_path_snapshot() -> None:
    catalog = TagCatalog(default_tags("2026-05-08T08:30:00+08:00"))

    path = catalog.default_path()
    snapshot = catalog.snapshot_for_path(path)

    assert path == TagPath("tag_expense", "tag_cash", "tag_food", "tag_711")
    assert snapshot.as_tuple() == ("支出", "現金", "伙食", "7-11")
