from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class AdDemoTests(unittest.TestCase):
    def test_generated_fixture_plans_without_paid_calls_and_requires_operator_approval(self):
        generator = ROOT / "scripts/make_ad_demo_assets.py"
        driver = ROOT / "scripts/run_ad_demo.py"
        self.assertTrue(generator.is_file(), "deterministic demo generator missing")
        self.assertTrue(driver.is_file(), "real local demo driver missing")
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary)
            result = subprocess.run([str(PYTHON), str(generator), "--media-root", str(media),
                                     "--job-id", "demo", "--size", "small"],
                                    capture_output=True, text=True, timeout=30, check=True)
            self.assertNotIn("secret", result.stdout.lower())
            job = media / "demo"
            with (job / "variants.csv").open() as table:
                self.assertEqual(len(list(csv.DictReader(table))), 6)
            with Image.open(job / "logo_A.png") as logo:
                self.assertEqual(logo.mode, "RGBA")
            base = [str(PYTHON), str(driver), "--media-root", str(media), "--job-id", "demo"]
            planned = json.loads(subprocess.run([*base, "plan"], check=True, capture_output=True,
                                               text=True, timeout=30).stdout)
            self.assertEqual(planned["status"], "planned", planned)
            self.assertEqual(planned["render_count"], 6)
            refused = subprocess.run([*base, "render_batch"], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("approve-plan", refused.stderr)


if __name__ == "__main__":
    unittest.main()
