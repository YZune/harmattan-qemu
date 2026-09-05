"""Unit checks for the pixel verifier; not device-model regression coverage."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "smoke-arm64-display.py"
SPEC = importlib.util.spec_from_file_location("display_smoke", SCRIPT)
DISPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISPLAY)


class DisplayVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header = b"P6\n864 480\n255\n"
        cls.rgb = DISPLAY.expected_rgb()

    def test_exact_pixels(self):
        self.assertEqual(
            DISPLAY.verify_ppm(self.header + self.rgb),
            "b6ff0ca8ca766fafe69943c8ad692947155775a477fe6285f65303de6ea3c42c")

    def test_second_frame_must_change(self):
        with self.assertRaisesRegex(ValueError, "pixel mismatch"):
            DISPLAY.verify_ppm(self.header + self.rgb, inverted=True)

    def test_inverted_pixels(self):
        self.assertEqual(
            DISPLAY.verify_ppm(self.header + bytes(255 - v for v in self.rgb), True),
            "1c82ea638e61488697f3389a7272cfcf0252fdac3b13a46d934579d9345f24cd")

    def test_wrong_dimensions(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            DISPLAY.verify_ppm(b"P6\n480 864\n255\n" + self.rgb)

    def test_truncated_frame(self):
        with self.assertRaisesRegex(ValueError, "pixel length"):
            DISPLAY.verify_ppm(self.header + self.rgb[:-1])

    def test_colour_order(self):
        pixels = bytearray(self.rgb)
        offset = (10 * 864 + 550) * 3  # red band: swapping R/B must fail
        pixels[offset], pixels[offset + 2] = pixels[offset + 2], pixels[offset]
        with self.assertRaisesRegex(ValueError, "pixel mismatch"):
            DISPLAY.verify_ppm(self.header + pixels)

    def test_command_echo_is_not_checkpoint(self):
        self.assertFalse(DISPLAY.has_line(DISPLAY.frame_command(1), b"N00_FRAME_1_READY"))
        self.assertTrue(DISPLAY.has_line(b"\nN00_FRAME_1_READY\n/ # ", b"N00_FRAME_1_READY"))

    def test_rotation_normalization_uses_fixed_asymmetric_matrix(self):
        # Raw 3x2: ABC / DEF. Expected surfaces are independent fixtures.
        raw = b'P6\n3 2\n255\n' + b''.join(bytes([v]) * 3 for v in b'ABCDEF')
        for angle, width, height, order in ((0, 3, 2, b'ABCDEF'),
                (90, 2, 3, b'CFBEAD'), (180, 3, 2, b'FEDCBA'), (270, 2, 3, b'DAEBFC')):
            surface = f'P6\n{width} {height}\n255\n'.encode() + b''.join(bytes([v]) * 3 for v in order)
            self.assertEqual(DISPLAY.native_ppm(surface, angle, 3, 2), raw)

    def test_rotation_input_corners(self):
        self.assertEqual(DISPLAY.surface_point(0, 0, 270), (479, 0))
        self.assertEqual(DISPLAY.surface_point(863, 479, 270), (0, 863))
        self.assertEqual(DISPLAY.surface_point(863, 0, 90), (0, 0))
        self.assertEqual(DISPLAY.surface_point(0, 479, 180), (863, 0))
        self.assertEqual(DISPLAY.surface_point(8192, 8192, 270, 32768, 32768), (24575, 8192))

    def test_rotation_cannot_accept_wrong_size_or_angle(self):
        for data, angle in ((self.header + self.rgb, 270),
                            (b'P6\n480 864\n255\n' + self.rgb[:-1], 270),
                            (self.header + self.rgb, 45)):
            with self.assertRaises(ValueError):
                DISPLAY.native_ppm(data, angle)

    def test_display_rejects_host_reentrancy_and_bad_exit(self):
        DISPLAY.validate_display_host(b'', 0)
        DISPLAY.validate_display_host(b'N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n', 0)
        for log, code in ((b'warning: Blocked re-entrant IO\n', 0), (b'', 1),
                (b'N00_GLES summary calls=1 swaps=0 faults=0 workers=joined\n', 0)):
            with self.assertRaises(ValueError):
                DISPLAY.validate_display_host(log, code)

    def test_child_dyld_path_survives_python_shell_shim(self):
        with patch.dict('os.environ', {'HARMATTAN_DGLES_RUNTIME_DIR': '/private/test/dgles', 'KEEP': 'yes'}, clear=True):
            env = DISPLAY.qemu_environment()
            self.assertEqual(env['DYLD_LIBRARY_PATH'], '/private/test/dgles')
            self.assertEqual(env['KEEP'], 'yes')
        with patch.dict('os.environ', {'KEEP': 'yes'}, clear=True):
            self.assertNotIn('DYLD_LIBRARY_PATH', DISPLAY.qemu_environment())


if __name__ == "__main__":
    unittest.main()
