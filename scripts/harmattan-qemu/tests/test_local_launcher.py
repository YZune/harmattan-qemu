import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('local_launcher', Path(__file__).resolve().parents[2] / 'create-local-launcher.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LocalLauncherTests(unittest.TestCase):
    def test_paths_are_literal_overrides_survive_and_arguments_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "a ' quoted $(touch UNEXPECTED) directory"
            scripts = root / 'scripts/harmattan-qemu'
            scripts.mkdir(parents=True)
            (scripts / 'run-arm64-ui.sh').write_text('printf "%s\\n" "$HARMATTAN_UI_BUILD_ROOT" "$HARMATTAN_UI_AUDIO" "$@"\n')
            command = root / 'Run N9.command'
            command.write_text(launcher.render(root, {'HARMATTAN_UI_BUILD_ROOT': root,
                                                       'HARMATTAN_PORT_WORKSPACE': root / 'fresh runs',
                                                       'HARMATTAN_UI_NETWORK': 'user'}, 'pulse'))
            env = {k: v for k, v in os.environ.items() if not k.startswith('HARMATTAN_')}
            result = subprocess.run(['/bin/sh', str(command)], env=env, check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(), ['Network: user; audio: pulse; browser: original', str(root), 'pulse'])
            self.assertTrue((root / 'fresh runs').is_dir())
            env['HARMATTAN_UI_BUILD_ROOT'] = 'explicit override'
            result = subprocess.run(['/bin/sh', str(command), '--network-diagnostic', 'one argument'],
                                    env=env, check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(), ['Network: user; audio: off; browser: original', 'explicit override', 'off',
                                                         '--network-diagnostic', 'one argument'])
            self.assertFalse((root / 'UNEXPECTED').exists())

    def test_separate_basic_shortcut_preserves_original_and_allows_explicit_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / 'scripts/harmattan-qemu'
            scripts.mkdir(parents=True)
            (scripts / 'run-arm64-ui.sh').write_text('printf "%s\\n" "$HARMATTAN_UI_BROWSER_MODE"\n')
            original = root / 'Run N9.command'
            original.write_bytes(b'original settings\n')
            basic = root / launcher.launcher_name('Run N9 Basic Web.command')
            launcher.write_launcher(basic, launcher.render(root, {
                'HARMATTAN_PORT_WORKSPACE': root / 'runs', 'HARMATTAN_UI_NETWORK': 'user',
                'HARMATTAN_UI_BROWSER_MODE': 'basic'}, 'off'))
            env = {k: v for k, v in os.environ.items() if not k.startswith('HARMATTAN_')}
            result = subprocess.run(['sh', str(basic)], env=env, check=True, capture_output=True, text=True)
            self.assertIn('webpage JavaScript is disabled', result.stdout)
            self.assertEqual(result.stdout.splitlines()[-1], 'basic')
            env['HARMATTAN_UI_BROWSER_MODE'] = 'original'
            result = subprocess.run(['sh', str(basic)], env=env, check=True, capture_output=True, text=True)
            self.assertNotIn('JavaScript is disabled', result.stdout)
            self.assertEqual(result.stdout.splitlines()[-1], 'original')
            self.assertEqual(original.read_bytes(), b'original settings\n')

    def test_shortcut_name_cannot_escape_output_directory(self):
        for name in ('../escape.command', '/tmp/escape.command', 'dir/escape.command',
                     'dir\\escape.command', '.command', 'name.sh', 'a\x00.command', 'a\n.command'):
            with self.subTest(name=name), self.assertRaises(argparse.ArgumentTypeError):
                launcher.launcher_name(name)

    def test_replacement_keeps_exact_original_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'Run N9.command'
            output.write_bytes(b'old launcher\n')
            with self.assertRaises(ValueError):
                launcher.write_launcher(output, 'new\n')
            backup = launcher.write_launcher(output, 'new\n', replace=True)
            self.assertEqual(backup.read_bytes(), b'old launcher\n')
            self.assertEqual(output.read_text(), 'new\n')
            self.assertEqual(output.stat().st_mode & 0o777, 0o755)
            link = root / 'link'; link.symlink_to(output)
            with self.assertRaises(ValueError):
                launcher.write_launcher(link, 'bad', replace=True)
            self.assertEqual(output.read_text(), 'new\n')

    def test_network_checks_the_plain_and_cocoa_binaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = ('qemu-system-arm', 'qemu-img', 'meson-info/intro-buildoptions.json',
                     'Harmattan N9.app/Contents/MacOS/qemu-system-arm')
            for name in files:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'old')
            launcher.validate_build(root, 'off', 'off')
            for name in (files[0], files[3]):
                with self.assertRaisesRegex(ValueError, 'networking patch'):
                    launcher.validate_build(root, 'user', 'off')
                (root / name).write_bytes(b'n00-smc91c111-window')
            launcher.validate_build(root, 'user', 'off')
            with self.assertRaisesRegex(ValueError, 'black frame'):
                launcher.validate_build(root, 'user', 'black')
