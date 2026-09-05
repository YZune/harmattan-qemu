"""Read the original boot movie from a private disk clone; never mount or edit it.

The small ext4 reader supports the pinned PR1.3 layout only, not arbitrary guest
filesystems. See https://www.kernel.org/doc/html/latest/filesystems/ext4/ .
No decoder, firmware, extracted movie, or debugfs is shipped with the app.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
import time

MOVIE = '/usr/share/MProgressIndicator/themes/opengl/MainAnimation_LowNoise.mp4'
MOVIE_SHA256 = '19e311e44e102c84d75fe921f6af3af212173a86cbb549714ee1118b8d4ea40a'
MAX_FILE = 2 * 1024**2


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


class Ext4:
    """4 KiB extents/direct blocks and 32-byte descriptors; no symlink traversal."""

    def __init__(self, stream, start, length):
        self.stream, self.start, self.length = stream, start, length
        sb = self.read(1024, 1024)
        if (sb[56:58] != b'\x53\xef' or u32(sb, 24) != 2 or
                struct.unpack_from('<H', sb, 88)[0] != 256 or
                u32(sb, 96) & ~4 != 0x242):  # filetype, extents, flex_bg
            raise ValueError('Boot movie requires the prepared PR1.3 ext4 layout')
        # Historical prepared disks can retain needs_recovery. We never replay
        # their journal: only the immutable movie's exact hash is accepted.
        self.blocks, self.inodes = u32(sb, 4), u32(sb, 0)
        self.per_group = u32(sb, 40)
        if not (0 < self.blocks * 4096 <= length and 0 < self.inodes <= 1048576 and
                0 < self.per_group <= self.inodes):
            raise ValueError('Invalid boot filesystem geometry')
        self.length = self.blocks * 4096

    def read(self, offset, size):
        if not (0 <= offset and 0 < size <= MAX_FILE and offset + size <= self.length):
            raise ValueError('Boot filesystem read outside its bounded partition')
        self.stream.seek(self.start + offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError('Truncated boot filesystem')
        return data

    def inode(self, number):
        if not 1 <= number <= self.inodes:
            raise ValueError('Boot filesystem inode out of range')
        group, slot = divmod(number - 1, self.per_group)
        table = u32(self.read(4096 + group * 32, 32), 8)
        if not table:
            raise ValueError('Missing boot filesystem inode table')
        return self.read(table * 4096 + slot * 256, 256)

    def contents(self, inode, kind):
        mode = struct.unpack_from('<H', inode)[0]
        size = u32(inode, 4) | (u32(inode, 108) << 32)
        if stat.S_IFMT(mode) != kind:
            raise ValueError('Boot path must use regular directories/files')
        if not 0 < size <= MAX_FILE:
            raise ValueError('Boot file/directory exceeds its size limit')
        if not u32(inode, 32) & 0x80000:
            # The original root directory predates extent allocation.
            if size > 12 * 4096 or kind != stat.S_IFDIR:
                raise ValueError('Unsupported boot filesystem block mapping')
            blocks = struct.unpack_from('<12I', inode, 40)[:(size + 4095) // 4096]
            if not all(blocks):
                raise ValueError('Sparse boot directory')
            return b''.join(self.read(block * 4096, 4096) for block in blocks)[:size]
        seen, extents = set(), []

        def walk(node, expected_depth=None):
            magic, count, maximum, depth = struct.unpack_from('<HHHH', node)
            if (magic != 0xf30a or not 0 < count <= maximum <= (len(node) - 12) // 12 or
                    depth > 2 or (expected_depth is not None and depth != expected_depth)):
                raise ValueError('Invalid boot filesystem extent tree')
            previous = -1
            for offset in range(12, 12 + count * 12, 12):
                logical = u32(node, offset)
                if logical <= previous:
                    raise ValueError('Unordered boot filesystem extents')
                previous = logical
                if depth:
                    block = u32(node, offset + 4) | (struct.unpack_from('<H', node, offset + 8)[0] << 32)
                    if not block or block in seen or len(seen) >= 128:
                        raise ValueError('Cyclic or oversized boot extent tree')
                    seen.add(block)
                    walk(self.read(block * 4096, 4096), depth - 1)
                else:
                    count_blocks, high, low = struct.unpack_from('<HHI', node, offset + 4)
                    if not 0 < count_blocks <= 32768 or not (low | high):
                        raise ValueError('Unwritten or missing boot extent')
                    extents.append((logical, count_blocks, low | (high << 32)))

        walk(inode[40:100])
        result = bytearray()
        blocks = (size + 4095) // 4096
        position = 0
        for logical, count, physical in extents:
            if logical != position or position + count > blocks:
                raise ValueError('Sparse, overlapping or oversized boot extents')
            result.extend(self.read(physical * 4096, count * 4096))
            position += count
        if position != blocks:
            raise ValueError('Incomplete boot file extents')
        return bytes(result[:size])

    def file(self, path):
        number = 2
        for component in path.strip('/').split('/'):
            if not component or component in ('.', '..'):
                raise ValueError('Invalid boot resource path')
            directory = self.contents(self.inode(number), stat.S_IFDIR)
            matches = []
            offset = 0
            while offset < len(directory):
                if offset + 8 > len(directory):
                    raise ValueError('Truncated boot directory entry')
                child, length, name_length = struct.unpack_from('<IHB', directory, offset)
                if (length < 8 or length % 4 or length > 4096 - offset % 4096 or
                        offset + length > len(directory) or name_length > length - 8):
                    raise ValueError('Invalid boot directory entry')
                name = directory[offset + 8:offset + 8 + name_length]
                if child and name == component.encode():
                    matches.append(child)
                offset += length
            if len(matches) != 1:
                raise ValueError(f'Missing or ambiguous original boot resource: {path}')
            number = matches[0]
        return self.contents(self.inode(number), stat.S_IFREG)


def read_movie(disk):
    with disk.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        mbr = stream.read(512)
        if not 512 <= size <= 32 * 1024**3 or len(mbr) != 512 or mbr[510:] != b'\x55\xaa':
            raise ValueError('Boot animation requires a prepared raw disk')
        partition = mbr[462:478]
        start, sectors = struct.unpack_from('<II', partition, 8)
        if partition[4] != 0x83 or not start or not sectors or (start + sectors) * 512 > size:
            raise ValueError('Invalid boot animation root partition')
        movie = Ext4(stream, start * 512, sectors * 512).file(MOVIE)
    if hashlib.sha256(movie).hexdigest() != MOVIE_SHA256:
        raise ValueError('Original PR1.3 boot movie SHA-256 mismatch')
    return movie


def remux_movie(movie):
    """Rewrap the pinned AVI's MPEG-4 packets as silent MP4, without decoding.

    Despite its .mp4 name, the retail file is RIFF/AVI with an MP3 stream.
    AVFoundation accepts its unchanged MPEG-4 video in an ISO media container.
    This is intentionally one known clip, not a general AVI/MP4 converter.
    """
    if hashlib.sha256(movie).hexdigest() != MOVIE_SHA256:
        raise ValueError('Cannot remux an unverified original boot movie')

    def chunks(start, end):
        while start < end:
            if start + 8 > end:
                raise ValueError('Truncated boot movie chunk')
            kind, length = struct.unpack_from('<4sI', movie, start)
            stop = start + 8 + length
            if stop + length % 2 > end:
                raise ValueError('Boot movie chunk exceeds container')
            yield kind, start + 8, stop
            start = stop + length % 2

    if movie[:4] != b'RIFF' or movie[8:12] != b'AVI ' or u32(movie, 4) + 8 != len(movie):
        raise ValueError('Unexpected original boot movie container')
    packets, keys = [], []
    for kind, start, stop in chunks(12, len(movie)):
        if kind == b'LIST' and movie[start:start + 4] == b'movi':
            packets = [movie[a:b] for tag, a, b in chunks(start + 4, stop) if tag == b'00dc']
        elif kind == b'idx1':
            if (stop - start) % 16:
                raise ValueError('Invalid original boot movie index')
            sample = 0
            for offset in range(start, stop, 16):
                tag, flags, _, _ = struct.unpack_from('<4sIII', movie, offset)
                if tag == b'00dc':
                    sample += 1
                    if flags & 16:
                        keys.append(sample)
    if len(packets) != 100 or not keys or keys[0] != 1:
        raise ValueError('Unexpected original boot video samples')
    config_end = packets[0].find(b'\x00\x00\x01\xb3')  # first group-of-VOP header
    if config_end != 45:
        raise ValueError('Unexpected original MPEG-4 decoder configuration')

    def box(kind, payload=b''):
        return struct.pack('>I4s', 8 + len(payload), kind) + payload

    def full(kind, payload=b'', flags=0):
        return box(kind, struct.pack('>I', flags) + payload)

    def integers(*values):
        return struct.pack('>' + 'I' * len(values), *values)

    def descriptor(tag, payload):
        # The known decoder descriptors are each shorter than 128 bytes.
        if len(payload) >= 128:
            raise ValueError('Oversized MPEG-4 descriptor')
        return bytes((tag, len(payload))) + payload

    ftyp = box(b'ftyp', b'isom' + integers(512) + b'isomiso2mp41')
    mdat = box(b'mdat', b''.join(packets))
    matrix = integers(65536, 0, 0, 0, 65536, 0, 0, 0, 0x40000000)
    duration = 100 * 1001
    mvhd = full(b'mvhd', integers(0, 0, 24000, duration, 65536) +
                struct.pack('>H10x', 256) + matrix + bytes(24) + integers(2))
    tkhd = full(b'tkhd', integers(0, 0, 1, 0, duration) + bytes(16) + matrix +
                integers(854 << 16, 480 << 16), flags=3)
    mdhd = full(b'mdhd', integers(0, 0, 24000, duration) + struct.pack('>HH', 0x55c4, 0))
    hdlr = full(b'hdlr', integers(0) + b'vide' + bytes(12) + b'VideoHandler\0')
    config = descriptor(4, b'\x20\x11' + max(map(len, packets)).to_bytes(3, 'big') +
                        bytes(8) + descriptor(5, packets[0][:config_end]))
    esds = full(b'esds', descriptor(3, b'\x00\x01\x00' + config + descriptor(6, b'\x02')))
    entry = (struct.pack('>6xH16xHHIIIH', 1, 854, 480, 0x480000, 0x480000, 0, 1) +
             bytes(32) + struct.pack('>HH', 24, 65535) + esds)
    stbl = box(b'stbl', full(b'stsd', integers(1) + box(b'mp4v', entry)) +
               full(b'stts', integers(1, len(packets), 1001)) +
               full(b'stsc', integers(1, 1, len(packets), 1)) +
               full(b'stsz', integers(0, len(packets), *map(len, packets))) +
               full(b'stco', integers(1, len(ftyp) + 8)) + full(b'stss', integers(len(keys), *keys)))
    dinf = box(b'dinf', full(b'dref', integers(1) + full(b'url ', flags=1)))
    minf = box(b'minf', full(b'vmhd', bytes(8), flags=1) + dinf + stbl)
    trak = box(b'trak', tkhd + box(b'mdia', mdhd + hdlr + minf))
    return ftyp + mdat + box(b'moov', mvhd + trak)


def prepare(disk, directory, rotation):
    if rotation not in (0, 90, 180, 270):
        raise ValueError('Invalid boot animation rotation')
    movie = read_movie(disk)
    playback = remux_movie(movie)
    directory.mkdir(mode=0o700, exist_ok=False)
    (directory / 'movie.mp4').write_bytes(playback)
    return {'N00_COCOA_BOOT_ANIMATION': str(directory), 'N00_COCOA_BOOT_ROTATION': str(rotation)}, {
        'enabled': True, 'guest_resource': MOVIE, 'sha256': MOVIE_SHA256,
        'playback_sha256': hashlib.sha256(playback).hexdigest(),
        'scope': 'original MPEG-4 packets remuxed from AVI to silent MP4; guest framebuffer and startup checks unchanged'}


def signal(directory, state):
    if state not in ('play', 'ready'):
        raise ValueError('Invalid boot presentation state')
    temporary = directory / '.phase'
    temporary.write_text(state + '\n')
    temporary.replace(directory / 'phase')


def reveal(directory, drain):
    signal(directory, 'ready')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if (directory / 'failed').exists():
            raise ValueError('Native boot animation failed; inspect boot/failed')
        acknowledged = directory / 'revealed'
        if acknowledged.exists() and acknowledged.read_text() == 'ready\n':
            return
        drain(0.05)
    raise ValueError('Native boot presentation did not acknowledge desktop reveal')
