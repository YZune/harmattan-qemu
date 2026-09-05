from pathlib import Path
import platform
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
        (work / 'shutdown-request.inc').write_text(body(
            code, '- (NSApplicationTerminateReply)applicationShouldTerminate:') + '\n')
        completion = body(code, '    dispatch_async(dispatch_get_main_queue()')
        (work / 'shutdown-completion.inc').write_text(completion + ');\n')
        cls.binary = str(work / 'shutdown')
        compiled = subprocess.run(['clang', '-Wall', '-Wextra', '-Wno-unused-parameter',
                                   '-framework', 'Cocoa', '-I', str(work), str(source),
                                   '-o', cls.binary], capture_output=True, text=True)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)

    def run_case(self, mode, status):
        result = subprocess.run([self.binary, mode, str(status)],
                                check=True, capture_output=True, text=True, timeout=5)
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
