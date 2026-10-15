from __future__ import annotations

import copy
import re
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from server.run_budget import neutral_error

Action = Literal["accept", "reject", "revert", "undo", "reapply", "dismiss", "recheck", "acceptFree", "rejectAll", "trimToFit", "editCut"]
STATES = {"proposed", "awaiting_approval", "running", "ready", "accepted", "rejected", "reverted", "out_of_date", "failed", "paused_at_cap"}
REVIEW = {"proposed", "ready"}
COPY_KEYS = {"title", "label", "description", "detail", "prompt", "message", "failureTitle", "failureMessage", "label", "elapsedLabel", "approvedAtLabel"}
JARGON = re.compile(r"\b(diff|commit|merge|branch|planner|llm|tokens|aws|amazon|clerk|cloudflare|vercel)\b|\d\s*%", re.I)


class ChangesConflictError(ValueError):
    pass


class ChangesActionBody(BaseModel):
    expected_revision: int = Field(gt=0, strict=True)
    take_id: str | None = Field(default=None, min_length=1, max_length=120)
    cut: dict[str, Any] | None = None
    max_duration_ms: int | None = Field(default=None, ge=0, strict=True)


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 9007199254740991


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("This changeset is unavailable.")


def _only(value: dict, keys: str) -> dict:
    _require(isinstance(value, dict))
    return {key: copy.deepcopy(value[key]) for key in keys.split() if key in value}


def _safe(value: Any, key: str = "") -> Any:
    if key in COPY_KEYS and not isinstance(value, str):
        return "Change" if key == "title" else "Media" if key == "label" else ""
    if isinstance(value, dict):
        return {name: _safe(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, key) for item in value]
    if isinstance(value, str) and (key in COPY_KEYS or key == "specs"):
        fallback = "Change" if key == "title" else "Media" if key == "label" else ""
        return fallback if JARGON.search(value) else neutral_error(value, fallback)
    return value


def _cut(value: dict, takes: list[dict]) -> dict:
    _require(isinstance(value, dict) and isinstance(value.get("id"), str) and _integer(value.get("createdAt")))
    cut = _only(value, "id label createdAt slots order voiceRef voiceDurationMs stillRefs")
    _require(isinstance(cut.get("slots"), list) and isinstance(cut.get("order"), list))
    cut["slots"] = [_only(slot, "slotId takeId inMs outMs title") for slot in cut["slots"] if isinstance(slot, dict)]
    _require(len(cut["slots"]) == len(value["slots"]))
    for slot in cut["slots"]:
        _require(isinstance(slot.get("slotId"), str) and _integer(slot.get("inMs")) and _integer(slot.get("outMs")))
        _require(slot["outMs"] - slot["inMs"] >= 500 and any(take["id"] == slot.get("takeId") and take["slotId"] == slot["slotId"] and take["durationMs"] >= slot["outMs"] for take in takes))
    _require(all(isinstance(item, str) for item in cut["order"]) and len(set(cut["order"])) == len(cut["order"]) == len(cut["slots"]))
    _require(set(cut["order"]) == {slot["slotId"] for slot in cut["slots"]})
    _require("voiceDurationMs" not in cut or _integer(cut["voiceDurationMs"]))
    _require(cut.get("voiceRef") is None or isinstance(cut["voiceRef"], str))
    _require("stillRefs" not in cut or isinstance(cut["stillRefs"], dict) and all(value is None or isinstance(value, str) for value in cut["stillRefs"].values()))
    return cut


