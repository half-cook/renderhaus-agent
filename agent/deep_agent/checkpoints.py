from __future__ import annotations

import base64
from importlib.metadata import version

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

ENGINE_VERSIONS = {
    name: version(name) for name in ("deepagents", "langgraph", "langgraph-checkpoint")
}


def _encode(value):
    kind, data = value
    return [kind, base64.b64encode(data).decode("ascii")]


def _decode(value):
    kind, data = value
    if kind not in {"msgpack", "json", "empty", "null", "bytes", "bytearray"}:
        raise ValueError("Unsupported checkpoint serialization.")
    return kind, base64.b64decode(data, validate=True)


class StudioCheckpointer(InMemorySaver):
    """Persist every checkpoint and pending write, including nested HITL tasks."""

    def __init__(self, thread_id, snapshot=None, sink=None):
        super().__init__(serde=JsonPlusSerializer(
            allowed_msgpack_modules=[("agent.studio_agent_next", "StudioAgentOutput")],
        ))
        self.thread_id = thread_id
        self.sink = sink
        if snapshot:
            if snapshot.get("engines") != ENGINE_VERSIONS:
                raise ValueError("Deep Agents checkpoint versions changed. Start a new conversation.")
            try:
                for ns, checkpoint_id, checkpoint, metadata, parent in snapshot["storage"]:
                    self.storage[thread_id][ns][checkpoint_id] = (
                        _decode(checkpoint), _decode(metadata), parent,
                    )
                for ns, checkpoint_id, task_id, index, channel, value, path in snapshot["writes"]:
                    self.writes[(thread_id, ns, checkpoint_id)][(task_id, index)] = (
                        task_id, channel, _decode(value), path,
                    )
                for ns, channel, channel_version, value in snapshot["blobs"]:
                    self.blobs[(thread_id, ns, channel, channel_version)] = _decode(value)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid Deep Agents conversation checkpoint.") from exc

    def snapshot(self):
        return {
            "engines": ENGINE_VERSIONS,
            "storage": [
                [ns, checkpoint_id, _encode(checkpoint), _encode(metadata), parent]
                for ns, checkpoints in self.storage[self.thread_id].items()
                for checkpoint_id, (checkpoint, metadata, parent) in checkpoints.items()
            ],
            "writes": [
                [ns, checkpoint_id, task_id, index, channel, _encode(value), path]
                for (thread, ns, checkpoint_id), writes in self.writes.items()
                if thread == self.thread_id
                for (task_id, index), (_, channel, value, path) in writes.items()
            ],
            "blobs": [
                [ns, channel, channel_version, _encode(value)]
                for (thread, ns, channel, channel_version), value in self.blobs.items()
                if thread == self.thread_id
            ],
        }

    def put(self, *args, **kwargs):
        config = super().put(*args, **kwargs)
        self.publish()
        return config

    def put_writes(self, *args, **kwargs):
        super().put_writes(*args, **kwargs)
        self.publish()

    def publish(self):
        if self.sink:
            self.sink(self.snapshot())
