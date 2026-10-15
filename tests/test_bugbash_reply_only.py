from server.studio import _DECLINED_SUMMARY, _reply_only_run, _reply_text


def test_question_or_refusal_with_no_tools_is_a_reply():
    assert _reply_only_run({"assets": [], "tool_events": []}) == (True, False)


def test_tool_search_does_not_count_as_work():
    events = [{"name": "x_amz_bedrock_agentcore_search", "status": "completed"}]
    assert _reply_only_run({"tool_events": events}) == (True, False)


def test_not_now_on_first_card_is_a_declined_reply():
    events = [{"name": "x_amz_bedrock_agentcore_search", "status": "completed"},
              {"name": "Fal___generate_wan3_t2v", "status": "rejected"}]
    assert _reply_only_run({"tool_events": events}) == (True, True)
    assert "nothing was charged" in _DECLINED_SUMMARY


def test_any_media_work_or_asset_is_not_a_reply():
    for status in ("failed", "succeeded", "dry_run", "running", ""):
        assert _reply_only_run({"tool_events": [{"name": "Fal___generate_wan3_t2v", "status": status}]}) == (False, False)
    assert _reply_only_run({"assets": [{"kind": "audio"}], "tool_events": []}) == (False, False)


def test_reply_text_drops_incomplete_prefix():
    assert _reply_text("Incomplete. No logo asset was available.") == "No logo asset was available."
    assert _reply_text("Here is a plan.") == "Here is a plan."
