"""Public API contracts of the copilot backend (consumed by the Streamlit GUI)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolStatus = Literal["success", "error", "invalid_input", "unavailable", "timeout", "skipped"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ToolCallRecord(BaseModel):
    step: int
    tool: str
    server: str
    purpose: str
    status: ToolStatus
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: str
    duration_ms: float
    attempts: int = 0
    retries: list[str] = Field(default_factory=list)
    api_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    result: Any = None
    trace_id: str

    @property
    def ref(self) -> str:
        return f"T{self.step}"


class ToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    read_only: bool | None = None


class Citation(BaseModel):
    id: str
    doc_id: str
    revision: str
    title: str
    doc_type: str
    section: str
    heading_path: str
    trust_level: str
    status: str
    score: float
    similarity: float
    matched_alarm_codes: list[str] = Field(default_factory=list)
    excerpt: str
    source_path: str
    cited: bool = False


class QuarantinedSource(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    trust_level: str
    reason: str
    signals: list[str]


class Cause(BaseModel):
    cause: str
    evidence: list[str] = Field(default_factory=list)


class Action(BaseModel):
    action: str
    urgency: Literal["immediate", "short_term", "follow_up"] = "short_term"
    citations: list[str] = Field(default_factory=list)


class ConsistencyFinding(BaseModel):
    api_recommendation: str
    verdict: Literal["consistent", "inconsistent", "not_covered"]
    explanation: str
    citations: list[str] = Field(default_factory=list)
    tool_ref: str | None = None


class ProcedureRef(BaseModel):
    doc_id: str
    section: str | None = None
    reason: str
    citation: str | None = None


class AlarmPanel(BaseModel):
    assets: list[dict[str, Any]] = Field(default_factory=list)
    related_assets: list[dict[str, Any]] = Field(default_factory=list)
    active_alarms: list[dict[str, Any]] = Field(default_factory=list)
    historical_summary: dict[str, Any] | None = None
    focus_alarm: dict[str, Any] | None = None
    priority_scores: list[dict[str, Any]] = Field(default_factory=list)
    correlation_insights: list[str] = Field(default_factory=list)
    common_causes: list[dict[str, Any]] = Field(default_factory=list)
    rationalization: list[dict[str, Any]] = Field(default_factory=list)
    trend: dict[str, Any] | None = None
    kpis: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    trace_id: str
    question: str
    intent: str
    intent_method: str
    entities: dict[str, Any]
    time_window: dict[str, str] | None = None
    answer_markdown: str
    summary: str
    confidence: Literal["high", "medium", "low"]
    likely_causes: list[Cause] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)
    consistency_findings: list[ConsistencyFinding] = Field(default_factory=list)
    procedures: list[ProcedureRef] = Field(default_factory=list)
    alarm_panel: AlarmPanel = Field(default_factory=AlarmPanel)
    citations: list[Citation] = Field(default_factory=list)
    quarantined_sources: list[QuarantinedSource] = Field(default_factory=list)
    tools_discovered: list[str] = Field(default_factory=list)
    tool_trace: list[ToolCallRecord] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    llm: dict[str, Any] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
