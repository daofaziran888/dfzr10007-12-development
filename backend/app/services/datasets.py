"""训练数据集字段清单：模型注册清单与数据目录检索共用这一份口径。

模型注册里的「训练数据」保存数据集编号；这里维护唯一一份字段清单。
数据目录检索通过目录条目上的数据集编号引用同一份清单，避免两边各写一份后漂移。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

TRAINING_DATASETS: dict[str, dict[str, Any]] = {
    "DS-CUSTOMER-001": {
        "数据集编号": "DS-CUSTOMER-001",
        "数据集名称": "客户流失训练集",
        "业务域": "客户运营",
        "目录条目编号": "CATA-0001",
        "更新频率": "每日",
        "数据等级": "L2",
        "负责人": "赵启明",
        "字段清单": [
            {"字段名": "客户ID", "类型": "string", "说明": "客户唯一标识"},
            {"字段名": "年龄", "类型": "int", "说明": "客户年龄"},
            {"字段名": "在网时长", "类型": "int", "说明": "连续在网月数"},
            {"字段名": "月消费", "类型": "decimal", "说明": "近 30 天消费金额"},
            {"字段名": "投诉次数", "类型": "int", "说明": "近 90 天投诉次数"},
            {"字段名": "是否流失", "类型": "boolean", "说明": "训练标签，1 表示流失"},
        ],
    },
    "DS-SALES-002": {
        "数据集编号": "DS-SALES-002",
        "数据集名称": "销售预测训练集",
        "业务域": "销售分析",
        "目录条目编号": "CATA-0002",
        "更新频率": "每小时",
        "数据等级": "L3",
        "负责人": "赵启明",
        "字段清单": [
            {"字段名": "门店编号", "类型": "string", "说明": "门店唯一标识"},
            {"字段名": "日期", "类型": "date", "说明": "业务日期"},
            {"字段名": "商品类目", "类型": "string", "说明": "商品一级类目"},
            {"字段名": "促销力度", "类型": "decimal", "说明": "当日促销折扣"},
            {"字段名": "销售额", "类型": "decimal", "说明": "训练标签，当日销售额"},
        ],
    },
    "DS-RISK-003": {
        "数据集编号": "DS-RISK-003",
        "数据集名称": "授信风险训练集",
        "业务域": "风险控制",
        "目录条目编号": "CATA-0003",
        "更新频率": "每日",
        "数据等级": "L4",
        "负责人": "赵启明",
        "字段清单": [
            {"字段名": "申请编号", "类型": "string", "说明": "授信申请唯一标识"},
            {"字段名": "收入水平", "类型": "decimal", "说明": "月均收入"},
            {"字段名": "负债率", "类型": "decimal", "说明": "负债/收入"},
            {"字段名": "历史逾期次数", "类型": "int", "说明": "近 24 个月逾期次数"},
            {"字段名": "授信额度", "类型": "decimal", "说明": "申请额度"},
            {"字段名": "风险等级", "类型": "string", "说明": "训练标签，A/B/C/D"},
        ],
    },
}

DATASET_ALIASES = {
    "客户流失训练集": "DS-CUSTOMER-001",
    "销售预测训练集": "DS-SALES-002",
    "授信风险训练集": "DS-RISK-003",
}


def resolve_dataset(value: Any) -> dict[str, Any] | None:
    """按数据集编号或数据集名称找到同一份训练数据定义。"""
    key = str(value or "").strip()
    if not key:
        return None
    if key in TRAINING_DATASETS:
        return TRAINING_DATASETS[key]
    alias = DATASET_ALIASES.get(key)
    if alias:
        return TRAINING_DATASETS[alias]
    for dataset in TRAINING_DATASETS.values():
        if dataset["数据集编号"] == key or dataset["数据集名称"] == key:
            return dataset
    return None


def dataset_code(value: Any) -> str | None:
    dataset = resolve_dataset(value)
    return str(dataset["数据集编号"]) if dataset else None


def field_manifest(value: Any) -> list[dict[str, str]]:
    """返回字段清单副本；调用方修改不会污染共享口径。"""
    dataset = resolve_dataset(value)
    if dataset is None:
        return []
    return deepcopy(dataset["字段清单"])


def field_names(value: Any) -> list[str]:
    return [item["字段名"] for item in field_manifest(value)]
