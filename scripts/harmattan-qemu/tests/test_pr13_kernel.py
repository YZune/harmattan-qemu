"""Kernel bundle boundaries and sparse-image replacement regressions."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "kernel_probe", Path(__file__).resolve().parents[1] / "prepare-pr13-kernel-probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def bundle(extra=None, link=False, duplicate=False):
    files = {x: b"kernel" for x in probe.ROOT_FILES}
    files.update({probe.MODULE_PREFIX + x: b"module" for x in probe.REQUIRED_MODULES})
    files.update(extra or {})
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
                       for name, data in files.items()).encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in {"output-sha256.txt": manifest, **{
                "output/" + k: v for k, v in files.items()}}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if duplicate:
            archive.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo("output/symlink")
            info.type, info.linkname = tarfile.SYMTYPE, "/tmp/escape"
            archive.addfile(info)
    stream.seek(0)
    return tarfile.open(fileobj=stream, mode="r")


class KernelBundleTests(unittest.TestCase):
    def test_case_distinct_modules_are_preserved(self):
        lower = probe.MODULE_PREFIX + "xt_rateest.ko"
        upper = probe.MODULE_PREFIX + "xt_RATEEST.ko"
        with bundle({lower: b"match", upper: b"target"}) as archive:
            files = probe.inspect_bundle(archive)
        self.assertNotEqual(files[lower], files[upper])

    def test_traversal_is_rejected(self):
        with bundle({probe.MODULE_PREFIX + "../../escape": b"x"}) as archive:
            with self.assertRaisesRegex(ValueError, "unexpected"):
                probe.inspect_bundle(archive)

    def test_links_are_rejected(self):
        with bundle(link=True) as archive:
            with self.assertRaisesRegex(ValueError, "links"):
                probe.inspect_bundle(archive)

    def test_duplicate_members_are_rejected(self):
        with bundle(duplicate=True) as archive:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                probe.inspect_bundle(archive)

    def test_missing_required_module_is_rejected(self):
        old = probe.REQUIRED_MODULES
        try:
            probe.REQUIRED_MODULES = old - {"omap_ssi.ko"}
            archive = bundle()
        finally:
            probe.REQUIRED_MODULES = old
        with archive, self.assertRaisesRegex(ValueError, "incomplete"):
            probe.inspect_bundle(archive)

    def test_changed_zero_block_replaces_old_data_only_in_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root, disk = Path(folder) / "root", Path(folder) / "disk"
            block = 1024 * 1024
            root.write_bytes(b"\0" * block + b"u" * block)
            disk.write_bytes(b"prefix" + b"x" * block + b"u" * block + b"suffix")
            self.assertEqual(probe.copy_changed_root(root, disk, 6), block)
            self.assertEqual(disk.read_bytes(), b"prefix" + root.read_bytes() + b"suffix")
