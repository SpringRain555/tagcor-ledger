"""稅務畫面的中文句子、表格列與資料狀態格式。"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

import pytest

from tagcor_ledger.application.tax.data import TaxDataStatus
from tagcor_ledger.domain.tax.dataset import TaxSource
from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset
from tagcor_ledger.domain.tax.estimate import (
    Estimate,
    EstimateCaution,
    EstimateLine,
    EstimateStep,
    LineSource,
    UNSUPPORTED_REASON_NAMES,
    UnsupportedReason,
)
from tagcor_ledger.domain.tax.freshness import (
    DatasetLoad,
    DatasetLoadState,
    FreshnessIssue,
    FreshnessProblem,
)
from tagcor_ledger.domain.tax.kinds import (
    INCOME_KIND_NAMES,
    TAX_KIND_NAMES,
    Flow,
    IncomeKind,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import PaymentFact, TaxMappingRow
from tagcor_ledger.domain.tax.reminders import (
    ReminderCycle,
    ReminderState,
    ReminderSwitch,
    ReminderView,
)
from tagcor_ledger.ui.controller.tax import TaxOverview
from tagcor_ledger.ui.formatting.tax import (
    INCOME_KIND_SHORT,
    QUESTION_INSTRUCTION,
    REMINDER_STATE_NAMES,
    SWITCH_NAMES,
    TAX_KIND_SHORT_NAMES,
    coverage_lines,
    dataset_location_text,
    folded_sentence,
    freshness_sentence,
    reminder_sentence,
    status_sentence,
    tax_reminder_values,
    tax_source_values,
    unset_sentence,
    update_instruction,
)
from tagcor_ledger.ui.formatting.tax_estimate import (
    ESTIMATE_FOOTER,
    TAX_ESTIMATE_REFUSAL_FOOTER,
    caution_lines,
    estimate_line_values,
    estimate_status,
    official_diff_text,
    refusal_lines,
    tax_estimate_unsaved_note,
)
from tagcor_ledger.ui.formatting.tax_mapping import (
    tax_mapping_expense_options,
    tax_mapping_income_options,
    tax_mapping_values,
)
from tagcor_ledger.domain.tax.dataset import Window
from tools.tax_data.validate import _freshness_message


def _cycle(
    kind: TaxKind,
    *,
    start: date = date(2026, 5, 1),
    end: date = date(2026, 5, 31),
    estimated: bool = False,
    note: str | None = None,
) -> ReminderCycle:
    window = Window(kind, start.year, start, end, estimated, note, ())
    from datetime import timedelta

    return ReminderCycle(kind, start.year, window, start - timedelta(days=14), end + timedelta(days=30))


def _view(
    kind: TaxKind,
    state: ReminderState,
    *,
    cycle: ReminderCycle | None = None,
    paid: PaymentFact | None = None,
) -> ReminderView:
    return ReminderView(kind, state, cycle, None, paid)


def _estimate(
    *,
    refused: tuple[UnsupportedReason, ...] = (),
    balance: int | None = 0,
    filing_exempt: bool | None = False,
    official_diff: int | None = None,
    cautions: tuple[EstimateCaution, ...] = (),
) -> Estimate:
    return Estimate(2025, refused, (), None, None, balance, filing_exempt, official_diff, cautions)


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (ReminderState.DISABLED, "不提醒"),
        (ReminderState.UNSET, "未設定"),
        (ReminderState.NO_WINDOW, "沒有期間資料"),
        (ReminderState.HANDLED, "已處理"),
        (ReminderState.NOT_APPLICABLE, "本年不適用"),
        (ReminderState.PAID, "已繳"),
        (ReminderState.DORMANT, "未到"),
        (ReminderState.UPCOMING, "即將開始"),
        (ReminderState.OPEN, "期間中"),
        (ReminderState.OVERDUE, "已過期限"),
    ],
)
def test_reminder_state_names_cover_every_state(state: ReminderState, label: str) -> None:
    assert REMINDER_STATE_NAMES[state] == label


def test_switch_and_income_short_names() -> None:
    assert SWITCH_NAMES == {
        ReminderSwitch.ON: "開",
        ReminderSwitch.OFF: "關",
        ReminderSwitch.UNSET: "未設定",
    }
    assert INCOME_KIND_SHORT == {
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


def test_upcoming_reminder_sentence_uses_estimated_dates() -> None:
    cycle = _cycle(
        TaxKind.VEHICLE_LICENSE_TAX,
        start=date(2027, 4, 1),
        end=date(2027, 4, 30),
        estimated=True,
    )
    view = _view(TaxKind.VEHICLE_LICENSE_TAX, ReminderState.UPCOMING, cycle=cycle)

    assert reminder_sentence(view, today=date(2027, 3, 18)) == (
        # REQ-0011 §UI 2026-11-09：總覽提醒不標示預估期間。
        "使用牌照稅：2027/04/01 開始繳納，2027/04/30 截止。"
    )


def test_open_reminder_sentence_shows_days_left_and_last_year_payment() -> None:
    view = _view(
        TaxKind.HOUSE_TAX,
        ReminderState.OPEN,
        cycle=_cycle(TaxKind.HOUSE_TAX),
        paid=PaymentFact(2, 3210, "2025-05-12"),
    )

    assert reminder_sentence(view, today=date(2026, 5, 22)) == (
        "房屋稅：繳納期間到 2026/05/31，還有 9 天（去年 3,210 元）。"
    )


def test_open_reminder_on_last_day_says_today_is_due() -> None:
    view = _view(TaxKind.INCOME_TAX, ReminderState.OPEN, cycle=_cycle(TaxKind.INCOME_TAX))

    assert reminder_sentence(view, today=date(2026, 5, 31)) == (
        "綜合所得稅：申報期間到 2026/05/31，今天截止。"
    )


def test_overdue_reminder_sentence_uses_tax_action() -> None:
    view = _view(
        TaxKind.LAND_VALUE_TAX,
        ReminderState.OVERDUE,
        cycle=_cycle(
            TaxKind.LAND_VALUE_TAX,
            start=date(2026, 11, 1),
            end=date(2026, 11, 30),
        ),
    )

    assert reminder_sentence(view, today=date(2026, 12, 1)) == (
        "地價稅：2026/11/30 已過繳納期限，帳上還沒有繳款紀錄。"
    )


@pytest.mark.parametrize(
    ("estimate", "suffix"),
    [
        (_estimate(balance=2700), "（估計應補 2,700 元）"),
        (_estimate(balance=-3000), "（估計應退 3,000 元）"),
        (_estimate(balance=0), "（估計不用補也沒得退）"),
        (_estimate(balance=0, filing_exempt=True), "（估計可免申報）"),
    ],
)
def test_income_tax_reminder_estimate_suffixes(estimate: Estimate, suffix: str) -> None:
    view = _view(TaxKind.INCOME_TAX, ReminderState.OPEN, cycle=_cycle(TaxKind.INCOME_TAX))

    assert reminder_sentence(view, today=date(2026, 5, 22), estimate=estimate) == (
        f"綜合所得稅：申報期間到 2026/05/31，還有 9 天{suffix}。"
    )


@pytest.mark.parametrize(
    ("reason", "suffix"),
    [
        (UnsupportedReason.INPUTS_MISSING, "（試算：申報狀況還沒填）"),
        (UnsupportedReason.UNMAPPED_INCOME, "（試算：有收入未歸類）"),
        (UnsupportedReason.DATASET_UNAVAILABLE, "（試算：稅務資料不齊）"),
        (UnsupportedReason.WITH_SPOUSE, "（試算不支援）"),
    ],
)
def test_income_tax_reminder_refusal_suffixes(
    reason: UnsupportedReason, suffix: str
) -> None:
    view = _view(
        TaxKind.INCOME_TAX,
        ReminderState.OPEN,
        cycle=_cycle(TaxKind.INCOME_TAX, estimated=True),
    )

    assert reminder_sentence(
        view,
        today=date(2026, 5, 22),
        estimate=_estimate(refused=(reason,), balance=None, filing_exempt=None),
    ) == f"綜合所得稅：申報期間到 2026/05/31，還有 9 天{suffix}。"  # REQ-0011 §UI 2026-11-09


def test_fuel_fee_short_name_is_only_used_in_overview_sentence() -> None:
    view = _view(
        TaxKind.FUEL_FEE,
        ReminderState.OPEN,
        cycle=_cycle(TaxKind.FUEL_FEE, estimated=True),
        paid=PaymentFact(2, 123_456, "2025-05-31"),
    )

    sentence = reminder_sentence(view, today=date(2026, 5, 22))
    values = tax_reminder_values(view, switch=ReminderSwitch.ON, today=date(2026, 5, 22))

    # REQ-0011 §UI 2026-11-09：總覽用短名且不標預估，提醒表保留正式稅名與預估期間。
    assert TAX_KIND_SHORT_NAMES[TaxKind.FUEL_FEE] == "公路使用養護安全管理費"
    assert sentence == "公路使用養護安全管理費：繳納期間到 2026/05/31，還有 9 天（去年 123,456 元）。"
    assert "預估" not in sentence and "（原燃料費）" not in sentence
    assert values[0] == "公路使用養護安全管理費（原燃料費）"
    assert values[2].endswith("（預估）")


def test_income_tax_reminder_refusal_suffixes_follow_the_required_priority() -> None:
    view = _view(TaxKind.INCOME_TAX, ReminderState.OPEN, cycle=_cycle(TaxKind.INCOME_TAX))
    estimate = _estimate(
        refused=(
            UnsupportedReason.DATASET_UNAVAILABLE,
            UnsupportedReason.UNMAPPED_INCOME,
            UnsupportedReason.INPUTS_MISSING,
        ),
        balance=None,
        filing_exempt=None,
    )

    assert reminder_sentence(view, today=date(2026, 5, 22), estimate=estimate).endswith(
        "（試算：申報狀況還沒填）。"
    )


def test_reminder_sentence_rejects_dormant_state() -> None:
    view = _view(TaxKind.HOUSE_TAX, ReminderState.DORMANT, cycle=_cycle(TaxKind.HOUSE_TAX))

    with pytest.raises(ValueError):
        reminder_sentence(view, today=date(2026, 4, 1))


def test_folded_and_unset_sentences() -> None:
    assert folded_sentence(3) == "另有 3 件稅務提醒。"
    assert unset_sentence(4) == "還有 4 項稅務提醒沒決定要不要開。"


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        (
            FreshnessProblem(FreshnessIssue.DATASET_MISSING),
            "稅務資料不在，稅務提醒與試算暫停。",
        ),
        (
            FreshnessProblem(FreshnessIssue.DATASET_INVALID),
            "稅務資料格式有誤，稅務提醒與試算暫停。",
        ),
        (FreshnessProblem(FreshnessIssue.NOT_POPULATED), "稅務資料還沒建立。"),
        (
            FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025, 2026)),
            "稅務資料缺 2025、2026 年度的參數，該更新了。",
        ),
        (
            FreshnessProblem(FreshnessIssue.REVIEW_DUE, due_on=date(2026, 11, 30)),
            "稅務資料該複查了（預定 2026/11/30）。",
        ),
        (
            FreshnessProblem(FreshnessIssue.LAW_REVIEW_DUE),
            "報稅季前，法規參考庫該全面複查一次。",
        ),
    ],
)
def test_freshness_sentences_match_the_requirement(
    problem: FreshnessProblem, expected: str
) -> None:
    assert freshness_sentence(problem) == expected


def test_validator_and_ui_render_the_same_freshness_templates() -> None:
    problems = (
        FreshnessProblem(FreshnessIssue.DATASET_MISSING),
        FreshnessProblem(FreshnessIssue.DATASET_INVALID),
        FreshnessProblem(FreshnessIssue.NOT_POPULATED),
        FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025, 2026)),
        FreshnessProblem(FreshnessIssue.REVIEW_DUE, due_on=date(2026, 11, 30)),
        FreshnessProblem(FreshnessIssue.LAW_REVIEW_DUE),
    )
    date_pattern = re.compile(r"\d{4}[/\-]\d{2}[/\-]\d{2}")

    for problem in problems:
        ui_text = freshness_sentence(problem)
        validator_text = _freshness_message(problem)
        assert date_pattern.sub("{date}", ui_text) == date_pattern.sub("{date}", validator_text)


def test_update_instruction_lists_each_issue_and_uses_plain_text() -> None:
    problems = (
        FreshnessProblem(FreshnessIssue.DATASET_MISSING),
        FreshnessProblem(FreshnessIssue.DATASET_INVALID),
        FreshnessProblem(FreshnessIssue.NOT_POPULATED),
        FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025, 2026)),
        FreshnessProblem(FreshnessIssue.REVIEW_DUE, due_on=date(2026, 11, 30)),
        FreshnessProblem(FreshnessIssue.LAW_REVIEW_DUE),
    )
    text = update_instruction(problems, today=date(2026, 11, 9))

    assert "這次要補：建立稅務資料檔、修正稅務資料的格式錯誤、第一次填入稅務資料、2025 年度的參數、2026 年度的參數、例行複查（預定 2026-11-30）、法規參考庫的年度複查。" in text
    assert "--today 2026-11-09 --require-current" in text
    assert "`" not in text and "**" not in text
    assert update_instruction((), today=date(2026, 11, 9)).splitlines()[0].endswith(
        "這次要補：例行複查。"
    )


def test_question_instruction_and_estimate_footer_are_fixed() -> None:
    assert QUESTION_INSTRUCTION == "問稅務問題：請依 docs/operations/tax-questions.md 回答："
    assert ESTIMATE_FOOTER == "這是估計，不是申報；以財政部稅額試算為準；不會改動帳本任何金額。"


def test_status_sentence_prefers_freshness_problem_over_unset_count() -> None:
    overview = TaxOverview(
        reminders=(),
        folded=0,
        problem=FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025, 2026)),
        unset_count=4,
        income_tax_estimate=None,
    )

    assert status_sentence(overview) == "稅務資料缺 2025、2026 年度的參數，該更新了。"
    assert status_sentence(TaxOverview((), 0, None, 4, None)) == (
        "還有 4 項稅務提醒沒決定要不要開。"
    )
    assert status_sentence(TaxOverview((), 0, None, 0, None)) is None


@pytest.mark.parametrize(
    ("estimate", "expected"),
    [
        (_estimate(balance=1234), "估計：應補 1,234 元"),
        (_estimate(balance=-3000), "估計：應退 3,000 元"),
        (_estimate(balance=0), "估計：不用補也沒得退"),
        (
            _estimate(balance=0, filing_exempt=True),
            "估計：不用補也沒得退；所得沒有超過免稅額加標準扣除額，依所得稅法第 71 條可以不申報。",
        ),
        (
            _estimate(refused=(UnsupportedReason.INPUTS_MISSING,), balance=None),
            "這一年不試算。",
        ),
    ],
)
def test_estimate_status_outcomes(estimate: Estimate, expected: str) -> None:
    assert estimate_status(estimate) == expected


@pytest.mark.parametrize(
    ("reason", "advice"),
    [
        (UnsupportedReason.DATASET_UNAVAILABLE, "照資料狀態分頁的指示更新資料。"),
        (UnsupportedReason.PARAMETERS_MISSING, "照資料狀態分頁的指示更新資料。"),
        (UnsupportedReason.BASIC_LIVING_PENDING, "等財政部 11 月底公告後再更新資料。"),
        (UnsupportedReason.INPUTS_MISSING, "先填這一年的申報狀況。"),
        (UnsupportedReason.UNMAPPED_INCOME, "到所得歸類分頁把收入歸類。"),
        (UnsupportedReason.WITH_SPOUSE, "請改用財政部稅額試算。"),
        (UnsupportedReason.DEPENDENT_OF_OTHER, "請改用財政部稅額試算。"),
        (UnsupportedReason.DEPENDENT_INCOME, "請改用財政部稅額試算。"),
        (UnsupportedReason.ITEMIZED_DEDUCTION, "請改用財政部稅額試算。"),
        (UnsupportedReason.OTHER_SPECIAL_DEDUCTIONS, "請改用財政部稅額試算。"),
        (UnsupportedReason.UNSUPPORTED_INCOME, "請改用財政部稅額試算。"),
        (UnsupportedReason.WRITING_LECTURE_OVER_CAP, "請改用財政部稅額試算。"),
        (UnsupportedReason.FOREIGN_INCOME_AMT, "請改用財政部稅額試算。"),
        (UnsupportedReason.AMT_POSSIBLE, "請改用財政部稅額試算。"),
    ],
)
def test_refusal_lines_pair_reason_and_advice(
    reason: UnsupportedReason, advice: str
) -> None:
    estimate = _estimate(refused=(reason,), balance=None, filing_exempt=None)

    expected = (
        [UNSUPPORTED_REASON_NAMES[reason], TAX_ESTIMATE_REFUSAL_FOOTER]
        if advice == TAX_ESTIMATE_REFUSAL_FOOTER
        else [f"{UNSUPPORTED_REASON_NAMES[reason]} {advice}"]
    )
    assert refusal_lines(estimate) == expected


def test_refusal_lines_coalesce_multiple_official_estimate_recommendations() -> None:
    estimate = _estimate(
        refused=(
            UnsupportedReason.WITH_SPOUSE,
            UnsupportedReason.ITEMIZED_DEDUCTION,
        ),
        balance=None,
        filing_exempt=None,
    )

    lines = refusal_lines(estimate)

    assert lines[:2] == [
        UNSUPPORTED_REASON_NAMES[UnsupportedReason.WITH_SPOUSE],
        UNSUPPORTED_REASON_NAMES[UnsupportedReason.ITEMIZED_DEDUCTION],
    ]
    assert lines.count(TAX_ESTIMATE_REFUSAL_FOOTER) == 1


def test_refusal_lines_keep_fixable_advice_and_one_official_estimate_recommendation() -> None:
    estimate = _estimate(
        refused=(UnsupportedReason.INPUTS_MISSING, UnsupportedReason.WITH_SPOUSE),
        balance=None,
        filing_exempt=None,
    )

    lines = refusal_lines(estimate)

    assert lines == [
        "這一年的申報狀況還沒填。 先填這一年的申報狀況。",
        UNSUPPORTED_REASON_NAMES[UnsupportedReason.WITH_SPOUSE],
        TAX_ESTIMATE_REFUSAL_FOOTER,
    ]


def test_refusal_lines_only_show_fixable_advice_when_every_reason_is_fixable() -> None:
    estimate = _estimate(
        refused=(UnsupportedReason.INPUTS_MISSING, UnsupportedReason.UNMAPPED_INCOME),
        balance=None,
        filing_exempt=None,
    )

    lines = refusal_lines(estimate)

    assert lines == [
        "這一年的申報狀況還沒填。 先填這一年的申報狀況。",
        "有收入還沒歸類。 到所得歸類分頁把收入歸類。",
    ]


def test_unsaved_estimate_note_uses_the_source_year_or_default_summary() -> None:
    assert tax_estimate_unsaved_note(2025) == (
        "這一年還沒存過，先帶入 2025 年度的設定；按「儲存並試算」才會算。"
    )
    assert tax_estimate_unsaved_note(None) == (
        "這一年還沒存過，先用預設值（自己單獨申報、標準扣除、沒有受扶養人）；"
        "按「儲存並試算」才會算。"
    )


def test_estimate_line_values_format_sources_and_negative_balance() -> None:
    source = TaxSource(
        "income", "測試來源", "財政部", "https://example.test", date(2026, 1, 2), "a" * 64, "2026-01-03T10:00:00+08:00"
    )
    sources = {source.id: source}
    lines = (
        EstimateLine(EstimateStep.SALARY_GROSS, 12345, LineSource.LEDGER, 2, (), True),
        EstimateLine(EstimateStep.SALARY_GROSS, 12345, LineSource.MANUAL, None, (), True),
        EstimateLine(EstimateStep.TAX, 12345, LineSource.DATASET, None, ("income",), True),
        EstimateLine(EstimateStep.SAVINGS_DEDUCTION, 12345, LineSource.COMPUTED, None, ("missing",), True),
        EstimateLine(EstimateStep.BALANCE, -12345, LineSource.COMPUTED, None, (), True),
        EstimateLine(EstimateStep.EXEMPT_INCOME, 500, LineSource.LEDGER, 1, (), False),
    )

    assert [estimate_line_values(line, sources=sources) for line in lines] == [
        ["薪資收入", "12,345", "帳本 2 筆"],
        ["薪資收入", "12,345", "扣繳憑單（你填的）"],
        ["應納稅額", "12,345", "財政部公告：測試來源"],
        ["減：儲蓄投資特別扣除額", "12,345", "計算（missing）"],
        ["應補（退）稅額", "−12,345", "計算"],
        ["免稅所得（不併入，依你的歸類）", "500", "帳本 1 筆（依你的歸類）"],
    ]


def test_caution_lines_use_domain_names() -> None:
    estimate = _estimate(cautions=(EstimateCaution.SALARY_FROM_LEDGER,))

    assert caution_lines(estimate) == [
        "薪資用的是帳本的實領金額，通常低於扣繳憑單的給付總額；有扣繳憑單時請填給付總額。"
    ]


@pytest.mark.parametrize(
    ("difference", "expected"),
    [
        (1234, "與財政部相差 +1,234 元。常見原因：用了實領而非給付總額、漏記收入、扣繳沒填、歸類錯。"),
        (-3000, "與財政部相差 −3,000 元。常見原因：用了實領而非給付總額、漏記收入、扣繳沒填、歸類錯。"),
        (0, "與財政部相同。"),
        (None, None),
    ],
)
def test_official_diff_text(difference: int | None, expected: str | None) -> None:
    assert official_diff_text(_estimate(official_diff=difference)) == expected


def test_tax_reminder_values_show_announcement_note_and_paid_fact() -> None:
    view = _view(
        TaxKind.HOUSE_TAX,
        ReminderState.OPEN,
        cycle=_cycle(TaxKind.HOUSE_TAX, estimated=False, note="期間順延說明"),
        paid=PaymentFact(2, 3210, "2025-05-12"),
    )

    assert tax_reminder_values(view, switch=ReminderSwitch.ON, today=date(2026, 5, 10)) == [
        "房屋稅",
        "開",
        "2026/05/01～2026/05/31",
        "期間中",
        "3,210 元（2 筆）",
        "期間順延說明",
    ]


def _mapping_row(**changes: object) -> TaxMappingRow:
    values: dict[str, object] = {
        "category_id": "category",
        "parent_id": None,
        "category_name": "薪資",
        "item_name": None,
        "archived": False,
        "income_kind": None,
        "expense_kind": None,
        "parent_income_kind": None,
        "parent_expense_kind": None,
        "effective_income_kind": None,
        "effective_expense_kind": None,
        "own_year_count": 0,
        "own_year_minor": 0,
        "year_count": 0,
        "year_minor": 0,
    }
    values.update(changes)
    return TaxMappingRow(**values)  # type: ignore[arg-type]


def test_tax_mapping_category_options_keep_unmapped_and_no_expense_choices() -> None:
    row = _mapping_row()

    assert tax_mapping_income_options(row)[0] == ("未歸類", None)
    assert tax_mapping_expense_options(row)[0] == ("無", None)


@pytest.mark.parametrize(
    ("row", "flow", "expected"),
    [
        (
            _mapping_row(parent_id="parent", parent_income_kind=IncomeKind.SALARY),
            Flow.INCOME,
            f"沿用類別：{INCOME_KIND_NAMES[IncomeKind.SALARY]}",
        ),
        (
            _mapping_row(parent_id="parent"),
            Flow.INCOME,
            "沿用類別（類別還沒歸類）",
        ),
        (
            _mapping_row(parent_id="parent", parent_expense_kind=TaxKind.HOUSE_TAX),
            Flow.EXPENSE,
            f"沿用類別：{TAX_KIND_NAMES[TaxKind.HOUSE_TAX]}",
        ),
        (
            _mapping_row(parent_id="parent"),
            Flow.EXPENSE,
            "沿用類別（無）",
        ),
    ],
)
def test_tax_mapping_item_options_describe_the_inherited_value(
    row: TaxMappingRow, flow: Flow, expected: str
) -> None:
    options = (
        tax_mapping_income_options(row)
        if flow is Flow.INCOME
        else tax_mapping_expense_options(row)
    )

    assert options[0] == (expected, None)
    assert all(value is not None for _label, value in options[1:])


@pytest.mark.parametrize(
    ("row", "expected_state"),
    [
        (
            _mapping_row(own_year_count=1, own_year_minor=1000, year_count=1, year_minor=1000),
            "未歸類",
        ),
        (_mapping_row(income_kind=IncomeKind.SALARY), "已歸類"),
        (
            _mapping_row(
                parent_id="parent",
                item_name="薪資項目",
                income_kind=IncomeKind.SALARY,
                parent_income_kind=IncomeKind.SALARY,
                effective_income_kind=IncomeKind.SALARY,
            ),
            "已歸類（覆蓋類別）",
        ),
        (
            _mapping_row(
                parent_id="parent",
                item_name="薪資項目",
                effective_income_kind=IncomeKind.INTEREST_TAXABLE,
            ),
            "沿用類別：利息所得（應稅）",
        ),
        (_mapping_row(), "—"),
    ],
)
def test_tax_mapping_values_states(row: TaxMappingRow, expected_state: str) -> None:
    values = tax_mapping_values(row)

    assert values[-1] == expected_state


def test_tax_mapping_values_show_category_item_kind_and_annual_income() -> None:
    row = _mapping_row(
        parent_id="parent",
        category_name="薪資",
        item_name="月薪",
        income_kind=IncomeKind.SALARY,
        parent_income_kind=IncomeKind.SALARY,
        expense_kind=TaxKind.HOUSE_TAX,
        year_count=3,
        year_minor=123456,
    )

    assert tax_mapping_values(row) == [
        "薪資",
        "月薪",
        "薪資所得",
        "房屋稅",
        "3 筆 123,456 元",
        "已歸類（覆蓋類別）",
    ]


def test_tax_mapping_values_marks_own_kind_as_override_when_parent_has_mapping() -> None:
    row = _mapping_row(
        parent_id="parent",
        item_name="薪資項目",
        income_kind=IncomeKind.SALARY,
        parent_income_kind=IncomeKind.INTEREST_TAXABLE,
    )

    assert tax_mapping_values(row)[-1] == "已歸類（覆蓋類別）"


def test_tax_mapping_values_does_not_call_own_kind_an_override_without_parent_mapping() -> None:
    row = _mapping_row(
        parent_id="parent",
        item_name="薪資項目",
        income_kind=IncomeKind.SALARY,
        parent_income_kind=None,
    )

    assert tax_mapping_values(row)[-1] == "已歸類"


def test_tax_source_values_and_dataset_location_are_compact() -> None:
    source = TaxSource(
        "source",
        "年度參數",
        "財政部",
        "https://example.test/source",
        date(2026, 1, 2),
        "123456789abc" + "0" * 52,
        "2026-02-03T10:00:00+08:00",
    )

    assert tax_source_values(source) == [
        "年度參數",
        "財政部",
        "2026/01/02",
        "2026/02/03",
        "123456789abc",
        "https://example.test/source",
    ]
    assert dataset_location_text(Path("C:/private/reference/tax/dataset.json")) == "tax\\dataset.json"


def test_coverage_lines_read_dataset_and_hide_when_unavailable() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tax" / "sample.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    dataset = parse_tax_dataset(raw)
    status = TaxDataStatus(
        path=fixture,
        load=DatasetLoad(DatasetLoadState.OK, dataset=dataset),
        dataset=dataset,
        problems=(),
        sources=dataset.sources,
        reviewed_at=dataset.reviewed_at,
        next_review_on=dataset.next_review_on,
        missing_windows=(),
        law_oldest_reviewed_at=None,
    )

    assert "所得年度參數：2025、2026" in coverage_lines(status)
    assert "基本生活費：2025、2026" in coverage_lines(status)
    assert "公告期間：2026 年 綜合所得稅、房屋稅、公路使用養護安全管理費（原燃料費）" in coverage_lines(status)
    unavailable = TaxDataStatus(
        path=fixture,
        load=DatasetLoad(DatasetLoadState.MISSING),
        dataset=None,
        problems=(),
        sources=(),
        reviewed_at=None,
        next_review_on=None,
        missing_windows=(),
        law_oldest_reviewed_at=None,
    )
    assert coverage_lines(unavailable) == []

