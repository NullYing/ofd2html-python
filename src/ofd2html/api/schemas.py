"""Pydantic response model: matches the contract documented in the plan."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ConvertResponse(BaseModel):
    code: int
    msg: str
    data: Optional[str] = None
    task_id: Optional[str] = None
