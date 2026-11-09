"""稅務畫面使用的名稱、句子與表格列。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from tagcor_ledger.application.tax.data import TaxDataStatus
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
from tagcor_ledger.domain.tax.freshness import (
    FRESHNESS_SENTENCES,
    FreshnessIssue,
    FreshnessProblem,
)
from tagcor_ledger.domain.tax.kinds import (
    TAX_KIND_ACTIONS,
    TAX_KIND_NAMES,
    IncomeKind,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import TaxMappingRow
from tagcor_ledger.domain.tax.reminders import (
    ReminderState,
    ReminderSwitch,
    ReminderView,
    days_left,
)
from tagcor_ledger.ui.formatting.primitives import display_date, group_digits

if TYPE_CHECKING:
    from tagcor_ledger.ui.controller.tax import TaxOverview


REMINDER_STATE_NAMES = {
    ReminderState.DISABLED: "不提醒",
    ReminderState.UNSET: "未設定",
    ReminderState.NO_WINDOW: "沒有期間資料",
    ReminderState.HANDLED: "已處理",
    ReminderState.NOT_APPLICABLE: "本年不適用",
    ReminderState.PAID: "已繳",
    ReminderState.DORMANT: "未到",
    ReminderState.UPCOMING: "即將開始",
    ReminderState.OPEN: "期間中",
    ReminderState.OVERDUE: "已過期限",
}

SWITCH_NAMES = {
    ReminderSwitch.ON: "開",
    ReminderSwitch.OFF: "關",
    ReminderSwitch.UNSET: "未設定",
}

INCOME_KIND_SHORT = {
    IncomeKind.SALARY: "薪資所得",
    IncomeKind.INTEREST_TAXABLE: "利息所得（應稅）",
    IncomeKind.INTEREST_EXEMPT: "利息（免稅）",
    IncomeKind.PRIZE: "競賽／中獎獎金",
    IncomeKind.WRITING_LECTURE: "稿費、講演鐘點費",
    IncomeKind.EXEMPT_INCOME: "免稅所得",
    IncomeKind.FOREIGN_INCOME: "海外所得",
    IncomeKind.OTHER_INCOME: "其他所得",
    IncomeKind.EXCLUDED: "不計入",
    IncomeKind.UNSUPPORTED: "不支援",
}

ESTIMATE_FOOTER = "這是估計，不是申報；以財政部稅額試算為準；不會改動帳本任何金額。"
QUESTION_INSTRUCTION = "問稅務問題：請依 docs/operations/tax-questions.md 回答："


def reminder_sentence(
    view: ReminderView,
    *,
    today: date,
    estimate: Estimate | None = None,
) -> str:
    """資產總覽待辦的一行提醒；只接受會顯示在總覽的三種狀態。"""
    cycle = view.cycle
    if cycle is None or view.state not in {
        ReminderState.UPCOMING,
        ReminderState.OPEN,
        ReminderState.OVERDUE,
    }:
        raise ValueError("只有有期間的即將開始、期間中與已過期限提醒能顯示在總覽")

    name = TAX_KIND_NAMES[view.kind]
    action = TAX_KIND_ACTIONS[view.kind]
    start = display_date(cycle.window.start.isoformat())
    due = display_date(cycle.window.end.isoformat())
    if view.state is ReminderState.UPCOMING:
        sentence = f"{name}：{start} 開始{action}，{due} 截止"
    elif view.state is ReminderState.OPEN:
        remaining = days_left(cycle, today=today)
        if remaining == 0:
            sentence = f"{name}：{action}期間到 {due}，今天截止"
        else:
            sentence = f"{name}：{action}期間到 {due}，還有 {remaining} 天"
    else:
        sentence = f"{name}：{due} 已過{action}期限，帳上還沒有繳款紀錄"

    additions: list[str] = []
    if view.kind is TaxKind.INCOME_TAX:
        if estimate is not None:
            additions.append(_income_estimate_parenthetical(estimate))
    elif view.last_year_paid is not None:
        paid = view.last_year_paid
        additions.append(f"（去年 {group_digits(paid.total_minor)} 元）")
    if cycle.window.estimated:
        additions.append("（日期為預估）")
    return sentence + "".join(additions) + "。"


def _income_estimate_parenthetical(estimate: Estimate) -> str:
    reasons = set(estimate.refused)
    if UnsupportedReason.INPUTS_MISSING in reasons:
        return "（試算：申報狀況還沒填）"
    if UnsupportedReason.UNMAPPED_INCOME in reasons:
        return "（試算：有收入未歸類）"
    if reasons.intersection(
        {
            UnsupportedReason.DATASET_UNAVAILABLE,
            UnsupportedReason.PARAMETERS_MISSING,
            UnsupportedReason.BASIC_LIVING_PENDING,
        }
    ):
        return "（試算：稅務資料不齊）"
    if reasons:
        return "（試算不支援）"
    if estimate.filing_exempt:
        return "（估計可免申報）"
    balance = estimate.balance_minor
    if balance is None:
        return "（試算不支援）"
    if balance > 0:
        return f"（估計應補 {group_digits(balance)} 元）"
    if balance < 0:
        return f"（估計應退 {group_digits(abs(balance))} 元）"
    return "（估計不用補也沒得退）"


def folded_sentence(n: int) -> str:
    return f"另有 {n} 件稅務提醒。"


def unset_sentence(n: int) -> str:
    return f"還有 {n} 項稅務提醒沒決定要不要開。"


def freshness_sentence(problem: FreshnessProblem) -> str:
    template = FRESHNESS_SENTENCES[problem.issue]
    years = "、".join(str(year) for year in problem.years)
    due = display_date(problem.due_on.isoformat()) if problem.due_on is not None else ""
    return template.format(years=years, due=due)


def status_sentence(overview: TaxOverview) -> str | None:
    if overview.problem is not None:
        return freshness_sentence(overview.problem)
    if overview.unset_count > 0:
        return unset_sentence(overview.unset_count)
    return None


def update_instruction(
    problems: Sequence[FreshnessProblem], *, today: date
) -> str:
    items: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item not in seen:
            seen.add(item)
            items.append(item)

    for problem in problems:
        if problem.issue is FreshnessIssue.DATASET_MISSING:
            add("建立稅務資料檔")
        elif problem.issue is FreshnessIssue.DATASET_INVALID:
            add("修正稅務資料的格式錯誤")
        elif problem.issue is FreshnessIssue.NOT_POPULATED:
            add("第一次填入稅務資料")
        elif problem.issue is FreshnessIssue.PARAMETERS_MISSING:
            for year in problem.years:
                add(f"{year} 年度的參數")
        elif problem.issue is FreshnessIssue.REVIEW_DUE:
            due = problem.due_on.isoformat() if problem.due_on is not None else ""
            add(f"例行複查（預定 {due}）")
        elif problem.issue is FreshnessIssue.LAW_REVIEW_DUE:
            add("法規參考庫的年度複查")
    if not items:
        add("例行複查")
    needed = "、".join(items)
    return (
        "請依 docs/operations/tax-data-runbook.md 更新 reference/tax/。"
        f"這次要補：{needed}。\n"
        f"完成條件：python tools/tax_data/validate.py --today {today.isoformat()} "
        "--require-current 結束碼為 0。\n"
        "做完先給我看差異摘要與來源網址，等我說可以再 commit。"
    )


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
            advice = "請改用財政部稅額試算。"
        lines.append(f"{UNSUPPORTED_REASON_NAMES[reason]} {advice}")
    return lines


def estimate_line_values(
    line: EstimateLine, *, sources: Mapping[str, TaxSource]
) -> list[str]:
    amount = (
        f"−{group_digits(abs(line.amount_minor))}"
        if line.step is EstimateStep.BALANCE and line.amount_minor < 0
        else group_digits(line.amount_minor)
    )
    titles = [
        sources[source_id].title if source_id in sources else source_id
        for source_id in line.source_ids
    ]
    if line.source is LineSource.LEDGER:
        basis = f"帳本 {line.ledger_count} 筆"
    elif line.source is LineSource.MANUAL:
        basis = "扣繳憑單（你填的）"
    elif line.source is LineSource.DATASET:
        basis = "財政部公告" + (f"：{'、'.join(titles)}" if titles else "")
    else:
        basis = f"計算（{'、'.join(titles)}）" if titles else "計算"
    if line.step is EstimateStep.EXEMPT_INCOME:
        basis += "（依你的歸類）"
    return [ESTIMATE_STEP_NAMES[line.step], amount, basis]


def caution_lines(estimate: Estimate) -> list[str]:
    return [ESTIMATE_CAUTION_NAMES[caution] for caution in estimate.cautions]


def official_diff_text(estimate: Estimate) -> str | None:
    difference = estimate.official_diff_minor
    if difference is None:
        return None
    if difference == 0:
        return "與財政部相同。"
    sign = "+" if difference > 0 else "−"
    return (
        f"與財政部相差 {sign}{group_digits(abs(difference))} 元。"
        "常見原因：用了實領而非給付總額、漏記收入、扣繳沒填、歸類錯。"
    )


def tax_reminder_values(
    view: ReminderView,
    *,
    switch: ReminderSwitch,
    today: date,
) -> list[str]:
    cycle = view.cycle
    if cycle is None:
        period = "—"
        note = ""
    else:
        start = display_date(cycle.window.start.isoformat())
        end = display_date(cycle.window.end.isoformat())
        period = f"{start}～{end}"
        if cycle.window.estimated:
            period += "（預估）"
        note = cycle.window.note or "" if not cycle.window.estimated else ""
    paid = view.last_year_paid
    paid_text = (
        f"{group_digits(paid.total_minor)} 元（{group_digits(paid.count)} 筆）"
        if paid is not None
        else "—"
    )
    return [
        TAX_KIND_NAMES[view.kind],
        SWITCH_NAMES[switch],
        period,
        REMINDER_STATE_NAMES[view.state],
        paid_text,
        note,
    ]


def tax_mapping_values(row: TaxMappingRow) -> list[str]:
    income_kind = row.income_kind
    if row.unmapped:
        state = "未歸類"
    elif income_kind is not None and row.parent_id is not None:
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


def tax_source_values(source: TaxSource) -> list[str]:
    return [
        source.title,
        source.publisher,
        display_date(source.published_on.isoformat()) if source.published_on else "—",
        display_date(source.fetched_at),
        source.sha256[:12],
        source.url,
    ]


def dataset_location_text(path: Path) -> str:
    return "\\".join(Path(path).parts[-2:])


def coverage_lines(status: TaxDataStatus) -> list[str]:
    dataset = status.dataset
    if dataset is None:
        return []
    lines: list[str] = []
    if dataset.income_tax:
        years = "、".join(str(year) for year in sorted(dataset.income_tax))
        lines.append(f"所得年度參數：{years}")
    if dataset.basic_living_expense:
        years = "、".join(str(year) for year in sorted(dataset.basic_living_expense))
        lines.append(f"基本生活費：{years}")
    if dataset.interest_withholding:
        effective = "、".join(
            display_date(rule.effective_from.isoformat())
            for rule in dataset.interest_withholding
        )
        lines.append(f"利息扣繳規則生效日：{effective}")
    if dataset.nhi_supplementary_premium:
        effective = "、".join(
            display_date(rule.effective_from.isoformat())
            for rule in dataset.nhi_supplementary_premium
        )
        lines.append(f"補充保費規則生效日：{effective}")
    for year in sorted(dataset.years):
        kinds = dataset.years[year]
        if kinds:
            names = "、".join(TAX_KIND_NAMES[kind] for kind in kinds)
            lines.append(f"公告期間：{year} 年 {names}")
    return lines
