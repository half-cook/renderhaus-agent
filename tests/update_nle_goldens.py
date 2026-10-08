"""Regenerate offline NLE fixtures. Review the resulting diff before committing."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_nle_export import GOLDENS, archive_contents, snapshot


def main() -> None:
    for fps, drop_frame, label in ((24, False, "24"), (25, False, "25"), ("30000/1001", True, "2997df")):
        contents = archive_contents(snapshot(fps, drop_frame))
        for name, data in contents.items():
            if name.endswith(".edl"):
                destination = GOLDENS / label / Path(name).name
            elif label == "24" and name in {"timeline.otio", "timeline.fcpxml"}:
                destination = GOLDENS / name
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            print(destination.relative_to(GOLDENS))


if __name__ == "__main__":
    main()
