"""路由层共用依赖：从请求头解析当前操作人与角色。"""
from __future__ import annotations

from fastapi import Header

from app.services.identity import normalize_identity


def current_identity(
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> tuple[str, str]:
    return normalize_identity(x_operator, x_role)
