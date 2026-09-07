#!/usr/bin/env python3
"""Install a locally built kernel's modules into a new, private probe disk."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
import tarfile

SPEC = importlib.util.spec_from_file_location(
    "prepare_guest", Path(__file__).resolve().parents[1] / "prepare-guest.py")
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)

RELEASE = "2.6.32.54-n00-pr13"
KERNEL = "zImage-" + RELEASE
MODULE_PREFIX = "lib/modules/" + RELEASE + "/"
ROOT_FILES = {KERNEL, "vmlinux", "System.map", ".config"}
METADATA = {"output-sha256.txt", "compiler.txt", "input-sha256.txt",
            "aegis-original-sha256.txt", "aegis-source-check.txt", "kernel-symbols.txt"}
REQUIRED_MODULES = {"omap_ssi.ko", "phonet.ko", "ssi_protocol.ko",
                    "cmt.ko", "cmt_speech.ko", "kfgles2.ko", "modules.dep"}


def inspect_bundle(archive):
    """Use manifest paths only; never extract archive paths onto the host."""
    members = {}
    for member in archive.getmembers():
        if member.name in members:
            raise ValueError("duplicate bundle member")
        if not member.isfile() and not member.isdir():
            raise ValueError("bundle links and special files are forbidden")
        if member.size > 128 * 1024 * 1024:
            raise ValueError("oversized bundle member")
        members[member.name] = member
    if len(members) > 2048 or sum(x.size for x in members.values()) > 1024**3:
        raise ValueError("oversized kernel bundle")
    if "output-sha256.txt" not in members or members["output-sha256.txt"].size > 1024**2:
        raise ValueError("missing or oversized output manifest")
    manifest = archive.extractfile("output-sha256.txt").read().decode("ascii")
    files = {}
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if not match:
            raise ValueError("invalid output manifest")
        digest, name = match.groups()
        if name not in ROOT_FILES and not re.fullmatch(
                re.escape(MODULE_PREFIX) + r"[A-Za-z0-9_+.-]+", name):
            raise ValueError("unexpected kernel output path")
        if name.rsplit("/", 1)[-1] in {".", ".."} or name in files:
            raise ValueError("duplicate or unsafe kernel output path")
        member = members.get("output/" + name)
        if member is None or not member.isfile():
            raise ValueError("missing kernel output file")
        files[name] = digest
    required = ROOT_FILES | {MODULE_PREFIX + x for x in REQUIRED_MODULES}
    if not required <= files.keys():
        raise ValueError("incomplete kernel/module bundle")
    allowed = {"output/" + x for x in files} | METADATA
    if any(x.isfile() and x.name not in allowed for x in members.values()):
        raise ValueError("unlisted bundle file")
    return files


def copy_changed_root(rootfs, disk, offset):
    # Compare before writing so unchanged APFS clone extents remain shared.
    # Changed zero blocks must be written too; skipping holes would retain old data.
    changed = 0
    with rootfs.open("rb") as source, disk.open("r+b") as target:
        position = offset
        while data := source.read(1024 * 1024):
            target.seek(position)
            if target.read(len(data)) != data:
                target.seek(position)
                target.write(data)
                changed += len(data)
            position += len(data)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path, help="quiescent prepared raw base")
    parser.add_argument("--output", required=True, type=Path, help="new private directory")
    parser.add_argument("--debugfs", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("This probe-disk preparation requires macOS APFS cloning.")
    image = args.image.resolve(strict=True)
    before = image.stat()
    layout = prepare.partitions(image)
    out = args.output.absolute()
    if any(c in str(out) for c in ('\n', '\r', '"', ',')):
        parser.error("Output path contains unsupported characters.")
    if out.exists() or out.is_symlink():
        parser.error("Output already exists; select a fresh directory.")
    with tarfile.open(args.bundle, "r:gz") as archive:
        files = inspect_bundle(archive)
        out.mkdir(parents=True, exist_ok=False)
        stage = out / "staged-modules"
        stage.mkdir()
        commands = ["mkdir /lib/modules/" + RELEASE]
        for index, (name, digest) in enumerate(sorted(files.items())):
            is_module = name.startswith(MODULE_PREFIX)
            # Numeric staging names preserve xt_RATEEST/xt_rateest on APFS.
            destination = stage / str(index) if is_module else out / name
            source = archive.extractfile("output/" + name)
            actual = hashlib.sha256()
            with destination.open("xb") as stream:
                while data := source.read(1024 * 1024):
                    actual.update(data)
                    stream.write(data)
            if actual.hexdigest() != digest:
                raise ValueError("kernel bundle checksum mismatch: " + name)
            if is_module:
                commands.append(f'write "{destination}" /{name}')
        if "b0008000 T _stext" not in (out / "System.map").read_text().splitlines():
            raise ValueError("kernel entry is not at its required load address")
    disk, rootfs = out / "disk.raw", out / "rootfs.ext4"
    subprocess.run(["/bin/cp", "-c", str(image), str(disk)], check=True)
    _, offset, length = layout[1]
    prepare.copy_range(image, rootfs, offset, length, sparse=True)
    prepare.debugfs(args.debugfs.resolve(strict=True), rootfs, commands,
                    out / "module-install.log", write=True)
    changed = copy_changed_root(rootfs, disk, offset)
    after = image.stat()
    if (after.st_size, after.st_mtime_ns, after.st_ino) != (
            before.st_size, before.st_mtime_ns, before.st_ino):
        raise ValueError("base image changed during preparation; discard this probe")
    (out / "prepared-kernel.json").write_text(json.dumps({
        "scope": "experimental kernel/module probe; full services unverified",
        "base_image": str(image), "base_mtime_ns": before.st_mtime_ns,
        "kernel_release": RELEASE, "kernel_sha256": files[KERNEL],
        "modules": sum(x.endswith(".ko") for x in files),
        "changed_root_bytes": changed, "full_services": False,
        "module_layout": "matching release directory; existing current symlink unchanged"
    }, indent=2) + "\n")
    print(f"Prepared private probe: {out}; run diagnostics with -snapshot.")


if __name__ == "__main__":
    main()
