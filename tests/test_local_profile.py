from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from server import config, secrets


FAKE_VALUE = "fake-private-value-do-not-display"


class LocalProfileTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.dotenv = patch.object(config, "load_dotenv")
        self.dotenv.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.dotenv.stop)
        secrets.clear_secrets_cache()
        self.addCleanup(secrets.clear_secrets_cache)

    def load(self, values):
        with patch("server.secrets.fetch_secret_map", return_value=values):
            config.load_local_env()

    def test_profile_unset_preserves_secret_precedence_and_defaults(self):
        os.environ.update(RENDERHAUS_SECRETS_NAME="fake", FAL_DRY_RUN="true")
        values = {
            "FAL_DRY_RUN": "false",
            "AGENT_MODEL": "openai:production",
            "AGENTCORE_GATEWAY_URL": "https://production.example/mcp",
            "AWS_S3_BUCKET": "production",
            "APP_URL": "https://production.example",
        }
        self.load(values)
        self.assertEqual(
            dict(os.environ),
            {
                "RENDERHAUS_SECRETS_NAME": "fake",
                **values,
                **{k: v for k, v in config.DEFAULT_ENV.items() if k not in values},
            },
        )

    def test_local_profile_wins_after_secret_and_repeated_load(self):
        from server.local_profile import DRY_RUN_FLAGS

        os.environ.update(
            RENDERHAUS_LOCAL_PROFILE="local",
            RENDERHAUS_SECRETS_NAME="fake",
            AWS_PROFILE="satya",
            AWS_REGION="us-east-1",
        )
        values = {key: "false" for key in DRY_RUN_FLAGS}
        values.update(
            ANTHROPIC_API_KEY=FAKE_VALUE,
            OPENAI_API_KEY=FAKE_VALUE,
            HF_TOKEN=FAKE_VALUE,
            AGENTCORE_GATEWAY_URL="https://production.example/mcp",
            AGENTCORE_GATEWAY_AUTH_TOKEN=FAKE_VALUE,
            AGENTCORE_RUNTIME_ARN="production",
            AGENTCORE_DEV_URL="https://production.example",
            APP_URL="https://production.example",
            AWS_S3_BUCKET="production",
            PROVIDER_INPUT_BUCKET="production",
            REMOTION_APP_BUCKET_NAME="production",
            NODE_ENV="production",
            AGENT_MODEL="openai:production",
            STRIPE_SECRET_KEY=FAKE_VALUE,
            STRIPE_WEBHOOK_SECRET=FAKE_VALUE,
            RENDERHAUS_LOCAL_PROFILE="production",
            RENDERHAUS_LOCAL_LIVE_PROVIDERS="FAL",
            AWS_REGION="wrong-region",
        )
        for _ in range(2):
            self.load(values)
            self.assertTrue(all(os.environ[key] == "true" for key in DRY_RUN_FLAGS))
            self.assertEqual(os.environ["AGENTCORE_GATEWAY_URL"], "http://127.0.0.1:8765/mcp")
            self.assertEqual(os.environ["AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP"], "true")
            for key in (
                "AGENTCORE_RUNTIME_ARN",
                "AGENTCORE_DEV_URL",
                "AGENTCORE_GATEWAY_AUTH_TOKEN",
                "AWS_S3_BUCKET",
                "PROVIDER_INPUT_BUCKET",
                "REMOTION_APP_BUCKET_NAME",
                "STRIPE_SECRET_KEY",
                "STRIPE_WEBHOOK_SECRET",
            ):
                self.assertFalse(os.environ.get(key))
            self.assertEqual(os.environ["APP_URL"], "http://localhost:5174")
            self.assertEqual(os.environ["NODE_ENV"], "development")
            self.assertEqual(os.environ["AWS_REGION"], "us-east-1")
            self.assertEqual(os.environ["AWS_PROFILE"], "satya")
            self.assertEqual(os.environ["RENDERHAUS_AGENT_MODEL"], "anthropic:claude-sonnet-5-5")
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], FAKE_VALUE)
            self.assertEqual(os.environ["OPENAI_API_KEY"], FAKE_VALUE)

    def test_only_explicit_local_provider_opt_in_enables_live(self):
        from server.local_profile import DRY_RUN_FLAGS

        os.environ.update(
            RENDERHAUS_LOCAL_PROFILE="local",
            RENDERHAUS_SECRETS_NAME="fake",
            RENDERHAUS_LOCAL_LIVE_PROVIDERS="FAL, TOPAZ",
            RENDERHAUS_AGENT_MODEL="anthropic:chosen",
        )
        with self.assertLogs("server.local_profile", level="WARNING") as logs:
            self.load({"FAL_DRY_RUN": "true", "TOPAZ_DRY_RUN": "true", "HF_TOKEN": FAKE_VALUE})
        self.assertEqual(os.environ["FAL_DRY_RUN"], "false")
        self.assertEqual(os.environ["TOPAZ_DRY_RUN"], "false")
        self.assertTrue(
            all(
                os.environ[k] == "true"
                for k in DRY_RUN_FLAGS
                if k not in {"FAL_DRY_RUN", "TOPAZ_DRY_RUN"}
            )
        )
        self.assertEqual(os.environ["RENDERHAUS_AGENT_MODEL"], "anthropic:chosen")
        self.assertNotIn(FAKE_VALUE, " ".join(logs.output))
        self.assertIn("LIVE", " ".join(logs.output))

    def test_bad_opt_in_fails_before_secret_fetch_without_echoing_input(self):
        os.environ.update(
            RENDERHAUS_LOCAL_PROFILE="local",
            RENDERHAUS_SECRETS_NAME="fake",
            RENDERHAUS_LOCAL_LIVE_PROVIDERS=FAKE_VALUE,
        )
        with patch("server.secrets.fetch_secret_map") as fetch:
            with self.assertRaisesRegex(ValueError, "InvalidLocalProvider") as error:
                config.load_local_env()
        fetch.assert_not_called()
        self.assertNotIn(FAKE_VALUE, str(error.exception))

    def test_all_repo_flags_are_covered(self):
        from server.local_profile import DRY_RUN_FLAGS

        found = set()
        for directory in ("agent", "providers", "server", "scripts"):
            for path in config.ROOT.joinpath(directory).rglob("*.py"):
                found.update(re.findall(r"\b[A-Z][A-Z0-9_]*_DRY_RUN\b", path.read_text()))
        self.assertFalse(found - set(DRY_RUN_FLAGS), found - set(DRY_RUN_FLAGS))

    def test_secret_cannot_change_identity_files_or_process_bootstrap(self):
        os.environ.update(
            RENDERHAUS_LOCAL_PROFILE="local",
            RENDERHAUS_SECRETS_NAME="fake",
            AWS_DEFAULT_PROFILE="satya",
            AWS_CONFIG_FILE="/fake/own-config",
            HOME="/fake/own-home",
            PATH="/fake/own-bin",
        )
        self.load(
            {
                key: FAKE_VALUE
                for key in (
                    "AWS_DEFAULT_PROFILE",
                    "AWS_CONFIG_FILE",
                    "AWS_SHARED_CREDENTIALS_FILE",
                    "AWS_ENDPOINT_URL",
                    "HOME",
                    "PATH",
                    "PYTHONPATH",
                    "PYTHONHOME",
                    "NODE_OPTIONS",
                )
            }
        )
        for key, expected in {
            "AWS_DEFAULT_PROFILE": "satya",
            "AWS_CONFIG_FILE": "/fake/own-config",
            "HOME": "/fake/own-home",
            "PATH": "/fake/own-bin",
        }.items():
            self.assertEqual(os.environ[key], expected)
        for key in (
            "AWS_SHARED_CREDENTIALS_FILE",
            "AWS_ENDPOINT_URL",
            "PYTHONPATH",
            "PYTHONHOME",
            "NODE_OPTIONS",
            "AWS_PROFILE",
        ):
            self.assertNotIn(key, os.environ)


class LocalAssetsTests(unittest.TestCase):
    def test_local_startup_and_legacy_session_never_use_aws(self):
        from server import assets

        with (
            patch.dict(os.environ, {"RENDERHAUS_LOCAL_PROFILE": "local"}),
            patch.object(assets.boto3.session, "Session") as session,
            tempfile.TemporaryDirectory() as folder,
            patch.object(assets, "CACHE_DIR", Path(folder)),
        ):
            assets.init_assets_db()
            with self.assertRaisesRegex(RuntimeError, "Use Studio assets"):
                assets._session()
        session.assert_not_called()
        assets._session.cache_clear()

    def test_deployed_assets_initialization_is_unchanged(self):
        from server import assets

        with (
            patch.dict(os.environ, {"AWS_S3_BUCKET": "fake-bucket"}, clear=True),
            patch.object(assets, "_ensure_dynamodb_table") as table,
            patch.object(assets, "_ensure_s3_bucket") as bucket,
            tempfile.TemporaryDirectory() as folder,
            patch.object(assets, "CACHE_DIR", Path(folder)),
        ):
            assets.init_assets_db()
        table.assert_called_once_with()
        bucket.assert_called_once_with()
