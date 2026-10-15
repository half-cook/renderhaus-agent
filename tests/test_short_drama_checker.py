from __future__ import annotations

import copy

import pytest


def outline():
    return {
        "series_id": "clock-shop",
        "title": "The clock shop",
        "revision": "v1",
        "adaptation_notes": "An original fictional story.",
        "cast": ["mei"],
        "beats": ["Mei finds a letter."],
        "episodes": [{"id": "ep01", "synopsis": "Mei opens the letter.", "hook": "Who sent it?"}],
        "assets": ["mei-reference", "shop-reference"],
    }


def episode():
    return {
        "episode_id": "ep01",
        "outline_hash": "outline-v1",
        "characters": [
            {
                "id": "mei",
                "profile": "Fictional clockmaker",
                "design_prompt": "Mei in red",
                "voice_prompt": "Quiet alto",
            }
        ],
        "art": [{"id": "shop", "description": "Clock shop", "design_prompt": "Amber clock shop"}],
        "locks": [
            {"id": "coat", "subject_id": "mei", "phrase": "red wool coat"},
            {"id": "room", "subject_id": "shop", "phrase": "amber clock shop"},
        ],
        "script": [{"id": "l1", "kind": "dialogue", "speaker_id": "mei", "text": "Come back."}],
        "segments": [
            {
                "id": "s1",
                "cuts": [
                    {
                        "id": "c1",
                        "duration_seconds": 4,
                        "subjects": ["mei", "shop"],
                        "lock_ids": ["coat", "room"],
                        "keyframe_prompt": "Mei, red wool coat, amber clock shop",
                        "video_prompt": "Mei, red wool coat, amber clock shop. She says Come back.",
                        "line_ids": ["l1"],
                    }
                ],
            }
        ],
    }


def cut(document):
    return document["segments"][0]["cuts"][0]


def test_outline_hash_is_stable_and_changes_with_content():
    from agent.deep_agent.short_drama import check_outline

    source = outline()
    original = copy.deepcopy(source)
    result = check_outline(source)
    assert result["ok"]
    assert result["outline"] == source
    assert source == original
    assert len(result["outline_hash"]) == 64
    assert (
        check_outline(dict(reversed(list(source.items()))))["outline_hash"]
        == result["outline_hash"]
    )
    source["episodes"][0]["hook"] = "Why has she returned?"
    assert check_outline(source)["outline_hash"] != result["outline_hash"]
    assert original["episodes"][0]["hook"] == "Who sent it?"


@pytest.mark.parametrize("field", ["series_id", "title", "revision", "adaptation_notes"])
def test_outline_rejects_blank_required_text(field):
    from agent.deep_agent.short_drama import check_outline

    source = outline()
    source[field] = " \n "
    result = check_outline(source)
    assert not result["ok"]
    assert "outline" not in result
    assert "outline_hash" not in result
    assert any(field in error for error in result["errors"])


@pytest.mark.parametrize("field", ["cast", "beats", "episodes", "assets"])
def test_outline_rejects_empty_required_lists(field):
    from agent.deep_agent.short_drama import check_outline

    source = outline()
    source[field] = []
    assert not check_outline(source)["ok"]


@pytest.mark.parametrize("field", ["cast", "episodes", "assets"])
def test_outline_rejects_duplicate_ids(field):
    from agent.deep_agent.short_drama import check_outline

    source = outline()
    source[field].append(copy.deepcopy(source[field][0]))
    assert not check_outline(source)["ok"]


def test_checker_returns_a_canonical_copy_without_mutating_input():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    original = copy.deepcopy(source)
    result = check_episode(source)
    assert result["ok"]
    assert source == original
    assert result["episode"]["script"] == source["script"]
    result["episode"]["characters"][0]["profile"] = "Changed"
    assert source == original
    assert result["duration_seconds"] == 4
    assert result["measured"] is False


@pytest.mark.parametrize("seconds", [2, 5])
def test_cut_duration_boundaries_are_inclusive(seconds):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)["duration_seconds"] = seconds
    assert check_episode(source)["ok"]


