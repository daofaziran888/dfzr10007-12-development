"""分析模型沉淀业务规则：模型注册清单、部署预检、部署流转与归属控制。

关键口径：
- 模型注册清单按「训练数据 + 评估指标 + 模型版本」汇总；训练数据字段清单直接引用
  ``app.services.datasets``，与数据目录检索共用同一份定义，不各自复制。
- 部署预检给出三档结论：可部署 / 需补充证据 / 拒绝部署。
- 同一「模型编号 + 模型版本」只保留一条注册记录，重复登记走更新而不是追加。
- 同一模型编号的部署由模块级锁串行化，任何时刻只有一个版本「是否生效」为真。
- 部署执行失败时，把该版本评估指标回退到上一份评估指标快照，生效版本保持不变。
- 模型写操作只允许归属负责人执行；历史发布记录保存执行当时的负责人，变更归属不回写。
"""
from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import date
from typing import Any

from app.services.datasets import dataset_code, resolve_dataset
from app.services.identity import PermissionDenied, ROLE_OWNER, ROLE_VIEWER
from app.store import store

MODULE = "model"
CATALOG_MODULE = "catalog"
REQUIRED_FIELDS = ["模型编号", "模型名称", "模型类型", "训练数据", "模型版本"]
STATUS_ORDER = ["草稿", "训练完成", "已部署", "已下线"]
ACTION_RULES = ["部署模型", "下线模型", "归档模型", "变更归属"]
MUTABLE_FIELDS = ["模型名称", "模型类型", "训练数据", "评估指标", "部署路径", "模型状态"]

# 模型类型 → 必备评估指标与部署门槛。缺失指标不直接拒绝，而是转「需补充证据」。
TYPE_RULES: dict[str, dict[str, Any]] = {
    "分类": {
        "required": ["AUC", "准确率"],
        "checks": [("AUC", ">=", 0.85), ("准确率", ">=", 0.85)],
    },
    "回归": {
        "required": ["RMSE", "R2"],
        "checks": [("RMSE", "<=", 1.0), ("R2", ">=", 0.80)],
    },
    "聚类": {
        "required": ["轮廓系数"],
        "checks": [("轮廓系数", ">=", 0.45)],
    },
}

VERSION_PATTERN = re.compile(r"^[vV]?\d+(?:[.\-][0-9A-Za-z]+)*$")
PATH_PATTERN = re.compile(r"^/models/[A-Za-z0-9][A-Za-z0-9._\-/]*$")

CONCLUSION_OK = "可部署"
CONCLUSION_EVIDENCE = "需补充证据"
CONCLUSION_REJECT = "拒绝部署"

# ---- 部署流水（进程内留档，跨请求保持；真实项目替换为数据库表） ----
_DEPLOYMENTS: list[dict[str, Any]] = []
_DEPLOYMENT_SEEDED = False
_DEPLOYMENTS_GUARD = threading.Lock()

# ---- 按模型编号分锁：注册去重与部署互斥 ----
_MODEL_LOCKS: dict[str, threading.Lock] = {}
_MODEL_LOCKS_GUARD = threading.Lock()


def _model_lock(model_code: str) -> threading.Lock:
    with _MODEL_LOCKS_GUARD:
        return _MODEL_LOCKS.setdefault(model_code, threading.Lock())


def _parse_metrics(text: Any) -> tuple[dict[str, float], list[str]]:
    """把「AUC=0.912;准确率=0.903」解析成指标字典；无法识别的片段单独返回。"""
    metrics: dict[str, float] = {}
    invalid: list[str] = []
    for part in re.split(r"[;；,，|]", str(text or "")):
        piece = part.strip()
        if not piece:
            continue
        if "=" in piece or ":" in piece or "：" in piece:
            key, raw = re.split(r"[=:：]", piece, maxsplit=1)
            key = key.strip()
            try:
                metrics[key] = float(raw.strip())
            except ValueError:
                invalid.append(piece)
        else:
            invalid.append(piece)
    return metrics, invalid


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _is_active(row: dict[str, Any]) -> bool:
    return bool(row.get("是否生效"))


