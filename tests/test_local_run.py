from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from server import config, secrets


FAKE_VALUE = "fake-private-value-do-not-display"


class LocalLauncherTests(unittest.TestCase):
    def setUp(self):
        from scripts import local_env

        self.local = local_env
        self.env = patch.dict(
            os.environ, {"AWS_PROFILE": "satya", "AWS_REGION": "us-east-1"}, clear=True
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        secrets.clear_secrets_cache()
        self.addCleanup(secrets.clear_secrets_cache)

    def test_check_only_reports_names_flags_never_values(self):
        client = Mock()
        client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "HF_TOKEN": FAKE_VALUE,
                    "ANTHROPIC_API_KEY": FAKE_VALUE,
                    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": FAKE_VALUE,
                    "CLERK_SECRET_KEY": FAKE_VALUE,
                    "FAL_DRY_RUN": "false",
                }
            )
        }
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("server.secrets.boto3.client", return_value=client),
            patch.object(config, "load_dotenv"),
            patch.object(self.local, "check_requirements"),
            patch.object(self.local, "check_identity"),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(self.local.main(["check", "--print-keys"]), 0)
        client.get_secret_value.assert_called_once_with(SecretId="renderhaus/app")
        self.assertIn("HF_TOKEN", output.getvalue())
        self.assertIn("FAL_DRY_RUN -> true", output.getvalue())
        self.assertNotIn(FAKE_VALUE, output.getvalue() + errors.getvalue())

    def test_aws_errors_are_actionable_and_never_echo_exception(self):
        failures = [
            (NoCredentialsError(), "NoCredentialsError", "aws configure"),
            (ProfileNotFound(profile=FAKE_VALUE), "ProfileNotFound", "AWS_PROFILE"),
            (
                ClientError(
                    {"Error": {"Code": "AccessDeniedException", "Message": FAKE_VALUE}},
                    "GetSecretValue",
                ),
                "AccessDeniedException",
                "docs/LOCAL_RUN.md",
            ),
            (
                ClientError(
                    {"Error": {"Code": "ExpiredTokenException", "Message": FAKE_VALUE}},
                    "GetSecretValue",
                ),
                "ExpiredTokenException",
                'aws sso login --profile "${AWS_PROFILE:-default}"',
            ),
            (
                ClientError(
                    {"Error": {"Code": "ResourceNotFoundException", "Message": FAKE_VALUE}},
                    "GetSecretValue",
                ),
                "ResourceNotFoundException",
                "AWS_REGION",
            ),
            (ValueError(FAKE_VALUE), "InvalidConfiguration", "docs/LOCAL_RUN.md"),
        ]
        for error, code, action in failures:
            with self.subTest(code=code):
                output = io.StringIO()
                with (
                    patch.object(self.local, "check_requirements"),
                    patch.object(self.local, "check_identity", side_effect=error),
                    contextlib.redirect_stderr(output),
                ):
                    self.assertNotEqual(self.local.main(["check"]), 0)
                self.assertIn(code, output.getvalue())
                self.assertIn(action, output.getvalue())
                self.assertNotIn(FAKE_VALUE, output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())

    def test_identity_cli_captures_output_and_sdk_fallback(self):
        with (
            patch.object(self.local.shutil, "which", return_value="/fake/aws"),
            patch.object(self.local.subprocess, "run", return_value=Mock(returncode=0)) as run,
        ):
            self.local.check_identity()
        self.assertEqual(
            run.call_args.args[0],
            ["/fake/aws", "sts", "get-caller-identity", "--region", "us-east-1"],
        )
        self.assertTrue(run.call_args.kwargs["capture_output"])
        with (
            patch.object(self.local.shutil, "which", return_value=None),
            patch.object(self.local.boto3, "client") as client,
        ):
            self.local.check_identity()
        client.assert_called_once_with("sts", region_name="us-east-1")
        client.return_value.get_caller_identity.assert_called_once_with()

    def test_studio_env_contains_only_clerk_keys_and_local_origins(self):
        from server.local_profile import studio_environment

        env = {
            "PATH": "/fake/bin",
            "HOME": "/fake/home",
            "HF_TOKEN": FAKE_VALUE,
            "AWS_SECRET_ACCESS_KEY": FAKE_VALUE,
            "CLERK_SECRET_KEY": "fake-clerk-private",
            "ANTHROPIC_API_KEY": FAKE_VALUE,
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "fake-public",
            "STUDIO_API_ORIGIN": "https://production.example",
            "NODE_OPTIONS": FAKE_VALUE,
        }
        child = studio_environment(env)
        self.assertEqual(child["NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"], "fake-public")
        self.assertEqual(child["CLERK_SECRET_KEY"], "fake-clerk-private")
        self.assertEqual(child["STUDIO_API_ORIGIN"], "http://127.0.0.1:8000")
        self.assertEqual(child["NODE_ENV"], "development")
        self.assertNotIn(FAKE_VALUE, str(child))
        self.assertEqual(child["PATH"], env["PATH"])

    def test_secret_errors_and_malformed_payloads_do_not_leak(self):
        for error in (
            ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": FAKE_VALUE}},
                "GetSecretValue",
            ),
            json.JSONDecodeError(FAKE_VALUE, FAKE_VALUE, 0),
        ):
            output = io.StringIO()
            with (
                patch.object(self.local, "check_requirements"),
                patch.object(self.local, "check_identity"),
                patch.object(self.local, "fetch_secret_map", side_effect=error),
                contextlib.redirect_stderr(output),
            ):
                self.assertEqual(self.local.main(["check"]), 1)
            self.assertNotIn(FAKE_VALUE, output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())

    def test_bad_secret_key_is_rejected_before_application(self):
        output = io.StringIO()
        with (
            patch.object(self.local, "check_requirements"),
            patch.object(self.local, "check_identity"),
            patch.object(self.local, "fetch_secret_map", return_value={"fake-bad-key": FAKE_VALUE}),
            contextlib.redirect_stderr(output),
        ):
            self.assertEqual(self.local.main(["check"]), 1)
        self.assertIn("InvalidSecret", output.getvalue())
        self.assertNotIn(FAKE_VALUE, output.getvalue())
        self.assertNotIn("fake-bad-key", os.environ)

    def test_cli_error_output_is_captured_and_redacted(self):
        with (
            patch.object(self.local, "check_requirements"),
            patch.object(self.local.shutil, "which", return_value="/fake/aws"),
            patch.object(
                self.local.subprocess,
                "run",
                return_value=Mock(
                    returncode=1, stderr=f"An error occurred (ExpiredToken) {FAKE_VALUE}"
                ),
            ) as run,
            contextlib.redirect_stderr(io.StringIO()) as output,
        ):
            self.assertEqual(self.local.main(["check"]), 1)
        self.assertNotIn(FAKE_VALUE, output.getvalue())
        self.assertIn("ExpiredToken", output.getvalue())
        self.assertEqual(
            run.call_args.args[0],
            ["/fake/aws", "sts", "get-caller-identity", "--region", "us-east-1"],
        )

    def test_preflight_requires_node_and_installed_studio_without_aws(self):
        with patch.object(self.local.shutil, "which", return_value=None):
            with self.assertRaisesRegex(self.local.LocalRunError, "MissingNode"):
                self.local.check_requirements()

        with (
            patch.object(self.local.shutil, "which", return_value="/fake/node"),
            patch.object(
                self.local.subprocess, "run", return_value=Mock(returncode=0, stdout="v20.8.1\n")
            ),
        ):
            with self.assertRaisesRegex(self.local.LocalRunError, "NodeVersion"):
                self.local.check_requirements()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(self.local, "ROOT", Path(folder)),
            patch.object(self.local.shutil, "which", return_value="/fake/node"),
            patch.object(
                self.local.subprocess, "run", return_value=Mock(returncode=0, stdout="v22.0.0\n")
            ),
        ):
            with self.assertRaisesRegex(self.local.LocalRunError, "MissingNodeModules"):
                self.local.check_requirements()

    def test_aws_cli_common_errors_are_mapped_without_raw_output(self):
        for message, code in (
            ("Unable to locate credentials", "NoCredentialsError"),
            ("The config profile could not be found", "ProfileNotFound"),
            ("Error loading SSO Token", "SSOUnauthorizedTokenError"),
            ("Could not connect to the endpoint URL", "EndpointConnectionError"),
        ):
            with (
                self.subTest(code=code),
                patch.object(self.local, "check_requirements"),
                patch.object(self.local.shutil, "which", return_value="/fake/aws"),
                patch.object(
                    self.local.subprocess,
                    "run",
                    return_value=Mock(returncode=1, stderr=message + FAKE_VALUE),
                ),
                contextlib.redirect_stderr(io.StringIO()) as output,
            ):
                os.environ["AWS_PROFILE"] = FAKE_VALUE
                self.assertEqual(self.local.main(["check"]), 1)
                self.assertIn(code, output.getvalue())
                self.assertNotIn(FAKE_VALUE, output.getvalue())

    def test_preflight_blocks_next_dotenv_files_without_reading_values(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(self.local, "ROOT", Path(folder)),
            patch.object(self.local.shutil, "which", return_value="/fake/node"),
            patch.object(
                self.local.subprocess, "run", return_value=Mock(returncode=0, stdout="v22.0.0\n")
            ),
        ):
            root = Path(folder)
            (root / "studio/node_modules/next").mkdir(parents=True)
            (root / "studio/.env.local").write_text(FAKE_VALUE)
            with self.assertRaisesRegex(self.local.LocalRunError, "StudioEnvFile") as error:
                self.local.check_requirements()
            self.assertNotIn(FAKE_VALUE, str(error.exception))

    def test_backend_import_happens_after_profile_loading(self):
        values = {
            "CLERK_SECRET_KEY": FAKE_VALUE,
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "fake-public",
            "RENDERHAUS_STUDIO_DATABASE": "/fake/production.sqlite3",
            "FAL_DRY_RUN": "false",
        }
        observed = {}

        def run_module(module, **kwargs):
            observed.update(
                module=module,
                profile=os.environ["RENDERHAUS_LOCAL_PROFILE"],
                database=os.environ["RENDERHAUS_STUDIO_DATABASE"],
                dry=os.environ["FAL_DRY_RUN"],
            )

        with (
            patch.object(self.local, "check_requirements"),
            patch.object(self.local, "check_identity"),
            patch.object(self.local, "port_open", return_value=False),
            patch.object(config, "load_dotenv"),
            patch("server.secrets.fetch_secret_map", return_value=values),
            patch.object(self.local, "fetch_secret_map", return_value=values),
            patch.object(self.local.runpy, "run_module", side_effect=run_module),
        ):
            self.assertEqual(self.local.main(["backend"]), 0)
        self.assertEqual(
            observed,
            {
                "module": "server.app",
                "profile": "local",
                "database": ".renderhaus/studio.sqlite3",
                "dry": "true",
            },
        )

    def test_up_cleans_started_children_when_later_spawn_fails(self):
        child = Mock(pid=43210)
        child.poll.return_value = None
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(self.local, "ROOT", Path(folder)),
            patch.object(self.local, "check_ports"),
            patch.object(self.local, "port_open", return_value=True),
            patch.object(self.local.subprocess, "Popen", side_effect=[child, OSError(FAKE_VALUE)]),
            patch.object(self.local.os, "killpg") as kill,
            patch.object(self.local, "process_group_alive", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(OSError):
                self.local.run_all({"AWS_PROFILE": "satya"})
            self.assertEqual(
                (Path(folder) / ".renderhaus/logs/gateway.log").stat().st_mode & 0o777, 0o600
            )
        kill.assert_called_once_with(43210, self.local.signal.SIGTERM)
        child.wait.assert_called_once()

    def test_invalid_local_opt_in_fails_before_any_aws_request(self):
        os.environ["RENDERHAUS_LOCAL_LIVE_PROVIDERS"] = FAKE_VALUE
        with (
            patch.object(self.local, "check_requirements"),
            patch.object(self.local, "check_identity") as identity,
            patch.object(self.local, "fetch_secret_map") as fetch,
            contextlib.redirect_stderr(io.StringIO()) as output,
        ):
            self.assertEqual(self.local.main(["check"]), 1)
        identity.assert_not_called()
        fetch.assert_not_called()
        self.assertNotIn(FAKE_VALUE, output.getvalue())

    def test_shutdown_also_stops_descendants_after_leader_exits(self):
        child = Mock(pid=43210)
        child.poll.return_value = 1
        with (
            patch.object(self.local.os, "killpg") as kill,
            patch.object(self.local, "process_group_alive", return_value=False),
        ):
            self.local.stop_children([child])
        kill.assert_called_once_with(43210, self.local.signal.SIGTERM)

    def test_shutdown_escalates_surviving_process_groups(self):
        child = Mock(pid=43210)
        child.poll.return_value = 1
        with (
            patch.object(self.local.os, "killpg") as kill,
            patch.object(self.local, "process_group_alive", return_value=True),
            patch.object(self.local.time, "monotonic", side_effect=[0, 11]),
        ):
            self.local.stop_children([child])
        self.assertEqual(
            kill.call_args_list,
            [
                unittest.mock.call(43210, self.local.signal.SIGTERM),
                unittest.mock.call(43210, self.local.signal.SIGKILL),
            ],
        )

    def test_status_never_contacts_aws(self):
        from scripts import local_env

        with (
            patch.object(local_env, "check_identity") as identity,
            patch.object(local_env, "load_environment") as load,
            patch.object(local_env, "port_open", return_value=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(local_env.main(["status"]), 0)
        identity.assert_not_called()
        load.assert_not_called()

    def test_wrapper_missing_venv_is_actionable_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            script = root / "scripts/run_local.sh"
            script.write_bytes((config.ROOT / "scripts/run_local.sh").read_bytes())
            result = subprocess.run(["bash", str(script), "check"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("make setup", result.stderr)

    def test_new_files_have_no_key_shaped_literals_and_local_files_are_ignored(self):
        for name in (
            "scripts/run_local.sh",
            "scripts/local_env.py",
            "server/local_profile.py",
            "docs/LOCAL_RUN.md",
        ):
            content = (config.ROOT / name).read_text()
            self.assertFalse(
                re.search(r"(?:sk-|pk_(?:live|test)_)[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16}", content),
                name,
            )
        paths = [".env.local", "studio/.env.local", ".renderhaus/logs/backend.log"]
        result = subprocess.run(
            ["git", "check-ignore", *paths], cwd=config.ROOT, capture_output=True, text=True
        )
        self.assertEqual(set(result.stdout.splitlines()), set(paths))
