"""SSI transfer, backpressure and negative DMA tests using the actual core."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class SSITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise RuntimeError("SSI tests require a C compiler")
        cls.work = tempfile.TemporaryDirectory(prefix="n00-ssi-")
        cls.addClassCleanup(cls.work.cleanup)
        cls.program = str(Path(cls.work.name) / "ssi-host")
        subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-I", str(ROOT / "ports/qemu-n00"),
                        str(Path(__file__).with_name("ssi-host.c")), "-o", cls.program],
                       capture_output=True, check=True)

    def check_case(self, case):
        result = subprocess.run([self.program, str(case)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS\n")
        self.assertEqual(result.stderr, "")

    def test_reset_and_read_only_identity(self): self.check_case(1)
    def test_disconnected_peer_does_not_complete_pio(self): self.check_case(2)
    def test_pio_backpressure_and_receive_interrupt(self): self.check_case(3)
    def test_bidirectional_dma_and_interrupt_acknowledgement(self): self.check_case(4)
    def test_invalid_memory_and_linked_dma_never_complete(self): self.check_case(5)
    def test_reset_cancels_pending_dma(self): self.check_case(6)
    def test_wake_and_receive_overrun(self): self.check_case(7)
    def test_unsupported_dma_modes_fail_without_copying(self): self.check_case(8)
    def test_eight_channels_do_not_mix_frames(self): self.check_case(9)
