from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class ViduPackagingTests(unittest.TestCase):
    def test_billing_only_change_rebuilds_gateway_and_runtime(self):
        workflow = Path(".github/workflows/deploy.yml").read_text()
        decision = workflow.split("      - id: pick\n", 1)[1].split("\n  gateway:", 1)[0]
        script = textwrap.dedent(decision.split("        run: |\n", 1)[1])
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: {
            "github.event.inputs.region || 'us-east-1'": "us-east-1",
            "github.event.inputs.skip_runtime_build || 'false'": "false",
            "github.event.inputs.target || ''": "",
            "github.event.inputs.provider || 'all'": "all",
            "github.event.before": "before",
            "github.sha": "after",
        }[match[1]], script)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            script = "git() { printf '%s\\n' 'server/billing_rates.py'; }\n" + script
            subprocess.run(["bash", "-c", script],
                           env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(output)},
                           check=True, capture_output=True, text=True)
            decisions = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(decisions["deploy_gateway"], "true")
        self.assertEqual(decisions["deploy_runtime"], "true")
        self.assertEqual(decisions["provider"], "all")

    def test_lambda_contains_importable_shared_billing_without_server_app(self):
        spec = importlib.util.spec_from_file_location("deploy_gateway", "scripts/deploy_gateway.py")
        deploy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deploy)
        with patch.object(deploy.subprocess, "run"):
            archive = deploy.build_lambda_zip()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            self.assertIn("server/billing_rates.py", bundle.namelist())
            self.assertIn("server/__init__.py", bundle.namelist())
            self.assertNotIn("server/app.py", bundle.namelist())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lambda.zip"
            path.write_bytes(archive)
            result = subprocess.run([sys.executable, "-I", "-c",
                "import sys; from datetime import date; sys.path.insert(0, sys.argv[1]); "
                "from server import billing_rates as b; "
                "assert b.__file__.startswith(sys.argv[1]); "
                "assert str(b.vidu_q4_rates(as_of=date(2026,12,1))['4K']) == '39'; "
                "print('packaged billing imported')", str(path)],
                text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), "packaged billing imported")
