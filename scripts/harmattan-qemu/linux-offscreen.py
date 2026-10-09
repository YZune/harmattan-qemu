"""Linux offscreen transport and lossless capture for the shared UI controller."""
import hashlib
import json
import os
from pathlib import Path
import select
import time


class PipeSerial:
    """QEMU pipe chardev, using private FIFOs without sockets or listeners."""

    def __init__(self, path, deadline):
        self.path = str(Path(path).resolve())
        # Commas delimit QEMU chardev options; do not reinterpret a pathname.
        if ',' in self.path or '\n' in self.path:
            raise ValueError('serial FIFO path must not contain commas or newlines')
        self.deadline = deadline
        self.read_fd = self.write_fd = None
        self.paths = []
        try:
            for suffix in ('.in', '.out'):
                name = self.path + suffix
                os.mkfifo(name, 0o600)
                self.paths.append(Path(name))
            # QEMU also opens both ends read/write. This avoids a blocking open
            # before it starts and does not need a helper process.
            self.write_fd = os.open(self.paths[0], os.O_RDWR | os.O_NONBLOCK)
            self.read_fd = os.open(self.paths[1], os.O_RDWR | os.O_NONBLOCK)
        except BaseException:
            self.close()
            raise

    def fileno(self):
        return self.read_fd

    def recv(self, length):
        return os.read(self.read_fd, length)

    def sendall(self, payload):
        pending = memoryview(payload)
        while pending:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('serial pipe write deadline expired')
            if not select.select([], [self.write_fd], [], min(remaining, .2))[1]:
                continue
            try:
                written = os.write(self.write_fd, pending)
                if written == 0:
                    raise RuntimeError('serial pipe write made no progress')
                pending = pending[written:]
            except BlockingIOError:
                continue

    def close(self):
        for name in ('read_fd', 'write_fd'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
        for path in self.paths:
            path.unlink(missing_ok=True)
        self.paths = []


def require_pillow():
    # The default macOS controller has no new Python dependency.
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError('Linux capture needs Pillow installed for this Python interpreter') from error
    return Image


def export_png(ppm, png):
    """Export and reopen every capture; authoritative validators keep the PPM."""
    Image = require_pillow()
    with Image.open(ppm) as original:
        original.load()
        if original.format != 'PPM' or original.mode != 'RGB':
            raise ValueError('QMP screenshot must be an RGB PPM')
        size, pixels = original.size, original.tobytes()
        original.save(png, format='PNG')
    with Image.open(png) as converted:
        converted.load()
        if (converted.format != 'PNG' or converted.mode != 'RGB' or
                converted.size != size or converted.tobytes() != pixels):
            raise ValueError('PNG export changed screenshot dimensions or pixel bytes')
    provenance = {
        'source': ppm.name, 'export': png.name,
        'operation': 'lossless PPM-to-PNG format export; no visual edits',
        'source_sha256': hashlib.sha256(ppm.read_bytes()).hexdigest(),
        'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
        'rgb_sha256': hashlib.sha256(pixels).hexdigest(), 'dimensions': list(size),
        'pixel_bytes_identical': True,
    }
    png.with_suffix('.png.provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