def _catalog_entry(dataset_code_value: str) -> dict[str, Any] | None:
    for row in store.rows(CATALOG_MODULE):
        if _as_text(row.get("数据集编号")) == dataset_code_value:
            return row
    name = ""
    dataset = resolve_dataset(dataset_code_value)
    if dataset:
        name = str(dataset["数据集名称"])
    for row in store.rows(CATALOG_MODULE):
        if name and _as_text(row.get("数据集名称")) == name:
            return row
    return None


def _ensure_deployment_seed() -> None:
    """给初始已部署的 MODE-0003 补一条历史发布留档，便于回退与归属复读。"""
    global _DEPLOYMENT_SEEDED
    with _DEPLOYMENTS_GUARD:
        if _DEPLOYMENT_SEEDED:
            return
        _DEPLOYMENTS.extend([
            {
                "记录编号": "DEPL-0001",
                "模型编号": "MODE-0003",
                "模型版本": "v3.0.0",
                "执行人": "林知远",
                "归属负责人": "林知远",
                "评估指标快照": "轮廓系数=0.52",
                "部署路径": "/models/mode-0003/v3.0.0",
                "结论": "历史发布",
                "结果": "生效中",
                "时间": "2026-10-08 09:30",
            }
        ])
        _DEPLOYMENT_SEEDED = True


def _next_deployment_id() -> str:
    return f"DEPL-{len(_DEPLOYMENTS) + 1:04d}"


def reset_state() -> None:
    """清空发布流水并回到种子数据，供测试与本地重置使用。"""
    global _DEPLOYMENT_SEEDED
    with _DEPLOYMENTS_GUARD:
        _DEPLOYMENTS.clear()
        _DEPLOYMENT_SEEDED = False
    store.reset()


def _latest_snapshot(model_code: str, *, exclude: set[str] | None = None) -> str:
    """返回该模型上一份成功发布的评估指标快照。"""
    exclude = exclude or set()
    for record in reversed(_DEPLOYMENTS):
        if record["模型编号"] != model_code:
            continue
        if record["模型版本"] in exclude:
            continue
        if record["结果"] in {"生效中", "已替换"} and record.get("评估指标快照"):
            return str(record["评估指标快照"])
    return ""


