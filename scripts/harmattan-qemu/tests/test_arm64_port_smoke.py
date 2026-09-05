"""Test the serial verifier with fake children; this does not test QEMU itself."""

from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "smoke-arm64-port.py"
READY = "print('HARMATTAN-HYBRID-RESCUE: shell ready\\n/ # ', flush=True)\n"
READ_PROBE = "probe = input()\nprint(probe, flush=True)\n"
CHECKPOINT = "print('\\nHARMATTAN_NATIVE_SMOKE_OK', flush=True)\n"
CONFIRM = ("confirm = input()\nprint(confirm, flush=True)\n"
           "print('\\nHARMATTAN_NATIVE_SMOKE_SETTLED', flush=True)\n")


class SmokeVerifierTests(unittest.TestCase):
    def test_lost_command_prefix_cannot_skip_sync_and_print_confirmation(self):
        spec = importlib.util.spec_from_file_location('serial_smoke', RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        # Regression for UART wakeup dropping the original "sync && " prefix.
        # The nested command's confirmation cannot execute independently.
        for count in range(1, 16):
            result = subprocess.run(['/bin/sh', '-c', runner.SYNC_CONFIRMATION[count:].decode()],
                                    capture_output=True, timeout=5)
            self.assertNotIn(b'\nHARMATTAN_NATIVE_SMOKE_SETTLED\n', result.stdout)

    def run_child(self, code):
        with tempfile.TemporaryDirectory(prefix="n00-verifier-test-") as directory:
            return subprocess.run(
                [sys.executable, str(RUNNER), "--log", str(Path(directory) / "serial.log"),
                 "--timeout", "2", "--settle", "0.1", "--",
                 sys.executable, "-u", "-c", code, "-snapshot"],
                text=True, capture_output=True, timeout=10,
            )

    def test_success_requires_final_confirmation(self):
        result = self.run_child(READY + READ_PROBE + CHECKPOINT + CONFIRM)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("final sync", result.stdout)

    def test_echoed_probe_does_not_pass(self):
        result = self.run_child(READY + READ_PROBE)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PASS:", result.stdout)

    def test_exit_after_checkpoint_does_not_pass(self):
        result = self.run_child(READY + READ_PROBE + CHECKPOINT)
        self.assertNotEqual(result.returncode, 0)

    def test_device_failures_do_not_pass(self):
        for marker in ("Kernel panic", "Internal error: Oops",
                       "Blocked re-entrant IO", "Spurious DMA IRQ"):
            with self.subTest(marker=marker):
                result = self.run_child(READY + READ_PROBE + CHECKPOINT
                                        + f"print({marker!r}, flush=True)\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAIL:", result.stderr)

    def test_timeout_does_not_pass(self):
        result = self.run_child("import time\ntime.sleep(30)\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL:", result.stderr)


if __name__ == "__main__":
    unittest.main()
