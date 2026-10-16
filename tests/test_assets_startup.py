from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from server import assets


class AssetBucketStartupTests(unittest.TestCase):
    def test_denied_bucket_probe_never_attempts_creation(self) -> None:
        client = Mock()
        denied = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket")
        client.head_bucket.side_effect = denied
        with patch.object(assets, "_s3", return_value=client), patch.object(
            assets, "_require_bucket", return_value="private-assets"
        ):
            with self.assertRaises(ClientError) as raised:
                assets._ensure_s3_bucket()
        self.assertIs(raised.exception, denied)
        client.create_bucket.assert_not_called()
        client.put_bucket_cors.assert_not_called()

    def test_missing_bucket_is_created_with_region_then_cors(self) -> None:
        client = Mock()
        client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
        )
        with patch.object(assets, "_s3", return_value=client), patch.object(
            assets, "_require_bucket", return_value="new-assets"
        ), patch.object(assets, "aws_region", return_value="ca-central-1"):
            assets._ensure_s3_bucket()
        client.create_bucket.assert_called_once_with(
            Bucket="new-assets", CreateBucketConfiguration={"LocationConstraint": "ca-central-1"}
        )
        client.put_bucket_cors.assert_called_once()
        rules = client.put_bucket_cors.call_args.kwargs["CORSConfiguration"]["CORSRules"]
        self.assertIn("http://localhost:5174", rules[0]["AllowedOrigins"])
        self.assertIn("http://127.0.0.1:5174", rules[0]["AllowedOrigins"])
        self.assertEqual(rules[0]["AllowedMethods"], ["GET", "HEAD", "PUT"])
        self.assertIn("ETag", rules[0]["ExposeHeaders"])
