from pathlib import Path
import platform
import subprocess
import tempfile
import unittest


@unittest.skipUnless(platform.system() == 'Darwin', 'requires native AppKit')
class N9SkinTests(unittest.TestCase):
    def test_native_view_glass_hits_coordinates_and_black_matte(self):
        source = Path(__file__).with_name('n9-skin-host.m')
        with tempfile.TemporaryDirectory(prefix='n9-skin-') as work:
            binary = str(Path(work) / 'geometry')
            subprocess.run(['clang', '-Wall', '-Wextra', '-Wno-unused-parameter',
                            '-Wno-unused-variable', '-framework', 'Cocoa',
                            '-framework', 'QuartzCore', str(source), '-o', binary],
                           check=True, capture_output=True)
            result = subprocess.run([binary], check=True, capture_output=True, text=True)
            self.assertIn('PASS: 30 native view layouts', result.stdout)


if __name__ == '__main__':
    unittest.main()
