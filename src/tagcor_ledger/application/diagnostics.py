"""診斷資訊匯出：出問題時能一鍵產生一份可以直接交出去的文字檔。

**這份檔案不含任何金額、備註、帳戶名稱或個人資料夾的路徑。** 它回答的是「環境長什麼樣、
檔案在哪、資料庫健不健康」，不是「你花了多少錢」。所以可以安心貼給別人看。

會放進去的東西刻意限制在這些：程式版本、schema 版本、七個路徑與各自存不存在、
資料庫大小、`PRAGMA integrity_check` 結果、資料筆數（只有數量，沒有內容）、
以及最近幾行日誌。**路徑以佔位符開頭**（`<資料根目錄>`、`%USERPROFILE%`），見 `_redact()`。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sqlite3

from tagcor_ledger import __version__
from tagcor_ledger.app.logging_setup import current_log_path
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result
from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

LOG_TAIL_LINES = 200
DATA_ROOT_PLACEHOLDER = "<資料根目錄>"
HOME_PLACEHOLDER = "%USERPROFILE%"

# 只數筆數，不讀內容。加表格到這裡之前先問「它的數量會洩漏什麼嗎」。
_COUNTED_TABLES = (
    "accounts",
    "categories",
    "transactions",
    "account_postings",
    "balance_snapshots",
    "transaction_templates",
    "deposit_contracts",
    "deposit_terms",
    "deposit_events",
)


class DiagnosticsService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def export(self, target: Path | None = None) -> Result:
        try:
            report = self.build_report()
        except (OSError, sqlite3.Error) as exc:
            return Result.fail(
                "DIAGNOSTICS_BUILD_FAILED",
                "診斷資訊無法產生 —— 多半是資料庫讀不到。請確認磁碟已連接。",
                # `detail` 不會印在畫面上（見 `ui/formatting.result_message()`），
                # 它是給日誌與人工排查看的。
                details={"detail": str(exc)},
            )
        if target is None:
            stamp = datetime.now(TAIPEI).strftime("%Y%m%d_%H%M%S")
            target = self.paths.export_dir / f"diagnostics_{stamp}.txt"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # **這一份刻意帶 BOM（`utf-8-sig`），是專案「寫檔一律無 BOM」的例外。**
            # 那條規則的對象是給程式讀的 `.md`／`.json`；這份是給人雙擊打開看的 `.txt`，
            # Windows 上沒有 BOM 的中文純文字很容易被編輯器猜成 cp950 而整份亂碼
            # （2026-08-18 實際發生過）。BOM 換來的是「打開就看得懂」。
            target.write_text(report, encoding="utf-8-sig")
        except OSError as exc:
            return Result.fail(
                "DIAGNOSTICS_WRITE_FAILED",
                "診斷資訊無法寫入。請確認匯出資料夾存在且可寫入、磁碟還有空間。",
                details={"detail": str(exc)},
            )
        return Result.ok("診斷資訊已匯出。", details={"path": str(target)})

    def build_report(self) -> str:
        lines: list[str] = [
            "TagCor Ledger 診斷資訊",
            "本檔案不含任何金額、備註、帳戶名稱或個人資料夾的路徑"
            f"（以 {DATA_ROOT_PLACEHOLDER}、{HOME_PLACEHOLDER} 表示），可以直接提供給他人。",
            "",
            f"產生時間　　： {datetime.now(TAIPEI).isoformat(timespec='seconds')}",
            f"程式版本　　： {__version__}",
            f"支援 schema ： v{LATEST_SCHEMA_VERSION}",
            f"資料庫 schema： {self._schema_version()}",
            "",
            "== 路徑 ==",
        ]
        for name, value in self.paths.as_dict().items():
            lines.append(f"{name:<12}: {value}{'' if Path(value).exists() else '   （不存在）'}")

        database = self.paths.database_path
        lines += [
            "",
            "== 資料庫 ==",
            f"檔案　　： {database}",
            f"存在　　： {'是' if database.exists() else '否'}",
            f"大小　　： {database.stat().st_size if database.exists() else 0} bytes",
            f"完整性　： {self._integrity_check()}",
            "",
            "== 筆數（只有數量，沒有內容） ==",
        ]
        for table, count in self.counts().items():
            lines.append(f"{table:<24}: {count}")

        lines += ["", f"== 最近 {LOG_TAIL_LINES} 行日誌 =="]
        lines += self._log_tail()
        return self._redact("\n".join(lines) + "\n")

    def _redact(self, text: str) -> str:
        """把個人資料夾的路徑換成佔位符。**整份報告一起換**，日誌尾段也在內。

        資料根目錄的**名字本身**就是要藏的東西 —— repo 是公開的，所以版控裡一律寫
        `<資料根目錄>`；這份檔案標榜可以直接交給別人，就不能把它寫出來。家目錄帶著
        使用者名稱，同理。佔位符之後那一段留著：「哪個子資料夾不見了」才是排查要的資訊。

        日誌一定要一起換：錯誤堆疊與 `OSError` 的訊息常常帶著完整路徑。
        **由長到短換**，資料根目錄在家目錄底下時才不會先被換成 `%USERPROFILE%\\...`。
        """
        replacements = sorted(
            ((self.paths.data_dir, DATA_ROOT_PLACEHOLDER), (Path.home(), HOME_PLACEHOLDER)),
            key=lambda pair: len(str(pair[0])),
            reverse=True,
        )
        for path, placeholder in replacements:
            pattern = _path_pattern(path)
            if pattern is not None:
                text = pattern.sub(placeholder, text)
        return text

    def _schema_version(self) -> str:
        if not self.paths.database_path.exists():
            return "（資料庫尚未建立）"
        try:
            with connect_database(self.paths.database_path) as connection:
                row = connection.execute(
                    "SELECT MAX(version) AS version FROM schema_migrations"
                ).fetchone()
            return f"v{int(row['version'])}" if row and row["version"] is not None else "（無紀錄）"
        except sqlite3.Error as exc:
            return f"（讀取失敗：{exc}）"

    def _integrity_check(self) -> str:
        if not self.paths.database_path.exists():
            return "（資料庫尚未建立）"
        try:
            with connect_database(self.paths.database_path) as connection:
                row = connection.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row is not None else "unknown"
        except sqlite3.Error as exc:
            return f"（檢查失敗：{exc}）"

    def counts(self) -> dict[str, int]:
        """各表筆數。**只有數量，沒有內容** —— 重製前的確認框也用這個。"""
        counts: dict[str, int] = {}
        if not self.paths.database_path.exists():
            return counts
        try:
            with connect_database(self.paths.database_path) as connection:
                for table in _COUNTED_TABLES:
                    try:
                        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    except sqlite3.Error:
                        counts[table] = -1
                        continue
                    counts[table] = int(row["n"]) if row is not None else -1
        except sqlite3.Error:
            return counts
        return counts

    def _log_tail(self) -> list[str]:
        log_path = current_log_path()
        if log_path is None or not log_path.exists():
            return ["（沒有日誌檔）"]
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return [f"（日誌讀取失敗：{exc}）"]
        return content[-LOG_TAIL_LINES:] or ["（日誌是空的）"]


def _path_pattern(path: Path) -> re.Pattern[str] | None:
    """比對一個路徑的所有常見寫法：`\\`、`/`、JSON 逸出過的 `\\\\`，大小寫不拘。

    結尾不能緊接著路徑字元 —— 否則 `...\\data` 會把兄弟資料夾 `...\\data2` 也換掉一半。
    **只有一段的路徑不換**（`/`、`D:`）：換了會把每一個磁碟代號都變成佔位符，
    而它本來就不私人。
    """
    text = str(path)
    parts = [re.escape(part) for part in re.split(r"[\\/]+", text) if part]
    if len(parts) < 2:
        return None
    lead = r"[\\/]+" if text[:1] in ("\\", "/") else ""
    return re.compile(lead + r"[\\/]+".join(parts) + r"(?![\w.-])", re.IGNORECASE)