def validate_document(value: dict) -> dict:
    d = _only(value, "revision changeset changes takes currentCut checkpointCut versions newTakeApproval")
    _require(_integer(d.get("revision")) and d["revision"] > 0)
    cs = d.get("changeset", {})
    _require(all(isinstance(cs.get(key), str) and cs[key] for key in ("id", "projectId", "checkpointCutId")))
    _require(all(_integer(cs.get(key)) for key in ("n", "createdAt", "estimateCents", "capCents", "actualCents")) and cs["n"] > 0)
    d["changeset"] = _only(cs, "id projectId n title createdAt checkpointCutId estimateCents capCents actualCents status lines")
    _require(cs.get("status") in {"open", "running", "paused_at_cap", "done"})
    _require(all(isinstance(d.get(key), list) for key in ("changes", "takes", "versions")))
    d["takes"] = [_only(take, "id slotId n mediaRef mediaKind posterUrl durationMs costCents parentTakeId createdAt width height reviewState") for take in d["takes"]]
    for take in d["takes"]:
        _require(all(isinstance(take.get(key), str) and take[key] for key in ("id", "slotId", "mediaRef")))
        _require(all(_integer(take.get(key)) for key in ("n", "durationMs", "costCents", "createdAt")) and take["n"] > 0 and take["durationMs"] > 0)
        _require(take.get("mediaKind") in {"video", "still"})
    _require(len({take["id"] for take in d["takes"]}) == len(d["takes"]))
    for key in ("currentCut", "checkpointCut"):
        d[key] = _cut(d.get(key, {}), d["takes"])
    d["versions"] = [_cut(cut, d["takes"]) for cut in d["versions"]]
    _require(cs["checkpointCutId"] == d["checkpointCut"]["id"])
    d["changes"] = [_only(change, "id changesetId n kind slotId title description beforeRef afterRef costCents state taken approval executionId callId") for change in d["changes"]]
    for change in d["changes"]:
        _require(isinstance(change.get("id"), str) and change.get("changesetId") == cs["id"] and _integer(change.get("n")) and change["n"] > 0)
        _require(change.get("state") in STATES and _integer(change.get("costCents")) and type(change.get("taken")) is bool)
        kind = change.get("kind")
        keys = {"take": "kind takeId", "trim": "kind inMs outMs", "reorder": "kind order", "voice": "kind mediaRef durationMs", "still": "kind mediaRef dependentSlotIds"}
        _require(kind in keys and (kind not in {"take", "trim", "still"} or isinstance(change.get("slotId"), str)))
        for side in ("beforeRef", "afterRef"):
            ref = change.get(side, {})
            _require(isinstance(ref, dict) and ref.get("kind") == kind)
            change[side] = _only(ref, keys[kind])
            _require(all(_integer(ref.get(key)) for key in (("inMs", "outMs") if kind == "trim" else ("durationMs",) if kind == "voice" else ())))
            _require(kind != "take" or isinstance(ref.get("takeId"), str))
            _require(kind not in {"voice", "still"} or ref.get("mediaRef") is None or isinstance(ref["mediaRef"], str))
            _require(kind not in {"reorder", "still"} or isinstance(ref.get("order" if kind == "reorder" else "dependentSlotIds"), list))
    _require(len({c["id"] for c in d["changes"]}) == len({c["n"] for c in d["changes"]}) == len(d["changes"]))
    approval_keys = "id status title tier prompt specs thumbUrl resultThumbUrl stepIndex stepCount lines estimateCents capCents balanceCents balanceAfterEstimateCents balanceAfterCapCents heldCents spentSoFarCents chargedCents raiseOptionsCents lowerCapOptionCents actualCents balanceBeforeCents balanceAfterCents walletTotalCents underEstimate approvedAtLabel elapsedLabel failureTitle failureMessage message estimateIncomplete approveEnabled"
    for change in d["changes"]:
        if "approval" in change:
            change["approval"] = _only(change["approval"], approval_keys)
    if "newTakeApproval" in d:
        d["newTakeApproval"] = _only(d["newTakeApproval"], approval_keys)
    for billing in [d["changeset"], *[c["approval"] for c in d["changes"] if "approval" in c], *([d["newTakeApproval"]] if "newTakeApproval" in d else [])]:
        _require(all(_integer(billing.get(key)) for key in ("estimateCents", "capCents")) and isinstance(billing.get("lines"), list))
        billing["lines"] = [_only(line, "kind label detail priceCents basis") for line in billing["lines"]]
        _require(all(_integer(line.get("priceCents")) for line in billing["lines"]))
    return _safe(d)


def _ref(cut: dict, change: dict) -> dict:
    kind = change["kind"]
    slot = next((slot for slot in cut["slots"] if slot["slotId"] == change.get("slotId")), {})
    if kind == "take":
        return {"kind": kind, "takeId": slot.get("takeId")}
    if kind == "trim":
        return {"kind": kind, "inMs": slot.get("inMs"), "outMs": slot.get("outMs")}
    if kind == "reorder":
        return {"kind": kind, "order": cut["order"]}
    if kind == "voice":
        return {"kind": kind, "mediaRef": cut.get("voiceRef"), "durationMs": cut.get("voiceDurationMs", 0)}
    if not slot:
        return {"kind": kind, "slotMissing": True}
    return {"kind": kind, "mediaRef": cut.get("stillRefs", {}).get(change["slotId"]), "dependentSlotIds": change["beforeRef"]["dependentSlotIds"]}


def _paid(change: dict) -> bool:
    approval = change.get("approval", {})
    return bool(change["costCents"] or approval.get("estimateCents") or approval.get("capCents") or approval.get("estimateIncomplete"))


