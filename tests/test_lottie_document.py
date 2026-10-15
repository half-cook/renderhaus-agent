"""Offline contracts for confined Lottie document authoring and validation."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from providers.lottie.authoring import author_document, patch_document
from providers.lottie.contracts import request_for, tool_schema
from providers.lottie.svg import svg_document
from providers.lottie.validation import validate_document


def minimal_document():
    return {
        "v": "5.12.2", "nm": "Success", "fr": 30, "ip": 0, "op": 30,
        "w": 128, "h": 128, "assets": [], "layers": [],
    }


def simple_scene():
    return {"layers": [{"name": "Success check", "shape": "path", "fill": None,
                        "stroke": "#14b87a", "path": {"v": [[-20, 0], [-5, 15], [24, -20]],
                        "i": [[0, 0]] * 3, "o": [[0, 0]] * 3, "c": False},
                        "animate": [{"property": "trim_end", "keyframes": [
                            {"frame": 0, "value": 0, "easing": "ease-in-out"},
                            {"frame": 60, "value": 100}]}]}]}


def test_minimal_document_is_valid_and_has_exact_metadata():
    report = validate_document(minimal_document())
    assert report == {"ok": True, "errors": [], "compatibility": {
        "lottie-web": [], "lottie-ios": [], "lottie-android": [], "dotlottie": []},
        "not_previewed": [], "metadata": {"width": 128, "height": 128,
        "fps": 30, "frame_count": 30, "duration_seconds": 1.0}}


@pytest.mark.parametrize(("key", "value", "message"), [
    ("fr", 0, "fr must be between 1 and 120"),
    ("w", True, "w must be an integer"),
    ("op", -1, "op must be greater than ip"),
    ("layers", {}, "layers must be an array"),
])
def test_validator_reports_precise_core_errors(key, value, message):
    document = minimal_document()
    document[key] = value
    assert message in validate_document(document)["errors"]


def test_missing_required_keys_and_unknown_types_are_rejected():
    document = minimal_document()
    del document["v"]
    assert "v is required" in validate_document(document)["errors"]
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["shapes"][0]["ty"] = "invented"
    assert any("unknown shape type 'invented'" in item for item in validate_document(document)["errors"])


def test_author_writes_named_layers_animation_easing_and_transparent_defaults():
    document = author_document(simple_scene())
    assert (document["w"], document["h"], document["fr"], document["op"]) == (256, 256, 60, 90)
    assert "bg" not in document
    layer = document["layers"][0]
    assert layer["nm"] == "Success check"
    trim = next(shape for shape in layer["shapes"] if shape["ty"] == "tm")
    assert trim["e"]["k"][0]["o"] == {"x": [0.42], "y": [0.0]}
    assert trim["e"]["k"][0]["i"] == {"x": [0.58], "y": [1.0]}
    report = validate_document(document)
    assert report["ok"], report
    assert report["not_previewed"] == []


@pytest.mark.parametrize("scene", [
    {"width": "256", "layers": []}, {"width": 2049, "layers": []},
    {"frames": 3601, "layers": []}, {"layers": [{"name": "", "shape": "ellipse"}]},
    {"layers": [{"name": "Dot", "shape": "ellipse", "vendor": "ignored"}]},
    {"layers": [{"name": "Dot", "shape": "ellipse", "animate": [{"property": "opacity",
        "keyframes": [{"frame": 0, "value": 0}, {"frame": 100, "value": 100}]}]}]},
    {"layers": [{"name": "Dot", "shape": "ellipse", "animate": [{"property": "position",
        "keyframes": [{"frame": 0, "value": 0}, {"frame": 10, "value": 1}]}]}]},
])
def test_scene_boundary_rejects_invalid_specs(scene):
    with pytest.raises((ValidationError, ValueError)):
        author_document(scene)


@pytest.mark.parametrize("arguments", [
    {"job_id": "job", "scene": {}, "lottie": {}},
    {"job_id": "job"}, {"job_id": "../escape", "scene": {}},
    {"job_id": "job", "input_path": "../escape.json"},
    {"job_id": "job", "svg_path": "https://bad.test/file.svg"},
    {"job_id": "job", "scene": {}, "patch": {}},
    {"job_id": "job", "scene": {}, "unknown": 1},
])
def test_author_request_rejects_ambiguous_or_unconfined_inputs(arguments):
    with pytest.raises((ValidationError, ValueError)):
        request_for("lottie_author", arguments)


def test_tool_contracts_are_strict_and_gateway_schema_has_no_references():
    assert request_for("lottie_author", {"job_id": "j", "scene": {}}).name == "animation"
    for tool in ("lottie_author", "lottie_validate", "lottie_preview_render"):
        schema = tool_schema(tool)["inputSchema"]
        assert schema["type"] == "object"
        assert "$ref" not in str(schema)
        assert schema["additionalProperties"] is False
    with pytest.raises((ValidationError, ValueError)):
        request_for("lottie_preview_render", {"job_id": "j", "input_path": "a.json", "max_size": "64"})
    with pytest.raises((ValidationError, ValueError)):
        request_for("lottie_validate", {"job_id": "j", "input_path": "a.json", "targets": ["unknown"]})


def test_patch_is_pure_and_replaces_arrays():
    original = minimal_document()
    updated = patch_document(original, {"nm": "Patched", "layers": [], "meta": {"author": "UI"}})
    assert original == minimal_document()
    assert updated["nm"] == "Patched" and updated["meta"] == {"author": "UI"}
    cyclic = {}
    cyclic["x"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        patch_document(original, cyclic)


def test_keyframes_have_increasing_frames_valid_handles_and_property_values():
    document = author_document(simple_scene())
    prop = document["layers"][0]["shapes"][-1]["e"]
    prop["k"][1]["t"] = 0
    assert any("strictly increasing" in error for error in validate_document(document)["errors"])
    prop["k"][1]["t"] = 60
    prop["k"][0]["o"]["x"] = [1.1]
    assert any("easing x must be between 0 and 1" in error for error in validate_document(document)["errors"])


def test_refs_parent_and_precomposition_cycles_are_rejected():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["parent"] = 1
    assert any("parent cycle" in error for error in validate_document(document)["errors"])
    document["layers"][0].pop("parent")
    document["layers"][0].update({"ty": 0, "refId": "missing"})
    assert any("missing asset reference 'missing'" in error for error in validate_document(document)["errors"])
    document["assets"] = [{"id": "loop", "layers": [{"ty": 0, "ind": 2, "refId": "loop",
        "ip": 0, "op": 90, "ks": deepcopy(document["layers"][0]["ks"])}]}]
    document["layers"][0]["refId"] = "loop"
    assert any("asset cycle" in error for error in validate_document(document)["errors"])


def test_compatibility_flags_expressions_effects_masks_and_blend_modes():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    layer = document["layers"][0]
    layer["ks"]["r"]["x"] = "time*10"
    layer.update({"ef": [{"ty": 5}], "masksProperties": [{"mode": "a"}], "bm": 1})
    report = validate_document(document)
    assert report["ok"], report
    assert any("expression" in item for item in report["compatibility"]["lottie-ios"])
    assert any("effect" in item for item in report["compatibility"]["lottie-android"])
    assert all(any(word in item for item in report["not_previewed"]) for word in ("expression", "effect", "mask", "blend"))


def test_every_ignored_unknown_feature_is_reported_not_previewed():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["ks"]["p"]["to"] = [2, 3]
    document["layers"][0]["shapes"][0]["d"] = 3
    document["layers"][0]["shapes"][1]["unknownExtension"] = 7
    report = validate_document(document)
    assert report["not_previewed"]
    assert any("unknownExtension" in item for item in report["not_previewed"])
    assert any("to" in item for item in report["not_previewed"])


def test_document_bounds_and_nonfinite_values_are_rejected_without_crashing():
    document = minimal_document()
    document["layers"] = [1] * 129
    assert any("at most 128" in error for error in validate_document(document)["errors"])
    document = minimal_document()
    document["fr"] = float("nan")
    assert any("finite" in error for error in validate_document(document)["errors"])
    document = minimal_document()
    document["self"] = document
    assert any("cyclic" in error for error in validate_document(document)["errors"])


def test_svg_checkmark_is_normalized_stroked_and_revealed():
    document = svg_document(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 100 80"><path id="check" d="M 20 55 L 45 75 L 95 30" fill="none" stroke="#14b87a" stroke-width="4"/></svg>')
    assert (document["w"], document["h"]) == (100, 80)
    assert document["layers"][0]["nm"] == "check"
    assert document["layers"][0]["ks"]["p"]["k"] == [-10.0, -20.0, 0]
    assert any(shape["ty"] == "tm" for shape in document["layers"][0]["shapes"])
    assert validate_document(document)["ok"]


@pytest.mark.parametrize("fragment", [
    '<script>alert(1)</script>', '<foreignObject/>', '<image href="https://bad.test/a.png"/>',
    '<path d="M0 0L1 1" onclick="alert(1)"/>', '<use href="#id"/>',
    '<path d="M0 0A2 2 0 0 0 4 4"/>', '<g transform="rotate(30)"><rect width="2" height="2"/></g>',
    '<rect width="2" height="2" style="fill: red"/>',
])
def test_svg_rejects_unsafe_or_unsupported_features(fragment):
    with pytest.raises(ValueError):
        svg_document(f'<svg viewBox="0 0 100 100">{fragment}</svg>'.encode())


def test_svg_rejects_entities_and_bad_geometry():
    with pytest.raises(ValueError, match="entities|DOCTYPE"):
        svg_document(b'<!DOCTYPE svg [<!ENTITY bomb "xxx">]><svg viewBox="0 0 100 100">&bomb;</svg>')
    with pytest.raises(ValueError, match="positive"):
        svg_document(b'<svg viewBox="0 0 -1 50"/>')


@pytest.mark.parametrize("value", [None, [], {}, "bad", True, 1.5])
def test_validator_handles_malformed_layer_indexes_and_shape_types_without_raising(value):
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["ind"] = value
    document["layers"][0]["parent"] = 1
    document["layers"][0]["shapes"][0]["ty"] = value
    report = validate_document(document)
    assert report["ok"] is False
    assert report["errors"]


def test_unknown_properties_and_advanced_shape_keyframes_are_checked():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["shapes"].append({"ty": "gf", "o": {"a": 1, "k": [
        {"t": 20, "s": [0], "o": {"x": [0], "y": [0]}, "i": {"x": [1], "y": [1]}},
        {"t": 10, "s": [100]}]}})
    report = validate_document(document)
    assert any("strictly increasing" in error for error in report["errors"])
    assert any("gf" in reason for reason in report["not_previewed"])


def test_separated_dimensions_are_valid_but_explicitly_not_previewed():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["ks"]["p"] = {"s": True, "x": {"a": 0, "k": 10}, "y": {"a": 0, "k": 20}}
    report = validate_document(document)
    assert report["ok"], report
    assert any("separated" in reason for reason in report["not_previewed"])


def test_json_depth_and_total_keyframes_are_bounded():
    document = minimal_document()
    nested = document
    for _ in range(33):
        nested["child"] = {}
        nested = nested["child"]
    assert any("nesting" in error for error in validate_document(document)["errors"])


@pytest.mark.parametrize("source, expected_vertices", [
    ("M 10 10 h 10 v 10 l -10 0 z", [[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]),
    ("M 10 10 C 15 0 25 0 30 10", [[10.0, 10.0], [30.0, 10.0]]),
    ("M 10 10 q 10 20 20 0", [[10.0, 10.0], [30.0, 10.0]]),
])
def test_svg_supported_path_commands_preserve_native_vertices(source, expected_vertices):
    document = svg_document(f'<svg viewBox="0 0 64 64"><path d="{source}"/></svg>'.encode())
    path = document["layers"][0]["shapes"][0]["ks"]["k"]
    assert path["v"] == expected_vertices
    assert validate_document(document)["ok"]


def test_svg_preserves_stack_order_inherited_colors_and_stroke_geometry():
    document = svg_document(b'<svg viewBox="0 0 64 64"><g fill="#f00"><rect id="back" x="4" y="8" width="20" height="12"/><circle id="front" cx="20" cy="20" r="4"/></g></svg>')
    assert [layer["nm"] for layer in document["layers"]] == ["front", "back"]
    back = document["layers"][1]
    assert back["ks"]["p"]["k"] == [14.0, 14.0, 0]
    assert back["shapes"][1]["c"]["k"] == [1.0, 0.0, 0.0, 1.0]


def test_document_refuses_external_assets_and_flags_local_assets():
    document = minimal_document()
    document["assets"] = [{"id": "image", "p": "https://example.com/a.png"}]
    assert any("external" in error for error in validate_document(document)["errors"])
    document["assets"][0]["p"] = "image.png"
    report = validate_document(document)
    assert report["ok"]
    assert any("asset" in reason for reason in report["not_previewed"])


def test_absolute_input_paths_are_allowed_only_inside_the_selected_job(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDERHAUS_MEDIA_DIR", str(tmp_path))
    job = tmp_path / "job"
    job.mkdir()
    inside = str(job / "animation.json")
    assert request_for("lottie_validate", {"job_id": "job", "input_path": inside}).input_path == inside
    with pytest.raises(ValueError, match="inside the job directory"):
        request_for("lottie_validate", {"job_id": "job", "input_path": str(tmp_path / "other.json")})
    outside = tmp_path / "outside"
    outside.mkdir()
    (job / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        request_for("lottie_validate", {"job_id": "job", "input_path": "escape/animation.json"})


def test_giant_integers_and_wrong_boolean_flags_fail_soft():
    document = minimal_document()
    document["fr"] = 10 ** 1000
    assert validate_document(document)["ok"] is False
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["shapes"][0]["p"]["a"] = True
    assert any("must be 0 or 1" in error for error in validate_document(document)["errors"])


def test_requested_targets_filter_compatibility_report():
    document = author_document({"layers": [{"name": "Dot", "shape": "ellipse"}]})
    document["layers"][0]["ks"]["o"]["x"] = "50"
    report = validate_document(document, targets=("lottie-ios",))
    assert set(report["compatibility"]) == {"lottie-ios"}
    assert any("expression" in warning for warning in report["compatibility"]["lottie-ios"])


def test_nonzero_depth_and_nonuniform_stroke_scale_are_explicitly_not_previewed():
    document = author_document({"layers": [{"name": "Check", "shape": "path", "fill": None,
        "stroke": "#000000", "path": {"v": [[0, 0], [10, 10]], "i": [[0, 0]] * 2,
        "o": [[0, 0]] * 2, "c": False}}]})
    layer = document["layers"][0]
    layer["ks"]["p"]["k"][2] = 1
    layer["ks"]["s"]["k"] = [200, 100, 100]
    reasons = validate_document(document)["not_previewed"]
    assert any("depth" in reason for reason in reasons)
    assert any("nonuniform" in reason for reason in reasons)