@pytest.mark.parametrize(
    "seconds", [1.99, 5.01, True, False, "4", float("nan"), float("inf"), -float("inf")]
)
def test_cut_duration_rejects_invalid_numbers_without_an_exception(seconds):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)["duration_seconds"] = seconds
    result = check_episode(source)
    assert not result["ok"]
    assert "episode" not in result
    assert any("duration_seconds" in error for error in result["errors"])


@pytest.mark.parametrize("count,seconds,expected", [(3, 5, True), (4, 4, False)])
def test_generation_segment_has_a_fifteen_second_limit(count, seconds, expected):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    first = cut(source)
    source["segments"][0]["cuts"] = [
        {
            **copy.deepcopy(first),
            "id": f"c{i}",
            "duration_seconds": seconds,
            "line_ids": ["l1"] if i == 0 else [],
        }
        for i in range(count)
    ]
    result = check_episode(source)
    assert result["ok"] is expected
    assert result["duration_seconds"] == count * seconds
    if not expected:
        assert any("15" in error for error in result["errors"])


@pytest.mark.parametrize("field", ["keyframe_prompt", "video_prompt"])
def test_each_prompt_requires_verbatim_lock_text(field):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)[field] = cut(source)[field].replace("red wool coat", "red coat")
    result = check_episode(source)
    assert not result["ok"]
    assert any("coat" in error and field in error for error in result["errors"])


def test_every_applicable_lock_must_be_cited():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["locks"].append({"id": "hair", "subject_id": "mei", "phrase": "short black hair"})
    cut(source)["keyframe_prompt"] += ", short black hair"
    cut(source)["video_prompt"] += ", short black hair"
    result = check_episode(source)
    assert not result["ok"]
    assert any("hair" in error for error in result["errors"])


def test_depicted_subject_needs_a_continuity_lock():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["locks"] = source["locks"][1:]
    cut(source)["lock_ids"] = ["room"]
    result = check_episode(source)
    assert not result["ok"]
    assert any("mei" in error and "lock" in error for error in result["errors"])


def test_cut_cannot_cite_a_lock_for_an_undepicted_subject():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)["subjects"] = ["mei"]
    result = check_episode(source)
    assert not result["ok"]
    assert any("room" in error and "subject" in error for error in result["errors"])


@pytest.mark.parametrize(
    "field,value,identifier",
    [
        ("subjects", ["ghost"], "ghost"),
        ("lock_ids", ["fake"], "fake"),
        ("line_ids", ["fake-line"], "fake-line"),
    ],
)
def test_cut_references_must_exist(field, value, identifier):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)[field] = value
    result = check_episode(source)
    assert not result["ok"]
    assert any(identifier in error for error in result["errors"])


def test_lock_subject_and_dialogue_speaker_must_exist():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["locks"][0]["subject_id"] = "ghost"
    source["script"][0]["speaker_id"] = "shop"
    result = check_episode(source)
    assert not result["ok"]
    assert any("ghost" in error for error in result["errors"])
    assert any("speaker" in error and "shop" in error for error in result["errors"])


@pytest.mark.parametrize("collection", ["characters", "art", "locks", "script", "segments"])
def test_duplicate_ids_are_rejected(collection):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source[collection].append(copy.deepcopy(source[collection][0]))
    result = check_episode(source)
    assert not result["ok"]
    assert any("duplicate" in error.lower() for error in result["errors"])


def test_cut_ids_are_unique_across_segments():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    second = copy.deepcopy(source["segments"][0])
    second["id"] = "s2"
    second["cuts"][0]["line_ids"] = []
    source["segments"].append(second)
    assert not check_episode(source)["ok"]


def test_character_and_art_ids_share_the_subject_namespace():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["art"][0]["id"] = "mei"
    assert not check_episode(source)["ok"]


