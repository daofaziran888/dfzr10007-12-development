"""分析模型沉淀接口：模型注册清单、部署预检与部署动作。

写操作按调用者角色与归属负责人校验：只有归属负责人可以部署、下线、归档或变更归属；
数据目录成员与普通查看者拿到只读注册信息。身份通过 X-Operator / X-Role 请求头声明。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import current_identity
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.identity import PermissionDenied
from app.services.model import ModelService

router = APIRouter(prefix="/api/model", tags=["分析模型沉淀"])

service = ModelService()

LIST_FIELDS = ["模型编号", "模型名称", "模型类型", "训练数据", "评估指标", "模型版本", "部署路径", "模型状态", "负责人"]
STATUSES = ["草稿", "训练完成", "已部署", "已下线", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按模型编号或模型版本检索"),
    status: str | None = Query(default=None, description="草稿、训练完成、已部署、已下线"),
    page: int = 1,
    size: int = 20,
    identity: tuple[str, str] = Depends(current_identity),
) -> PageResult[dict]:
    """按模型编号与状态过滤分析模型沉淀列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    operator, role = identity
    items, total = service.list_entries(
        keyword=keyword, status=status, page=page, size=size, role=role, operator=operator,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/registry", response_model=dict)
def registry() -> dict[str, Any]:
    """模型注册清单：按训练数据、评估指标与模型版本汇总，供部署前核对。"""
    return service.registry()


@router.get("/deployments", response_model=dict)
def deployments(model_code: str | None = Query(default=None, description="按模型编号过滤发布流水")) -> dict[str, Any]:
    """模型发布流水：保留执行人与归属负责人，归属变更后历史记录不重写。"""
    items = service.deployments(model_code=model_code)
    return {"items": items, "total": len(items)}


@router.get("/export")
def export_entries(identity: tuple[str, str] = Depends(current_identity)) -> dict[str, Any]:
    """导出分析模型沉淀清单：返回当前过滤条件下的全量数据。"""
    operator, role = identity
    items, total = service.list_entries(page=1, size=10000, role=role, operator=operator)
    return {"module": "model", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, identity: tuple[str, str] = Depends(current_identity)) -> dict:
    """读取单条模型注册明细；不存在时给出可读的错误说明。"""
    operator, role = identity
    entry = service.get_entry(entry_id, role=role, operator=operator)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"模型注册 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/precheck", response_model=dict)
def precheck(entry_id: int) -> dict:
    """部署预检：给出可部署、需补充证据或拒绝部署的结论与依据。"""
    result = service.precheck(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"模型注册 {entry_id} 不存在或已归档")
    return result


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, identity: tuple[str, str] = Depends(current_identity)) -> ActionResult:
    """登记一条模型注册；同一模型编号+版本重复登记只保留一份记录。"""
    operator, role = identity
    try:
        entry, missing, duplicated = service.create_entry(payload.values, operator=operator, role=role)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message="模型注册未登记")
    if duplicated:
        return ActionResult(ok=True, message="同一模型版本已存在，已更新原记录且未新增副本", entry=entry)
    return ActionResult(ok=True, message="模型注册已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    identity: tuple[str, str] = Depends(current_identity),
) -> ActionResult:
    """执行部署模型、下线模型、归档模型、变更归属；越权动作返回 403 并说明原因。"""
    operator, role = identity
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, payload.values, operator=operator, role=role)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
