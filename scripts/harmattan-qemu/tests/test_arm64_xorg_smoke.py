import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "smoke-arm64-xorg.py"
SPEC = importlib.util.spec_from_file_location("xorg_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def serial_log():
    return b"\n".join(SMOKE.MARKERS) + (
        b"\nX.Org X Server 1.9.5\n"
        b"(II) Loading /usr/lib/xorg/modules/drivers/omapfb_drv.so\n"
        b"(--) omapfb(0): Virtual size is 864x480 (pitch 864)\n"
        b"(--) omapfb(0): Depth 24, (==) framebuffer bpp 32\n"
    )


class XorgGateTests(unittest.TestCase):
    def test_complete_xorg_and_x11_evidence(self):
        self.assertEqual(SMOKE.validate_serial(serial_log()), [])

    def test_every_checkpoint_required_once(self):
        for marker in SMOKE.MARKERS:
            for data in (serial_log().replace(marker, b"echo " + marker),
                         serial_log() + marker + b"\n"):
                with self.assertRaises(ValueError):
                    SMOKE.validate_serial(data)

    def test_known_input_errors_are_reported_not_hidden(self):
        data = serial_log() + b"\n".join(b"(EE) " + error for error in SMOKE.INPUT_ERRORS)
        errors = SMOKE.validate_serial(data)
        self.assertEqual(len(errors), 7)
        self.assertIn("mtev: cannot open device", errors)

    def test_unknown_xorg_errors_fail(self):
        for error in (b"(EE) Screen initialization failed", b"Fatal server error", b"X11 draw/fence error"):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log() + b"\n" + error)

    def test_log_legend_is_not_an_error_record(self):
        data = serial_log() + b"(WW) warning, (EE) error, (NI) not implemented, (??) unknown.\n"
        self.assertEqual(SMOKE.validate_serial(data), [])
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(data + b"[    1.234] (EE) unknown real failure\n")

    def test_driver_and_dimensions_required(self):
        for old, new in ((b"1.9.5", b"1.20.0"), (b"omapfb_drv.so", b"fake_drv.so"),
                         (b"864x480", b"480x864"), (b"bpp 32", b"bpp 16")):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log().replace(old, new))

    def test_exact_root_frame(self):
        frame = b"P6\n864 480\n255\n" + bytes((0x37, 0x69, 0xa8)) * 414720
        self.assertEqual(len(SMOKE.verify_frame(frame)), 64)
        for bad in (frame[:-1], frame + b"\0", frame[:-1] + b"\0",
                    frame.replace(b"864 480", b"480 864", 1)):
            with self.assertRaises(ValueError):
                SMOKE.verify_frame(bad)

    def test_no_hidden_gles_calls_and_clean_exit(self):
        log = b"N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n"
        SMOKE.validate_host(log)
        for data in (log.replace(b"calls=0", b"calls=1"),
                     log.replace(b"faults=0", b"faults=1"), log + b"late output",
                     log.replace(b"workers=joined", b"workers=running")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(data)


if __name__ == "__main__":
    unittest.main()
