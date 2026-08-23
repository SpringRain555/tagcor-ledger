"""兩層類別樹的建立、封存、恢復、重新命名與刪除。

第一層是 `類別`、第二層是 `項目`（`level` 1 與 2），不要叫成「分類／細項」。
"""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.models import Category, CategoryNode, CategoryTreeFilter
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    has_any_reference,
    order_by,
)

CATEGORY_SORT_FIELDS: dict[str, str] = {
    "custom": "category_node.sort_order",
    "name": "category_node.name COLLATE NOCASE",
    "item_count": "item_count",
    "status": "category_node.status",
    # 「項目」那頁才用得到：先照所屬類別、再照項目自己。
    "parent_custom": "category_parent.sort_order",
    # 不用 `COALESCE(..., '')`：排序時 NULL 在 ASC 本來就排最前、DESC 排最後，
    # 跟空字串一樣。少一個字面值，白名單的「不得出現引號」就守得住。
    "parent_name": "category_parent.name COLLATE NOCASE",
}
"""**`ORDER BY` 的白名單。** key 是畫面送進來的欄位名，value 是固定的 SQL 運算式。
畫面永遠只能送 key —— 這份清單必須是封閉的，組裝規則見 `base.order_by()`。

**自訂順序拆成 `custom` 與 `parent_custom` 兩個欄位**，因為 `sort_order` 的意義
只在同一組之內。項目跨類別比自己的 `sort_order` 會互相穿插（每組都是 10、20、30），
要先用 `parent_custom` 把同一類別的聚在一起，第二層才輪得到 `custom`。
"""

CATEGORY_DEFAULT_ORDER: tuple[str, ...] = (
    "COALESCE(category_parent.sort_order, category_node.sort_order)",
    "COALESCE(category_parent.name, category_node.name) COLLATE NOCASE",
    "category_node.level",
    "category_node.sort_order",
)
"""沒有指定規格時的順序：**項目跟在自己的類別後面**。

這不是「某一欄的排序」，是這份資料本來的形狀，而且要同時容納只有第一層、只有第二層、
以及兩層混在一起（排序視窗就是這樣查的）三種情況 —— 所以用 `COALESCE` 而不是
單一欄位，也因此它沒辦法表達成一個 `SortLevel`。
"""

CATEGORY_TIEBREAKERS: tuple[str, ...] = (
    "category_node.name COLLATE NOCASE",
    "category_node.category_id",
)
"""完全同分時的最終順序。少了它，畫面每次重整都可能換一個樣子。"""


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

    def list_category_tree(
        self,
        *,
        include_archived: bool = False,
        tree_filter: CategoryTreeFilter | None = None,
    ) -> list[CategoryNode]:
        """一句話取回兩層類別、上層名稱與子項目數，**篩選與排序都在 SQL 裡**。

        舊的做法是先 `list_categories()` 拿到所有類別，再對**每一個**類別各呼叫一次
        `list_categories(parent_id=...)` —— 而每一次都開一條新連線。

        預設排序刻意讓項目跟在自己的類別後面：先照上層（沒有上層就照自己）的
        `sort_order` 與名稱，再照 `level`。

        `include_archived` 留著給既有呼叫端用；`tree_filter` 一給就以它為準。
        """
        selected = tree_filter or CategoryTreeFilter(
            status="all" if include_archived else "active"
        )
        conditions: list[str] = []
        values: list[object] = []
        if selected.status in {"active", "archived"}:
            conditions.append("category_node.status = ?")
            values.append(selected.status)
        if selected.level is not None:
            conditions.append("category_node.level = ?")
            values.append(selected.level)
        if selected.parent_id is not None:
            conditions.append("category_node.parent_id = ?")
            values.append(selected.parent_id)
        if selected.search:
            # 項目也讓使用者用類別名搜得到 —— 打「交通」要列出交通底下的每一項。
            conditions.append(
                "(category_node.name LIKE '%' || ? || '%' COLLATE NOCASE"
                " OR COALESCE(category_parent.name, '') LIKE '%' || ? || '%' COLLATE NOCASE)"
            )
            values.extend([selected.search, selected.search])
        where = " AND ".join(["1 = 1", *conditions])

        # 子項目數跟著同一個狀態條件走：列表顯示封存的項目時，數字也要含它們，
        # 否則「0 項」底下卻列得出東西。
        item_status = (
            "" if selected.status == "all" else f"AND category_item.status = '{selected.status}'"
        )

        # **`ORDER BY` 只從白名單來。** 規格是畫面傳進來的，任何字串內插都是一條
        # 注入路徑；`order_by()` 查不到的欄位整層跳過，不接受未知的值。
        order = order_by(
            selected.sort,
            fields=CATEGORY_SORT_FIELDS,
            default=CATEGORY_DEFAULT_ORDER,
            tiebreakers=CATEGORY_TIEBREAKERS,
        )

        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT category_node.category_id, category_node.name, category_node.parent_id, category_node.level,
                       category_node.status, category_node.sort_order,
                       category_parent.name AS parent_name,
                       (
                           SELECT COUNT(*) FROM categories AS category_item
                           WHERE category_item.parent_id = category_node.category_id {item_status}
                       ) AS item_count
                FROM categories AS category_node
                LEFT JOIN categories AS category_parent ON category_parent.category_id = category_node.parent_id
                WHERE {where}
                ORDER BY {order}
                """,
                tuple(values),
            ).fetchall()
        return [
            CategoryNode(
                category=Category(
                    category_id=str(row["category_id"]),
                    name=str(row["name"]),
                    parent_id=row["parent_id"],
                    level=int(row["level"]),
                    status=str(row["status"]),
                    sort_order=int(row["sort_order"]),
                ),
                parent_name=row["parent_name"],
                item_count=int(row["item_count"]),
            )
            for row in rows
        ]

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

    def set_category_order(
        self,
        ordered_ids: list[str],
        *,
        parent_id: str | None,
        level: int,
    ) -> None:
        """把**一整組**的自訂順序寫下來（同一個 `parent_id` 底下的同一層）。

        **收整份清單，不是「往上一格」。** 排序視窗本來就握有完整順序，送整份進來
        比在資料庫裡算相對位置簡單，也順便擋掉「清單過期」——`_apply_sort_order()`
        會要求送進來的 id 與現況是**完全一樣的一組**，不多不少。

        `sort_order` 的意義**只在同一組之內**。項目跨類別比 `sort_order` 沒有意義
        （每一組都是 10、20、30，會互相穿插），所以呼叫端一定要指名是哪一組 ——
        這也是為什麼「項目」的排序視窗要先選類別。
        """
        with database_transaction(self.paths.database_path) as connection:
            current = [
                str(row["category_id"])
                for row in connection.execute(
                    """
                    SELECT category_id FROM categories
                    WHERE parent_id IS ? AND level = ?
                    """,
                    (parent_id, level),
                ).fetchall()
            ]
            self._apply_sort_order(
                connection,
                table="categories",
                id_column="category_id",
                current_ids=current,
                ordered_ids=ordered_ids,
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.reorder",
                entity_type="category",
                entity_id=parent_id or "root",
                details={"level": level, "count": len(ordered_ids)},
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
