"""稅務領域使用的封閉列舉與繁體中文顯示文字。"""

from enum import StrEnum


class TaxKind(StrEnum):
    """稅務提醒使用的稅目。"""

    INCOME_TAX = "income_tax"
    HOUSE_TAX = "house_tax"
    LAND_VALUE_TAX = "land_value_tax"
    VEHICLE_LICENSE_TAX = "vehicle_license_tax"
    FUEL_FEE = "fuel_fee"


TAX_KIND_NAMES = {
    TaxKind.INCOME_TAX: "綜合所得稅",
    TaxKind.HOUSE_TAX: "房屋稅",
    TaxKind.LAND_VALUE_TAX: "地價稅",
    TaxKind.VEHICLE_LICENSE_TAX: "使用牌照稅",
    TaxKind.FUEL_FEE: "汽車燃料使用費",
}

TAX_KIND_ACTIONS = {
    TaxKind.INCOME_TAX: "申報",
    TaxKind.HOUSE_TAX: "繳納",
    TaxKind.LAND_VALUE_TAX: "繳納",
    TaxKind.VEHICLE_LICENSE_TAX: "繳納",
    TaxKind.FUEL_FEE: "繳納",
}


class IncomeKind(StrEnum):
    """綜合所得稅試算與帳務對應使用的所得類別。"""

    SALARY = "salary"
    INTEREST_TAXABLE = "interest_taxable"
    INTEREST_EXEMPT = "interest_exempt"
    PRIZE = "prize"
    WRITING_LECTURE = "writing_lecture"
    EXEMPT_INCOME = "exempt_income"
    FOREIGN_INCOME = "foreign_income"
    OTHER_INCOME = "other_income"
    EXCLUDED = "excluded"
    UNSUPPORTED = "unsupported"


INCOME_KIND_NAMES = {
    IncomeKind.SALARY: "薪資所得（含工讀、勞僱型助理）",
    IncomeKind.INTEREST_TAXABLE: "利息所得（應稅，例：定存）",
    IncomeKind.INTEREST_EXEMPT: "利息（免稅：郵政存簿儲金）",
    IncomeKind.PRIZE: "競技競賽及機會中獎獎金",
    IncomeKind.WRITING_LECTURE: "稿費、講演鐘點費",
    IncomeKind.EXEMPT_INCOME: "免稅所得（獎學金、學習型助學金等，依使用者判斷）",
    IncomeKind.FOREIGN_INCOME: "海外所得（例：國外平台的競賽獎金）",
    IncomeKind.OTHER_INCOME: "其他所得",
    IncomeKind.EXCLUDED: (
        "不計入（不是所得：初始金額、他人轉入、退稅、轉帳；"
        "或分離課稅已完稅，例：統一發票中獎）"
    ),
    IncomeKind.UNSUPPORTED: "不支援（股利、租賃、財產交易…）",
}

INCOME_KIND_NOTES = {
    IncomeKind.SALARY: "併入綜合所得，先減薪資所得特別扣除額（所得稅法第 14 條第三類、第 17 條）。",
    IncomeKind.INTEREST_TAXABLE: (
        "併入綜合所得，可減儲蓄投資特別扣除額（所得稅法第 14 條第四類、第 17 條）。"
    ),
    IncomeKind.INTEREST_EXEMPT: (
        "郵政存簿儲金的利息免納所得稅；定期儲金不適用（郵政儲金匯兌法第 20 條）。"
    ),
    IncomeKind.PRIZE: (
        "全額併入綜合所得；參加競技、競賽的必要費用可以減除，試算沒有減"
        "（所得稅法第 14 條第八類）。"
    ),
    IncomeKind.WRITING_LECTURE: (
        "稿費、版稅、講演鐘點費等全年合計在免稅上限內免稅（所得稅法第 4 條第 1 項第 23 款）。"
    ),
    IncomeKind.EXEMPT_INCOME: (
        "例如獎學金、研究考察補助費（所得稅法第 4 條第 1 項第 8 款）；算不算免稅由你判斷。"
    ),
    IncomeKind.FOREIGN_INCOME: (
        "不併入綜合所得，但可能計入最低稅負的基本所得額（所得基本稅額條例第 12 條）。"
    ),
    IncomeKind.OTHER_INCOME: "全額併入綜合所得（所得稅法第 14 條第十類）。",
    IncomeKind.EXCLUDED: "不是所得，或已依法分離課稅完稅的款項，不計入綜合所得總額。",
    IncomeKind.UNSUPPORTED: "試算不支援這類所得；該年有這類收入時試算會拒算，請改用財政部稅額試算。",
}

OVERRIDABLE_INCOME_KINDS = frozenset(
    {
        IncomeKind.SALARY,
        IncomeKind.INTEREST_TAXABLE,
        IncomeKind.PRIZE,
        IncomeKind.WRITING_LECTURE,
    }
)


class Flow(StrEnum):
    """帳務對應的收支方向。"""

    INCOME = "income"
    EXPENSE = "expense"


class ReminderMark(StrEnum):
    """使用者對稅務提醒設定的標記。"""

    HANDLED = "handled"
    NOT_APPLICABLE = "not_applicable"


REMINDER_MARK_NAMES = {
    ReminderMark.HANDLED: "已處理",
    ReminderMark.NOT_APPLICABLE: "本年不適用",
}


class FilingStatus(StrEnum):
    """綜合所得稅申報身分。"""

    SINGLE = "single"
    WITH_SPOUSE = "with_spouse"
    DEPENDENT_OF_OTHER = "dependent_of_other"


FILING_STATUS_NAMES = {
    FilingStatus.SINGLE: "自己單獨申報",
    FilingStatus.WITH_SPOUSE: "與配偶合併申報",
    FilingStatus.DEPENDENT_OF_OTHER: "被他人列為受扶養人",
}


class DeductionChoice(StrEnum):
    """申報時選用的扣除額方式。"""

    STANDARD = "standard"
    ITEMIZED = "itemized"


DEDUCTION_CHOICE_NAMES = {
    DeductionChoice.STANDARD: "標準扣除額",
    DeductionChoice.ITEMIZED: "列舉扣除額",
}
