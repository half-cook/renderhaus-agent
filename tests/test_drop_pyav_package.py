from __future__ import annotations

import io
from pathlib import Path
import re
import tomllib
import unittest
from unittest.mock import patch
import zipfile

from scripts import ci_check


ROOT = Path(__file__).resolve().parents[1]


def package(extra: str | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (
            "server/billing_rates.py",
            "providers/remotion/mp4_probe.py",
            "providers/remotion/delivery_presets.json",
            "pydantic_core/_pydantic_core.cpython-311-aarch64-linux-gnu.so",
            "opentimelineio/_otio.cpython-311-aarch64-linux-gnu.so",
        ):
            archive.writestr(name, b"package data")
        data = ROOT / 'providers/shot_recipes'
        for path in data.rglob('*'):
            if path.is_file() and path.suffix != '.py' and '__pycache__' not in path.parts:
                archive.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
        if extra:
            archive.writestr(extra, b"forbidden binary")
    return output.getvalue()


class DropPyAVPackageTests(unittest.TestCase):
    def test_project_dependencies_do_not_reintroduce_pyav(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        names = {
            re.split(r"[\s<>=!~;\[]", dep, maxsplit=1)[0].lower().replace("_", "-")
            for dep in config["project"]["dependencies"]
        }
        self.assertNotIn("av", names, "PyAV bundles GPL FFmpeg libraries into the Lambda ZIP")

    def test_clean_lambda_package_passes(self) -> None:
        ci_check.validate_lambda_zip(package())

    def test_delivery_presets_cannot_be_omitted_from_the_lambda_package(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(package())) as source, zipfile.ZipFile(output, "w") as target:
            for item in source.infolist():
                if item.filename != "providers/remotion/delivery_presets.json":
                    target.writestr(item, source.read(item))
        with self.assertRaisesRegex(AssertionError, "delivery presets"):
            ci_check.validate_lambda_zip(output.getvalue())

    def test_pyav_or_ffmpeg_libraries_fail_lambda_validation(self) -> None:
        for name in (
            "av/__init__.py",
            "av.libs/libpostproc.so.58",
            "elsewhere/libx264-abc.so.164",
            "elsewhere/libavcodec-abc.so.61",
            "av-14.2.0.dist-info/METADATA",
        ):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                ci_check.validate_lambda_zip(package(name))

    def test_package_total_size_is_bounded(self) -> None:
        with (
            patch.object(ci_check, "MAX_LAMBDA_UNCOMPRESSED_BYTES", 32),
            self.assertRaises(AssertionError),
        ):
            ci_check.validate_lambda_zip(package())

    def test_package_compressed_size_is_bounded(self) -> None:
        with patch.object(ci_check, "MAX_LAMBDA_ZIP_BYTES", 32), self.assertRaises(AssertionError):
            ci_check.validate_lambda_zip(package())


if __name__ == "__main__":
    unittest.main()
