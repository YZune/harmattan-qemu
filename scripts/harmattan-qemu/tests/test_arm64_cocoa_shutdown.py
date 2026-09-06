from pathlib import Path
import os
import platform
import re
import subprocess
import tempfile
import unittest


def postimage(patch):
    """Read the new/context lines; the tested bodies are complete in their hunks."""
    return '\n'.join(line[1:] for line in patch.splitlines()
                     if line[:1] in ('+', ' ') and not line.startswith('+++'))


def body(source, marker):
    start = source.index(marker)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


@unittest.skipUnless(platform.system() == 'Darwin', 'requires native Cocoa dispatch queue')
class CocoaShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='cocoa-shutdown-')
        cls.addClassCleanup(cls.work.cleanup)
        work = Path(cls.work.name)
        source = Path(__file__).with_name('cocoa-shutdown-host.m')
        patch = source.parents[3] / 'ports/qemu-n00/qemu-9.1.3-n00-cocoa-shutdown.patch'
        code = postimage(patch.read_text())
        request = body(code, '- (NSApplicationTerminateReply)applicationShouldTerminate:') + '\n'
        # Apply the actual incremental method hunk to the tested old body.
        # The separate include-only hunk is supplied by the compiler below.
        increment = patch.with_name('qemu-9.1.3-n00-storage-shutdown.patch').read_text()
        applied = 0
        for hunk in re.split(r'^@@[^\n]*\n', increment, flags=re.M)[1:]:
            before = ''.join(line[1:] for line in hunk.splitlines(True) if line.startswith((' ', '-')))
            after = ''.join(line[1:] for line in hunk.splitlines(True) if line.startswith((' ', '+')))
            if before in request:
                request = request.replace(before, after, 1)
                applied += 1
        if applied != 1:
            raise ValueError('expected one complete storage shutdown method hunk')
        (work / 'shutdown-request.inc').write_text(request)
        completion = body(code, '    dispatch_async(dispatch_get_main_queue()')
        (work / 'shutdown-completion.inc').write_text(completion + ');\n')
        cls.binary = str(work / 'shutdown')
        compiled = subprocess.run(['clang', '-Wall', '-Wextra', '-Wno-unused-parameter',
                                   '-framework', 'Cocoa', '-I', str(work),
                                   '-include', str(patch.with_name('n00-storage-shutdown.h')), str(source),
                                   '-o', cls.binary], capture_output=True, text=True)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)

    def run_case(self, mode, status):
        env = os.environ.copy()
        env.pop('N00_COCOA_STORAGE_SHUTDOWN', None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request'
            if mode in ('persistent', 'storage-fail'):
                env['N00_COCOA_STORAGE_SHUTDOWN'] = str(path)
            if mode == 'storage-fail':
                path.write_bytes(b'keep')
            result = subprocess.run([self.binary, mode, str(status)], env=env,
                                    check=True, capture_output=True, text=True, timeout=5)
            if mode == 'persistent':
                self.assertEqual(path.read_bytes(), b'sync\n')
            if mode == 'storage-fail':
                self.assertEqual(path.read_bytes(), b'keep')
        self.assertIn('PASS:', result.stdout)

    def test_cancel_does_not_shutdown_or_release_input(self):
        self.run_case('cancel', 0)

    def test_repeated_ui_quit_waits_for_cleanup_and_keeps_status(self):
        for status in (0, 7):
            with self.subTest(status=status):
                self.run_case('ui', status)

    def test_qmp_guest_exit_has_no_pending_appkit_reply(self):
        for status in (0, 7):
            with self.subTest(status=status):
                self.run_case('remote', status)

    def test_persistent_quit_waits_for_controller_and_preserves_cleanup(self):
        self.run_case('persistent', 0)

    def test_failed_storage_request_keeps_guest_running(self):
        self.run_case('storage-fail', 0)
