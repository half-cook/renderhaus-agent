"""Reload project memory from checkpointed files on each invocation."""

from deepagents.middleware.memory import MemoryMiddleware


class ProjectMemory(MemoryMiddleware):
    @property
    def name(self):
        return "MemoryMiddleware"

    def before_agent(self, state, runtime, config):
        return super().before_agent(
            {key: value for key, value in state.items() if key != "memory_contents"}, runtime, config,
        )

    async def abefore_agent(self, state, runtime, config):
        return await super().abefore_agent(
            {key: value for key, value in state.items() if key != "memory_contents"}, runtime, config,
        )
