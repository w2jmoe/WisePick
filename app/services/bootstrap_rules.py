"""
Bootstrap rules for WisePick API v0.
Simple keyword �?capability mapping with versioning.

IMPORTANT: This is a COLD-START BOOTSTRAP mechanism only.

Current bootstrap_rules:
- Provide initial capability matching during cold start (0 feedback)
- Use simple keyword matching for quick capability identification
- Are static and hardcoded for v0

NOT the final capability learning system.

Future capability matching will be driven by:
- execution_feedback (real success/failure outcomes)
- semantic_clustering (grouping similar capabilities)
- embedding_similarity (vector-based task-capability matching)
- execution_outcomes (latency, cost, quality metrics)

As feedback accumulates, bootstrap weight decays and the system
shifts from rule-driven to execution-data-driven capability routing.

Do NOT add extensive hardcoded rules here. This is intentionally minimal.
"""

BOOTSTRAP_VERSION = "v0"

# Simple keyword to capability mapping
RULES = [
    {
        "key": "audio_to_transcription_v1",
        "keywords": ["录音", "转写", "会议", "语音", "字幕", "听写", "audio", "transcribe", "meeting"],
        "capability": "transcription"
    },
    {
        "key": "text_to_writing_v1", 
        "keywords": ["�?, "文案", "文章", "邮件", "总结", "公告", "write", "article", "essay", "summary", "content"],
        "capability": "writing"
    },
    {
        "key": "image_generation_v1",
        "keywords": ["�?, "图片", "海报", "�?, "设计", "插画", "生图", "generate image", "poster", "design"],
        "capability": "image_generation"
    },
    {
        "key": "code_generation_v1",
        "keywords": ["代码", "编程", "python", "爬虫", "写代�?, "script", "code", "program", "csv", "automation script"],
        "capability": "coding"
    },
    {
        "key": "automation_v1",
        "keywords": ["自动�?, "工作�?, "流程", "发邮�?, "抓数�?, "爬数�?, "automation", "workflow", "schedule", "cron", "api", "email"],
        "capability": "automation"
    },
    {
        "key": "translation_v1",
        "keywords": ["翻译", "translate", "translation"],
        "capability": "translation"
    },
    {
        "key": "presentation_v1",
        "keywords": ["ppt", "幻灯�?, "演示", "汇报", "presentation", "slide", "deck", "keynote", "powerpoint", "精美", "设计", "模板"],
        "capability": "presentation"
    },
    {
        "key": "general_content_v1",
        "keywords": ["通用", "一�?, "内容", "general", "content", "assistant", "help", "支持", "咨询"],
        "capability": "general_content"
    },
]

def extract_capabilities(task: str) -> list[str]:
    """
    Extract capabilities from task using bootstrap rules.
    Returns list of matched capabilities, empty if no match.
    """
    if not task or not isinstance(task, str):
        return []
    
    task_lower = task.lower()
    capabilities = set()
    
    for rule in RULES:
        for keyword in rule["keywords"]:
            if keyword.lower() in task_lower:
                capabilities.add(rule["capability"])
                break
    
    return list(capabilities)
