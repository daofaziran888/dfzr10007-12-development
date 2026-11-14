"""调用者身份与权限：模型部署、模型版本改写与目录维护共用一套角色口径。

平台当前不接统一登录，调用方通过 ``X-Operator`` / ``X-Role`` 请求头声明身份，
中文身份值按 URL 编码传输（HTTP 头只保证 ASCII）；未声明时按最小权限处理：
操作人「访客」、角色「普通查看者」。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

ROLE_OWNER = "模型负责人"
ROLE_CATALOG = "数据目录成员"
ROLE_VIEWER = "普通查看者"
ROLE_CHOICES = [ROLE_OWNER, ROLE_CATALOG, ROLE_VIEWER]
DEFAULT_OPERATOR = "访客"

_ROLE_ALIASES = {
    "模型负责人": ROLE_OWNER,
    "owner": ROLE_OWNER,
    "model_owner": ROLE_OWNER,
    "数据目录成员": ROLE_CATALOG,
    "catalog": ROLE_CATALOG,
    "catalog_member": ROLE_CATALOG,
    "普通查看者": ROLE_VIEWER,
    "viewer": ROLE_VIEWER,
    "readonly": ROLE_VIEWER,
}


class PermissionDenied(Exception):
    """当前调用者没有执行该动作的权限。路由层据此返回 403。"""


def normalize_identity(operator: Any, role: Any) -> tuple[str, str]:
    """把请求头或载荷里的身份收敛到三个角色之一，避免拼写差异绕过权限。"""
    name = unquote(str(operator or "").strip()) or DEFAULT_OPERATOR
    raw_role = unquote(str(role or "").strip())
    return name, _ROLE_ALIASES.get(raw_role.lower(), _ROLE_ALIASES.get(raw_role, ROLE_VIEWER))
