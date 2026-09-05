import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "smoke-arm64-gles-public.py"
SPEC = importlib.util.spec_from_file_location("public_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def serial_log(noxshm="0"):
    libraries = (b"/usr/lib/libEGL.so.1.3.0", b"/usr/lib/libGLESv2.so.1.4.9",
                 b"/usr/lib/libX11.so.6.3.0", b"/lib/libc-2.10.1.so")
    maps = [b"40000000-40010000 r-xp 00000000 b3:02 1 " + name for name in libraries]
    if noxshm == "0":
        maps.append(b"50000000-50195000 rw-s 00000000 00:09 0 /SYSV00000000 (deleted)")
    identities = [f"{digest}  {name}".encode() for name, digest in SMOKE.LIBRARIES.items()]
    return b"\n".join((*SMOKE.MARKERS, f"N00_PUBLIC_START noxshm={noxshm}".encode(),
                       *identities, b"N00_PUBLIC_MAPS_BEGIN", *maps, b"N00_PUBLIC_MAPS_END")) + (
        b"\nX.Org X Server 1.9.5\n"
        b"(II) Loading /usr/lib/xorg/modules/drivers/omapfb_drv.so\n"
        b"(--) omapfb(0): Virtual size is 864x480 (pitch 864)\n"
        b"(--) omapfb(0): Depth 24, (==) framebuffer bpp 32\n"
    )


def host_log():
    return (
        b"N00_GLES connect client=0 abi=1\n"
        b"N00_GLES connect client=1 abi=2\n"
        b"N00_GLES current client=1 es=2 renderer=Apple Test GPU\n"
        b"N00_GLES terminate client=1 released=1 backend=retained\n"
        b"N00_GLES terminate client=1 rejected=bad-display\n"
        b"N00_GLES disconnect client=1\n"
        b"N00_GLES disconnect client=0\n"
        b"N00_GLES render compiles=2 links=1 uploads=2 draws=2 rejects=0\n"
        b"N00_GLES summary calls=69 swaps=2 faults=0 workers=joined\n"
    )


class PublicAPIGateTests(unittest.TestCase):
    def test_shell_api_marker_and_profiles_cannot_be_mixed(self):
        data = serial_log() + b"N00_SHELL_API_OK pixels=30 rejects=2\n"
        SMOKE.validate_serial(data, "0", shell_api=True)
        for candidate, profile in ((data, False), (serial_log(), True),
                                   (data.replace(b"pixels=30", b"pixels=29"), True)):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(candidate, "0", shell_api=profile)

    def test_shell_api_exact_rendering_and_expected_rejections(self):
        data = host_log().replace(b"calls=69", b"calls=177").replace(
            b"compiles=2 links=1 uploads=2 draws=2 rejects=0", b"compiles=4 links=2 uploads=3 draws=11 rejects=2")
        self.assertEqual(SMOKE.validate_host(data, shell_api=True)["expected_parameter_rejections"], 2)
        for candidate, profile in ((data, False), (host_log(), True),
                                   (data.replace(b"rejects=2", b"rejects=3"), True)):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(candidate, shell_api=profile)

    def test_both_exchange_modes_and_actual_mappings(self):
        for mode, sizes in (("0", [1658880]), ("1", [])):
            result = SMOKE.validate_serial(serial_log(mode), mode)
            self.assertEqual(result["sysv_mapping_bytes"], sizes)
            self.assertEqual(result["runtime_library_md5"], SMOKE.LIBRARIES)

    def test_every_checkpoint_once_not_echoed_or_partial(self):
        for marker in (*SMOKE.MARKERS, b"N00_PUBLIC_START noxshm=0"):
            for data in (serial_log().replace(marker, b"echo " + marker),
                         serial_log() + marker + b"\n",
                         serial_log().replace(marker + b"\n", b"") + marker):
                with self.assertRaises(ValueError):
                    SMOKE.validate_serial(data, "0")

    def test_checkpoint_waits_for_complete_line(self):
        marker = b"N00_PUBLIC_GUEST_OK"
        self.assertFalse(SMOKE.checkpoint(marker, marker))
        self.assertFalse(SMOKE.checkpoint(b"echo " + marker + b"\n", marker))
        self.assertTrue(SMOKE.checkpoint(marker + b"\r\n", marker))

    def test_failures_cannot_be_hidden_by_success_markers(self):
        for failure in (b"N00_PUBLIC_FAIL: draw", b"N00_PUBLIC_EXIT_139",
                        b"N00_PUBLIC_XORG_STOPPED_1"):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log() + failure + b"\n", "0")

    def test_original_executable_library_mappings_required(self):
        for old, new in ((b"libEGL.so.1.3.0", b"libEGL.so.replaced"),
                         (b"libGLESv2.so.1.4.9", b"libGLESv2.so.replaced"),
                         (b"libX11.so.6.3.0", b"libX11.so.replaced"),
                         (b"libc-2.10.1.so", b"libc-replaced.so"),
                         (b"r-xp", b"r--p")):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log().replace(old, new), "0")

    def test_mapping_snapshot_must_be_unique(self):
        for data in (serial_log().replace(b"MAPS_BEGIN", b"MAPS_NOT_BEGIN"),
                     serial_log() + serial_log()):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(data, "0")

    def test_shared_segment_size_and_mode_not_only_environment(self):
        for data, mode in ((serial_log().replace(b"50195000", b"50194000"), "0"),
                           (serial_log().replace(b"noxshm=0", b"noxshm=1"), "1"),
                           (serial_log("1").replace(b"noxshm=1", b"noxshm=0"), "0")):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(data, mode)

    def test_every_runtime_library_digest_pinned_once(self):
        for name, digest in SMOKE.LIBRARIES.items():
            for data in (serial_log().replace(digest.encode(), b"0" * 32),
                         serial_log() + f"{digest}  {name}\n".encode()):
                with self.assertRaises(ValueError):
                    SMOKE.validate_serial(data, "0")

    def test_original_termination_defect_explicitly_expected(self):
        for value in (b"result=1 error=3000", b"result=0 error=300c"):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log().replace(b"result=0 error=3008", value), "0")
        SMOKE.validate_host(host_log())
        for line in (b"N00_GLES terminate client=1 released=1 backend=retained\n",
                     b"N00_GLES terminate client=1 rejected=bad-display\n"):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(host_log().replace(line, b""))

    def test_known_input_errors_reported_unknown_errors_fail(self):
        data = serial_log() + b"\n".join(b"(EE) " + error for error in SMOKE.xorg.INPUT_ERRORS) + b"\n"
        self.assertEqual(len(SMOKE.validate_serial(data, "0")["known_input_errors"]), 7)
        for error in (b"(EE) Screen initialization failed", b"Fatal server error",
                      b"X Error of failed request"):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log() + error + b"\n", "0")

    def test_display_driver_and_dimensions_required(self):
        for old, new in ((b"1.9.5", b"1.20.0"), (b"omapfb_drv.so", b"fake_drv.so"),
                         (b"864x480", b"480x864"), (b"bpp 32", b"bpp 16")):
            with self.assertRaises(ValueError):
                SMOKE.validate_serial(serial_log().replace(old, new), "0")

    def test_exact_host_calls_renderer_and_clean_exit(self):
        self.assertEqual(SMOKE.validate_host(host_log())["calls"], 69)
        for old, new in ((b"abi=2", b"abi=1"), (b"Apple Test GPU", b"software renderer"),
                         (b"calls=69", b"calls=68"), (b"swaps=2", b"swaps=1"),
                         (b"faults=0", b"faults=1"), (b"workers=joined", b"workers=running"),
                         (b"draws=2", b"draws=0"), (b"rejects=0", b"rejects=1")):
            with self.assertRaises(ValueError):
                SMOKE.validate_host(host_log().replace(old, new))
        with self.assertRaises(ValueError):
            SMOKE.validate_host(host_log() + b"late output")

    def test_both_exact_frames_and_texture_change(self):
        header = b"P6\n864 480\n255\n"
        top = bytes((0, 0, 255)) * 432 + bytes((255, 255, 255)) * 432
        hashes = []
        for frame in range(2):
            bottom = bytes((255, 0, 255 if frame else 0)) * 432 + bytes((0, 255, 0)) * 432
            data = header + top * 240 + bottom * 240
            hashes.append(SMOKE.verify_frame(data, frame))
            for bad in (data[:-1], data + b"\0", data[:-1] + b"\xff",
                        data.replace(b"864 480", b"480 864", 1)):
                with self.assertRaises(ValueError):
                    SMOKE.verify_frame(bad, frame)
            with self.assertRaises(ValueError):
                SMOKE.verify_frame(data, 1 - frame)
        self.assertNotEqual(*hashes)


if __name__ == "__main__":
    unittest.main()
