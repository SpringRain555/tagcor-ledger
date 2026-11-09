"""稅務 use case：資料、新鮮度、提醒、申報試算與所得歸類。"""

from tagcor_ledger.application.tax.classification import TaxClassificationSection
from tagcor_ledger.application.tax.data import TaxDataSection
from tagcor_ledger.application.tax.filing import TaxFilingSection
from tagcor_ledger.application.tax.reminders import TaxReminderSection


class TaxService(TaxDataSection, TaxReminderSection, TaxFilingSection, TaxClassificationSection):
    """稅務 use case 入口，各方法由獨立 section 提供。"""
