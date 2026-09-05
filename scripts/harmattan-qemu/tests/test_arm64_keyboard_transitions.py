import copy
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/filename)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
MOTION=load('keyboard_motion_test','probe-arm64-keyboard-transitions.py')
ANIMATIONS=load('keyboard_handoff_test','arm64-animations.py')

class InputHandoffTests(unittest.TestCase):
    def test_public_x11_handoff_order_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'handoff'
            subprocess.run([shutil.which('clang'),'-O2','-Wall','-Wextra','-Werror',
                str(SCRIPTS/'tests/compositor-input-handoff-host.c'),str(SCRIPTS/'compositor-input-handoff-guest.c'),
                '-o',str(target)],check=True,capture_output=True)
            for mode in range(15):
                with self.subTest(mode=mode):
                    result=subprocess.run([str(target),str(mode)],capture_output=True)
                    self.assertEqual(result.returncode,125 if mode==7 else 0,result.stderr.decode())

    def test_runtime_requires_balanced_restore(self):
        prefix=b'N00_COMPOSITOR_INPUT_HANDOFF_'
        events=b''.join(prefix+b'PRESERVED id='+str(i).encode()+b' parent=20 input=30 reason=input-map\n'+
                        prefix+b'SHARED id='+str(i).encode()+b' parent=20 input=30 reason=parent-backing\n'+
                        prefix+b'RESTORED id='+str(i).encode()+b' parent=20 input=30 reason=direct\n' for i in (1,2))
        def wrap(value):return b'\nN00_ANIMATIONS_BEGIN\n'+value+b'N00_ANIMATIONS_END\n'
        self.assertTrue(ANIMATIONS.validate_input_handoff(wrap(events))['root_background_restored'])
        for bad in (events.rsplit(prefix,1)[0],events.replace(b'RESTORED id=2',b'RESTORED id=3'),
                    events.replace(prefix+b'SHARED id=1 parent=20 input=30 reason=parent-backing\n',b''),
                    events.replace(b'reason=direct',b'reason=timeout'),events+prefix+b'ERROR unknown\n'):
            with self.assertRaises(ValueError):ANIMATIONS.validate_input_handoff(wrap(bad))


def fixture():
    pixels=b'\xff'*(MOTION.PIXELS*3)
    digest=hashlib.sha256(pixels).hexdigest()
    frames={stage+'.ppm':MOTION.HEADER+pixels for stage in MOTION.STAGES}
    samples=[];operations=[]
    for i,stage in enumerate(MOTION.STAGES):
        begin=i*3
        operations.append(dict(stage=stage,begin=begin,end=begin+2.2))
        for j in range(30):
            sample=dict(stage=stage,start=begin+j*.075,end=begin+j*.075+.005,
                        relative=begin+j*.075+.005,rgb_sha256=digest)
            if j==0:sample['frame']=stage+'.ppm'
            samples.append(sample)
    return dict(samples=samples,operations=operations),frames

class KeyboardMotionTests(unittest.TestCase):
    def test_complete_observations_and_saved_pixels_required(self):
        data,frames=fixture()
        self.assertTrue(MOTION.summarize(data,frames)['passed'])
        for mutate in (lambda d:d['operations'][-1].pop('end'),lambda d:d['samples'].pop(0),
                       lambda d:d['samples'][3].update(rgb_sha256='0'*64),
                       lambda d:d['operations'][0].update(begin=1)):
            broken=copy.deepcopy(data);mutate(broken)
            with self.assertRaises(ValueError):MOTION.summarize(broken,frames)

    def test_full_and_partial_black_flash_fail(self):
        for fraction in (1,.3):
            data,frames=fixture()
            count=int(MOTION.PIXELS*fraction)
            rgb=bytes(count*3)+b'\xff'*((MOTION.PIXELS-count)*3)
            frames['flash.ppm']=MOTION.HEADER+rgb
            data['samples'][10].update(frame='flash.ppm',rgb_sha256=hashlib.sha256(rgb).hexdigest())
            data['samples'][11]['frame']='show.ppm'
            result=MOTION.summarize(data,frames)
            self.assertFalse(result['passed'])
            self.assertEqual(result['stages']['show']['excessive_black_samples'],1)

if __name__=='__main__':unittest.main()
