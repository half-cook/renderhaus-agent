from agent.deep_agent.budget import _has_media


def test_cache_control_is_not_media():
    content = [{"type": "text", "text": "system", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert _has_media(content) is False


def test_real_media_still_detected():
    assert _has_media([{"type": "image", "source": {"type": "base64", "data": "x"}}]) is True


def test_tool_caller_metadata_is_not_media():
    block = {"type": "tool_use", "id": "t1", "name": "x", "input": {}, "caller": {"type": "direct"}}
    assert _has_media([{"type": "thinking", "thinking": "..."}, block]) is False
