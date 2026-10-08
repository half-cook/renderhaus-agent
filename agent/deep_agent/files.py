from dataclasses import replace

from langchain.agents.middleware import wrap_tool_call
from langgraph.types import Command


@wrap_tool_call
async def subagent_file_updates(request, handler):
    original = request.runtime.state.get("files", {})
    result = await handler(request)
    if request.tool_call["name"] != "task" or not isinstance(result, Command):
        return result
    if not isinstance(result.update, dict) or "files" not in result.update:
        return result
    changed = {path: value for path, value in result.update["files"].items()
               if path not in original or value != original[path]}
    return replace(result, update={**result.update, "files": changed})
