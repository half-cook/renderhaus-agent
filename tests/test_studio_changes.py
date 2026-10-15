from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.studio_state import StudioRepository


def changes_document():
    cut = {"id": "checkpoint", "label": "Checkpoint", "createdAt": 1,
           "slots": [{"slotId": "shot", "takeId": "take-1", "inMs": 0, "outMs": 5000}], "order": ["shot"]}
    base = {"changesetId": "changes-1", "slotId": "shot", "description": "", "taken": False}
    return {"revision": 1, "changeset": {"id": "changes-1", "projectId": "film", "n": 1,
            "title": "Warmer finish", "createdAt": 1, "checkpointCutId": "checkpoint", "estimateCents": 97,
            "capCents": 150, "actualCents": 95, "status": "open", "lines": [
                {"kind": "media", "label": "Media", "priceCents": 67, "basis": "fixed"},
                {"kind": "orchestration", "label": "Agent orchestration", "priceCents": 28, "basis": "fixed"}]},
            "changes": [{**base, "id": "change-1", "n": 1, "kind": "take", "title": "Warm light",
                         "beforeRef": {"kind": "take", "takeId": "take-1"}, "afterRef": {"kind": "take", "takeId": "take-2"},
                         "costCents": 65, "taken": True, "state": "ready"},
                        {**base, "id": "change-2", "n": 2, "kind": "trim", "title": "Shorter ending",
                         "beforeRef": {"kind": "trim", "inMs": 0, "outMs": 5000},
                         "afterRef": {"kind": "trim", "inMs": 0, "outMs": 4200}, "costCents": 0, "state": "proposed"}],
            "takes": [{"id": f"take-{n}", "slotId": "shot", "n": n, "mediaRef": "/beta/shot-lift.jpg",
                       "mediaKind": "still", "durationMs": 5000, "costCents": 65, "createdAt": 1} for n in (1, 2, 3)],
            "currentCut": {**copy.deepcopy(cut), "id": "current"}, "checkpointCut": cut, "versions": [copy.deepcopy(cut)]}


