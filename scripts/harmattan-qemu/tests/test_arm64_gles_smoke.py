import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "smoke-arm64-gles.py"
SPEC = importlib.util.spec_from_file_location("gles_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def host_log(negative=False):
    data = b""
    if negative:
        data += b"N00_GLES connect client=1 abi=1\n"
        data += b"qemu-system-arm: N00_GLES rejected guest memory client=1 api=0 call=6\n"
        data += b"qemu-system-arm: N00_GLES invalid MMIO offset=0x400\n"
        data += b"qemu-system-arm: N00_GLES invalid MMIO offset=0x3f004\n"
        data += b"N00_GLES disconnect client=1\n"
    for es, abi in ((1, 2), (2, 2), (2, 1)):
        data += f"N00_GLES connect client=1 abi={abi}\n".encode()
        data += f"N00_GLES current client=1 es={es} renderer=Apple M5 Max\n".encode()
        data += b"N00_GLES disconnect client=1\n"
    calls, faults = (126, 3) if negative else (120, 0)
    return data + f"N00_GLES summary calls={calls} swaps=6 faults={faults} workers=joined\n".encode()


def render_host_log(negative=False):
    data = b"N00_GLES connect client=1 abi=2\nN00_GLES current client=1 es=2 renderer=Apple M5 Max\n"
    if negative:
        data += b"qemu-system-arm: N00_GLES rejected guest memory client=1 api=2 call=98\n"
    data += b"N00_GLES disconnect client=1\n"
    return data + (f"N00_GLES render compiles=3 links=1 uploads=3 draws=4 rejects={6 if negative else 0}\n"
                   f"N00_GLES summary calls={122 if negative else 104} swaps=4 faults={1 if negative else 0} workers=joined\n").encode()


class GLESGateTests(unittest.TestCase):
    def test_complete_guest_markers(self):
        SMOKE.validate_serial(b"\r\n".join(SMOKE.MARKERS) + b"\r\n")

    def test_missing_or_echoed_marker_is_not_pass(self):
        for data in (b"\n".join(SMOKE.MARKERS[:-1]),
                     b"\n".join(b"echo " + m for m in SMOKE.MARKERS)):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(data)

    def test_guest_failure_wins_over_pass_markers(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(b"\n".join(SMOKE.MARKERS) + b"\nN00_GLES_FAIL: pixels")

    def test_negative_guest_marker_required(self):
        data = b"\n".join(SMOKE.MARKERS) + b"\n"
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(data, True)
        SMOKE.validate_serial(data + b"\nN00_GLES_NEGATIVE_OK\n", True)

    def test_positive_host_requires_exact_counts_and_abi(self):
        self.assertEqual(SMOKE.validate_host(host_log())["swaps"], 6)
        for old, new in ((b"calls=120", b"calls=119"),
                         (b"swaps=6", b"swaps=5"),
                         (b"faults=0", b"faults=1"),
                         (b"abi=1", b"abi=2"),
                         (b"renderer=Apple", b"renderer=Software")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(host_log().replace(old, new))

    def test_negative_host_requires_exact_rejections(self):
        SMOKE.validate_host(host_log(True), True)
        for data in (host_log(True).replace(b"0x400", b"0x404"),
                     host_log(True).replace(b"faults=3", b"faults=2")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(data, True)

    def test_incomplete_workers_or_unexpected_error(self):
        for data in (host_log().replace(b"workers=joined", b"workers=running"),
                     b"ERROR: bad CGL context\n" + host_log(),
                     host_log() + b"unexpected late output\n"):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(data)

    def test_exact_frame_and_color_damage(self):
        left_top = bytes((0, 255, 255)) * 432
        right_top = bytes((0, 0, 255)) * 432
        left_bottom = bytes((0, 255, 0)) * 432
        right_bottom = left_top
        pixels = (left_top + right_top) * 240 + (left_bottom + right_bottom) * 240
        data = b"P6\n864 480\n255\n" + pixels
        self.assertEqual(SMOKE.verify_frame(data),
                         "ebae8e4de2f11b9e070cf9e27d00074db42e8c84dee8097302734a0caee1e290")
        for bad in (data[:-1], data[:-1] + b"\0", data.replace(b"864 480", b"480 864", 1)):
            with self.assertRaises(ValueError):
                SMOKE.verify_frame(bad)

    def test_repeated_pass_marker_rejected(self):
        for render, markers in ((False, SMOKE.MARKERS), (True, SMOKE.RENDER_MARKERS)):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(b"\n".join(markers + (markers[0],)) + b"\n", render=render)

    def test_render_serial_requires_all_paths(self):
        data = b"\r\n".join(SMOKE.RENDER_MARKERS) + b"\r\n"
        SMOKE.validate_serial(data, render=True)
        for marker in SMOKE.RENDER_MARKERS:
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(data.replace(marker, b"echo " + marker), render=True)

    def test_render_negative_guest_requires_recovery_and_rejections(self):
        data = b"\n".join(SMOKE.RENDER_MARKERS) + b"\n"
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(data, negative=True, render=True)
        SMOKE.validate_serial(data + b"\nN00_GLES_RENDER_NEGATIVE_OK rejections=7\n", negative=True, render=True)

    def test_fragmented_exit_marker_waits_for_newline(self):
        self.assertFalse(SMOKE.probe_complete(b"N00_PROBE_EXIT_0"))
        self.assertTrue(SMOKE.probe_complete(b"N00_PROBE_EXIT_0\r\n"))
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(b"\n".join(SMOKE.RENDER_MARKERS), render=True)

    def test_nonzero_exit_and_complete_failure_are_fatal(self):
        for data in (b"N00_PROBE_EXIT_2\n", b"N00_PROBE_EXIT_01\n", b"N00_GLES_FAIL: pixel mismatch\n"):
            with self.assertRaises(ValueError):
                SMOKE.probe_complete(data)
        self.assertFalse(SMOKE.probe_complete(b"N00_GLES_FAIL: "))

    def test_render_host_counts_and_real_renderer(self):
        result = SMOKE.validate_host(render_host_log(), render=True)
        self.assertEqual(result["render"]["draws"], 4)
        for old, new in ((b"calls=104", b"calls=103"), (b"swaps=4", b"swaps=3"),
                         (b"compiles=3", b"compiles=2"), (b"links=1", b"links=0"),
                         (b"uploads=3", b"uploads=2"), (b"draws=4", b"draws=3"),
                         (b"rejects=0", b"rejects=1"), (b"abi=2", b"abi=1"),
                         (b"renderer=Apple", b"renderer=Software")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                SMOKE.validate_host(render_host_log().replace(old, new), render=True)

    def test_render_negative_faults_are_exact_not_ignored(self):
        SMOKE.validate_host(render_host_log(True), negative=True, render=True)
        for old, new in ((b"api=2 call=98", b"api=2 call=99"),
                         (b"calls=122", b"calls=121"), (b"faults=1", b"faults=0"),
                         (b"rejects=6", b"rejects=7")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(render_host_log(True).replace(old, new), negative=True, render=True)

    def test_render_and_clear_profiles_cannot_be_mixed(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_host(host_log(), render=True)
        with self.assertRaises(ValueError):
            SMOKE.validate_host(render_host_log())
        with self.assertRaises(ValueError):
            SMOKE.validate_serial(b"\n".join(SMOKE.MARKERS), render=True)

    def test_render_requires_single_final_worker_and_render_summaries(self):
        data = render_host_log()
        stats = b"N00_GLES render compiles=3 links=1 uploads=3 draws=4 rejects=0\n"
        for bad in (data + b"late output", data.replace(stats, b""), stats + data,
                    data.replace(b"workers=joined", b"workers=running")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(bad, render=True)

    def test_render_frame_exact_orientation_and_tint(self):
        top = bytes((0, 0, 255)) * 576 + bytes((255, 0, 255)) * 288
        bottom = bytes((255, 0, 0)) * 288 + b"\0\0\0" * 288 + bytes((255, 0, 0)) * 288
        data = b"P6\n864 480\n255\n" + top * 240 + bottom * 240
        self.assertEqual(len(SMOKE.verify_frame(data, render=True)), 64)
        for bad in (data[:-1], data + b"\0", data[:-1] + b"\xff",
                    b"P6\n864 480\n255\n" + bottom * 240 + top * 240):
            with self.assertRaises(ValueError):
                SMOKE.verify_frame(bad, render=True)


if __name__ == "__main__":
    unittest.main()
