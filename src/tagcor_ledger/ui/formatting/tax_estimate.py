"""綜合所得稅試算分頁使用的文字與明細格式。"""

from __future__ import annotations

from collections.abc import Mapping

from tagcor_ledger.domain.tax.dataset import TaxSource
from tagcor_ledger.domain.tax.estimate import (
    ESTIMATE_CAUTION_NAMES,
    ESTIMATE_STEP_NAMES,
    UNSUPPORTED_REASON_NAMES,
    Estimate,
    EstimateLine,
    EstimateStep,
    LineSource,
    UnsupportedReason,
)
from tagcor_ledger.domain.tax.kinds import (
    DEDUCTION_CHOICE_NAMES,
    FILING_STATUS_NAMES,
    INCOME_KIND_NAMES,
    OVERRIDABLE_INCOME_KINDS,
    DeductionChoice,
    FilingStatus,
    IncomeKind,
)
from tagcor_ledger.ui.formatting.primitives import group_digits


ESTIMATE_FOOTER = "這是估計，不是申報；以財政部稅額試算為準；不會改動帳本任何金額。"
TAX_ESTIMATE_HEADERS = ["步驟", "金額", "依據"]
TAX_OVERRIDE_HEADERS = ("所得類別", "給付總額", "扣繳稅額")
TAX_ESTIMATE_INPUT_TITLE = "輸入"
TAX_ESTIMATE_RESULT_TITLE = "試算結果"
TAX_ESTIMATE_YEAR_LABEL = "所得年度"
TAX_ESTIMATE_IN_PROGRESS = "年度進行中"
TAX_ESTIMATE_FILING_LABEL = "申報方式"
TAX_ESTIMATE_DEDUCTION_LABEL = "扣除方式"
TAX_ESTIMATE_OTHER_SPECIAL_LABEL = "有其他特別扣除"
TAX_ESTIMATE_DEPENDENT_INCOME_LABEL = "受扶養人有所得"
TAX_ESTIMATE_FILER_70_PLUS_LABEL = "本人 70 歲以上"
TAX_ESTIMATE_DEPENDENTS_LABEL = "受扶養人數"
TAX_ESTIMATE_DEPENDENTS_70_PLUS_LABEL = "其中免稅額增加 50% 的人數"
TAX_ESTIMATE_DEPENDENTS_70_PLUS_NOTE = (
    "70 歲以上的受扶養直系尊親屬；115 年度起也包括未成年的受扶養子女（所得稅法第 17 條）。"
)
TAX_ESTIMATE_OVERRIDE_TITLE = "扣繳憑單"
TAX_ESTIMATE_OVERRIDE_GROSS_LABEL = "給付總額"
TAX_ESTIMATE_OVERRIDE_WITHHELD_LABEL = "扣繳稅額"
TAX_ESTIMATE_OVERRIDE_BLANK_NOTE = "兩格都留白就使用帳本資料；個別留白的欄位也使用帳本資料。"
TAX_ESTIMATE_OFFICIAL_TITLE = "財政部結果（對答案）"
TAX_ESTIMATE_OFFICIAL_TAX_LABEL = "應納稅額"
TAX_ESTIMATE_OFFICIAL_BALANCE_LABEL = "應補／應退"
TAX_ESTIMATE_BALANCE_DUE = "應補"
TAX_ESTIMATE_BALANCE_REFUND = "應退"
TAX_ESTIMATE_AMOUNT_PLACEHOLDER = "整數元"
TAX_ESTIMATE_AMOUNT_ERROR = "金額只能填非負整數元，不要加逗號、小數、單位或空白。"
TAX_ESTIMATE_SAVE_BUTTON = "儲存並試算"
TAX_ESTIMATE_UNSAVED_RESULT = "按左邊的「儲存並試算」才會算。"
TAX_ESTIMATE_LEDGER_HINT = "帳本：{count} 筆 {amount} 元"
TAX_ESTIMATE_SAVE_SUCCESS = "申報狀況與扣繳憑單已儲存。"
TAX_ESTIMATE_REFUSAL_FOOTER = "請改用財政部稅額試算。"
_FOOTNOTE_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CAPPED_STEPS = {EstimateStep.SALARY_DEDUCTION, EstimateStep.SAVINGS_DEDUCTION}

TAX_FILING_OPTIONS: tuple[tuple[str, FilingStatus], ...] = tuple(
    (FILING_STATUS_NAMES[kind], kind) for kind in FilingStatus
)
TAX_DEDUCTION_OPTIONS: tuple[tuple[str, DeductionChoice], ...] = tuple(
    (DEDUCTION_CHOICE_NAMES[kind], kind) for kind in DeductionChoice
)
TAX_OVERRIDE_OPTIONS: tuple[tuple[str, IncomeKind], ...] = tuple(
    (INCOME_KIND_NAMES[kind], kind)
    for kind in IncomeKind
    if kind in OVERRIDABLE_INCOME_KINDS
)


