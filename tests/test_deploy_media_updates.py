import unittest
from unittest.mock import MagicMock, patch

from providers.catalog import get_provider
from scripts import deploy_media_updates as deploy


class MediaDeploymentPreflightTests(unittest.TestCase):
    def test_missing_target_on_any_page_fails_before_all_mutations(self):
        for missing in ("mureka", "remotion"):
            present = "remotion" if missing == "mureka" else "mureka"
            control, lam = MagicMock(), MagicMock()
            control.list_gateway_targets.side_effect = [
                {"items": [], "nextToken": "page-2"},
                {"items": [{"name": get_provider(present).target_name, "targetId": "present"}]},
            ]
            with self.subTest(missing=missing), patch.object(deploy, "load_local_env"), \
                 patch.object(deploy.boto3, "client", side_effect=[lam, control]), \
                 patch.object(deploy, "_find_gateway", return_value={"gatewayId": "gateway"}), \
                 patch.object(deploy, "build_lambda_zip") as package, \
                 patch.object(deploy.subprocess, "run") as upload:
                with self.assertRaisesRegex(RuntimeError, get_provider(missing).target_name):
                    deploy.main()
            self.assertEqual(control.list_gateway_targets.call_args.kwargs["nextToken"], "page-2")
            self.assertEqual(lam.mock_calls, [])
            package.assert_not_called()
            upload.assert_not_called()
            control.update_gateway_target.assert_not_called()

    def test_all_target_details_and_schemas_are_read_before_upload(self):
        control, lam = MagicMock(), MagicMock()
        control.list_gateway_targets.side_effect = [
            {"items": [{"name": get_provider("mureka").target_name, "targetId": "m"}], "nextToken": "page-2"},
            {"items": [{"name": get_provider("remotion").target_name, "targetId": "r"}]},
        ]
        control.get_gateway_target.side_effect = [
            {"targetConfiguration": {"mcp": {"lambda": {}}}, "credentialProviderConfigurations": []},
            RuntimeError("Target unavailable"),
        ]
        with patch.object(deploy, "load_local_env"), \
             patch.object(deploy.boto3, "client", side_effect=[lam, control]), \
             patch.object(deploy, "_find_gateway", return_value={"gatewayId": "gateway"}), \
             patch.object(deploy.subprocess, "run") as upload:
            with self.assertRaisesRegex(RuntimeError, "Target unavailable"):
                deploy.main()
        self.assertEqual(control.get_gateway_target.call_count, 2)
        self.assertEqual(lam.mock_calls, [])
        upload.assert_not_called()
        control.update_gateway_target.assert_not_called()


if __name__ == "__main__":
    unittest.main()
