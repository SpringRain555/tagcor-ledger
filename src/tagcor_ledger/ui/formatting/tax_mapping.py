"""所得歸類分頁使用的標籤、選項與資料列格式。"""

from __future__ import annotations

from tagcor_ledger.domain.tax.kinds import (
    INCOME_KIND_NAMES,
    INCOME_KIND_NOTES,
    TAX_KIND_NAMES,
    IncomeKind,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import TaxMappingRow
from tagcor_ledger.ui.formatting.primitives import group_digits
from tagcor_ledger.ui.formatting.tax import INCOME_KIND_SHORT


TAX_MAPPING_HEADERS = ["類別", "項目", "收入算作", "支出算作", "該年收入", "狀態"]
TAX_MAPPING_YEAR_LABEL = "所得年度"
TAX_MAPPING_WARNING = "{year}：{count} 筆收入（{amount} 元）未歸類。"
TAX_MAPPING_CONFIGURE_BUTTON = "設定歸類…"
TAX_MAPPING_DIALOG_TITLE = "設定所得歸類"
TAX_MAPPING_INCOME_LABEL = "收入算作"
TAX_MAPPING_EXPENSE_LABEL = "支出算作"
TAX_MAPPING_UNMAPPED = "未歸類"
TAX_MAPPING_NO_EXPENSE = "無"
TAX_MAPPING_SAVE_SUCCESS = "所得歸類已儲存。"
TAX_MAPPING_NO_CHANGE = "沒有變更。"
TAX_MAPPING_NOTE_LINES = (
    "項目留空就沿用類別；只有同一個類別底下性質不同時才需要設項目。",
    "歸類不分年度，改了會影響每一年的試算；程式不依名稱猜，全部由你選。",
)
TAX_MAPPING_INCOME_NOTES = INCOME_KIND_NOTES


def tax_mapping_income_options(
    row: TaxMappingRow,
) -> tuple[tuple[str, IncomeKind | None], ...]:
    if row.parent_id is None:
        inherit_label = TAX_MAPPING_UNMAPPED
    elif row.parent_income_kind is None:
        inherit_label = "沿用類別（類別還沒歸類）"
    else:
        inherit_label = f"沿用類別：{INCOME_KIND_NAMES[row.parent_income_kind]}"
    return ((inherit_label, None),) + tuple(
        (INCOME_KIND_NAMES[kind], kind) for kind in IncomeKind
    )


def tax_mapping_expense_options(
    row: TaxMappingRow,
) -> tuple[tuple[str, TaxKind | None], ...]:
    if row.parent_id is None:
        inherit_label = TAX_MAPPING_NO_EXPENSE
    elif row.parent_expense_kind is None:
        inherit_label = "沿用類別（無）"
    else:
        inherit_label = f"沿用類別：{TAX_KIND_NAMES[row.parent_expense_kind]}"
    return ((inherit_label, None),) + tuple(
        (TAX_KIND_NAMES[kind], kind) for kind in TaxKind
    )


def tax_mapping_warning(year: int, count: int, amount_minor: int) -> str:
    """所得歸類分頁未歸類收入的摘要；只由歸類列的年度實際值加總。"""
    return TAX_MAPPING_WARNING.format(
        year=year,
        count=group_digits(count),
        amount=group_digits(amount_minor),
    )


def tax_mapping_values(row: TaxMappingRow) -> list[str]:
    income_kind = row.income_kind
    if row.unmapped:
        state = "未歸類"
    elif income_kind is not None and row.parent_income_kind is not None:
        state = "已歸類（覆蓋類別）"
    elif income_kind is not None:
        state = "已歸類"
    elif row.effective_income_kind is not None:
        state = f"沿用類別：{INCOME_KIND_SHORT[row.effective_income_kind]}"
    else:
        state = "—"

    income_text = INCOME_KIND_SHORT[income_kind] if income_kind is not None else "—"
    expense_text = TAX_KIND_NAMES[row.expense_kind] if row.expense_kind is not None else "—"
    annual_income = (
        f"{row.year_count} 筆 {group_digits(row.year_minor)} 元"
        if row.year_count > 0
        else "—"
    )
    return [
        row.category_name,
        row.item_name or "—",
        income_text,
        expense_text,
        annual_income,
        state,
    ]