def tax_estimate_unsaved_note(source_year: int | None) -> str:
    """說明未儲存年度的預填來源，或目前使用的預設值。"""
    if source_year is None:
        return (
            "這一年還沒存過，先用預設值（自己單獨申報、標準扣除、沒有受扶養人）；"
            "按「儲存並試算」才會算。"
        )
    return f"這一年還沒存過，先帶入 {source_year} 年度的設定；按「儲存並試算」才會算。"


def estimate_status(estimate: Estimate) -> str:
    if estimate.refused or estimate.balance_minor is None:
        return "這一年不試算。"
    balance = estimate.balance_minor
    if balance > 0:
        status = f"估計：應補 {group_digits(balance)} 元"
    elif balance < 0:
        status = f"估計：應退 {group_digits(abs(balance))} 元"
    else:
        status = "估計：不用補也沒得退"
    if estimate.filing_exempt:
        status += "；所得沒有超過免稅額加標準扣除額，依所得稅法第 71 條可以不申報。"
    return status


def refusal_lines(estimate: Estimate) -> list[str]:
    lines: list[str] = []
    needs_official_estimate = False
    for reason in estimate.refused:
        if reason in {
            UnsupportedReason.DATASET_UNAVAILABLE,
            UnsupportedReason.PARAMETERS_MISSING,
        }:
            advice = "照資料狀態分頁的指示更新資料。"
        elif reason is UnsupportedReason.BASIC_LIVING_PENDING:
            advice = "等財政部 11 月底公告後再更新資料。"
        elif reason is UnsupportedReason.INPUTS_MISSING:
            advice = "先填這一年的申報狀況。"
        elif reason is UnsupportedReason.UNMAPPED_INCOME:
            advice = "到所得歸類分頁把收入歸類。"
        else:
            lines.append(UNSUPPORTED_REASON_NAMES[reason])
            needs_official_estimate = True
            continue
        lines.append(f"{UNSUPPORTED_REASON_NAMES[reason]} {advice}")
    if needs_official_estimate:
        lines.append(TAX_ESTIMATE_REFUSAL_FOOTER)
    return lines


def estimate_line_values(
    line: EstimateLine,
    *,
    footnotes: Mapping[str, str] | None = None,
) -> list[str]:
    amount = (
        f"-{group_digits(abs(line.amount_minor))}"
        if line.step is EstimateStep.BALANCE and line.amount_minor < 0
        else group_digits(line.amount_minor)
    )
    # 照註腳編號的順序排（`footnotes` 依編號建立），不是照這一行 source_ids 的順序 ——
    # 否則會出現「公告③②」。
    wanted = set(line.source_ids)
    markers = "".join(
        mark for source_id, mark in (footnotes or {}).items() if source_id in wanted
    )
    if line.source is LineSource.LEDGER:
        basis = f"帳本 {line.ledger_count} 筆"
    elif line.source is LineSource.MANUAL:
        basis = "扣繳憑單（你填的）"
    elif line.source is LineSource.DATASET:
        basis = f"公告{markers}"
    else:
        if markers and line.step in _CAPPED_STEPS:
            basis = f"計算（上限{markers}）"
        else:
            basis = f"計算{markers}"
    if line.step is EstimateStep.EXEMPT_INCOME:
        basis += "（依你的歸類）"
    return [ESTIMATE_STEP_NAMES[line.step], amount, basis]


def estimate_source_footnote_markers(estimate: Estimate) -> dict[str, str]:
    """依明細第一次出現的順序，為來源編號。"""
    source_ids = dict.fromkeys(
        source_id for line in estimate.lines for source_id in line.source_ids
    )
    return {
        source_id: _FOOTNOTE_MARKS[index]
        if index < len(_FOOTNOTE_MARKS)
        else f"({index + 1})"
        for index, source_id in enumerate(source_ids)
    }


def estimate_source_footnotes(
    estimate: Estimate, sources: Mapping[str, TaxSource]
) -> list[str]:
    """依明細第一次出現的順序，產生來源標題註腳。"""
    markers = estimate_source_footnote_markers(estimate)
    return [
        f"{marker} {sources[source_id].title if source_id in sources else source_id}"
        for source_id, marker in markers.items()
    ]


def caution_lines(estimate: Estimate) -> list[str]:
    return [ESTIMATE_CAUTION_NAMES[caution] for caution in estimate.cautions]


def official_diff_text(estimate: Estimate) -> str | None:
    difference = estimate.official_diff_minor
    if difference is None:
        return None
    if difference == 0:
        return "與財政部相同。"
    sign = "+" if difference > 0 else "-"
    return (
        f"與財政部相差 {sign}{group_digits(abs(difference))} 元。"
        "常見原因：用了實領而非給付總額、漏記收入、扣繳沒填、歸類錯。"
    )


def tax_estimate_ledger_hint(count: int, amount_minor: int) -> str:
    """試算輸入旁顯示的帳本基準數字。"""
    return TAX_ESTIMATE_LEDGER_HINT.format(
        count=group_digits(count), amount=group_digits(amount_minor)
    )