class StudioChangesTests(unittest.TestCase):
    def setUp(self):
        from server import studio
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.repo = StudioRepository(root / "state.sqlite3", root / "media")
        self.repo.create_project("user:user-a", "user-a", "Film", project_id="film")
        repository_patch = patch.object(studio, "repository", self.repo)
        repository_patch.start()
        self.addCleanup(repository_patch.stop)
        self.app = FastAPI()
        self.app.include_router(studio.router)
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-a"})
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def seed(self, document=None):
        return self.repo.save_changes_document("user:user-a", "film", "user-a", document or changes_document())

    def action(self, n, action, revision=1, **body):
        return self.client.post(f"/api/studio/changesets/changes-1/changes/{n}/{action}",
                                json={"expected_revision": revision, **body})

    def test_empty_project_has_no_fixture_changes(self):
        response = self.client.get("/api/studio/projects/film/changesets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": []})

    def test_accept_free_preserves_paid_take_and_persists_after_repository_restart(self):
        self.seed()
        response = self.action(0, "acceptFree")
        self.assertEqual(response.status_code, 200, response.text)
        document = response.json()
        self.assertEqual(document["currentCut"]["slots"][0]["takeId"], "take-1")
        self.assertEqual(document["currentCut"]["slots"][0]["outMs"], 4200)
        self.assertEqual(document["changes"][0]["state"], "ready")
        reloaded = StudioRepository(self.repo.database_path, self.repo.media_root).list_changes_documents("user:user-a", "film")
        self.assertEqual(reloaded[0], document)
        self.assertEqual(document["changeset"]["actualCents"], 95)

    def test_take_and_trim_are_independent_and_existing_rejected_take_can_be_chosen(self):
        self.seed()
        trim = self.action(2, "accept").json()
        accepted = self.action(1, "accept", trim["revision"], take_id="take-3")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        document = accepted.json()
        self.assertEqual(document["currentCut"]["slots"][0], {"slotId": "shot", "takeId": "take-3", "inMs": 0, "outMs": 4200})
        self.assertEqual(len(document["takes"]), 3)
        self.assertEqual(document["changeset"]["actualCents"], 95)

    def test_shorter_selected_take_preserves_the_original_proposal_and_cut(self):
        document = changes_document()
        document["takes"][2]["durationMs"] = 4000
        stored = self.seed(document)
        response = self.action(1, "accept", take_id="take-3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stored)
        self.assertEqual(response.json()["changes"][0]["afterRef"]["takeId"], "take-2")

    def test_other_ready_change_cannot_select_an_untaken_paid_result(self):
        document = changes_document()
        document["changes"][0].update(state="awaiting_approval", taken=False)
        other = copy.deepcopy(document["changes"][0])
        other.update(id="other-take", n=3, state="ready", taken=True, costCents=0, afterRef={"kind": "take", "takeId": "take-3"})
        document["changes"].append(other)
        stored = self.seed(document)
        response = self.action(3, "accept", take_id="take-2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), stored)
        self.assertEqual(response.json()["currentCut"]["slots"][0]["takeId"], "take-1")

    def test_untaken_paid_change_cannot_be_accepted(self):
        document = changes_document()
        document["changes"][0].update(state="awaiting_approval", taken=False)
        self.seed(document)
        response = self.action(1, "accept")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changes"][0]["state"], "awaiting_approval")
        self.assertEqual(response.json()["currentCut"]["slots"][0]["takeId"], "take-1")

    def test_incomplete_zero_priced_quote_is_not_free_and_private_fields_are_not_returned(self):
        document = changes_document()
        document["changes"][0].update(costCents=0, taken=False, approval={"id": "quote", "status": "pending", "title": "Paid step",
            "specs": [], "estimateCents": 0, "capCents": 0, "estimateIncomplete": True, "lines": [], "provider": "OpenAI"})
        self.seed(document)
        response = self.action(0, "acceptFree")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changes"][0]["state"], "ready")
        self.assertEqual(response.json()["currentCut"]["slots"][0]["takeId"], "take-1")
        self.assertNotIn("provider", response.json()["changes"][0]["approval"])

    def test_stale_revision_marks_target_out_of_date_without_overwriting_newer_cut(self):
        self.seed()
        self.action(2, "accept")
        response = self.action(1, "accept", 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changes"][0]["state"], "out_of_date")
        self.assertEqual(response.json()["currentCut"]["slots"][0]["outMs"], 4200)
        self.assertEqual(response.json()["currentCut"]["slots"][0]["takeId"], "take-1")

    def test_restore_is_a_new_saved_version_and_reject_keeps_takes(self):
        self.seed()
        rejected = self.action(1, "reject").json()
        self.assertEqual(len(rejected["takes"]), 3)
        accepted = self.action(2, "accept", rejected["revision"]).json()
        response = self.client.post("/api/studio/changesets/changes-1/restore", json={"expected_revision": accepted["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        document = response.json()
        self.assertNotEqual(document["currentCut"]["id"], "checkpoint")
        self.assertEqual(document["currentCut"]["slots"][0]["outMs"], 5000)
        self.assertEqual(document["versions"][-1]["id"], document["currentCut"]["id"])
        self.assertEqual(document["versions"][-2]["id"], accepted["currentCut"]["id"])
        self.assertEqual(document["versions"][-2]["slots"][0]["outMs"], 4200)
        self.assertEqual(document["changes"][1]["state"], "reverted")

    def test_restore_preserves_current_snapshot_when_its_id_collides_with_an_older_saved_version(self):
        document = changes_document()
        older = copy.deepcopy(document["currentCut"])
        document["versions"].append(older)
        document["currentCut"]["slots"][0]["takeId"] = "take-2"
        document["changes"][0]["state"] = "accepted"
        self.seed(document)
        response = self.client.post("/api/studio/changesets/changes-1/restore", json={"expected_revision": 1})
        self.assertEqual(response.status_code, 200)
        saved = next(cut for cut in response.json()["versions"] if cut["slots"][0]["takeId"] == "take-2")
        self.assertNotEqual(saved["id"], older["id"])
        preserved = next(cut for cut in response.json()["versions"] if cut["id"] == older["id"])
        self.assertEqual(preserved["slots"][0]["takeId"], "take-1")

    def test_copy_is_neutral_and_invalid_cents_cannot_become_free(self):
        document = changes_document()
        document["changes"][0]["title"] = "OpenAI branch fee 12%"
        self.seed(document)
        self.assertEqual(self.client.get("/api/studio/projects/film/changesets").json()["items"][0]["changes"][0]["title"], "Change")
        for value in (None, -1, 0.65, "65", True):
            invalid = changes_document()
            invalid["changes"][1]["costCents"] = value
            with self.assertRaises(ValueError):
                self.repo.save_changes_document("user:user-a", "film", "user-a", invalid)

    def test_changes_routes_require_project_ownership_and_authentication(self):
        self.seed()
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "user-b"})
        self.assertEqual(self.client.get("/api/studio/projects/film/changesets").status_code, 404)
        self.assertEqual(self.action(1, "accept").status_code, 404)
        self.assertEqual(self.client.post("/api/studio/changesets/changes-1/restore", json={"expected_revision": 1}).status_code, 404)
        def signed_out():
            raise HTTPException(status_code=401, detail="unauthorized")
        self.app.dependency_overrides[require_auth] = signed_out
        self.assertEqual(self.action(1, "accept").status_code, 401)

    def test_missing_revision_and_invalid_action_fail_without_writing(self):
        self.seed()
        self.assertEqual(self.client.post("/api/studio/changesets/changes-1/changes/1/accept", json={}).status_code, 422)
        self.assertEqual(self.action(1, "approve").status_code, 422)
        self.assertEqual(self.repo.list_changes_documents("user:user-a", "film")[0]["revision"], 1)

    def test_selected_taken_result_can_replace_accepted_rejected_and_reverted_changes(self):
        for state in ("accepted", "rejected", "reverted"):
            with self.subTest(state=state):
                document = changes_document()
                document["changeset"]["id"] = "changes-" + state
                for item in document["changes"]:
                    item["changesetId"] = document["changeset"]["id"]
                document["changes"][0]["state"] = state
                if state == "accepted":
                    document["currentCut"]["slots"][0]["takeId"] = "take-2"
                self.seed(document)
                response = self.client.post(f"/api/studio/changesets/changes-{state}/changes/1/accept",
                                            json={"expected_revision": 1, "take_id": "take-3"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["currentCut"]["slots"][0]["takeId"], "take-3")
                self.assertEqual(response.json()["changes"][0]["state"], "accepted")
                self.assertEqual(response.json()["revision"], 2)

    def test_voice_trim_can_use_proposed_duration_without_accepting_pending_changes(self):
        document = changes_document()
        document["currentCut"].update(voiceRef="/voice.wav", voiceDurationMs=6000)
        self.seed(document)
        response = self.action(0, "trimToFit", max_duration_ms=4200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["currentCut"]["voiceDurationMs"], 4200)
        self.assertEqual(response.json()["currentCut"]["slots"][0]["outMs"], 5000)
        self.assertEqual(response.json()["changes"][1]["state"], "proposed")
        invalid = self.action(0, "trimToFit", response.json()["revision"], max_duration_ms=10)
        self.assertEqual(invalid.status_code, 422)

    def test_manual_cut_edit_is_saved_atomically_and_marks_only_affected_proposals_stale(self):
        document = changes_document()
        self.seed(document)
        cut = copy.deepcopy(document["currentCut"])
        cut["slots"][0]["outMs"] = 4800
        cut["slots"][0]["title"] = "OpenAI branch fee 12%"
        response = self.action(0, "editCut", cut=cut)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changes"][0]["state"], "ready")
        self.assertEqual(response.json()["changes"][1]["state"], "out_of_date")
        self.assertNotEqual(response.json()["currentCut"]["id"], "current")
        self.assertEqual(response.json()["currentCut"]["slots"][0]["title"], "Change")
        self.assertEqual(self.repo.list_changes_documents("user:user-a", "film")[0], response.json())

    def test_manual_cut_edit_cannot_bypass_paid_approval_or_replace_attached_media(self):
        document = changes_document()
        document["changes"][0].update(state="awaiting_approval", taken=False)
        document["currentCut"].update(voiceRef="/voice.wav", voiceDurationMs=4000, stillRefs={"shot": "/still.jpg"})
        self.seed(document)
        mutations = [lambda cut: cut["slots"][0].update(takeId="take-2"),
                     lambda cut: cut.update(voiceRef="/unapproved.wav"),
                     lambda cut: cut.update(voiceDurationMs=1000),
                     lambda cut: cut.update(stillRefs={"shot": "/unapproved.jpg"})]
        for mutate in mutations:
            cut = copy.deepcopy(document["currentCut"])
            mutate(cut)
            response = self.action(0, "editCut", cut=cut)
            self.assertEqual(response.status_code, 422, response.text)
            stored = self.repo.list_changes_documents("user:user-a", "film")[0]
            self.assertEqual(stored["currentCut"], document["currentCut"])
            self.assertEqual(stored["changes"][0]["state"], "awaiting_approval")
            self.assertEqual(stored["revision"], 1)

    def test_malformed_cut_media_metadata_is_rejected_without_writing(self):
        self.seed()
        for patch_value in ({"voiceRef": {"url": "/voice.wav"}}, {"stillRefs": []}, {"stillRefs": {"shot": 45}}):
            cut = {**changes_document()["currentCut"], **patch_value}
            self.assertEqual(self.action(0, "editCut", cut=cut).status_code, 422)
            self.assertEqual(self.repo.list_changes_documents("user:user-a", "film")[0]["revision"], 1)

    def test_deleted_still_target_becomes_stale_and_cannot_accept_an_orphan_image_swap(self):
        document = changes_document()
        document["currentCut"]["stillRefs"] = {"shot": "/still.jpg"}
        document["changes"] = [{"id": "still-change", "changesetId": "changes-1", "n": 1, "kind": "still", "slotId": "shot",
            "title": "Warmer still", "description": "", "state": "proposed", "costCents": 0, "taken": False,
            "beforeRef": {"kind": "still", "mediaRef": "/still.jpg", "dependentSlotIds": ["shot"]},
            "afterRef": {"kind": "still", "mediaRef": "/warm-still.jpg", "dependentSlotIds": ["shot"]}}]
        self.seed(document)
        cut = {**document["currentCut"], "slots": [], "order": []}
        deleted = self.action(0, "editCut", cut=cut)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["changes"][0]["state"], "out_of_date")
        document["changeset"]["id"] = "changes-absent"
        document["changes"][0]["changesetId"] = "changes-absent"
        document["currentCut"] = cut
        self.seed(document)
        response = self.client.post("/api/studio/changesets/changes-absent/changes/1/accept", json={"expected_revision": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["changes"][0]["state"], "out_of_date")
        self.assertEqual(response.json()["currentCut"]["stillRefs"]["shot"], "/still.jpg")