@pytest.mark.parametrize("line_ids", [[], ["l1", "l1"]])
def test_every_script_line_is_assigned_exactly_once(line_ids):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    cut(source)["line_ids"] = line_ids
    result = check_episode(source)
    assert not result["ok"]
    assert any("l1" in error and "once" in error for error in result["errors"])


@pytest.mark.parametrize(
    "text,expected",
    [
        ("abc", 0.4),
        ("abcdefghijklmn", 1.2),
        ("天地玄黄", 1.0),
        ("天 地ab", 0.7),
        ("ひらがな", 1.0),
        ("한글", 0.5),
        ("𠮷", 0.4),
    ],
)
def test_dialogue_estimates_are_deterministic_and_not_measurements(text, expected):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["script"][0]["text"] = text
    result = check_episode(source)
    assert result["ok"]
    assert result["dialogue_estimates"] == {"l1": expected}
    assert result["measured"] is False


def test_summed_dialogue_must_fit_the_cut():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["script"] = [
        {"id": f"l{i}", "kind": "dialogue", "speaker_id": "mei", "text": "天地玄黄宇宙洪荒日"}
        for i in range(2)
    ]
    cut(source)["line_ids"] = ["l0", "l1"]
    result = check_episode(source)
    assert not result["ok"]
    assert result["dialogue_estimates"] == {"l0": 2.3, "l1": 2.3}
    assert any("c1" in error and "duration" in error for error in result["errors"])


def test_action_duration_and_dialogue_share_the_cut_time():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["script"].insert(
        0, {"id": "a1", "kind": "action", "text": "Mei opens the door.", "duration_seconds": 4}
    )
    cut(source)["line_ids"] = ["a1", "l1"]
    assert not check_episode(source)["ok"]
    source["script"][0]["duration_seconds"] = 2
    assert check_episode(source)["ok"]


@pytest.mark.parametrize(
    "change",
    [
        {"speaker_id": "mei"},
        {"duration_seconds": True},
        {"duration_seconds": float("nan")},
        {"duration_seconds": 0},
        {"duration_seconds": "2"},
    ],
)
def test_action_shape_and_duration_are_strict(change):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["script"] = [
        {"id": "l1", "kind": "action", "text": "Mei waits.", "duration_seconds": 2, **change}
    ]
    assert not check_episode(source)["ok"]


def test_dialogue_does_not_accept_an_invented_duration():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["script"][0]["duration_seconds"] = 0.1
    assert not check_episode(source)["ok"]


def test_captions_preserve_exact_dialogue_text():
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["captions"] = [{"line_id": "l1", "text": "Come back."}]
    assert check_episode(source)["ok"]
    source["captions"][0]["text"] = "Come back!"
    result = check_episode(source)
    assert not result["ok"]
    assert any("caption" in error.lower() and "l1" in error for error in result["errors"])


@pytest.mark.parametrize("kind", ["missing", "action", "duplicate"])
def test_caption_references_must_be_unique_dialogue_lines(kind):
    from agent.deep_agent.short_drama import check_episode

    source = episode()
    source["captions"] = [{"line_id": "l1", "text": "Come back."}]
    if kind == "missing":
        source["captions"][0]["line_id"] = "ghost"
    elif kind == "action":
        source["script"] = [
            {"id": "l1", "kind": "action", "text": "Come back.", "duration_seconds": 2}
        ]
    else:
        source["captions"].append(copy.deepcopy(source["captions"][0]))
    assert not check_episode(source)["ok"]


@pytest.mark.parametrize("value", [None, [], "episode", {"episode_id": 1}])
def test_malformed_documents_return_errors(value):
    from agent.deep_agent.short_drama import check_episode, check_outline

    for checker in (check_episode, check_outline):
        result = checker(value)
        assert result["ok"] is False
        assert result["errors"]


def test_unknown_document_fields_cannot_fabricate_approval():
    from agent.deep_agent.short_drama import check_episode, check_outline

    source = episode()
    source["approved"] = True
    assert not check_episode(source)["ok"]
    source = outline()
    source["approved"] = True
    assert not check_outline(source)["ok"]
