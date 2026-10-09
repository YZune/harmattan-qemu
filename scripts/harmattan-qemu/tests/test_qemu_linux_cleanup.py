import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "smoke-qemu-linux-cleanup.py"
SPEC = importlib.util.spec_from_file_location("qemu_linux_cleanup", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)
SUMMARY = "N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n"
WORKER = "N00_GLES connect client=1 abi=1\nN00_GLES disconnect client=1\n"


class LinuxCleanupTest(unittest.TestCase):
    def test_prelaunch_running_and_paused(self):
        for mode in ("prelaunch", "running", "paused"):
            worker = "" if mode == "prelaunch" else WORKER
            result = SMOKE.validate_cleanup(mode, 0, worker + SUMMARY + SMOKE.MARKER + "\n")
            self.assertTrue(result["cleanup_before_main_return"])

    def test_old_atexit_only_cleanup_fails(self):
        with self.assertRaisesRegex(ValueError, "before libc atexit"):
            SMOKE.validate_cleanup("running", 0, SMOKE.MARKER + "\n" + WORKER + SUMMARY)

    def test_duplicate_fallback_teardown_fails(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_cleanup("running", 0, WORKER + SUMMARY + SMOKE.MARKER + "\n" + SUMMARY)

    def test_worker_must_be_joined(self):
        for worker in ("", WORKER.replace("N00_GLES disconnect client=1\n", "")):
            with self.assertRaises(ValueError):
                SMOKE.validate_cleanup("paused", 0, worker + SUMMARY + SMOKE.MARKER + "\n")

    def test_summary_must_follow_worker_disconnect(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_cleanup("running", 0, SUMMARY + WORKER + SMOKE.MARKER + "\n")

    def test_fault_exit_and_missing_marker_fail(self):
        output = WORKER + SUMMARY + SMOKE.MARKER + "\n"
        for code, log in ((-11, output), (0, output.replace("faults=0", "faults=1")),
                          (0, WORKER + SUMMARY)):
            with self.assertRaises(ValueError):
                SMOKE.validate_cleanup("running", code, log)

    def test_unexpected_stderr_is_not_hidden_by_success(self):
        output = WORKER + SUMMARY + SMOKE.MARKER + "\n"
        for unknown in ("warning: failed operation\n", "N00_GLES fault ignored\n", "\n"):
            with self.assertRaisesRegex(ValueError, "unexpected QEMU stderr"):
                SMOKE.validate_cleanup("running", 0, unknown + output)


if __name__ == "__main__":
    unittest.main()
