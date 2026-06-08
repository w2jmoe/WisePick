from typing import Any

from pydantic import BaseModel, Field


class DecideRequest(BaseModel):
    task: str = Field(..., description="需要完成的任务描述")
    context: dict[str, Any] | None = Field(default=None, description="任务上下文")
    constraints: dict[str, Any] | None = Field(default=None, description="限制条件，例如 china_available: true")


class DecideResponse(BaseModel):
    decision_id: str
    # Capability routing fields (new semantic layer)
    capability_id: str = Field(
        default="",
        description="Executable capability type; empty when callable=false",
    )
    execution_type: str = Field(default="api", description="Execution mechanism: api, mcp, function_call")
    provider: str = Field(
        default="",
        description="Specific provider implementation; empty when callable=false",
    )
    callable: bool = Field(default=True, description="Whether this capability can be directly executed")
    # Legacy field (maintained for backward compatibility)
    tool_key: str = Field(
        default="",
        description="[Legacy] Same as provider; empty when callable=false",
    )
    reason: str
    confidence: float
    explain: dict
    trace: dict