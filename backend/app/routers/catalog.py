"""数据目录检索接口：维护目录条目，覆盖发布条目、下线条目、归档条目等动作。

字段清单统一引用训练数据字段清单（``app.services.datasets``），与分析模型沉淀的
模型注册清单使用同一份定义，不重复维护。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import current_identity
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.catalog import CatalogService
from app.services.datasets import TRAINING_DATASETS, field_manifest
from app.services.identity import PermissionDenied

router = APIRouter(prefix="/api/catalog", tags=["数据目录检索"])

service = CatalogService()

LIST_FIELDS = ["条目编号", "数据集名称", "业务域", "数据集编号", "更新频率", "数据等级", "负责人", "条目状态"]
STATUSES = ["草稿", "已发布", "已下线", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按条目编号、数据集编号或数据集名称检索"),
    status: str | None = Query(default=None, description="草稿、已发布、已下线、已归档"),
    page: int = 1,
    size: int = 20,
    identity: tuple[str, str] = Depends(current_identity),
) -> PageResult[dict]:
    """按条目编号与状态过滤数据目录检索列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    _operator, role = identity
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, role=role)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/field-manifests", response_model=dict)
def field_manifests() -> dict[str, Any]:
    """训练数据字段清单：模型注册清单与目录检索共用，返回同一份只读定义。"""
    items = [
        {
            "数据集编号": dataset["数据集编号"],
            "数据集名称": dataset["数据集名称"],
            "业务域": dataset["业务域"],
            "目录条目编号": dataset["目录条目编号"],
            "字段清单": field_manifest(dataset["数据集编号"]),
            "字段数": len(dataset["字段清单"]),
        }
        for dataset in TRAINING_DATASETS.values()
    ]
    return {"items": items, "total": len(items), "来源": "模型注册与数据目录检索共用同一份训练数据字段清单"}


@router.get("/export")
def export_entries(identity: tuple[str, str] = Depends(current_identity)) -> dict[str, Any]:
    """导出数据目录检索清单：返回当前过滤条件下的全量数据。"""
    _operator, role = identity
    items, total = service.list_entries(page=1, size=10000, role=role)
    return {"module": "catalog", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, identity: tuple[str, str] = Depends(current_identity)) -> dict:
    """读取单条目录条目明细；不存在时给出可读的错误说明。"""
    _operator, role = identity
    entry = service.get_entry(entry_id, role=role)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"目录条目 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, identity: tuple[str, str] = Depends(current_identity)) -> ActionResult:
    """登记一条目录条目，缺字段时说明原因而不是静默丢弃。"""
    _operator, role = identity
    try:
        entry, missing = service.create_entry(payload.values, role=role)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="目录条目已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    identity: tuple[str, str] = Depends(current_identity),
) -> ActionResult:
    """对单条目录条目执行发布条目、下线条目、归档条目；不允许的动作会被拦下并说明原因。"""
    _operator, role = identity
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, role=role)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
