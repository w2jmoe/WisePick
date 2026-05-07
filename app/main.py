from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.models.tool_spec import ApiToolSpec  # noqa: F401 �?�?Base 注册模型
from app.models.decision import Decision  # noqa: F401
from app.models.feedback import Feedback  # noqa: F401
from app.routers import decide
from app.routers import feedback

SEED_TOOLS = [
    {
        "tool_key": "feishu_minutes",
        "name": "Feishu Minutes",
        "description": "Meeting transcription tool",
        "capabilities": "transcription,audio,meeting",
        "enabled": True,
        "bootstrap_weight": 0.70,
        "metadata": '{"provider": "feishu", "bootstrap": true}',
    },
    {
        "tool_key": "tongyi_tingwu",
        "name": "Tongyi Tingwu",
        "description": "Meeting transcription tool",
        "capabilities": "transcription,audio,meeting",
        "enabled": True,
        "bootstrap_weight": 0.65,
        "metadata": '{"provider": "alibaba", "bootstrap": true}',
    },
    {
        "tool_key": "chatgpt",
        "name": "ChatGPT",
        "description": "General writing and reasoning tool",
        "capabilities": "writing,summary,general_llm,general_content",
        "enabled": True,
        "bootstrap_weight": 0.60,
        "metadata": '{"provider": "openai", "bootstrap": true}',
    },
    {
        "tool_key": "canva",
        "name": "Canva",
        "description": "Presentation and design tool",
        "capabilities": "presentation,design,image_generation",
        "enabled": True,
        "bootstrap_weight": 0.65,
        "metadata": '{"provider": "canva", "bootstrap": true}',
    },
    {
        "tool_key": "github_copilot",
        "name": "GitHub Copilot",
        "description": "Coding assistant",
        "capabilities": "coding,code_generation",
        "enabled": True,
        "bootstrap_weight": 0.70,
        "metadata": '{"provider": "github", "bootstrap": true}',
    },
]


def seed_tools(db: Session) -> None:
    """Insert mock tool data at startup (idempotent, skip if already exists)."""
    for data in SEED_TOOLS:
        exists = db.query(ApiToolSpec).filter(ApiToolSpec.tool_key == data["tool_key"]).first()
        if not exists:
            # Convert metadata string to dict for JSON storage and map to 'meta' attribute
            tool_data = data.copy()
            if "metadata" in tool_data:
                if isinstance(tool_data["metadata"], str):
                    import json
                    tool_data["meta"] = json.loads(tool_data["metadata"])
                else:
                    tool_data["meta"] = tool_data["metadata"]
                del tool_data["metadata"]
            db.add(ApiToolSpec(**tool_data))
    db.commit()


def _migrate_api_decision_logs_observability_columns() -> None:
    """PostgreSQL：为已存在的表补充可观测性字段（create_all 不会自动加列）�?""
    insp = inspect(engine)
    if not insp.has_table("api_decision_logs"):
        return
    if engine.dialect.name != "postgresql":
        return
    cols = {c["name"] for c in insp.get_columns("api_decision_logs")}
    json_type = "JSONB"
    alters: list[str] = []
    if "detected_capabilities" not in cols:
        alters.append(f"ALTER TABLE api_decision_logs ADD COLUMN detected_capabilities {json_type}")
    if "candidate_tools" not in cols:
        alters.append(f"ALTER TABLE api_decision_logs ADD COLUMN candidate_tools {json_type}")
    if "filtered_out_tools" not in cols:
        alters.append(f"ALTER TABLE api_decision_logs ADD COLUMN filtered_out_tools {json_type}")
    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Base.metadata.create_all(bind=engine)  # 移除自动建表，Supabase 已托�?schema
    _migrate_api_decision_logs_observability_columns()
    with SessionLocal() as db:
        seed_tools(db)
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.include_router(decide.router)
app.include_router(feedback.router)


@app.get("/")
def root():
    return {"service": settings.APP_TITLE, "version": settings.APP_VERSION, "docs": "/docs"}


@app.get("/health")
def health_check():
    """轻量健康检查接口，用于监控和负载均衡�?""
    return {
        "status": "ok",
        "service": "wisepick-api",
        "version": "v0"
    }
