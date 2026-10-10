"""Execute the maintained FBO wire marshaller with a bounded fake GL backend."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PORT = ROOT / "ports/qemu-n00"


def added_file(patch, name):
    section = patch.split(f"diff --git a/{name} b/{name}\n", 1)[1]
    section = section.split("diff --git ", 1)[0]
    return "\n".join(line[1:] for line in section.splitlines()
                     if line.startswith("+") and not line.startswith("+++")) + "\n"


class GLESFBOMarshallingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler or not shutil.which("patch"):
            raise RuntimeError("FBO marshalling tests require a C compiler and patch")
        cls.work = tempfile.TemporaryDirectory(prefix="n00-fbo-")
        cls.addClassCleanup(cls.work.cleanup)
        work = Path(cls.work.name)
        arm = work / "hw/arm"
        arm.mkdir(parents=True)
        base = (PORT / "qemu-9.1.3-n00-gles.patch").read_text()
        for name in ("n00_gles_port.c", "n00_gles_wire.h"):
            (arm / name).write_text(added_file(base, "hw/arm/" + name))
        # Apply the real layer sequence, including consumers of render-patch context.
        for layer in ("render", "public", "shell"):
            subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i",
                            str(PORT / f"qemu-9.1.3-n00-gles-{layer}.patch")],
                           cwd=work, capture_output=True, text=True, check=True)
        port = (arm / "n00_gles_port.c").read_text()
        decoder = re.search(r"static uint32_t arg\(.*?\n}\n", port, re.S)
        if not decoder:
            raise AssertionError("Production stack decoder not found")
        (arm / "n00_gles_args.inc").write_text(decoder.group())
        render = (arm / "n00_gles_render.inc").read_text()
        rejection = re.search(r"static bool render_error\(.*?\n}\n", render, re.S)
        if not rejection:
            raise AssertionError("Production rejection helper not found")
        (arm / "n00_gles_render_error.inc").write_text(rejection.group())
        cls.program = str(work / "gles-fbo-host")
        subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-I", str(arm),
                        str(Path(__file__).with_name("gles-fbo-host.c")),
                        "-o", cls.program], capture_output=True, text=True, check=True)

    def check_case(self, number):
        result = subprocess.run([self.program, str(number)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS\n")
        self.assertEqual(result.stderr, "")

    def test_names_preflight_endian_and_rollback(self): self.check_case(1)
    def test_live_limits_delete_reuse_and_lazy_bind(self): self.check_case(2)
    def test_storage_bounds_budget_and_failed_resize(self): self.check_case(3)
    def test_scalar_queries_guards_and_context_isolation(self): self.check_case(4)
    def test_fifth_argument_and_wrapped_stack(self): self.check_case(5)

    def test_retained_storage_name_isolation_and_detach(self): self.check_case(6)

    def test_bounded_rejection_diagnostic_preserves_errors(self):
        result = subprocess.run([self.program, "7"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS\n")
        expected = ("N00_GLES render-reject client=3 api=2 abi=2 call=94 error=0500 "
                    "r0=00008d41 r1=000088f0 r2=00000360 r3=000001e0")
        self.assertEqual(result.stderr.splitlines(), [expected] * 64 + [
            "N00_GLES render-reject limit=64 further=suppressed"])

    def test_wrong_binding_targets_remain_rejected(self): self.check_case(8)
