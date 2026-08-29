from __future__ import annotations

import unittest
from unittest.mock import patch

from providers.seedance.api import wait_for_video_task


class SeedanceProviderTests(unittest.TestCase):
    def test_wait_for_video_task_treats_dry_run_as_terminal(self) -> None:
        with (
            patch(
                "providers.seedance.api._retrieve_task",
                return_value={"job_id": "dry-task", "status": "dry_run"},
            ) as retrieve,
            patch("providers.seedance.api.time.sleep") as sleep,
        ):
            result = wait_for_video_task("dry-task", timeout_seconds=600)

        self.assertEqual(result["status"], "dry_run")
        retrieve.assert_called_once_with(job_id="dry-task", download=True)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
