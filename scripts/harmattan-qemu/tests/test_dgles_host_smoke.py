import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "smoke-dgles-host.py"
SPEC = importlib.util.spec_from_file_location("dgles_host_smoke", SCRIPT)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def valid_output(api=2):
    lines = ["EGL 1.4", "GL_VENDOR=Apple", "GL_RENDERER=test", "GL_VERSION=test"]
    lines += list(SMOKE.COMMON_MARKERS)
    if api == 2:
        lines.append("USER_FBO_SWITCH_OK")
    lines.append(f"HARMATTAN_DGLES{api}_HOST_SMOKE_OK")
    lines.append("GLES_WORKER_JOIN_OK")
    return "\n".join(lines) + "\n"


class DGLESHostSmokeTest(unittest.TestCase):
    def test_both_apis(self):
        for api in (1, 2):
            SMOKE.validate_result(api, 0, valid_output(api), "")

    def test_zero_exit_without_checkpoints_is_not_success(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, "", "")

    def test_wrong_api_marker(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(1, 0, valid_output(2), "")

    def test_echo_or_partial_marker_is_not_success(self):
        output = valid_output().replace("USER_FBO_SWITCH_OK", "echo USER_FBO_SWITCH_OK")
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, output, "")

    def test_missing_renderer(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, valid_output().replace("GL_RENDERER=test", "GL_RENDERER="), "")

    def test_failure_exit_or_stderr(self):
        for code, stderr in ((1, ""), (-11, ""), (0, "GL error")):
            with self.assertRaises(ValueError):
                SMOKE.validate_result(2, code, valid_output(), stderr)

    def test_failure_before_success(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, "FAIL: earlier error\n" + valid_output(), "")

    def test_duplicate_checkpoint(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, "USER_FBO_SWITCH_OK\n" + valid_output(), "")

    def test_rendered_but_worker_did_not_exit(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_result(2, 0, valid_output().replace("GLES_WORKER_JOIN_OK\n", ""), "")


if __name__ == "__main__":
    unittest.main()
