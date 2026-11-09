"""驗證公開稅務資料集的格式與來源引用。"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Mapping, cast
from urllib.parse import urlparse

from tagcor_ledger.domain.tax.arithmetic import PPM, Rounding
from tagcor_ledger.domain.tax.kinds import TaxKind


_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_YEAR = re.compile(r"^[0-9]{4}$")
_MONTH_DAY = re.compile(r"^[0-9]{2}-[0-9]{2}$")
_AMOUNT_FIELDS = (
    "exemption",
    "exemption_70_plus",
    "standard_deduction_single",
    "salary_special_deduction_cap",
    "savings_investment_cap",
    "writing_lecture_exemption_cap",
    "foreign_income_amt_threshold",
    "amt_basic_exemption",
)


def _mapping(value: object, path: str, problems: list[str]) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        problems.append(f"{path}：應為物件。")
        return None
    if any(not isinstance(key, str) for key in value):
        problems.append(f"{path}：物件的欄位名稱必須是文字。")
    return cast(Mapping[str, object], value)


def _required(obj: Mapping[str, object], key: str, path: str, problems: list[str]) -> object:
    if key not in obj:
        problems.append(f"{path}.{key}：缺少必要欄位。")
        return None
    return obj[key]


def _integer(
    value: object,
    path: str,
    problems: list[str],
    *,
    nullable: bool = False,
) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{path}：應為非負整數。")
        return None
    if value < 0:
        problems.append(f"{path}：不得小於 0。")
        return None
    return value


def _iso_date(
    value: object,
    path: str,
    problems: list[str],
    *,
    nullable: bool = False,
) -> date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        problems.append(f"{path}：應為合法 ISO 日期。")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        problems.append(f"{path}：不是合法 ISO 日期。")
        return None
    if parsed.isoformat() != value:
        problems.append(f"{path}：應使用 YYYY-MM-DD 格式。")
        return None
    return parsed


def _string(value: object, path: str, problems: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{path}：應為非空文字。")
        return None
    return value


def _string_list(value: object, path: str, problems: list[str]) -> list[str] | None:
    if not isinstance(value, list):
        problems.append(f"{path}：應為文字陣列。")
        return None
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            problems.append(f"{path}[{index}]：應為文字。")
        else:
            result.append(item)
    return result


def _source_ids(
    obj: Mapping[str, object],
    path: str,
    problems: list[str],
    references: list[tuple[str, str]],
) -> tuple[str, ...]:
    raw = _required(obj, "source_ids", path, problems)
    ids = _string_list(raw, f"{path}.source_ids", problems)
    if ids is None:
        return ()
    if not ids:
        problems.append(f"{path}.source_ids：至少要引用一個來源。")
    for index, source_id in enumerate(ids):
        references.append((source_id, f"{path}.source_ids[{index}]"))
    return tuple(ids)


def _tax_kind(value: str, path: str, problems: list[str]) -> TaxKind | None:
    try:
        return TaxKind(value)
    except ValueError:
        problems.append(f"{path}：未知稅目「{value}」。")
        return None


def _validate_sources(
    value: object,
    problems: list[str],
) -> tuple[set[str], list[tuple[str, str]]]:
    ids: set[str] = set()
    references: list[tuple[str, str]] = []
    if not isinstance(value, list):
        problems.append("sources：應為陣列。")
        return ids, references

    for index, raw_source in enumerate(value):
        path = f"sources[{index}]"
        source = _mapping(raw_source, path, problems)
        if source is None:
            continue
        source_id = _string(_required(source, "id", path, problems), f"{path}.id", problems)
        if source_id is not None:
            if _SOURCE_ID.fullmatch(source_id) is None:
                problems.append(f"{path}.id：格式應符合 ^[a-z0-9][a-z0-9-]*$。")
            if source_id in ids:
                problems.append(f"{path}.id：來源識別字重複。")
            ids.add(source_id)
        for name in ("title", "publisher"):
            _string(_required(source, name, path, problems), f"{path}.{name}", problems)

        url = _string(_required(source, "url", path, problems), f"{path}.url", problems)
        if url is not None:
            try:
                parsed_url = urlparse(url)
                secure_url = parsed_url.scheme == "https" and bool(parsed_url.netloc)
            except ValueError:
                secure_url = False
            if not secure_url:
                problems.append(f"{path}.url：網址必須是 https。")

        published = _required(source, "published_on", path, problems)
        _iso_date(published, f"{path}.published_on", problems, nullable=True)

        sha256 = _string(_required(source, "sha256", path, problems), f"{path}.sha256", problems)
        if sha256 is not None and _SHA256.fullmatch(sha256) is None:
            problems.append(f"{path}.sha256：應為 64 個小寫十六進位字元。")

        fetched_at = _string(
            _required(source, "fetched_at", path, problems), f"{path}.fetched_at", problems
        )
        if fetched_at is not None:
            try:
                parsed_datetime = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            except ValueError:
                problems.append(f"{path}.fetched_at：應為合法 ISO 日期時間。")
            else:
                if parsed_datetime.tzinfo is None:
                    problems.append(f"{path}.fetched_at：必須包含時區。")
    return ids, references


def _validate_calendar(
    value: object,
    problems: list[str],
    references: list[tuple[str, str]],
) -> None:
    calendar = _mapping(value, "calendar", problems)
    if calendar is None:
        return

    typical = _mapping(_required(calendar, "typical", "calendar", problems), "calendar.typical", problems)
    if typical is not None:
        for raw_kind, raw_window in typical.items():
            if not isinstance(raw_kind, str):
                problems.append("calendar.typical：稅目欄位名稱必須是文字。")
                continue
            _tax_kind(raw_kind, f"calendar.typical.{raw_kind}", problems)
            path = f"calendar.typical.{raw_kind}"
            window = _mapping(raw_window, path, problems)
            if window is None:
                continue
            month_days: list[tuple[int, int] | None] = []
            for field in ("start", "end"):
                date_text = _string(
                    _required(window, field, path, problems), f"{path}.{field}", problems
                )
                month_day: tuple[int, int] | None = None
                if date_text is not None:
                    if _MONTH_DAY.fullmatch(date_text) is None:
                        problems.append(f"{path}.{field}：應為合法 MM-DD 日期。")
                    else:
                        month, day = (int(part) for part in date_text.split("-"))
                        try:
                            date(2001, month, day)
                        except ValueError:
                            problems.append(f"{path}.{field}：應為合法 MM-DD 日期。")
                        else:
                            month_day = (month, day)
                month_days.append(month_day)
            _string(_required(window, "basis", path, problems), f"{path}.basis", problems)
            _source_ids(window, path, problems, references)
            if all(day is not None for day in month_days):
                typical_start = cast(tuple[int, int], month_days[0])
                typical_end = cast(tuple[int, int], month_days[1])
                if typical_start > typical_end:
                    problems.append(f"{path}：開始日期不可晚於結束日期。")

    years = _mapping(_required(calendar, "years", "calendar", problems), "calendar.years", problems)
    if years is not None:
        for raw_year, raw_windows in years.items():
            if not isinstance(raw_year, str):
                problems.append("calendar.years：年度鍵必須是文字。")
                continue
            year_path = f"calendar.years.{raw_year}"
            if _YEAR.fullmatch(raw_year) is None or int(raw_year) == 0:
                problems.append(f"{year_path}：年度鍵必須是四位數西元年。")
                continue
            year = int(raw_year)
            windows = _mapping(raw_windows, year_path, problems)
            if windows is None:
                continue
            for raw_kind, raw_window in windows.items():
                if not isinstance(raw_kind, str):
                    problems.append(f"{year_path}：稅目欄位名稱必須是文字。")
                    continue
                _tax_kind(raw_kind, f"{year_path}.{raw_kind}", problems)
                path = f"{year_path}.{raw_kind}"
                window = _mapping(raw_window, path, problems)
                if window is None:
                    continue
                annual_start = _iso_date(
                    _required(window, "start", path, problems), f"{path}.start", problems
                )
                annual_end = _iso_date(
                    _required(window, "end", path, problems), f"{path}.end", problems
                )
                note = _required(window, "note", path, problems)
                if note is not None and not isinstance(note, str):
                    problems.append(f"{path}.note：應為文字或 null。")
                _source_ids(window, path, problems, references)
                if annual_start is not None and annual_start.year != year:
                    problems.append(f"{path}.start：日期必須落在 {year} 年內。")
                if annual_end is not None and annual_end.year != year:
                    problems.append(f"{path}.end：日期必須落在 {year} 年內。")
                if (
                    annual_start is not None
                    and annual_end is not None
                    and annual_start > annual_end
                ):
                    problems.append(f"{path}：開始日期不可晚於結束日期。")


def _rate_ppm(value: object, path: str, problems: list[str]) -> int | None:
    rate = _integer(value, path, problems)
    if rate is not None and not 0 < rate < PPM:
        problems.append(
            f"{path}：比率必須大於 0、小於 {PPM}（100%）。"
        )
    return rate


def _sourced_amount(
    value: object,
    path: str,
    problems: list[str],
    references: list[tuple[str, str]],
) -> int | None:
    obj = _mapping(value, path, problems)
    if obj is None:
        return None
    amount = _integer(_required(obj, "value", path, problems), f"{path}.value", problems)
    _source_ids(obj, path, problems, references)
    return amount


def _validate_basic_living(
    value: object,
    problems: list[str],
    references: list[tuple[str, str]],
) -> None:
    """最上層的基本生活費序列：所得年度 → 金額與出處（公告時程與 income_tax 差一年，見 dataset.py）。"""
    years = _mapping(value, "basic_living_expense", problems)
    if years is None:
        return
    for raw_year, amount in years.items():
        path = f"basic_living_expense.{raw_year}"
        if _YEAR.fullmatch(str(raw_year)) is None or int(raw_year) == 0:
            problems.append(f"{path}：所得年度鍵必須是四位數西元年。")
            continue
        _sourced_amount(amount, path, problems, references)


def _validate_rounding(
    value: object,
    path: str,
    problems: list[str],
    references: list[tuple[str, str]],
) -> None:
    obj = _mapping(value, path, problems)
    if obj is None:
        return
    rounding = _required(obj, "value", path, problems)
    if not isinstance(rounding, str) or rounding not in {item.value for item in Rounding}:
        problems.append(f"{path}.value：進位方式只能是 floor 或 half_up。")
    _source_ids(obj, path, problems, references)


def _validate_income_tax(
    value: object,
    problems: list[str],
    references: list[tuple[str, str]],
) -> None:
    years = _mapping(value, "income_tax", problems)
    if years is None:
        return
    for raw_year, raw_parameters in years.items():
        if not isinstance(raw_year, str):
            problems.append("income_tax：所得年度鍵必須是文字。")
            continue
        path = f"income_tax.{raw_year}"
        if _YEAR.fullmatch(raw_year) is None or int(raw_year) == 0:
            problems.append(f"{path}：所得年度鍵必須是四位數西元年。")
            continue
        parameters = _mapping(raw_parameters, path, problems)
        if parameters is None:
            continue
        if "basic_living_expense" in parameters:
            problems.append(
                f"{path}.basic_living_expense：應移至最上層 basic_living_expense 序列。"
            )
        amounts: dict[str, int | None] = {}
        for field in _AMOUNT_FIELDS:
            amounts[field] = _sourced_amount(
                _required(parameters, field, path, problems), f"{path}.{field}", problems, references
            )
        exemption = amounts.get("exemption")
        exemption_70_plus = amounts.get("exemption_70_plus")
        if (
            exemption is not None
            and exemption_70_plus is not None
            and exemption_70_plus < exemption
        ):
            problems.append(
                f"{path}.exemption_70_plus.value：不得小於 exemption.value。"
            )
        raw_brackets = _mapping(
            _required(parameters, "brackets", path, problems), f"{path}.brackets", problems
        )
        if raw_brackets is None:
            continue
        rows = _required(raw_brackets, "rows", f"{path}.brackets", problems)
        _source_ids(raw_brackets, f"{path}.brackets", problems, references)
        bracket_rows: list[tuple[int | None, int | None, int | None]] = []
        if not isinstance(rows, list):
            problems.append(f"{path}.brackets.rows：應為陣列。")
            rows = []
        for index, raw_row in enumerate(rows):
            row_path = f"{path}.brackets.rows[{index}]"
            row = _mapping(raw_row, row_path, problems)
            if row is None:
                bracket_rows.append((None, None, None))
                continue
            up_to_value = _required(row, "up_to", row_path, problems)
            up_to = _integer(up_to_value, f"{row_path}.up_to", problems, nullable=True)
            rate = _rate_ppm(
                _required(row, "rate_ppm", row_path, problems),
                f"{row_path}.rate_ppm",
                problems,
            )
            difference = _integer(
                _required(row, "progressive_difference", row_path, problems),
                f"{row_path}.progressive_difference",
                problems,
            )
            bracket_rows.append((up_to, rate, difference))
        if len(rows) < 2:
            problems.append(f"{path}.brackets.rows：級距至少需要 2 列。")
        if bracket_rows:
            if bracket_rows[-1][0] is not None:
                problems.append(f"{path}.brackets.rows[{len(bracket_rows) - 1}].up_to：最後一列必須是 null。")
            for index, (up_to, _, _) in enumerate(bracket_rows[:-1]):
                if up_to is None:
                    problems.append(f"{path}.brackets.rows[{index}].up_to：只有最後一列可為 null。")
            if bracket_rows[0][2] is not None and bracket_rows[0][2] != 0:
                problems.append(f"{path}.brackets.rows[0].progressive_difference：第一列必須是 0。")
            for index in range(1, len(bracket_rows)):
                previous_up_to, previous_rate, previous_difference = bracket_rows[index - 1]
                current_up_to, current_rate, current_difference = bracket_rows[index]
                if (
                    previous_up_to is not None
                    and current_up_to is not None
                    and current_up_to <= previous_up_to
                ):
                    problems.append(
                        f"{path}.brackets.rows[{index}].up_to：級距上限必須嚴格遞增。"
                    )
                if (
                    previous_rate is not None
                    and current_rate is not None
                    and current_rate <= previous_rate
                ):
                    problems.append(f"{path}.brackets.rows[{index}].rate_ppm：稅率必須嚴格遞增。")
                if (
                    previous_up_to is not None
                    and previous_rate is not None
                    and current_rate is not None
                    and previous_difference is not None
                    and current_difference is not None
                ):
                    numerator = previous_up_to * (current_rate - previous_rate)
                    if numerator % PPM != 0:
                        problems.append(
                            f"{path}.brackets.rows[{index}].progressive_difference：累進差額計算不能整除。"
                        )
                    else:
                        expected = previous_difference + numerator // PPM
                        if current_difference != expected:
                            problems.append(
                                f"{path}.brackets.rows[{index}].progressive_difference：累進差額應為 {expected}，實際 {current_difference}。"
                            )
        _validate_rounding(
            _required(parameters, "tax_rounding", path, problems),
            f"{path}.tax_rounding",
            problems,
            references,
        )


def _validate_rule_list(
    value: object,
    path: str,
    problems: list[str],
    references: list[tuple[str, str]],
    *,
    premium: bool,
) -> None:
    if not isinstance(value, list):
        problems.append(f"{path}：應為陣列。")
        return
    previous_date: date | None = None
    for index, raw_rule in enumerate(value):
        rule_path = f"{path}[{index}]"
        rule = _mapping(raw_rule, rule_path, problems)
        if rule is None:
            continue
        effective = _iso_date(
            _required(rule, "effective_from", rule_path, problems),
            f"{rule_path}.effective_from",
            problems,
        )
        if effective is not None:
            if previous_date is not None and effective <= previous_date:
                problems.append(f"{rule_path}.effective_from：生效日必須嚴格遞增。")
            previous_date = effective
        _rate_ppm(
            _required(rule, "rate_ppm", rule_path, problems),
            f"{rule_path}.rate_ppm",
            problems,
        )
        if premium:
            threshold = _integer(
                _required(rule, "threshold_at_least", rule_path, problems),
                f"{rule_path}.threshold_at_least",
                problems,
            )
            cap = _integer(
                _required(rule, "base_cap", rule_path, problems),
                f"{rule_path}.base_cap",
                problems,
            )
            if threshold is not None and cap is not None and cap <= threshold:
                problems.append(f"{rule_path}.base_cap：必須大於 threshold_at_least。")
        else:
            _integer(
                _required(rule, "exempt_if_tax_at_most", rule_path, problems),
                f"{rule_path}.exempt_if_tax_at_most",
                problems,
            )
        rounding = _required(rule, "rounding", rule_path, problems)
        if not isinstance(rounding, str) or rounding not in {item.value for item in Rounding}:
            problems.append(f"{rule_path}.rounding：進位方式只能是 floor 或 half_up。")
        _source_ids(rule, rule_path, problems, references)


def validate_tax_dataset(raw: object) -> list[str]:
    """依 REQ-0011 驗證規則 1–7 檢查資料集並回傳所有問題。"""
    problems: list[str] = []
    root = _mapping(raw, "dataset", problems)
    if root is None:
        return problems

    schema_version = _integer(_required(root, "schema_version", "dataset", problems), "schema_version", problems)
    if schema_version is not None and schema_version != 1:
        problems.append(f"schema_version：只支援 1，實際為 {schema_version}。")
    reviewed_at = _iso_date(
        _required(root, "reviewed_at", "dataset", problems),
        "reviewed_at",
        problems,
        nullable=True,
    )
    next_review_on = _iso_date(
        _required(root, "next_review_on", "dataset", problems),
        "next_review_on",
        problems,
        nullable=True,
    )
    if reviewed_at is not None and (
        next_review_on is None or next_review_on <= reviewed_at
    ):
        problems.append(
            "next_review_on：已複查的資料要寫下次複查日，而且要晚於 reviewed_at。"
        )
    _string_list(_required(root, "notes", "dataset", problems), "notes", problems)
    source_ids, references = _validate_sources(
        _required(root, "sources", "dataset", problems), problems
    )
    _validate_calendar(_required(root, "calendar", "dataset", problems), problems, references)
    _validate_income_tax(_required(root, "income_tax", "dataset", problems), problems, references)
    _validate_basic_living(
        _required(root, "basic_living_expense", "dataset", problems), problems, references
    )
    _validate_rule_list(
        _required(root, "interest_withholding", "dataset", problems),
        "interest_withholding",
        problems,
        references,
        premium=False,
    )
    _validate_rule_list(
        _required(root, "nhi_supplementary_premium", "dataset", problems),
        "nhi_supplementary_premium",
        problems,
        references,
        premium=True,
    )
    for source_id, path in references:
        if source_id not in source_ids:
            problems.append(f"{path}：引用不存在的來源「{source_id}」。")
    referenced_ids = {source_id for source_id, _ in references}
    if isinstance(root.get("sources"), list):
        for index, raw_source in enumerate(cast(list[object], root["sources"])):
            if isinstance(raw_source, Mapping) and isinstance(raw_source.get("id"), str):
                source_id = cast(str, raw_source["id"])
                if source_id in source_ids and source_id not in referenced_ids:
                    problems.append(f"sources[{index}].id：來源「{source_id}」沒有被引用。")
    return problems
