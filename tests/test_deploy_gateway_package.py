from __future__ import annotations

import hashlib
import unittest
from unittest.mock import Mock, patch

from providers.catalog import get_provider
from scripts import deploy_gateway as deploy


class GatewayPackageTests(unittest.TestCase):
    def test_large_package_uses_same_region_bucket_for_create_and_update(self) -> None:
        package = b"gateway package"
        s3 = Mock()
        s3.get_bucket_location.return_value = {"LocationConstraint": None}
        key = f"renderhaus/gateway-code/{hashlib.sha256(package).hexdigest()}.zip"
        with patch.object(deploy, "DIRECT_ZIP_LIMIT", 1, create=True), \
                patch.object(deploy.boto3, "client", return_value=s3):
            code = deploy.lambda_package_code(package, env={"AWS_S3_BUCKET": "media"}, region="us-east-1")
        self.assertEqual(code, {"S3Bucket": "media", "S3Key": key})
        s3.put_object.assert_called_once_with(Bucket="media", Key=key, Body=package,
                                             ContentType="application/zip")
        for exists in (True, False):
            with self.subTest(exists=exists):
                lam = Mock()
                function = {"Configuration": {"FunctionArn": "arn:lambda"}}
                missing = deploy.ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "GetFunction")
                lam.get_function.side_effect = [function if exists else missing, function]
                with patch.object(deploy.time, "sleep"):
                    deploy._upsert_lambda(lam, spec=get_provider("remotion"), role_arn="role", region="us-east-1",
                                          secret_name="", env={}, code=code)
                if exists:
                    self.assertEqual(lam.update_function_code.call_args.kwargs["S3Bucket"], "media")
                    self.assertNotIn("ZipFile", lam.update_function_code.call_args.kwargs)
                else:
                    self.assertEqual(lam.create_function.call_args.kwargs["Code"], code)

    def test_small_package_and_invalid_bucket_never_upload(self) -> None:
        with patch.object(deploy, "DIRECT_ZIP_LIMIT", 1, create=True), \
                patch.object(deploy.boto3, "client") as client:
            self.assertEqual(deploy.lambda_package_code(b"x", env={}, region="us-east-1"), {"ZipFile": b"x"})
            client.assert_not_called()
            with self.assertRaisesRegex(ValueError, "AWS_S3_BUCKET or REMOTION_APP_BUCKET_NAME"):
                deploy.lambda_package_code(b"large", env={}, region="us-east-1")
            client.assert_not_called()
            client.return_value.get_bucket_location.return_value = {"LocationConstraint": "eu-west-1"}
            with self.assertRaisesRegex(ValueError, "same region"):
                deploy.lambda_package_code(b"large", env={"REMOTION_APP_BUCKET_NAME": "renderer"}, region="us-east-1")
            client.return_value.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