class ModelService:
    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        role: str = ROLE_VIEWER,
        operator: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("模型编号", ""))
                or keyword in str(row.get("模型版本", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self.present_entry(row, role=role, operator=operator) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int, *, role: str = ROLE_VIEWER, operator: str = "") -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self.present_entry(row, role=role, operator=operator)

    def present_entry(self, row: dict[str, Any], *, role: str, operator: str) -> dict[str, Any]:
        """对外呈现注册信息：附带预检结论与当前身份可执行的动作；查看者只读。"""
        entry = deepcopy(row)
        check = self.check_deployment(row)
        entry["部署预检结论"] = check["结论"]
        entry["部署预检说明"] = "；".join(check["拒绝原因"] + check["缺失证据"]) or "证据齐全"
        entry["可执行动作"] = self.allowed_actions(row, role=role, operator=operator)
        # readonly 只看权限，不看当前状态：归属负责人即使暂时没有可执行动作，也不是只读身份。
        can_write = role == ROLE_OWNER and _as_text(row.get("负责人")) == operator
        entry["readonly"] = not can_write
        if role != ROLE_OWNER:
            entry["只读说明"] = "只读注册信息：当前身份无模型写权限"
        elif not can_write:
            entry["只读说明"] = f"只读注册信息：模型归属负责人 {row.get('负责人')}，当前操作人无写权限"
        else:
            entry["只读说明"] = ""
        return entry

    def allowed_actions(self, row: dict[str, Any], *, role: str, operator: str) -> list[str]:
        """当前身份在当前状态下真正可执行的动作；用于前端按钮与只读判定。"""
        if role != ROLE_OWNER or _as_text(row.get("负责人")) != operator:
            return []
        status = _as_text(row.get("status"))
        if _as_text(row.get("模型状态")) == "已归档":
            return []
        if status == "已下线":
            actions = ["归档模型"]
        elif status == "已部署" or _is_active(row):
            # 生效中的版本只能下线或转移归属，不能重复部署。
            actions = ["下线模型"]
        elif self.check_deployment(row)["结论"] == CONCLUSION_OK:
            actions = ["部署模型"]
        else:
            # 预检未通过时不给部署入口，结论与缺失证据在预检面板里查看。
            actions = []
        return actions + ["变更归属"]

    def registry(self) -> dict[str, Any]:
        """模型注册清单：按训练数据、评估指标与模型版本汇总，供部署核对。"""
        groups: dict[str, dict[str, Any]] = {}
        for row in store.rows(MODULE):
            model_code = _as_text(row.get("模型编号"))
            group = groups.setdefault(model_code, {
                "模型编号": model_code,
                "模型名称": row.get("模型名称"),
                "模型类型": row.get("模型类型"),
                "负责人": row.get("负责人"),
                "训练数据": self._training_data_block(row),
                "版本列表": [],
            })
            check = self.check_deployment(row)
            group["版本列表"].append({
                "记录ID": row.get("id"),
                "模型版本": row.get("模型版本"),
                "评估指标": row.get("评估指标") or "",
                "模型状态": row.get("status"),
                "是否生效": bool(row.get("是否生效")),
                "部署路径": row.get("部署路径") or "",
                "预检结论": check["结论"],
                "预检说明": "；".join(check["拒绝原因"] + check["缺失证据"]) or "证据齐全",
            })
        datasets = []
        for group in groups.values():
            block = group["训练数据"]
            if block["数据集编号"] and block["数据集编号"] not in {item["数据集编号"] for item in datasets}:
                datasets.append(self._training_data_block_by_code(block["数据集编号"]))
        return {
            "清单口径": "按训练数据字段清单、评估指标与模型版本生成；字段清单与数据目录检索共用",
            "数据集": datasets,
            "items": sorted(groups.values(), key=lambda item: item["模型编号"]),
        }

    def _training_data_block(self, row: dict[str, Any]) -> dict[str, Any]:
        dataset = resolve_dataset(row.get("训练数据"))
        if dataset is None:
            return {
                "数据集编号": "",
                "数据集名称": _as_text(row.get("训练数据")),
                "字段清单": [],
                "字段数": 0,
                "引用状态": "未在共用字段清单中登记",
            }
        return self._training_data_block_by_code(str(dataset["数据集编号"]))

    def _training_data_block_by_code(self, code: str) -> dict[str, Any]:
        dataset = resolve_dataset(code)
        if dataset is None:
            return {"数据集编号": code, "数据集名称": "", "字段清单": [], "字段数": 0, "引用状态": "未登记"}
        catalog = _catalog_entry(code)
        return {
            "数据集编号": dataset["数据集编号"],
            "数据集名称": dataset["数据集名称"],
            "业务域": dataset["业务域"],
            "目录条目编号": dataset["目录条目编号"],
            "目录状态": catalog.get("status") if catalog else "未登记",
            "字段清单": deepcopy(dataset["字段清单"]),
            "字段数": len(dataset["字段清单"]),
            "引用状态": "与数据目录检索共用同一份字段清单",
        }

    def deployments(self, model_code: str | None = None) -> list[dict[str, Any]]:
        _ensure_deployment_seed()
        rows = list(_DEPLOYMENTS)
        if model_code:
            rows = [row for row in rows if row["模型编号"] == model_code]
        return deepcopy(rows)

    # ---------- 部署预检 ----------

    def check_deployment(self, row: dict[str, Any]) -> dict[str, Any]:
        """按训练数据、评估指标和模型版本判定部署条件。"""
        _ensure_deployment_seed()
        reject: list[str] = []
        gaps: list[str] = []
        checks: list[str] = []

        model_type = _as_text(row.get("模型类型"))
        rules = TYPE_RULES.get(model_type)
        if rules is None:
            reject.append(f"模型类型「{model_type or '空'}」不在可部署类型（分类/回归/聚类）内")

        version = _as_text(row.get("模型版本"))
        if not version:
            reject.append("缺少模型版本，无法定位待部署制品")
        elif not VERSION_PATTERN.match(version):
            reject.append(f"模型版本「{version}」格式不合法")

        status = _as_text(row.get("status"))
        if status == "草稿":
            gaps.append("模型版本仍为草稿，训练尚未完成")
        elif status == "已下线":
            reject.append("模型版本已下线，不允许重新部署")
        elif status not in {"训练完成", "已部署"}:
            gaps.append(f"模型状态「{status or '空'}」不足以支撑部署")

        path = _as_text(row.get("部署路径"))
        if not path:
            gaps.append("缺少部署路径")
        elif not PATH_PATTERN.match(path):
            reject.append(f"部署路径「{path}」不符合 /models/ 仓库规范")

        # 训练数据必须能在共用字段清单中解析，并且目录条目处于已发布状态。
        dataset = resolve_dataset(row.get("训练数据"))
        if dataset is None:
            reject.append(f"训练数据「{_as_text(row.get('训练数据')) or '空'}」未在共用字段清单中登记")
        else:
            catalog = _catalog_entry(str(dataset["数据集编号"]))
            if catalog is None:
                gaps.append(f"训练数据 {dataset['数据集编号']} 尚未登记数据目录条目")
            elif catalog.get("status") == "草稿":
                gaps.append(f"数据目录条目 {catalog.get('条目编号')} 仍为草稿，字段清单未发布")
            elif catalog.get("status") in {"已下线", "已归档"}:
                reject.append(f"数据目录条目 {catalog.get('条目编号')} 状态为「{catalog.get('status')}」，训练数据不可用")
            else:
                checks.append(f"训练数据 {dataset['数据集编号']} 字段清单已发布（{len(dataset['字段清单'])} 个字段）")

        # 评估指标：缺失转「需补充证据」，低于门槛转「拒绝部署」。
        metrics, invalid = _parse_metrics(row.get("评估指标"))
        if invalid:
            reject.append("评估指标无法解析：" + "、".join(invalid))
        if rules is not None:
            missing = [key for key in rules["required"] if key not in metrics]
            if missing:
                gaps.append("缺少评估指标：" + "、".join(missing))
            for key, op, threshold in rules["checks"]:
                if key not in metrics:
                    continue
                value = metrics[key]
                passed = value >= threshold if op == ">=" else value <= threshold
                if passed:
                    checks.append(f"{key}={value:g}（门槛 {op}{threshold:g}）")
                else:
                    reject.append(f"{key}={value:g} 未达部署门槛 {op}{threshold:g}")

        snapshot = _latest_snapshot(_as_text(row.get("模型编号")))
        active_row = next(
            (item for item in store.rows(MODULE)
             if _as_text(item.get("模型编号")) == _as_text(row.get("模型编号")) and _is_active(item)),
            None,
        )
        if active_row and not snapshot:
            snapshot = _as_text(active_row.get("评估指标"))

        if reject:
            conclusion = CONCLUSION_REJECT
        elif gaps:
            conclusion = CONCLUSION_EVIDENCE
        else:
            conclusion = CONCLUSION_OK

        return {
            "模型编号": row.get("模型编号"),
            "模型版本": row.get("模型版本"),
            "模型类型": row.get("模型类型"),
            "训练数据": self._training_data_block(row),
            "评估指标": deepcopy(metrics),
            "评估指标快照": snapshot,
            "结论": conclusion,
            "拒绝原因": reject,
            "缺失证据": gaps,
            "通过项": checks,
            "可执行部署": conclusion == CONCLUSION_OK,
        }

    def precheck(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self.check_deployment(row)

    # ---------- 注册 ----------

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        operator: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记模型注册；同一模型编号+版本只保留一份，重复登记收敛为更新。"""
        if role != ROLE_OWNER:
            raise PermissionDenied("只有模型负责人可以登记模型注册")
        missing = [field for field in REQUIRED_FIELDS if not _as_text(values.get(field))]
        if missing:
            return None, missing, False

        model_code = _as_text(values.get("模型编号"))
        version = _as_text(values.get("模型版本"))
        with _model_lock(model_code):
            rows = store.rows(MODULE)
            existing = next(
                (row for row in rows
                 if _as_text(row.get("模型编号")) == model_code
                 and _as_text(row.get("模型版本")) == version),
                None,
            )
            if existing is not None:
                if _as_text(existing.get("负责人")) != operator:
                    raise PermissionDenied(
                        f"模型版本 {model_code}/{version} 归属 {existing.get('负责人')}，当前操作人不能改写"
                    )
                for field in MUTABLE_FIELDS:
                    if field in values and _as_text(values.get(field)):
                        existing[field] = values.get(field)
                if _as_text(values.get("模型状态")) in STATUS_ORDER:
                    existing["status"] = _as_text(values.get("模型状态"))
                    existing["模型状态"] = existing["status"]
                return existing, [], True

            new_row = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "status": "草稿",
                "pending": True,
                "abnormal": False,
                "是否生效": False,
                "负责人": operator,
                "注册时间": date.today().isoformat(),
            }
            for field in REQUIRED_FIELDS + ["评估指标", "部署路径"]:
                new_row[field] = values.get(field) or ""
            if _as_text(values.get("模型状态")) in STATUS_ORDER:
                new_row["status"] = _as_text(values.get("模型状态"))
            new_row["模型状态"] = new_row["status"]
            rows.append(new_row)
            return new_row, [], False

    # ---------- 动作 ----------

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
        *,
        operator: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, str]:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"模型注册 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分析模型沉淀可执行范围"
        if role != ROLE_OWNER:
            raise PermissionDenied("模型写操作只允许模型负责人执行，数据目录成员与普通查看者无权改写")
        if _as_text(row.get("负责人")) != operator:
            raise PermissionDenied(
                f"模型注册 {row.get('模型编号')} 归属负责人 {row.get('负责人')}，只允许归属负责人执行该动作"
            )

        if action == "变更归属":
            return self._transfer_owner(row, values, operator)
        if action == "部署模型":
            return self._deploy(row, operator)

        if action == "下线模型":
            with _model_lock(_as_text(row.get("模型编号"))):
                if not _is_active(row) and _as_text(row.get("status")) != "已部署":
                    return None, "只有生效中的模型版本可以下线"
                row["是否生效"] = False
                row["status"] = "已下线"
                row["模型状态"] = "已下线"
                row["pending"] = False
                self._close_deployment(_as_text(row.get("模型编号")), _as_text(row.get("模型版本")), result="已下线")
            return row, "模型版本已下线"

        if action == "归档模型":
            if _as_text(row.get("status")) != "已下线":
                return None, "只有已下线的模型版本可以归档"
            row["pending"] = False
            row["模型状态"] = "已归档"
            return row, "模型版本已归档留档"
        return None, f"动作「{action}」暂不可执行"

    def _transfer_owner(
        self,
        row: dict[str, Any],
        values: dict[str, Any],
        operator: str,
    ) -> tuple[dict[str, Any], str]:
        new_owner = _as_text(values.get("负责人"))
        if not new_owner:
            return None, "变更归属需要提供新负责人"
        previous = _as_text(row.get("负责人"))
        if new_owner == previous:
            return row, f"模型归属已经是 {new_owner}，无需变更"
        model_code = _as_text(row.get("模型编号"))
        with _model_lock(model_code):
            # 归属按模型编号整体迁移，保证同一模型的版本不会出现两个负责人。
            affected = 0
            for item in store.rows(MODULE):
                if _as_text(item.get("模型编号")) == model_code:
                    item["负责人"] = new_owner
                    affected += 1
        return row, f"模型 {model_code} 归属已由 {previous} 变更为 {new_owner}，历史发布仍按原责任人留档（{affected} 个版本）"

    def _deploy(self, row: dict[str, Any], operator: str) -> tuple[dict[str, Any] | None, str]:
        model_code = _as_text(row.get("模型编号"))
        version = _as_text(row.get("模型版本"))
        with _model_lock(model_code):
            # 锁内重新计算预检，避免预检与部署之间的状态漂移。
            latest = store.find(MODULE, int(row.get("id", 0)))
            if latest is None:
                return None, f"模型注册 {row.get('id')} 不存在或已归档"
            check = self.check_deployment(latest)
            if check["结论"] != CONCLUSION_OK:
                reasons = "；".join(check["拒绝原因"] + check["缺失证据"])
                return None, f"部署预检结论为「{check['结论']}」：{reasons}，暂不执行部署"
            if _is_active(latest):
                return latest, f"模型 {model_code}/{version} 已是生效版本，无需重复部署"

            metric_before = _as_text(latest.get("评估指标"))
            # 回退快照：该模型上一份成功发布记录里的评估指标。
            snapshot = _latest_snapshot(model_code, exclude={version})
            if not snapshot:
                active_row = next(
                    (item for item in store.rows(MODULE)
                     if _as_text(item.get("模型编号")) == model_code and _is_active(item)
                     and _as_text(item.get("模型版本")) != version),
                    None,
                )
                snapshot = _as_text(active_row.get("评估指标")) if active_row else metric_before
            path = _as_text(latest.get("部署路径"))

            conflict = next(
                (item for item in store.rows(MODULE)
                 if item.get("id") != latest.get("id")
                 and _as_text(item.get("部署路径")) == path
                 and (_is_active(item) or _as_text(item.get("status")) == "已部署")),
                None,
            )
            if conflict is not None:
                return None, self._rollback(latest, snapshot, check, version, operator, path,
                                            reason=f"部署路径 {path} 已被 {conflict.get('模型编号')}/{conflict.get('模型版本')} 占用")

            previous = next(
                (item for item in store.rows(MODULE)
                 if _as_text(item.get("模型编号")) == model_code and _is_active(item)),
                None,
            )
            previous_snapshot = _latest_snapshot(model_code, exclude={version}) or snapshot
            if previous is not None and previous.get("id") != latest.get("id"):
                try:
                    previous["是否生效"] = False
                    previous["status"] = "已下线"
                    previous["模型状态"] = "已下线"
                    previous["pending"] = False
                    self._close_deployment(model_code, _as_text(previous.get("模型版本")), result="已替换")
                except Exception:  # noqa: BLE001 - 流转异常需要回退，不能让两版本同时生效
                    previous["是否生效"] = True
                    previous["status"] = "已部署"
                    previous["模型状态"] = "已部署"
                    return None, self._rollback(
                        latest, previous_snapshot, check, version, operator, path,
                        reason="上一版本切换失败，已恢复原生效版本并回退评估指标快照",
                    )

            try:
                latest["是否生效"] = True
                latest["status"] = "已部署"
                latest["模型状态"] = "已部署"
                latest["pending"] = False
                latest["abnormal"] = False
                marker = len(_DEPLOYMENTS)
                _ensure_deployment_seed()
                _DEPLOYMENTS.append({
                    "记录编号": _next_deployment_id(),
                    "模型编号": model_code,
                    "模型版本": version,
                    "执行人": operator,
                    "归属负责人": _as_text(latest.get("负责人")),
                    "评估指标快照": metric_before,
                    "部署路径": path,
                    "结论": check["结论"],
                    "结果": "生效中",
                    "时间": date.today().isoformat(),
                })
                if len(_DEPLOYMENTS) != marker + 1:
                    raise RuntimeError("发布流水未写入")
            except Exception:  # noqa: BLE001 - 部署失败统一回退，保证同一模型只有一个生效版本
                latest["是否生效"] = False
                latest["status"] = "训练完成"
                latest["模型状态"] = "训练完成"
                _DEPLOYMENTS[:] = _DEPLOYMENTS[:marker] if "marker" in locals() else _DEPLOYMENTS
                if previous is not None and previous.get("id") != latest.get("id"):
                    previous["是否生效"] = True
                    previous["status"] = "已部署"
                    previous["模型状态"] = "已部署"
                    previous["pending"] = False
                return None, self._rollback(
                    latest, previous_snapshot, check, version, operator, path,
                    reason="部署执行异常，已恢复上一版本生效并回退评估指标快照",
                )
        return latest, f"模型 {model_code}/{version} 已部署生效，同一模型仅保留该版本生效"

    def _rollback(
        self,
        row: dict[str, Any],
        snapshot: str,
        check: dict[str, Any],
        version: str,
        operator: str,
        path: str,
        *,
        reason: str,
    ) -> str:
        """部署失败时把评估指标回退到上一份快照，并留一条失败流水。"""
        row["评估指标"] = snapshot
        row["pending"] = True
        row["abnormal"] = True
        _ensure_deployment_seed()
        _DEPLOYMENTS.append({
            "记录编号": _next_deployment_id(),
            "模型编号": _as_text(row.get("模型编号")),
            "模型版本": version,
            "执行人": operator,
            "归属负责人": _as_text(row.get("负责人")),
            "评估指标快照": snapshot,
            "部署路径": path,
            "结论": check["结论"],
            "结果": "失败已回退",
            "回退说明": reason,
            "时间": date.today().isoformat(),
        })
        return f"部署执行失败：{reason}；评估指标已回退到上一份快照，原生效版本保持不变"

    def _close_deployment(self, model_code: str, version: str, *, result: str) -> None:
        _ensure_deployment_seed()
        for record in reversed(_DEPLOYMENTS):
            if record["模型编号"] == model_code and record["模型版本"] == version and record["结果"] == "生效中":
                record["结果"] = result
                return


service = ModelService()
