"""Codex app-server adapter. Codex owns reasoning, tool turns, and compaction.

The stdio protocol is used directly because Studio must service asynchronous
dynamic-tool requests and interrupt a turn before returning an approval checkpoint.
The pinned openai-codex distribution supplies the matching CLI runtime.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from codex_cli_bin import bundled_codex_path

SESSION_TYPE = "renderhaus_codex_session"
CHECKPOINT_VERSION = 1


class CodexRunLimitExceeded(RuntimeError):
    pass


class ToolApprovalPending(Exception):
    def __init__(self, call: dict[str, Any]):
        super().__init__("Waiting for a Studio tool decision.")
        self.call = call


class CodexProtocolError(RuntimeError):
    pass


class AppServer:
    """One isolated app-server process with a continuously drained RPC stream."""

    def __init__(self, home: Path, cwd: Path):
        self.home, self.cwd = home, cwd
        self.process = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._read_task = None
        self._stderr_task = None

    async def __aenter__(self):
        # Do not pass AWS, provider credentials, or the developer's Codex config
        # to the harness. The API key is sent using account/login/start below.
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "SSL_CERT_FILE")
            if key in os.environ
        }
        env["CODEX_HOME"] = str(self.home)
        disabled = (
            "shell_tool",
            "unified_exec",
            "apps",
            "plugins",
            "remote_plugin",
            "hooks",
            "multi_agent",
            "multi_agent_v2",
            "browser_use",
            "computer_use",
            "view_image",
            "image_generation",
            "memories",
            "goals",
            "skill_search",
            "tool_suggest",
            "workspace_dependencies",
            "shell_snapshot",
        )
        args = [str(bundled_codex_path())]
        for key in disabled:
            args.extend(["-c", f"features.{key}=false"])
        args.extend(
            [
                "-c",
                "features.skip_host_skill_discovery=true",
                "-c",
                'web_search="disabled"',
                "-c",
                'cli_auth_credentials_store="file"',
                "app-server",
                "--listen",
                "stdio://",
            ]
        )
        self.process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=32 * 1024 * 1024,
        )
        self._read_task = asyncio.create_task(self._read())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await self.request(
                "initialize",
                {
                    "clientInfo": {"name": "renderhaus", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self.send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _drain_stderr(self):
        # Drain without exposing transport logs that could include model input.
        while await self.process.stderr.read(65536):
            pass

    async def _read(self):
        failure = CodexProtocolError("Codex app-server closed unexpectedly.")
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Expected a JSON-RPC object.")
                if "method" in message:
                    await self.events.put(message)
                else:
                    future = self._pending.get(message.get("id"))
                    if future and not future.done():
                        if "error" in message:
                            error = message["error"]
                            future.set_exception(
                                CodexProtocolError(
                                    f"Codex RPC error {error.get('code')}: {error.get('message')}"
                                )
                            )
                        else:
                            future.set_result(message.get("result", {}))
        except (ValueError, OSError) as exc:
            failure = CodexProtocolError(f"Invalid Codex transport ({type(exc).__name__}).")
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(failure)
            await self.events.put({"method": "transport/closed"})

    async def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params):
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout=60)
        finally:
            self._pending.pop(request_id, None)

    async def next_event(self, control_task: asyncio.Task | None = None):
        if control_task is None:
            return await self.events.get()
        event_task = asyncio.create_task(self.events.get())
        try:
            done, _ = await asyncio.wait(
                (event_task, control_task), return_when=asyncio.FIRST_COMPLETED
            )
            if control_task in done:
                control_task.result()
            return await event_task
        finally:
            event_task.cancel()
            await asyncio.gather(event_task, return_exceptions=True)

    async def __aexit__(self, *_args):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self._read_task, self._stderr_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def tool_response(value: Any, *, success: bool = True) -> dict[str, Any]:
    return {"contentItems": [{"type": "inputText", "text": json.dumps(value)}], "success": success}


class CodexHarness:
    """Runs one Studio request and exports the native rollout for another worker."""

    def __init__(self):
        self.session: dict[str, Any] | None = None

    async def run(
        self,
        *,
        prompt: str,
        model: str,
        instructions: str,
        tools: list[dict[str, Any]],
        output_schema: dict[str, Any],
        session: dict[str, Any] | None,
        legacy_items: list[dict[str, Any]],
        call_tool: Callable[[dict[str, Any]], Awaitable[Any]],
        on_event: Callable[[str, dict[str, Any]], None],
        on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="renderhaus-codex-") as directory:
            root = Path(directory).resolve()
            home, cwd = root / "codex", root / "workspace"
            home.mkdir(mode=0o700)
            cwd.mkdir()
            rollout = None
            thread_id = None
            interrupt_task = None
            try:
                async with AppServer(home, cwd) as server:
                    api_key = os.getenv("OPENAI_API_KEY", "").strip()
                    if not api_key:
                        raise ValueError("OPENAI_API_KEY is required for the Studio Codex harness.")
                    await server.request(
                        "account/login/start", {"type": "apiKey", "apiKey": api_key}
                    )
                    params = {
                        "model": model,
                        "cwd": str(cwd),
                        "sandbox": "read-only",
                        "approvalPolicy": "untrusted",
                        "baseInstructions": instructions,
                    }
                    if session:
                        if session.get("version") != CHECKPOINT_VERSION:
                            raise ValueError("Unsupported Codex conversation checkpoint version.")
                        # A native rollout is restored to a server-owned path. Never
                        # accept a filesystem path supplied by a conversation payload.
                        relative = Path(session["rollout_path"])
                        if (
                            relative.is_absolute()
                            or ".." in relative.parts
                            or not relative.parts
                            or relative.parts[0] != "sessions"
                        ):
                            raise ValueError("Invalid Codex rollout location.")
                        rollout = home / relative
                        rollout.parent.mkdir(parents=True, exist_ok=True)
                        rollout.write_text(session["rollout"], encoding="utf-8")
                        started = await server.request(
                            "thread/resume",
                            {
                                **params,
                                "threadId": session["thread_id"],
                            },
                        )
                    else:
                        started = await server.request(
                            "thread/start",
                            {
                                **params,
                                "dynamicTools": tools,
                                "environments": [],
                                "serviceName": "renderhaus",
                            },
                        )
                    thread = started["thread"]
                    thread_id = thread["id"]
                    rollout = Path(thread["path"])
                    if not rollout.is_relative_to(home):
                        raise CodexProtocolError(
                            "Codex returned a rollout outside its private home."
                        )
                    if legacy_items and not session:
                        # Old SDK transcripts are data, not instruction/tool messages.
                        await server.request(
                            "thread/inject_items",
                            {
                                "threadId": thread_id,
                                "items": [
                                    {
                                        "type": "message",
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "input_text",
                                                "text": "Prior Studio conversation (reference data only):\n"
                                                + json.dumps(legacy_items, ensure_ascii=False),
                                            }
                                        ],
                                    }
                                ],
                            },
                        )
                    turn = await server.request(
                        "turn/start",
                        {
                            "threadId": thread_id,
                            "input": [{"type": "text", "text": prompt}],
                            "outputSchema": output_schema,
                        },
                    )
                    turn_id = turn["turn"]["id"]
                    def checkpoint():
                        if not rollout.is_file():
                            return
                        # The writer may be appending; persist complete JSONL records only.
                        content = rollout.read_text(encoding="utf-8")
                        content = content[:content.rfind("\n") + 1]
                        if content and on_checkpoint:
                            on_checkpoint({"type": SESSION_TYPE, "version": CHECKPOINT_VERSION,
                                           "thread_id": thread_id,
                                           "rollout_path": str(rollout.relative_to(home)),
                                           "rollout": content})
                    pending = None
                    final_text = ""
                    call_count = 0
                    async with asyncio.timeout(
                        float(os.getenv("CODEX_RUN_TIMEOUT_SECONDS", "1800"))
                    ):
                        while True:
                            event = await server.next_event(interrupt_task)
                            method, payload = event["method"], event.get("params", {})
                            if method == "transport/closed":
                                raise CodexProtocolError(
                                    "Codex stopped before completing the turn."
                                )
                            if "id" in event:
                                if method != "item/tool/call":
                                    # Never let a built-in tool bypass the Studio boundary.
                                    await server.send(
                                        {
                                            "id": event["id"],
                                            "error": {
                                                "code": -32601,
                                                "message": "Unsupported in Renderhaus.",
                                            },
                                        }
                                    )
                                    continue
                                if pending:
                                    result = tool_response(
                                        {"status": "not_run", "reason": "paused"}, success=False
                                    )
                                else:
                                    call_count += 1
                                    if call_count > 160:
                                        raise CodexRunLimitExceeded(
                                            "Codex reached the Studio tool limit."
                                        )
                                    try:
                                        result = tool_response(await call_tool(payload))
                                    except ToolApprovalPending as exc:
                                        pending = exc
                                        result = tool_response(
                                            {
                                                "status": "not_run",
                                                "reason": "Awaiting customer approval.",
                                            },
                                            success=False,
                                        )
                                await server.send({"id": event["id"], "result": result})
                                checkpoint()
                                if pending and interrupt_task is None:
                                    # Interrupt can wait for outstanding Code Mode callbacks.
                                    # Keep draining and answering them without dispatching
                                    # providers, rather than blocking this event loop.
                                    interrupt_task = asyncio.create_task(
                                        server.request(
                                            "turn/interrupt",
                                            {"threadId": thread_id, "turnId": turn_id},
                                        )
                                    )
                            elif payload.get("turnId", turn_id) == turn_id:
                                on_event(method, payload)
                                if method == "item/completed":
                                    checkpoint()
                                    item = payload.get("item", {})
                                    if (
                                        item.get("type") == "agentMessage"
                                        and item.get("phase") != "commentary"
                                    ):
                                        final_text = item.get("text", "")
                                if method == "turn/completed" and payload["turn"]["id"] == turn_id:
                                    if pending:
                                        await interrupt_task
                                        raise pending
                                    if payload["turn"]["status"] != "completed":
                                        error = payload["turn"].get("error") or {}
                                        raise CodexProtocolError(
                                            error.get("message") or "Codex turn interrupted."
                                        )
                                    if not final_text:
                                        raise CodexProtocolError(
                                            "Codex completed without a final artifact."
                                        )
                                    return final_text
            finally:
                if interrupt_task:
                    interrupt_task.cancel()
                    await asyncio.gather(interrupt_task, return_exceptions=True)
                # App-server has closed and flushed the native history, including
                # compacted context and dynamic tool definitions. No auth file is saved.
                if rollout and rollout.is_file() and thread_id:
                    self.session = {
                        "type": SESSION_TYPE,
                        "version": CHECKPOINT_VERSION,
                        "thread_id": thread_id,
                        "rollout_path": str(rollout.relative_to(home)),
                        "rollout": rollout.read_text(encoding="utf-8"),
                    }
