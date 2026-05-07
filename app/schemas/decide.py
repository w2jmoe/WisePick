from typing import Any

from pydantic import BaseModel, Field


class DecideRequest(BaseModel):
    task: str = Field(..., description="需要完成的任务描述")
    context: dict[str, Any] | None = Field(default=None, description="任务上下文")
    constraints: dict[str, Any] | None = Field(default=None, description="限制条件，例如 china_available: true")


class DecideResponse(BaseModel):
    decision_id: str
    # Capability routing fields (new semantic layer)
    capability_id: str = Field(..., description="Executable capability type (e.g., audio_transcription, image_generation)")
    execution_type: str = Field(default="api", description="Execution mechanism: api, mcp, function_call")
    provider: str = Field(..., description="Specific provider implementation (e.g., feishu_minutes, openai)")
    callable: bool = Field(default=True, description="Whether this capability can be directly executed")
    # Legacy field (maintained for backward compatibility)
    tool_key: str = Field(..., description="[Legacy] Same as provider, maintained for backward compatibility")
    reason: str
    confidence: float
    explain: dict
    trace: dict