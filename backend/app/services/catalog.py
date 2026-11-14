"""数据目录检索业务规则：状态流转、字段校验与筛选口径都收在这里。

字段清单不在目录条目上单独保存，而是按「数据集编号」引用
``app.services.datasets`` 里同一份训练数据字段清单，模型注册清单也读这一份。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.datasets import dataset_code, resolve_dataset
from app.services.identity import PermissionDenied, ROLE_CATALOG, ROLE_VIEWER
from app.store import store

MODULE = "catalog"
REQUIRED_FIELDS = ["条目编号", "数据集名称", "业务域"]
STATUS_ORDER = ["草稿", "已发布", "已下线", "已归档"]
ACTION_RULES = {"发布条目": "已发布", "下线条目": "已下线", "归档条目": "已归档"}
NEGATIVE_ACTIONS = ["下线条目"]
CATALOG_WRITE_ROLES = {ROLE_CATALOG}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


class CatalogService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        role: str = ROLE_VIEWER,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("条目编号", ""))
                or keyword in str(row.get("数据集编号", ""))
                or keyword in str(row.get("数据集名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.present_entry(row, role=role) for row in rows[start:start + size]], total

    def present_entry(self, row: dict[str, Any], *, role: str = ROLE_VIEWER) -> dict[str, Any]:
        entry = deepcopy(row)
        code = _as_text(row.get("数据集编号")) or dataset_code(row.get("数据集名称")) or ""
        dataset = resolve_dataset(code) if code else None
        entry["字段清单"] = deepcopy(dataset["字段清单"]) if dataset else []
        entry["字段清单来源"] = (
            f"与模型注册共用训练数据字段清单（{dataset['数据集编号']}）" if dataset
            else "未关联共用字段清单"
        )
        entry["字段数"] = len(entry["字段清单"])
        entry["readonly"] = role not in CATALOG_WRITE_ROLES
        return entry

    def get_entry(self, entry_id: int, *, role: str = ROLE_VIEWER) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self.present_entry(row, role=role)

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        role: str = ROLE_VIEWER,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        if role not in CATALOG_WRITE_ROLES:
            raise PermissionDenied("普通查看者不能登记目录条目")
        missing = [field for field in REQUIRED_FIELDS if not _as_text(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        dataset = resolve_dataset(values.get("数据集编号") or values.get("数据集名称"))
        if dataset is not None:
            entry["数据集编号"] = dataset["数据集编号"]
            entry["数据集名称"] = values.get("数据集名称") or dataset["数据集名称"]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["负责人"] = _as_text(values.get("负责人")) or ""
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str, *, role: str = ROLE_VIEWER) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"目录条目 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据目录检索可执行范围"
        if role not in CATALOG_WRITE_ROLES:
            raise PermissionDenied("数据目录写操作只允许数据目录成员或模型负责人执行")
        source = STATUS_ORDER.index(ACTION_RULES[action]) - 1
        if source >= 0 and _as_text(entry.get("status")) != STATUS_ORDER[source]:
            return None, f"目录条目当前状态为「{entry.get('status')}」，不能执行「{action}」"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target == STATUS_ORDER[0]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"目录条目已{action}"
