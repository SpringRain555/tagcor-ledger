"""稅務畫面使用的名稱、句子與表格列。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from tagcor_ledger.application.reference import ReferenceEntry
from tagcor_ledger.application.tax.data import TaxDataStatus
from tagcor_ledger.domain.tax.dataset import TaxSource
from tagcor_ledger.domain.tax.estimate import (
    Estimate,
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

QUESTION_INSTRUCTION = "問稅務問題：請依 docs/operations/tax-questions.md 回答："
TAX_PAGE_NOTE = "提醒與試算是估計，以主管機關公告與財政部稅額試算為準。"
TAX_PAGE_TITLE = "稅務"
TAX_KIND_SHORT_NAMES: dict[TaxKind, str] = {
    **TAX_KIND_NAMES,
    TaxKind.FUEL_FEE: "公路使用養護安全管理費",
}
TAX_REMINDER_HEADERS = ["稅目", "開關", "期間", "狀態", "去年繳款", "備註"]
TAX_REMINDER_NOTE_LINES = (
    "提醒只依法定期間觸發；期間內記了一筆對應這個稅目的支出，就算已繳。",
    "繳款類別對應到稅目，在『所得歸類』分頁設定。",
)
TAX_DATA_SOURCE_HEADERS = ["來源", "發布機關", "發布日", "抓取", "SHA-256 前 12 碼", "網址"]
TAX_TAB_LABELS = {
    "reminders": "提醒",
    "estimate": "試算",
    "mapping": "所得歸類",
    "data": "資料狀態",
    "law": "法規參考",
}
TAX_SWITCH_OPTIONS = ("開", "關")
TAX_REMINDER_SWITCH_LABEL = "提醒開關"
TAX_REMINDER_ACTION_LABELS = ("標記已處理", "本年不適用", "取消標記")
TAX_NO_FRESHNESS_PROBLEMS = "稅務資料是最新的。"
TAX_NOT_REVIEWED = "—"
TAX_COPY_BUTTON = "複製"
TAX_COPIED = "已複製。"
TAX_VIEW_BUTTON = "查看"
TAX_UPDATE_TITLE = "更新稅務資料"
TAX_QUESTION_TITLE = "問稅務問題"
TAX_DATASET_LOCATION_LABEL = "資料集位置"
TAX_DATA_SUMMARY_LABEL = "資料摘要"
TAX_DATA_COVERAGE_LABEL = "涵蓋情形與規則生效日"
TAX_DATA_FRESHNESS_LABEL = "資料新鮮度"
TAX_DATA_SOURCES_LABEL = "資料來源"
TAX_DATA_ESTIMATED_LABEL = "只有預估期間的稅目"
TAX_LAW_NOTE = (
    "這個分頁只查條文；稅額的估計在『試算』分頁，"
    "數字來自 reference/tax/dataset.json，不是從條文推算。"
)
TAX_LAW_SEARCH_PLACEHOLDER = "搜尋條文、摘要或法規名稱，例如：存簿儲金、贈與"
TAX_LAW_STALE_HTML = (
    "<p><b>需複查</b>：這一篇超過半年沒有複查過，數字與條文可能已經修正。</p>"
)
TAX_LAW_HEADERS = ["法規", "條號", "標題", "版本", "複查"]
TAX_LAW_TOPICS_LABEL = "主題"
TAX_LAW_ALL_TOPICS = "全部主題"
TAX_LAW_REFRESH = "重新整理"
TAX_LAW_STATUS_HINT = "法規庫共 {count} 篇，建立於 {built_at}。條文原文抓自全國法規資料庫，每篇附來源網址與抓取時間。"
TAX_LAW_MISSING_LOCATION = "預期位置：專案底下的 {shown}"
TAX_LAW_STATUS_TEMPLATE = (
    "共 {count} 篇，建立於 {built_at}。"
    "條文原文抓自全國法規資料庫，每篇都附來源網址與抓取時間。"
)


def freshness_lines(problems: Sequence[FreshnessProblem]) -> list[str]:
    """一個新鮮度問題一行；沒有問題時也給出明確狀態。"""
    if not problems:
        return [TAX_NO_FRESHNESS_PROBLEMS]
    return [freshness_sentence(problem) for problem in problems]


def tax_data_summary_lines(status: TaxDataStatus, *, law_entry_count: int | None) -> list[str]:
    """資料複查與法規庫摘要，供資料狀態分頁逐行顯示。"""
    reviewed = display_date(status.reviewed_at.isoformat()) if status.reviewed_at else TAX_NOT_REVIEWED
    next_review = (
        display_date(status.next_review_on.isoformat())
        if status.next_review_on
        else TAX_NOT_REVIEWED
    )
    oldest = (
        display_date(status.law_oldest_reviewed_at.isoformat())
        if status.law_oldest_reviewed_at
        else TAX_NOT_REVIEWED
    )
    entries = str(law_entry_count) if law_entry_count is not None else TAX_NOT_REVIEWED
    return [
        f"資料複查日：{reviewed}",
        f"下次複查日：{next_review}",
        f"法規庫條數：{entries}",
        f"法規庫最舊複查日：{oldest}",
    ]


def estimated_window_lines(status: TaxDataStatus) -> list[str]:
    """指出目前只有預估期間的稅目與年度。"""
    return [
        f"{year} 年 {TAX_KIND_NAMES[kind]}只有預估期間。"
        for kind, year in status.missing_windows
    ]


def tax_law_topic_label(title: str, count: object) -> str:
    return f"{title}（{count}）"


def tax_law_status_hint(entry_count: object, built_at: object) -> str:
    return TAX_LAW_STATUS_HINT.format(count=entry_count, built_at=built_at)


def tax_law_missing_text(message: str, how: str, shown_path: str) -> str:
    location = TAX_LAW_MISSING_LOCATION.format(shown=shown_path)
    return f"{message}\n{how}\n{location}"


def tax_law_entry_values(entry: ReferenceEntry, *, stale: bool) -> list[str]:
    return [
        entry.law_name,
        f"第 {entry.article} 條",
        entry.title,
        entry.amended_date,
        "需複查" if stale else "已複查",
    ]


def tax_law_entry_html(entry: ReferenceEntry, *, stale: bool) -> str:
    """法規條文詳細內容；資料庫欄位一律逸出，只轉摘要的 Markdown 粗體。"""
    stale_note = TAX_LAW_STALE_HTML if stale else ""
    return (
        f"<h2>{_escape(entry.heading)}　{_escape(entry.title)}</h2>"
        f"{stale_note}"
        f"<p><b>白話摘要</b><br>{_html(entry.plain)}</p>"
        f"<p><b>對這個帳本的意義</b><br>{_html(entry.ledger_note)}</p>"
        "<p><b>條文原文</b>（摘要與原文有出入時，以原文為準）</p>"
        f"<pre>{_escape(entry.body)}</pre>"
        f"<hr><p>主管機關：{_escape(entry.agency)}　版本：{_escape(entry.amended_date)}　"
        f"法律狀態：{_escape(entry.legal_status)}</p>"
        f"<p>來源：{_escape(entry.source_url)}<br>"
        f"抓取時間：{_escape(entry.fetched_at)}　複查日期：{_escape(entry.reviewed_at)}</p>"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html(text: str) -> str:
    """摘要是我們自己寫的 Markdown 粗體，轉成 HTML；其餘一律逸出。"""
    escaped = _escape(text)
    parts = escaped.split("**")
    rebuilt = [f"<b>{part}</b>" if index % 2 else part for index, part in enumerate(parts)]
    return "".join(rebuilt).replace("\n", "<br>")


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

    name = TAX_KIND_SHORT_NAMES[view.kind]
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
