from __future__ import annotations

import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from providers.footage_memory.index import SCHEMA_VERSION, VideoIndex


EXTENSIONS = {
    "shots": {"asset_version_id", "idx", "t0_ms", "t1_ms", "caption", "shot_type",
              "keyframes_json", "analysed_at", "asset_id", "window_id"},
    "components": {"label", "label_embedding_ref", "kind", "created_at"},
    "tracks": {"component_id", "asset_version_id", "shot_id", "t0_ms", "t1_ms",
               "mean_conf", "bbox_path_json", "mask_blob_key", "mask_fps", "mask_w",
               "mask_h", "source", "model_ref", "asset_id", "window_id"},
    "masks": {"asset_id", "asset_version_id", "track_id", "shot_id", "window_id",
              "blob_key", "format", "fps", "width", "height", "created_at"},
    "annotations": {"thread_id", "parent_id", "author_kind", "author_id", "body",
                    "status", "mentions_json", "intent_hint", "changeset_id",
                    "change_item_id", "created_at", "updated_at"},
    "anchors": {"annotation_id", "kind", "asset_version_id", "shot_id", "t0_ms",
                "t1_ms", "frame_index", "geometry_json", "track_id", "audio_json",
                "word_ids_json", "snapshot_key", "asset_id", "window_id"},
    "analysis_jobs": {"asset_version_id", "depth", "status", "estimate_cents",
                      "cap_cents", "actual_cents", "tool_call_id", "error", "asset_id"},
}


class VideoIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project-a" / "video_index.sqlite3"
        self.index = VideoIndex(self.path, "project-a", "workspace-a")
        self.addCleanup(self.index.close)

    def asset(self, content_hash="hash-a", duration_s=30, asset_version_id=None):
        return self.index.upsert_asset(content_hash=content_hash, path_key="uploads/clip.mp4",
                                       duration_s=duration_s, fps=24,
                                       asset_version_id=asset_version_id)

    def add_events(self, asset=None, events=None):
        asset = asset or self.asset()
        window = self.index.add_window(asset["id"], 0, 30000)
        rows = self.index.replace_window_events(window["id"], events or [
            {"kind": "dialogue", "t0_ms": 1000, "t1_ms": 3000,
             "speaker": "Guest", "text": "My childhood was spent by the river.",
             "confidence": 0.8, "attrs": {"topic": "childhood"}},
            {"kind": "sound", "t0_ms": 4000, "t1_ms": 5000,
             "text": "A dog barks.", "confidence": 0.7},
            {"kind": "on_screen_text", "t0_ms": 6000, "t1_ms": 8000,
             "text": "CHILDHOOD RIVER", "confidence": 0.9},
            {"kind": "moment", "t0_ms": 9000, "t1_ms": 10000,
             "text": "Guest laughs about childhood.", "confidence": 0.75},
            {"kind": "person", "t0_ms": 10000, "t1_ms": 11000,
             "text": "Guest in a blue jacket.", "confidence": 0.9},
            {"kind": "object", "t0_ms": 12000, "t1_ms": 13000,
             "text": "Red mug on the table.", "confidence": 0.85},
            {"kind": "location", "t0_ms": 14000, "t1_ms": 15000,
             "text": "Interview studio.", "confidence": 0.9},
        ])
        self.index.mark_complete(asset["id"], "memory-v1")
        return asset, window, rows

    def test_schema_reopening_is_idempotent_and_preserves_events(self):
        asset, _, rows = self.add_events()
        self.index.mark_complete(asset["id"], "memory-v1")
        with VideoIndex(self.path, "project-a", "workspace-a") as reopened:
            self.assertEqual(reopened.query("childhood"), self.index.query("childhood"))
            self.assertEqual(reopened.event(rows[0]["id"])["text"], rows[0]["text"])
            self.assertEqual(reopened.asset(asset["id"])["memory_version"], "memory-v1")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_extensions_match_plan_are_scoped_and_remain_empty(self):
        self.add_events()
        with sqlite3.connect(self.path) as db:
            for table, expected in EXTENSIONS.items():
                with self.subTest(table=table):
                    columns = {r[1]: r[2] for r in db.execute(f"PRAGMA table_info({table})")}
                    self.assertTrue(expected | {"id", "project_id", "workspace_id"} <= columns.keys())
                    self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
            mask_types = dict((r[1], r[2]) for r in db.execute("PRAGMA table_info(masks)"))
            self.assertNotIn("BLOB", mask_types.values())

    def test_core_rows_all_carry_project_and_workspace(self):
        asset, _, _ = self.add_events()
        self.index.add_embedding(asset_id=asset["id"], owner_kind="event", owner_id="event",
                                 t_ms=1000, vector=[1.0, 0.0], model_ref="fixture")
        with sqlite3.connect(self.path) as db:
            for table in ("index_meta", "assets", "windows", "events", "speakers",
                          "search_docs", "embeddings"):
                self.assertEqual(db.execute(
                    f"SELECT DISTINCT project_id, workspace_id FROM {table}"
                ).fetchall(), [("project-a", "workspace-a")])

    def test_hash_and_version_reuse_ignore_reuploaded_path(self):
        original = self.asset(asset_version_id="av1")
        same = self.index.upsert_asset(content_hash="hash-a", path_key="uploads/reuploaded.mp4",
                                       duration_s=30, fps=24, asset_version_id="av1")
        self.assertEqual(original["id"], same["id"])
        self.assertEqual(self.index.find_asset("hash-a", "av1")["id"], original["id"])
        other_version = self.asset(asset_version_id="av2")
        self.assertNotEqual(original["id"], other_version["id"])
        self.assertIsNone(self.index.find_asset("hash-a", "unknown"))

    def test_two_project_indexes_never_share_assets_or_hits(self):
        asset, _, rows = self.add_events()
        with VideoIndex(Path(self.tmp.name) / "project-b" / "video_index.sqlite3", "project-b",
                        "workspace-a") as other:
            same_bytes = other.upsert_asset(content_hash="hash-a", path_key="clip.mp4", duration_s=30)
            self.assertNotEqual(same_bytes["id"], asset["id"])
            self.assertIsNone(other.asset(asset["id"]))
            self.assertIsNone(other.event(rows[0]["id"]))
            self.assertEqual(other.query("childhood"), [])
            with self.assertRaisesRegex(ValueError, "not found"):
                other.add_window(asset["id"], 0, 1000)

    def test_wrong_project_or_workspace_cannot_open_existing_database(self):
        self.add_events()
        for project, workspace in (("project-b", "workspace-a"), ("project-a", "workspace-b")):
            with self.subTest(project=project, workspace=workspace):
                with self.assertRaisesRegex(ValueError, "belongs to another project"):
                    VideoIndex(self.path, project, workspace)

    def test_events_and_speaker_attribution_round_trip(self):
        asset, _, rows = self.add_events()
        self.assertEqual({r["kind"] for r in rows},
                         {"dialogue", "sound", "on_screen_text", "moment", "person", "object", "location"})
        event = self.index.event(rows[0]["id"])
        self.assertEqual(event["speaker"], "Guest")
        self.assertEqual(event["attrs"], {"topic": "childhood"})
        self.assertEqual(event["t0_ms"], 1000)
        hit = next(hit for hit in self.index.query("river", scope=asset["id"]) if hit["kind"] == "dialogue")
        self.assertEqual(hit["t0_s"], 1)
        self.assertEqual(hit["t1_s"], 3)
        self.assertEqual(hit["speaker"], "Guest")
        self.assertTrue(hit["verify_required"])

    def test_replacing_window_is_idempotent_and_removes_old_search_docs(self):
        _, window, rows = self.add_events()
        replacement = [{"kind": "moment", "t0_ms": 2000, "t1_ms": 3000,
                        "text": "A balloon appears.", "confidence": 0.8}]
        one = self.index.replace_window_events(window["id"], replacement)
        two = self.index.replace_window_events(window["id"], replacement)
        self.index.mark_complete(one[0]["asset_id"], "memory-v1")
        self.assertEqual(one, two)
        self.assertEqual(self.index.query("childhood"), [])
        self.assertIsNone(self.index.event(rows[0]["id"]))
        self.assertEqual(len(self.index.query("balloon")), 1)

    def test_invalid_replacement_keeps_previous_complete_window(self):
        _, window, _ = self.add_events()
        with self.assertRaisesRegex(ValueError, "event kind"):
            self.index.replace_window_events(window["id"], [
                {"kind": "moment", "t0_ms": 1000, "t1_ms": 2000, "text": "valid"},
                {"kind": "made_up", "t0_ms": 1000, "t1_ms": 2000, "text": "invalid"},
            ])
        self.assertEqual(len(self.index.query("childhood")), 3)

    def test_search_ranking_deterministic_scoped_and_bounded(self):
        asset, _, _ = self.add_events()
        other = self.asset("hash-b")
        self.add_events(other, [{"kind": "moment", "t0_ms": 0, "t1_ms": 1000,
                                 "text": "Childhood river childhood river.", "confidence": 0.9}])
        first = self.index.query("childhood river", limit=2)
        self.assertEqual(first, self.index.query("CHILDHOOD RIVER", limit=2))
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0]["clip_id"], other["id"])
        self.assertTrue(all(h["clip_id"] == asset["id"] for h in self.index.query("childhood", asset["id"])))
        for limit in (0, -1, 101, True):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.index.query("childhood", limit=limit)
        self.assertEqual(self.index.query(" "), [])
        self.assertEqual(self.index.query('" OR *'), [])

    def test_fts_disabled_fallback_returns_same_rank_and_hits(self):
        self.add_events()
        expected = self.index.query("childhood river")
        with VideoIndex(self.path, "project-a", "workspace-a", use_fts=False) as fallback:
            self.assertFalse(fallback.fts_available)
            self.assertEqual(fallback.query("childhood river"), expected)
            self.assertEqual(fallback.query("no_match_word"), [])

    def test_fts_unavailable_at_runtime_falls_back(self):
        with patch.object(VideoIndex, "_create_fts", side_effect=sqlite3.OperationalError("no such module: fts5")):
            with VideoIndex(Path(self.tmp.name) / "fallback.sqlite3", "project-c") as fallback:
                self.assertFalse(fallback.fts_available)
                asset = fallback.upsert_asset(content_hash="hash", path_key="clip.mp4", duration_s=5)
                window = fallback.add_window(asset["id"], 0, 5000)
                fallback.replace_window_events(window["id"], [
                    {"kind": "sound", "text": "Church bells", "t0_ms": 0, "t1_ms": 1000}
                ])
                fallback.mark_complete(asset["id"], "memory-v1")
                self.assertEqual(fallback.query("bells")[0]["snippet"], "Church bells")

    def test_vec_absence_skips_without_changing_plain_embeddings(self):
        asset = self.asset()
        row = self.index.add_embedding(asset_id=asset["id"], owner_kind="caption", owner_id="caption1",
                                       t_ms=1000, vector=[1.0, -2.5, 0.0], model_ref="fixture-v1")
        self.assertEqual(row["dim"], 3)
        self.assertEqual(struct.unpack("<3f", row["vec"]), (1.0, -2.5, 0.0))
        with patch("providers.footage_memory.index.importlib.import_module", side_effect=ImportError):
            self.assertFalse(self.index.install_vec_adapter(3))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT vec FROM embeddings").fetchone()[0], row["vec"])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='embeddings_vec_3'").fetchone())

    def test_vec_present_but_unloadable_skips_cleanly(self):
        with patch("providers.footage_memory.index.importlib.import_module") as module:
            module.return_value.load.side_effect = sqlite3.OperationalError("disabled extension")
            self.assertFalse(self.index.install_vec_adapter(2))
        self.assertEqual(self.index.query("any"), [])

    def test_vector_adapter_sql_and_dimensions_with_optional_stub(self):
        asset = self.asset()
        self.index.add_embedding(asset_id=asset["id"], owner_kind="caption", owner_id="caption1",
                                 t_ms=0, vector=[1, 2], model_ref="fixture")
        statements = []
        real_db = self.index.connection

        class ConnectionStub:
            def enable_load_extension(self, enabled):
                statements.append(("enable", enabled))

            def execute(self, sql, args=()):
                statements.append((sql, args))
                if "CREATE VIRTUAL" in sql:
                    return real_db.execute("CREATE TABLE embeddings_vec_2(id TEXT, vec BLOB, project_id TEXT, workspace_id TEXT, asset_id TEXT)")
                return real_db.execute(sql, args)

            def commit(self):
                return real_db.commit()

            def rollback(self):
                return real_db.rollback()

        with patch("providers.footage_memory.index.importlib.import_module"):
            self.index.connection = ConnectionStub()
            try:
                self.assertTrue(self.index.install_vec_adapter(2))
            finally:
                self.index.connection = real_db
        ddl = next(sql for sql, _ in statements if sql.startswith("CREATE VIRTUAL"))
        self.assertIn("USING vec0", ddl)
        self.assertIn("float[2]", ddl)
        self.assertEqual(statements[-1], ("enable", False))
        self.assertEqual(tuple(real_db.execute("SELECT project_id,workspace_id FROM embeddings_vec_2").fetchone()),
                         ("project-a", "workspace-a"))
        for dim in (0, 100001, True, "2; DROP TABLE events"):
            with self.assertRaises(ValueError):
                self.index.install_vec_adapter(dim)

    def test_hierarchy_references_same_events_without_second_store(self):
        asset = self.asset(duration_s=1200)
        event_ids = []
        for t0 in (0, 300000, 600000, 900000):
            window = self.index.add_window(asset["id"], t0, t0 + 300000)
            event = self.index.replace_window_events(window["id"], [
                {"kind": "moment", "t0_ms": t0 + 1000, "t1_ms": t0 + 2000,
                 "text": f"Moment at {t0}", "confidence": 0.8}
            ])[0]
            event_ids.append(event["id"])
        hierarchy = self.index.hierarchy(asset["id"])
        self.assertEqual(hierarchy["kind"], "Root")
        self.assertEqual(hierarchy["asset_id"], asset["id"])
        covered = []
        for super_event in hierarchy["children"]:
            self.assertEqual(super_event["kind"], "SuperEvent")
            for macro in super_event["children"]:
                self.assertEqual(macro["kind"], "MacroEvent")
                self.assertGreaterEqual(macro["t1_ms"] - macro["t0_ms"], 180000)
                self.assertLessEqual(macro["t1_ms"] - macro["t0_ms"], 480000)
                self.assertEqual(macro["subgraph"]["kind"], "Subgraph")
                covered.extend(macro["subgraph"]["event_ids"])
        self.assertEqual(covered, event_ids)

    def test_hierarchy_json_is_only_event_references_and_cleared_on_rebuild(self):
        asset, window, rows = self.add_events()
        saved = json.loads(self.index.asset(asset["id"])["hierarchy_json"])
        ids = saved["children"][0]["children"][0]["subgraph"]["event_ids"]
        self.assertEqual(ids, [r["id"] for r in rows])
        self.index.replace_window_events(window["id"], [])
        self.assertIsNone(self.index.asset(asset["id"])["hierarchy_json"])

    def test_macro_ranges_stay_between_three_and_eight_minutes_when_possible(self):
        for seconds in (180, 310, 481, 900, 10800):
            asset = self.asset(content_hash=f"duration-{seconds}", duration_s=seconds)
            for super_event in self.index.hierarchy(asset["id"])["children"]:
                for macro in super_event["children"]:
                    self.assertGreaterEqual(macro["t1_ms"] - macro["t0_ms"], 180000)
                    self.assertLessEqual(macro["t1_ms"] - macro["t0_ms"], 480000)

    def test_verify_persists_refined_time_and_still_marks_retrieval(self):
        _, _, rows = self.add_events()
        self.index.verify_event(rows[0]["id"], "verified", 1200, 2800)
        event = self.index.event(rows[0]["id"])
        self.assertEqual(event["attrs"]["verification"],
                         {"verdict": "verified", "t0_ms": 1200, "t1_ms": 2800})
        self.assertTrue(self.index.query("river")[0]["verify_required"])
        with self.assertRaises(ValueError):
            self.index.verify_event(rows[0]["id"], "ground_truth", 1200, 2800)
        with self.assertRaises(ValueError):
            self.index.verify_event(rows[0]["id"], "verified", 0, 31000)

    def test_verification_can_refine_across_a_coarse_window_boundary(self):
        asset = self.asset(duration_s=60)
        window = self.index.add_window(asset["id"], 0, 30000)
        event = self.index.replace_window_events(window["id"], [
            {"kind": "moment", "t0_ms": 29000, "t1_ms": 30000, "text": "Guest laughs"}
        ])[0]
        self.index.verify_event(event["id"], "verified", 28500, 31500)
        self.assertEqual(self.index.event(event["id"])["attrs"]["verification"]["t1_ms"], 31500)

    def test_identical_embedding_owner_names_in_other_assets_do_not_overwrite(self):
        first, other = self.asset("hash-one"), self.asset("hash-two")
        one = self.index.add_embedding(asset_id=first["id"], owner_kind="caption", owner_id="caption",
                                       t_ms=0, vector=[1, 2], model_ref="fixture")
        two = self.index.add_embedding(asset_id=other["id"], owner_kind="caption", owner_id="caption",
                                       t_ms=0, vector=[3, 4], model_ref="fixture")
        self.assertNotEqual(one["id"], two["id"])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM embeddings").fetchone()[0], 2)

    def test_embedding_refuses_values_outside_float32_range_without_rows(self):
        asset = self.asset()
        with self.assertRaisesRegex(ValueError, "float32"):
            self.index.add_embedding(asset_id=asset["id"], owner_kind="caption", owner_id="caption",
                                     t_ms=0, vector=[1e100], model_ref="fixture")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM embeddings").fetchone()[0], 0)

    def test_invalid_times_confidence_and_paths_are_rejected(self):
        for path in ("../clip.mp4", "a/../../clip.mp4", "/etc/passwd", "a\\..\\clip.mp4", "https://host/clip.mp4"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "path"):
                    self.index.upsert_asset(content_hash="hash", path_key=path, duration_s=30)
        for duration in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                self.asset(duration_s=duration)
        asset = self.asset()
        for t0, t1 in ((-1, 2000), (5000, 1000), (0, 31000), (True, 1000)):
            with self.assertRaises(ValueError):
                self.index.add_window(asset["id"], t0, t1)
        window = self.index.add_window(asset["id"], 0, 30000)
        for confidence in (-0.1, 1.1, float("nan"), True):
            with self.assertRaises(ValueError):
                self.index.replace_window_events(window["id"], [
                    {"kind": "moment", "text": "bad confidence", "t0_ms": 0,
                     "t1_ms": 1000, "confidence": confidence}
                ])

    def test_mark_complete_refuses_incomplete_or_gapped_windows(self):
        asset = self.asset(duration_s=60)
        self.index.add_window(asset["id"], 0, 30000)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.index.mark_complete(asset["id"], "memory-v1")
        self.assertIsNone(self.index.asset(asset["id"])["indexed_at"])
        self.index.add_window(asset["id"], 30000, 60000)
        self.index.mark_complete(asset["id"], "memory-v1")
        self.assertIsNotNone(self.index.asset(asset["id"])["indexed_at"])

    def test_retry_with_new_window_layout_removes_obsolete_failed_windows(self):
        asset = self.asset(duration_s=60)
        obsolete = self.index.add_window(asset["id"], 0, 30000, status="failed")
        old_event = self.index.replace_window_events(obsolete["id"], [
            {"kind": "moment", "t0_ms": 0, "t1_ms": 1000, "text": "Old layout moment"}
        ])[0]
        retained = self.index.add_window(asset["id"], 40000, 60000, status="complete")
        retained_event = self.index.replace_window_events(retained["id"], [
            {"kind": "sound", "t0_ms": 41000, "t1_ms": 42000, "text": "Bell rings"}
        ])[0]
        self.index.prepare_window_layout(asset["id"], [(0, 20000), (20000, 40000), (40000, 60000)])
        self.assertEqual([row["id"] for row in self.index.windows(asset["id"])], [retained["id"]])
        self.assertIsNone(self.index.event(old_event["id"]))
        self.assertEqual(self.index.event(retained_event["id"])["text"], "Bell rings")
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT id FROM search_docs WHERE owner_id=?",
                                         (old_event["id"],)).fetchone())
        self.index.add_window(asset["id"], 0, 20000)
        self.index.add_window(asset["id"], 20000, 40000)
        self.index.mark_complete(asset["id"], "memory-v1")
        self.assertEqual(self.index.query("bell")[0]["hit_id"], retained_event["id"])

    def test_window_layout_reuses_requested_pending_and_completed_records(self):
        asset = self.asset(duration_s=60)
        complete = self.index.add_window(asset["id"], 0, 30000)
        pending = self.index.add_window(asset["id"], 30000, 60000, status="pending")
        self.index.prepare_window_layout(asset["id"], [(0, 30000), (30000, 60000)])
        self.index.prepare_window_layout(asset["id"], [(0, 30000), (30000, 60000)])
        self.assertEqual([(row["id"], row["status"]) for row in self.index.windows(asset["id"])],
                         [(complete["id"], "complete"), (pending["id"], "pending")])

    def test_completed_memory_cannot_be_cleared_by_changed_window_layout(self):
        asset, _, events = self.add_events()
        before = self.index.asset(asset["id"])
        self.index.prepare_window_layout(asset["id"], [(0, 30000)])
        self.assertEqual(self.index.asset(asset["id"]), before)
        with self.assertRaisesRegex(ValueError, "completed memory"):
            self.index.prepare_window_layout(asset["id"], [(0, 15000), (15000, 30000)])
        self.assertEqual(self.index.asset(asset["id"]), before)
        self.assertEqual(self.index.event(events[0]["id"])["text"], events[0]["text"])

    def test_obsolete_window_extension_reference_rolls_back_cleanup(self):
        asset = self.asset(duration_s=60, asset_version_id="av1")
        window = self.index.add_window(asset["id"], 0, 30000, status="failed")
        event = self.index.replace_window_events(window["id"], [
            {"kind": "moment", "t0_ms": 1000, "t1_ms": 2000, "text": "Referenced moment"}
        ])[0]
        with self.index.connection:
            self.index.connection.execute(
                "INSERT INTO shots(id,project_id,workspace_id,asset_id,asset_version_id,window_id,idx,t0_ms,t1_ms) "
                "VALUES('shot1',?,?,?,?,?,0,0,30000)",
                ("project-a", "workspace-a", asset["id"], "av1", window["id"]),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.prepare_window_layout(asset["id"], [(0, 20000), (20000, 40000), (40000, 60000)])
        self.assertEqual(self.index.event(event["id"])["text"], "Referenced moment")
        self.assertEqual(self.index.windows(asset["id"])[0]["id"], window["id"])
        with sqlite3.connect(self.path) as db:
            self.assertIsNotNone(db.execute("SELECT id FROM search_docs WHERE owner_id=?",
                                            (event["id"],)).fetchone())

    def test_invalid_window_layout_does_not_remove_existing_records(self):
        asset = self.asset(duration_s=30)
        original = self.index.add_window(asset["id"], 0, 30000, status="pending")
        for layout in ([], [(0, 31000)], [(-1, 30000)], [(0, 30000), (0, 30000)],
                       [(0, 15000), (16000, 30000)], [(0, 20000), (15000, 30000)]):
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    self.index.prepare_window_layout(asset["id"], layout)
                self.assertEqual(self.index.windows(asset["id"])[0]["id"], original["id"])

    def test_search_excludes_failed_windows_even_if_completion_metadata_is_old(self):
        asset, window, _ = self.add_events()
        with self.index.connection:
            self.index.connection.execute("UPDATE windows SET status='failed' WHERE id=?", (window["id"],))
        self.assertIsNotNone(self.index.asset(asset["id"])["memory_version"])
        self.assertEqual(self.index.query("childhood"), [])

    def test_queries_exclude_incomplete_memories(self):
        asset = self.asset()
        window = self.index.add_window(asset["id"], 0, 30000)
        self.index.replace_window_events(window["id"], [
            {"kind": "moment", "t0_ms": 0, "t1_ms": 1000, "text": "Childhood memory"}
        ])
        self.assertEqual(self.index.query("childhood"), [])
        self.index.mark_complete(asset["id"], "memory-v1")
        self.assertEqual(self.index.query("childhood")[0]["snippet"], "Childhood memory")

    def test_path_lookup_finds_stale_content_without_cross_project_rows(self):
        old = self.asset("old-hash")
        fresh = self.asset("new-hash")
        self.assertEqual({r["id"] for r in self.index.assets_for_path("uploads/clip.mp4")},
                         {old["id"], fresh["id"]})
        self.assertIsNone(self.index.asset_by_path("uploads/unknown.mp4"))

    def test_schema_v1_migrates_extensions_without_altering_core_data(self):
        path = Path(self.tmp.name) / "migration.sqlite3"
        sql = Path(__file__).resolve().parents[1] / "providers/footage_memory/sql/001_core.sql"
        with sqlite3.connect(path) as db:
            db.executescript(sql.read_text())
            db.execute("INSERT INTO index_meta(singleton,project_id,workspace_id) VALUES(1,?,?)",
                       ("legacy-project", "local"))
            db.execute("PRAGMA user_version=1")
        with VideoIndex(path, "legacy-project") as migrated:
            asset = migrated.upsert_asset(content_hash="hash", path_key="clip.mp4", duration_s=5)
            self.assertEqual(migrated.asset(asset["id"])["content_hash"], "hash")
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(db.execute("SELECT count(*) FROM shots").fetchone()[0], 0)

    def test_future_schema_is_rejected_without_migration(self):
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(ValueError, "newer"):
            VideoIndex(self.path, "project-a", "workspace-a")

    def test_local_index_does_not_open_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            self.add_events()
            self.assertEqual(self.index.query("dog")[0]["kind"], "sound")


if __name__ == "__main__":
    unittest.main()