def _change(d: dict, change: dict, action: str, take_id: str | None) -> None:
    state = change["state"]
    if action in {"reject", "dismiss"}:
        if state not in {"accepted", "rejected"}:
            change["state"] = "rejected"
        return
    if action in {"undo", "recheck"}:
        if state == "rejected" and action == "undo" or state == "out_of_date" and action == "recheck" and _ref(d["currentCut"], change) == change["beforeRef"]:
            change["state"] = "ready" if change["taken"] else "awaiting_approval" if _paid(change) else "proposed"
        return
    reverting = action == "revert"
    choosing = action == "accept" and change["kind"] == "take" and take_id is not None
    allowed = {"accepted"} if reverting else {"reverted"} if action == "reapply" else REVIEW | {"accepted", "rejected", "reverted"} if choosing else REVIEW
    if state not in allowed:
        return
    if not reverting and _paid(change) and not change["taken"]:
        return
    if _ref(d["currentCut"], change) != change["afterRef" if reverting or choosing and state == "accepted" else "beforeRef"]:
        change["state"] = "out_of_date"
        return
    cut, ref, kind = copy.deepcopy(d["currentCut"]), copy.deepcopy(change["beforeRef" if reverting else "afterRef"]), change["kind"]
    if take_id is not None and not reverting:
        _require(kind == "take" and any(t["id"] == take_id and t["slotId"] == change["slotId"] for t in d["takes"]))
        ref = {"kind": "take", "takeId": take_id}
    if kind == "take" and not reverting and any(item["kind"] == "take" and item["afterRef"]["takeId"] == ref["takeId"] and _paid(item) and not item["taken"] for item in d["changes"]):
        return
    slot = next((slot for slot in cut["slots"] if slot["slotId"] == change.get("slotId")), None)
    if kind in {"take", "trim"}:
        if not slot:
            change["state"] = "out_of_date"
            return
        slot.update({"takeId": ref["takeId"]} if kind == "take" else {"inMs": ref["inMs"], "outMs": ref["outMs"]})
    elif kind == "reorder":
        cut["order"] = ref["order"]
    elif kind == "voice":
        cut["voiceRef"], cut["voiceDurationMs"] = ref["mediaRef"], ref["durationMs"]
    else:
        if not slot:
            change["state"] = "out_of_date"
            return
        cut.setdefault("stillRefs", {})[change["slotId"]] = ref["mediaRef"]
    try:
        d["currentCut"] = _cut(cut, d["takes"])
        if take_id is not None and not reverting:
            change["afterRef"] = ref
        change["state"] = "reverted" if reverting else "accepted"
    except ValueError:
        if take_id is None:
            change["state"] = "out_of_date"


def transition_document(document: dict, n: int, action: str, expected_revision: int, *, take_id: str | None = None, cut: dict | None = None, max_duration_ms: int | None = None) -> dict:
    d = copy.deepcopy(document)
    change = next((item for item in d["changes"] if item["n"] == n), None)
    if expected_revision != d["revision"]:
        if not change:
            raise ChangesConflictError("The cut changed. Reload before trying again.")
        change["state"] = "out_of_date"
    elif action in {"restore", "editCut"}:
        _require(action != "editCut" or cut is not None)
        if action == "restore":
            previous = copy.deepcopy(d["currentCut"])
            if previous not in d["versions"]:
                while any(version["id"] == previous["id"] for version in d["versions"]):
                    previous["id"] = uuid.uuid4().hex
                d["versions"].append(previous)
        saved = _cut(cut if action == "editCut" and cut is not None else d["checkpointCut"], d["takes"])
        if action == "editCut":
            current = d["currentCut"]
            _require(all(any(old["slotId"] == slot["slotId"] and old["takeId"] == slot["takeId"] for old in current["slots"]) for slot in saved["slots"]))
            _require(saved.get("voiceRef") == current.get("voiceRef") and saved.get("voiceDurationMs", 0) == current.get("voiceDurationMs", 0) and saved.get("stillRefs", {}) == current.get("stillRefs", {}))
        saved.update(id=uuid.uuid4().hex, label="Restored checkpoint" if action == "restore" else "Current cut", createdAt=int(time.time() * 1000))
        d["currentCut"] = saved
        d["versions"].append(copy.deepcopy(saved))
        for item in d["changes"]:
            if action == "restore" and item["state"] == "accepted":
                item["state"] = "reverted"
            elif action == "editCut" and item["state"] in REVIEW and _ref(saved, item) != item["beforeRef"]:
                item["state"] = "out_of_date"
    elif action == "trimToFit":
        duration = sum(slot["outMs"] - slot["inMs"] for slot in d["currentCut"]["slots"])
        if max_duration_ms is not None:
            preview = copy.deepcopy(d)
            for item in preview["changes"]:
                if item["state"] in REVIEW and (not _paid(item) or item["taken"]):
                    _change(preview, item, "accept", None)
            _require(max_duration_ms in {duration, sum(slot["outMs"] - slot["inMs"] for slot in preview["currentCut"]["slots"])})
            duration = max_duration_ms
        if d["currentCut"].get("voiceRef") and d["currentCut"].get("voiceDurationMs", 0) > duration:
            d["currentCut"]["voiceDurationMs"] = duration
    elif action in {"acceptFree", "rejectAll"}:
        for item in d["changes"]:
            if action == "acceptFree" and item["state"] in REVIEW and not _paid(item) or action == "rejectAll" and item["state"] not in {"accepted", "rejected", "reverted"}:
                _change(d, item, "accept" if action == "acceptFree" else "reject", None)
    elif change:
        _change(d, change, action, take_id)
    else:
        raise KeyError("Change not found")
    if d != document:
        d["revision"] += 1
    return _safe(d)
