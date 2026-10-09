"""RunPod backend contract tests. Every HTTP request is mocked."""

from __future__ import annotations

import base64
import io
import json
import math
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from agent.deep_agent import continuity_qc_runpod as runpod_transport
from agent.deep_agent.continuity_qc import (
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    ContinuityConfig,
    ContinuityQC,
    FaceIdentityResult,
    Shot,
)


class Frame:
    def __init__(self, value):
        self.value = value

    def save(self, stream, *, format):
        if format != "PNG":
            raise AssertionError("Expected PNG transport")
        stream.write(b"fixture-frame-" + self.value.encode())


class Embedder:
    def __init__(self, model_id, similarity):
        self.model_id, self.similarity = model_id, similarity

    def embed(self, frame):
        if frame.value == "a":
            return [1.0, 0.0]
        return [self.similarity, math.sqrt(1.0 - self.similarity ** 2)]


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def completed(siglip=0.92, dino=0.74, *, dino_key="dinov2", pairs=None):
    return {
        "id": "job-1", "status": "COMPLETED",
        "output": {
            "models": {"siglip": SIGLIP_MODEL,
                       dino_key: DINOV3_MODEL if dino_key == "dinov3" else DINO_MODEL},
            "pairs": pairs if pairs is not None else [
                {"before": "one", "after": "two",
                 "similarities": {"siglip": siglip, dino_key: dino}},
            ],
        },
    }


class RunPodBackendTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.env = patch.dict("os.environ", {
            "CONTINUITY_QC_BACKEND": "local",
            "RUNPOD_API_KEY": "runpod-offline-test-key",
            "CONTINUITY_QC_RUNPOD_ENDPOINT_ID": "endpoint-test",
            "CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "10",
            "CONTINUITY_QC_RUNPOD_REQUEST_TIMEOUT_SECONDS": "2",
            "CONTINUITY_QC_RUNPOD_POLL_INTERVAL_SECONDS": "0.1",
            "CONTINUITY_QC_RUNPOD_MAX_RETRIES": "2",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        for target, replacement in (("time.monotonic", self.clock.monotonic),
                                    ("time.sleep", self.clock.sleep)):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http_patcher = patch.object(runpod_transport, "_open")
        self.http = self.http_patcher.start()
        self.addCleanup(self.http_patcher.stop)
        self.shots = [Shot("one", Frame("a")), Shot("two", Frame("b"))]

    def checker(self, **config):
        return ContinuityQC(config=ContinuityConfig(backend="runpod", **config))

    def assert_skipped(self, report):
        self.assertEqual(report.status, "skipped")
        self.assertFalse(report.accepted)
        self.assertEqual(report.pairs, ())
        self.assertTrue(report.reason)
        self.assertNotIn("runpod-offline-test-key", report.reason)

    def urls(self):
        return [call.args[0].full_url for call in self.http.call_args_list]

    def test_runsync_success_encodes_ordered_frames_and_scores_locally(self):
        self.http.return_value = response(completed())
        report = self.checker().score(self.shots)
        self.assertEqual(report.status, "completed")
        self.assertTrue(report.accepted)
        self.assertEqual(report.pairs[0].face_identity.status, "not configured")
        self.assertEqual(report.pairs[0].siglip_similarity, 0.92)
        request = self.http.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.runpod.ai/v2/endpoint-test/runsync")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)["input"]
        self.assertEqual(body["models"], ["siglip", "dinov2"])
        self.assertEqual(body["pairs"], [["one", "two"]])
        self.assertEqual(body["return"], ["similarities"])
        self.assertEqual([frame["id"] for frame in body["frames"]], ["one", "two"])
        self.assertEqual(base64.b64decode(body["frames"][0]["b64"]), b"fixture-frame-a")

    def test_backend_defaults_local_and_env_can_choose_runpod(self):
        self.assertEqual(ContinuityConfig().backend, "local")
        with patch.dict("os.environ", {"CONTINUITY_QC_BACKEND": "runpod"}):
            self.http.return_value = response(completed())
            self.assertTrue(ContinuityQC().score(self.shots).accepted)
        self.http.assert_called_once()

    def test_pending_runsync_polls_same_id_without_duplicate_submission(self):
        for status in ("IN_PROGRESS", "IN_QUEUE"):
            with self.subTest(status=status):
                self.http.reset_mock()
                self.http.side_effect = [response({"id": "job-1", "status": status}),
                                         response({"id": "job-1", "status": "IN_PROGRESS"}),
                                         response(completed())]
                self.assertTrue(self.checker().score(self.shots).accepted)
                self.assertEqual(self.urls(), [
                    "https://api.runpod.ai/v2/endpoint-test/runsync",
                    "https://api.runpod.ai/v2/endpoint-test/status/job-1",
                    "https://api.runpod.ai/v2/endpoint-test/status/job-1",
                ])

    def test_pending_runsync_without_id_submits_run_then_polls(self):
        self.http.side_effect = [response({"status": "IN_QUEUE"}),
                                 response({"id": "job-1", "status": "IN_QUEUE"}),
                                 response(completed())]
        self.assertTrue(self.checker().score(self.shots).accepted)
        self.assertEqual([url.rsplit("/", 1)[-1] for url in self.urls()],
                         ["runsync", "run", "job-1"])

    def test_runsync_timeout_falls_back_to_run_within_same_deadline(self):
        self.http.side_effect = [TimeoutError("private-detail"),
                                 response({"id": "job-1", "status": "IN_QUEUE"}),
                                 response(completed())]
        self.assertTrue(self.checker().score(self.shots).accepted)
        self.assertIn("https://api.runpod.ai/v2/endpoint-test/run", self.urls())

    def test_urlerror_timeout_also_falls_back(self):
        self.http.side_effect = [URLError(TimeoutError("private-detail")),
                                 response({"id": "job-1", "status": "IN_QUEUE"}),
                                 response(completed())]
        self.assertTrue(self.checker().score(self.shots).accepted)

    def test_total_deadline_returns_skipped_instead_of_hanging(self):
        self.http.side_effect = lambda *args, **kwargs: response(
            {"id": "job-1", "status": "IN_PROGRESS"})
        with patch.dict("os.environ", {"CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "0.25"}):
            self.assert_skipped(self.checker().score(self.shots))
        self.assertLessEqual(self.clock.now, 0.25)
        self.assertTrue(all(call.kwargs["timeout"] <= 0.25
                            for call in self.http.call_args_list))

    def test_request_that_completes_after_deadline_is_skipped(self):
        def late_response(*args, **kwargs):
            self.clock.now += 11.0
            return response(completed())
        self.http.side_effect = late_response
        self.assert_skipped(self.checker().score(self.shots))
        self.http.assert_called_once()

    def test_429_and_503_have_bounded_retry_then_success(self):
        for status in (429, 503):
            with self.subTest(status=status):
                self.http.reset_mock()
                self.http.side_effect = [HTTPError("https://example.test", status,
                                                   "private-detail", {}, None),
                                         response(completed())]
                self.assertTrue(self.checker().score(self.shots).accepted)
                self.assertEqual(self.http.call_count, 2)
                self.assertGreater(self.clock.now, 0)

    def test_network_error_has_bounded_retries(self):
        self.http.side_effect = URLError("private-detail")
        self.assert_skipped(self.checker().score(self.shots))
        self.assertEqual(self.http.call_count, 3)

    def test_401_validation_400_and_redirect_are_not_retried(self):
        for status in (401, 400, 302):
            with self.subTest(status=status):
                self.http.reset_mock()
                self.http.side_effect = HTTPError("https://example.test", status,
                                                   "runpod-offline-test-key", {}, None)
                self.assert_skipped(self.checker().score(self.shots))
                self.http.assert_called_once()

    def test_missing_credentials_or_endpoint_is_skipped_without_http(self):
        for name in ("RUNPOD_API_KEY", "CONTINUITY_QC_RUNPOD_ENDPOINT_ID"):
            with self.subTest(name=name), patch.dict("os.environ", {name: ""}):
                self.assert_skipped(self.checker().score(self.shots))
        self.http.assert_not_called()

    def test_invalid_backend_or_network_config_is_fail_soft(self):
        for env in ({"CONTINUITY_QC_BACKEND": "other"},
                    {"CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "nan"},
                    {"CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "0"},
                    {"CONTINUITY_QC_RUNPOD_MAX_RETRIES": "-1"},
                    {"CONTINUITY_QC_RUNPOD_ENDPOINT_ID": "../other"}):
            with self.subTest(env=env), patch.dict("os.environ", env):
                checker = ContinuityQC() if "CONTINUITY_QC_BACKEND" in env else self.checker()
                self.assert_skipped(checker.score(self.shots))
        self.http.assert_not_called()

    def test_invalid_frames_or_duplicate_ids_skip(self):
        for shots in ([Shot("one", object()), Shot("two", object())],
                      [Shot("one", Frame("a")), Shot("one", Frame("b"))],
                      []):
            with self.subTest(shots=shots):
                self.assert_skipped(self.checker().score(shots))
        self.http.assert_not_called()

    def test_malformed_json_and_job_envelope_skip(self):
        for payload in (b"not-json", b"[]", b"{}",
                        json.dumps({"status": "COMPLETED", "output": "wrong"}).encode(),
                        json.dumps({"status": "UNKNOWN", "id": "job-1"}).encode()):
            with self.subTest(payload=payload):
                self.http.return_value = io.BytesIO(payload)
                self.assert_skipped(self.checker().score(self.shots))

    def test_failed_terminal_job_or_worker_error_skips(self):
        for status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            with self.subTest(status=status):
                self.http.return_value = response({"id": "job-1", "status": status,
                                                   "error": "runpod-offline-test-key"})
                self.assert_skipped(self.checker().score(self.shots))
        self.http.return_value = response({"status": "COMPLETED", "output": {
            "error": {"code": "invalid_input", "message": "private-detail"}}})
        self.assert_skipped(self.checker().score(self.shots))

    def test_bad_similarity_types_nonfinite_and_out_of_range_skip(self):
        for value in ("0.92", True, None, float("nan"), float("inf"), 1.01, -1.01):
            with self.subTest(value=value):
                self.http.return_value = response(completed(siglip=value))
                self.assert_skipped(self.checker().score(self.shots))

    def test_missing_extra_or_reordered_pairs_and_model_mismatch_skip(self):
        payloads = [completed(pairs=[]), completed(pairs=[
            {"before": "two", "after": "one", "similarities": {"siglip": 1, "dinov2": 1}}]),
            completed(pairs=completed()["output"]["pairs"] * 2)]
        wrong_model = completed()
        wrong_model["output"]["models"]["dinov2"] = DINOV3_MODEL
        payloads.append(wrong_model)
        missing_similarity = completed()
        del missing_similarity["output"]["pairs"][0]["similarities"]["dinov2"]
        payloads.append(missing_similarity)
        for payload in payloads:
            with self.subTest(payload=payload):
                self.http.return_value = response(payload)
                self.assert_skipped(self.checker().score(self.shots))

    def test_transport_response_and_request_size_are_bounded(self):
        self.http.return_value = io.BytesIO(b" " * (10 * 1024 * 1024 + 1))
        self.assert_skipped(self.checker().score(self.shots))
        self.http.reset_mock()
        huge = Frame("a" * (10 * 1024 * 1024))
        self.assert_skipped(self.checker().score([Shot("one", huge), self.shots[1]]))
        self.http.assert_not_called()

    def test_local_and_remote_decision_parity_including_veto_and_custom_rules(self):
        for siglip, dino, config in ((0.92, 0.74, {}), (0.55, 0.11, {}),
                                    (1.0, 0.0, {}), (0.92, 0.74, {"rule": "legacy_min"}),
                                    (0.7, 0.3, {"acceptance_threshold": 0.8,
                                                "veto_threshold": 0.4})):
            with self.subTest(siglip=siglip, dino=dino, config=config):
                self.http.return_value = response(completed(siglip, dino))
                remote = self.checker(**config).score(self.shots)
                local = ContinuityQC(siglip=Embedder(SIGLIP_MODEL, siglip),
                                     dino=Embedder(DINO_MODEL, dino),
                                     config=ContinuityConfig(backend="local", **config)).score(self.shots)
                self.assertEqual(remote.accepted, local.accepted)
                self.assertAlmostEqual(remote.pairs[0].siglip_score, local.pairs[0].siglip_score)
                self.assertAlmostEqual(remote.pairs[0].dino_score, local.pairs[0].dino_score)
                self.assertEqual(remote.rule, local.rule)
                self.assertEqual(remote.acceptance_threshold, local.acceptance_threshold)

    def test_dinov3_opt_in_uses_matching_remote_model_and_calibration(self):
        self.http.return_value = response(completed(0.92, 0.8, dino_key="dinov3"))
        remote = self.checker(enable_dinov3=True).score(self.shots)
        local = ContinuityQC(siglip=Embedder(SIGLIP_MODEL, 0.92),
                             dino=Embedder(DINOV3_MODEL, 0.8),
                             config=ContinuityConfig(enable_dinov3=True)).score(self.shots)
        self.assertEqual(remote.accepted, local.accepted)
        self.assertEqual(remote.dino_model, DINOV3_MODEL)
        self.assertAlmostEqual(remote.pairs[0].dino_score, local.pairs[0].dino_score)
        self.assertEqual(json.loads(self.http.call_args.args[0].data)["input"]["models"],
                         ["siglip", "dinov3"])

    def test_three_shots_keep_adjacent_order_and_face_adapter(self):
        self.shots.append(Shot("three", Frame("c")))
        self.http.return_value = response(completed(pairs=[
            {"before": "one", "after": "two", "similarities": {"siglip": 1, "dinov2": 1}},
            {"before": "two", "after": "three", "similarities": {"siglip": 0, "dinov2": 0}},
        ]))
        face = Mock()
        face.compare.return_value = FaceIdentityResult("configured", 0.9)
        report = ContinuityQC(config=ContinuityConfig(backend="runpod"), face_identity=face).score(self.shots)
        self.assertEqual([pair.accepted for pair in report.pairs], [True, False])
        self.assertEqual([pair.face_identity.similarity for pair in report.pairs], [0.9, 0.9])
        self.assertEqual(face.compare.call_count, 2)

    def test_unexpected_adapter_exception_is_sanitized_and_fail_soft(self):
        self.http.side_effect = RuntimeError("runpod-offline-test-key")
        self.assert_skipped(self.checker().score(self.shots))

    def test_encoding_counts_towards_total_deadline(self):
        class SlowFrame(Frame):
            def save(frame, stream, *, format):
                self.clock.now += 11
                super().save(stream, format=format)
        self.assert_skipped(self.checker().score([Shot("one", SlowFrame("a")), self.shots[1]]))
        self.http.assert_not_called()

    def test_too_many_frames_skip_before_http(self):
        shots = [Shot(str(index), Frame("a")) for index in range(9)]
        self.assert_skipped(self.checker().score(shots))
        self.http.assert_not_called()

    def test_invalid_worker_ids_skip_before_http(self):
        for value in ("contains spaces", "unicodé", "slash/path"):
            with self.subTest(value=value):
                self.assert_skipped(self.checker().score([Shot(value, Frame("a")), self.shots[1]]))
        self.http.assert_not_called()

    def test_slow_open_or_read_cannot_block_past_total_deadline(self):
        for phase in ("open", "read"):
            with self.subTest(phase=phase):
                release = threading.Event()
                entered = threading.Event()
                exited = threading.Event()

                class SlowResponse(io.BytesIO):
                    def read(stream, size=-1):
                        if phase == "read":
                            entered.set()
                            release.wait(0.5)
                        return super().read(size)

                    def close(stream):
                        super().close()
                        exited.set()

                def slow_open(*args, **kwargs):
                    if phase == "open":
                        entered.set()
                        release.wait(0.5)
                    return SlowResponse(json.dumps(completed()).encode())

                self.http.side_effect = slow_open
                self.http.reset_mock()
                with patch("time.monotonic", time.perf_counter), patch("time.sleep", lambda _: None), patch.dict(
                    "os.environ", {"CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "0.04"}
                ):
                    started = time.perf_counter()
                    try:
                        report = self.checker().score(self.shots)
                        elapsed = time.perf_counter() - started
                        self.assert_skipped(report)
                        self.assertTrue(entered.is_set())
                        self.assertLess(elapsed, 0.2)
                        self.http.assert_called_once()
                    finally:
                        release.set()
                        self.assertTrue(exited.wait(1.0))

    def test_delayed_daemon_keeps_the_opener_captured_before_start(self):
        release, exited = threading.Event(), threading.Event()
        thread_class = threading.Thread

        def delayed_thread(*, target, daemon, name):
            def delayed():
                release.wait(1.0)
                try:
                    target()
                finally:
                    exited.set()
            return thread_class(target=delayed, daemon=daemon, name=name)

        self.http.return_value = response(completed())
        with patch("time.monotonic", time.perf_counter), patch.dict(
            "os.environ", {"CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS": "0.02"}
        ), patch.object(runpod_transport.threading, "Thread", side_effect=delayed_thread):
            try:
                self.assert_skipped(self.checker().score(self.shots))
                with patch.object(runpod_transport, "_open") as restored_opener:
                    release.set()
                    self.assertTrue(exited.wait(1.0))
                    restored_opener.assert_not_called()
                self.http.assert_called_once()
            finally:
                release.set()
                self.assertTrue(exited.wait(1.0))

    def test_local_backend_never_dispatches_http(self):
        local = ContinuityQC(siglip=Embedder(SIGLIP_MODEL, 0.92),
                             dino=Embedder(DINO_MODEL, 0.74),
                             config=ContinuityConfig(backend="local"))
        self.assertTrue(local.score(self.shots).accepted)
        self.http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
