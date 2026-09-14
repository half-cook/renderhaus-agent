import json
import unittest
from unittest.mock import patch

import httpx2

from agent.gateway_client import GatewayClient


class GatewayTransportSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_urls_are_rejected_before_client_creation(self):
        cases = [
            {"url": "http://gateway.example/mcp", "headers": {"Authorization": "Bearer test-only"}},
            {"url": "http://127.0.0.1:9000/mcp"},
            {"url": "http://127.0.0.1/mcp", "allow_loopback_http": "true"},
            *({"url": url, "allow_loopback_http": True} for url in (
                "http://remote.example/mcp", "http://localhost.evil.test/mcp", "http://127.1/mcp",
                "http://user:password@localhost/mcp", "http://localhost/mcp?token=test",
                "http://localhost/mcp#token", "http://localhost:wrong/mcp", "http://[::1]:99999/mcp",
                "http://localhost\\@remote.example/mcp", " http://localhost/mcp",
                "http://local\nhost/mcp", "http://%6cocalhost/mcp", "file:///mcp", "//localhost/mcp",
                "https:///mcp", "https://user:password@gateway.example/mcp",
            )),
            *({"url": "http://localhost/mcp", "allow_loopback_http": True, "headers": headers} for headers in (
                {"authorization": "Bearer test"}, {"Cookie": "session=test"}, {"X-Api-Key": "test"},
            )),
        ]
        for params in cases:
            with self.subTest(params=params), patch("agent.gateway_client.create_mcp_http_client") as create, \
                 patch("agent.gateway_client.httpx2.AsyncClient") as direct:
                with self.assertRaises(ValueError):
                    async with GatewayClient(params, name="test"):
                        self.fail("Invalid Gateway was connected")
                create.assert_not_called()
                direct.assert_not_called()

    async def test_https_with_bearer_and_explicit_loopback_remain_usable(self):
        for url, headers, opt_in in (
            ("https://gateway.example/mcp", {"Authorization": "Bearer test-only"}, False),
            ("http://localhost/mcp", {}, True),
            ("http://127.0.0.1/mcp", {}, True),
            ("http://[::1]/mcp", {}, True),
        ):
            requests = []
            def handle(request):
                requests.append(request)
                body = json.loads(request.content)
                if "id" not in body:
                    return httpx2.Response(202)
                return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1"},
                }})
            client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle), headers=headers, follow_redirects=True)
            with self.subTest(url=url), patch("agent.gateway_client.create_mcp_http_client", return_value=client), \
                 patch("agent.gateway_client.httpx2.AsyncClient", return_value=client):
                async with GatewayClient({"url": url, "headers": headers, "allow_loopback_http": opt_in}, name="test"):
                    self.assertFalse(client.follow_redirects)
            self.assertTrue(requests)
            self.assertEqual(requests[0].headers.get("authorization"), headers.get("Authorization"))

    async def test_redirect_never_sends_credentials_or_body_to_other_destination(self):
        for start, destination in (("https://gateway.example/mcp", "http://gateway.example/mcp"),
                                   ("http://localhost/mcp", "http://remote.example/mcp")):
            requests = []
            def redirect(request):
                requests.append(request)
                return httpx2.Response(307, headers={"Location": destination})
            headers = {"X-Api-Key": "test-only"} if start.startswith("https") else {}
            client = httpx2.AsyncClient(transport=httpx2.MockTransport(redirect), headers=headers, follow_redirects=True)
            with self.subTest(start=start), patch("agent.gateway_client.create_mcp_http_client", return_value=client), \
                 patch("agent.gateway_client.httpx2.AsyncClient", return_value=client):
                with self.assertRaises(Exception):
                    async with GatewayClient({"url": start, "headers": headers, "allow_loopback_http": True}, name="test"):
                        self.fail("Redirect should fail initialization")
            self.assertTrue(requests)
            self.assertTrue(all(str(request.url) == start for request in requests))


if __name__ == "__main__":
    unittest.main()
