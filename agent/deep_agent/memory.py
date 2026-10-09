from deepagents.middleware.memory import MemoryMiddleware
from langchain.agents.middleware import AgentMiddleware


class ProjectMemory(MemoryMiddleware):
    @property
    def name(self):
        return "MemoryMiddleware"


class AppendOnlyConversation(AgentMiddleware):
    """Retain raw history for models whose thinking signatures bind the full prefix."""

    @property
    def name(self):
        return "SummarizationMiddleware"


def append_only_middleware(model) -> list[AgentMiddleware]:
    model_name = getattr(model, "model", None) or getattr(model, "model_name", None)
    if model_name in {"claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}:
        return [AppendOnlyConversation()]
    return []
