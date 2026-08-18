"""兩層類別樹的建立、封存、恢復、重新命名與刪除。

第一層是 `類別`、第二層是 `項目`（`level` 1 與 2），不要叫成「分類／細項」。
"""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.models import Category
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    has_any_reference,
)


class CategoryStore(StoreBase):
    def list_categories(
        self,
        *,
        parent_id: str | None = None,
        include_archived: bool = False,
    ) -> list[Category]:
        status_clause = "" if include_archived else "AND status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT category_id, name, parent_id, level, status, sort_order
                FROM categories
                WHERE parent_id IS ? {status_clause}
                ORDER BY sort_order, name COLLATE NOCASE
                """,
                (parent_id,),
            ).fetchall()
        return [Category(**dict(row)) for row in rows]

    def create_category(self, *, name: str, parent_id: str | None = None) -> Category:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("CATEGORY_NAME_REQUIRED")
        level = 1
        if parent_id is not None:
            with connect_database(self.paths.database_path) as connection:
                parent = connection.execute(
                    "SELECT level, status FROM categories WHERE category_id = ?", (parent_id,)
                ).fetchone()
            if parent is None or parent["status"] != "active" or int(parent["level"]) != 1:
                raise ValueError("CATEGORY_PARENT_INVALID")
            level = 2
        timestamp = now_iso()
        category = Category(
            category_id=f"cat_{uuid4().hex}",
            name=clean_name,
            parent_id=parent_id,
            level=level,
            status="active",
            sort_order=100,
        )
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO categories(
                    category_id, parent_id, level, name, status, sort_order,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category.category_id,
                    category.parent_id,
                    category.level,
                    category.name,
                    category.status,
                    category.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.create",
                entity_type="category",
                entity_id=category.category_id,
                details=asdict(category),
            )
        return category

    def archive_category(self, category_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            children = connection.execute(
                """
                SELECT COUNT(*) AS count FROM categories
                WHERE parent_id = ? AND status = 'active'
                """,
                (category_id,),
            ).fetchone()
            if children is not None and int(children["count"]) > 0:
                raise ValueError("CATEGORY_HAS_ACTIVE_CHILDREN")
            changed = connection.execute(
                """
                UPDATE categories SET status = 'archived', updated_at = ?
                WHERE category_id = ? AND status = 'active'
                """,
                (now_iso(), category_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.archive",
                entity_type="category",
                entity_id=category_id,
                details={},
            )

    def restore_category(self, category_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT name, parent_id FROM categories
                WHERE category_id = ? AND status = 'archived'
                """,
                (category_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            parent_id = row["parent_id"]
            if parent_id is not None:
                parent = connection.execute(
                    "SELECT status FROM categories WHERE category_id = ?", (parent_id,)
                ).fetchone()
                if parent is None or parent["status"] != "active":
                    raise ValueError("CATEGORY_PARENT_NOT_ACTIVE")
            duplicate = connection.execute(
                """
                SELECT 1 FROM categories
                WHERE parent_id IS ? AND name = ? COLLATE NOCASE
                  AND status = 'active' AND category_id != ?
                """,
                (parent_id, row["name"], category_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("CATEGORY_ACTIVE_NAME_CONFLICT")
            connection.execute(
                "UPDATE categories SET status = 'active', updated_at = ? WHERE category_id = ?",
                (now_iso(), category_id),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.restore",
                entity_type="category",
                entity_id=category_id,
                details={},
            )

    def rename_category(self, category_id: str, name: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("CATEGORY_NAME_REQUIRED")
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE categories SET name = ?, updated_at = ?
                WHERE category_id = ? AND status = 'active'
                """,
                (clean_name, now_iso(), category_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            self._refresh_fts_for_category(connection, category_id)
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.rename",
                entity_type="category",
                entity_id=category_id,
                details={"name": clean_name},
            )

    def delete_category(self, category_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM categories WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            children = connection.execute(
                "SELECT 1 FROM categories WHERE parent_id = ? LIMIT 1",
                (category_id,),
            ).fetchone()
            if children is not None:
                raise ValueError("CATEGORY_HAS_CHILDREN")
            if has_any_reference(
                connection,
                [
                    ("category_allocations", "category_id = ?", (category_id,)),
                    ("transaction_templates", "category_id = ?", (category_id,)),
                    ("recurring_schedules", "category_id = ?", (category_id,)),
                    ("scheduled_occurrences", "category_id = ?", (category_id,)),
                ],
            ):
                raise ValueError("CATEGORY_IN_USE")
            connection.execute("DELETE FROM categories WHERE category_id = ?", (category_id,))
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.delete",
                entity_type="category",
                entity_id=category_id,
                details={},
            )

    @classmethod
    def _refresh_fts_for_category(
        cls,
        connection: sqlite3.Connection,
        category_id: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT DISTINCT ca.transaction_id
            FROM category_allocations ca
            JOIN categories c ON c.category_id = ca.category_id
            WHERE ca.category_id = ? OR c.parent_id = ?
            """,
            (category_id, category_id),
        ).fetchall()
        for row in rows:
            cls._refresh_fts(connection, str(row["transaction_id"]))
