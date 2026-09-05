import importlib.util
import hashlib
from pathlib import Path
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('keyboard', SCRIPTS/'arm64-keyboard.py')
KEYBOARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KEYBOARD)


def process(name, pid):
    return f'Name:\t{name}\nState:\tS (sleeping)\nTgid:\t{pid}\nPid:\t{pid}\nPPid:\t1\nTracerPid:\t0\nUid:\t29999\t29999\t29999\t29999\n'


def service(pid=363):
    # Synthetic protocol fixture, never used as runtime evidence.
    files = {**KEYBOARD.LIBRARIES, f'/proc/{pid}/exe':KEYBOARD.LIBRARIES['/usr/bin/meego-im-uiserver']}
    return (f'\nN00_IME_BEGIN\nN00_IME_PID {pid}\n'+process('meego-im-uiserv',pid)+
            ''.join(f'{digest}  {path}\n' for path,digest in files.items())+
            'N00_IME_KEYBOARD_MAPPED\nN00_IME_ARGUMENTS meego-im-uiserver -use-self-composition -software -local-theme -graphicssystem raster \n'
            f'N00_IME_OWNER_BEGIN\nmethod return\n   uint32 {pid}\nN00_IME_OWNER_END\nN00_IME_ADDRESS_BEGIN\n'
            '   variant string "unix:abstract=/tmp/maliit-server/dbus-Abc123,guid=0123456789abcdef0123456789abcdef"\n'
            'N00_IME_ADDRESS_END\nN00_IME_END\n').encode()


def notes():
    data = b''
    for stage in KEYBOARD.STAGES:
        saved = stage in ('saved','again','returned')
        active = '00000010' if stage == 'returned' else '00000020'
        data += (f'\nN00_KEYBOARD_BEGIN_{stage}\nN00_NOTES_PID 400\n'+process('notes',400)+
                 f'{KEYBOARD.NOTES_MD5}  /usr/bin/notes\n{KEYBOARD.NOTES_MD5}  /proc/400/exe\n'
                 'QT_IM_MODULE=MInputContext\nN00_NOTES_INPUT_CONTEXT_MAPPED\n'+
                 f'N00_X11_ACTIVE id={active}\nN00_X11_WINDOW id=00000020 map=2 geometry=864x480+0+0 pid=400 class=6e6f746573004e6f74657300\n'+
                 ('N00_NOTES_TEXT_HEX 51656D75\n' if saved else '')+
                 f'N00_NOTES_COUNT {int(saved)}\nN00_KEYBOARD_EXIT_{stage}_0\nN00_KEYBOARD_DONE_{stage}\n').encode()
    return data


def frames():
    header = b'P6\n864 480\n255\n'
    output = {}
    for stage in KEYBOARD.STAGES:
        pixels = bytearray(b'\xff'*(864*480*3))
        color = 40 if stage == 'symbols' else 0
        if stage in ('editor','typed','deleted','symbols','again'):
            for y in range(480):
                start = (y*864+550)*3
                pixels[start:(y+1)*864*3] = bytes([color])*((864-550)*3)
        output[stage] = header+pixels
    return output


class KeyboardTests(unittest.TestCase):
    def test_original_service_identity_and_owner(self):
        self.assertTrue(KEYBOARD.validate_serial(service()*4)['same_instance'])
        for data in (service()*3, service()*4+b'\nN00_IME_BEGIN\n', service()*3+service(364),
                     (service()*4).replace(b'uint32 363', b'uint32 999'),
                     (service()*4).replace(b'-use-self-composition', b'-manual-redirection'),
                     (service()*4).replace(b'N00_IME_KEYBOARD_MAPPED', b''),
                     (service()*4).replace(b'29999',b'0'),
                     (service()*4).replace(KEYBOARD.LIBRARIES['/usr/bin/meego-im-uiserver'].encode(),b'0'*32)):
            with self.assertRaises(ValueError): KEYBOARD.validate_serial(data)

    def test_real_database_text_and_repaint_are_both_required(self):
        good_frames = frames()
        layout_hashes = {stage:hashlib.sha256(KEYBOARD.portrait_crop(good_frames[stage], (0,550,480,864))).hexdigest() for stage in KEYBOARD.LAYOUT_RGB}
        patch = mock.patch.object(KEYBOARD, 'LAYOUT_RGB', layout_hashes)
        patch.start()
        self.addCleanup(patch.stop)
        home = {'home_window':'00000010'}
        self.assertEqual(KEYBOARD.validate_notes(notes(),home,good_frames)['saved_text'],'Qemu')
        self.assertTrue(KEYBOARD.validate_notes(notes().replace(b'Name:\tnotes\nState:\tS',b'Name:\tnotes\nState:\tD',1),home,good_frames)['same_instance'])
        for data in (notes().replace(b'51656D75',b'51656D7578'),
                     notes().replace(b'N00_NOTES_COUNT 1',b'N00_NOTES_COUNT 0'),
                     notes().replace(b'QT_IM_MODULE=MInputContext',b''),
                     notes().replace(b'N00_KEYBOARD_EXIT_saved_0',b'N00_KEYBOARD_EXIT_saved_1')):
            with self.assertRaises(ValueError): KEYBOARD.validate_notes(data,home,good_frames)
        stale = bytearray(good_frames['typed'])
        stale[len(b'P6\n864 480\n255\n')+((479-20)*864+470)*3] = 0
        with self.assertRaises(ValueError): KEYBOARD.validate_notes(notes(),home,{**good_frames,'typed':bytes(stale)})
        with self.assertRaises(ValueError): KEYBOARD.validate_notes(notes(),home,{**good_frames,'symbols':good_frames['deleted']})

    def test_portrait_crop_matches_native_rotation(self):
        data=bytearray(b'P6\n864 480\n255\n'+b'\0'*(864*480*3))
        offset=len(b'P6\n864 480\n255\n')+((479-17)*864+29)*3
        data[offset:offset+3]=b'\x01\x02\x03'
        self.assertEqual(KEYBOARD.portrait_crop(bytes(data),(17,29,18,30)),b'\x01\x02\x03')
        with self.assertRaises(ValueError): KEYBOARD.portrait_crop(bytes(data)[:-1],(17,29,18,30))


if __name__ == '__main__': unittest.main()
