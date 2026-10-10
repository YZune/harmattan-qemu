"""Private experiment protocol checks. Synthetic frames do not prove guest UI."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

BRIDGE = load('linux-live-bridge')
SHELL = load('diagnose-arm64-shell')

class FakeQMP:
    def __init__(self):
        self.calls = []
        self.process = SimpleNamespace(poll=lambda: None)
        self.pixels = bytes((19, 63, 211)) * (480 * 864)
        self.fail_capture = False
    def call(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == 'screendump':
            if self.fail_capture:
                raise RuntimeError('capture failure')
            Path(arguments['filename']).write_bytes(b'P6\n480 864\n255\n' + self.pixels)

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = BRIDGE.Session(Path(self.temp.name) / 'session')
        self.qmp = FakeQMP()
        self.session.qmp = self.qmp
        self.heartbeat()
    def tearDown(self):
        self.session.stop_startup_heartbeat()
        self.temp.cleanup()
    def event(self, seq=1, **values):
        return dict(controller_id=self.session.controller_id, client_id='testclient1234', seq=seq,
                    created_ms=int(time.time() * 1000)) | values
    def heartbeat(self, age=0, **values):
        value = dict(controller_id=self.session.controller_id, client_id='testclient1234',
                     updated_ms=int((time.time() - age) * 1000)) | values
        target = self.session.directory / ('heartbeat.' + value['client_id'] + '.json')
        BRIDGE.atomic_json(target, value)
        if age:
            os.utime(target, (time.time() - age, time.time() - age))
        return target
    def audit(self):
        return [json.loads(line) for line in (self.session.directory / 'input-audit.jsonl').read_text().splitlines()]
    def write(self, event):
        target = self.session.events / ('%s.%020d.json' % (event['client_id'], event['seq']))
        BRIDGE.atomic_json(target, event)
        return target
    def measured_session(self):
        self.session = BRIDGE.Session(Path(self.temp.name) / 'measured', metrics=True)
        self.session.qmp = self.qmp
        self.heartbeat()
    def performance(self, kind):
        return [record for line in (self.session.directory / 'performance.jsonl').read_text().splitlines()
                if (record := json.loads(line))['kind'] == kind]
    def observe_layout(self, layout):
        self.session.state['keyboard_layout'] = layout
        self.session.state['frame_counter'] += 1
    def due_step(self):
        with patch.object(BRIDGE.time, 'monotonic', return_value=self.session.next_step):
            self.session.step()
    def contacts(self):
        return [(args['events'][0]['data']['value'], args['events'][1]['data']['value'])
                for name, args in self.qmp.calls if name == 'input-send-event' and args['events'][-1]['data']['down']]
    def test_owned_private_directories_and_startup_gate(self):
        self.assertEqual(self.session.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.session.events.stat().st_mode & 0o777, 0o700)
        status = json.loads((self.session.directory / 'status.json').read_text())
        self.assertFalse(status['ready'])
        self.assertEqual(status['frame_counter'], 0)
        self.assertNotIn('storage', status)
        unprivate = Path(self.temp.name) / 'unprivate'
        unprivate.mkdir(mode=0o755)
        with self.assertRaises(ValueError): BRIDGE.Session(unprivate)
    def test_storage_notice_maps_prior_exit_without_changing_readiness_or_errors(self):
        self.session.state.update(error='existing error', key_error='existing key error')
        for profile, expected in (
                (None, {'mode': 'disposable', 'previous_exit_unclean': False}),
                (SimpleNamespace(previous_exit_unclean=False, state={'state': 'active'}),
                 {'mode': 'persistent', 'previous_exit_unclean': False}),
                (SimpleNamespace(previous_exit_unclean=True, state={'state': 'active'}),
                 {'mode': 'persistent', 'previous_exit_unclean': True})):
            with self.subTest(storage=expected):
                SHELL.publish_storage_notice(self.session, profile)
                status = json.loads((self.session.directory / 'status.json').read_text())
                self.assertEqual(status['storage'], expected)
                self.assertFalse(status['ready'])
                self.assertEqual(status['state'], 'starting')
                self.assertEqual(status['frame_counter'], 0)
                self.assertEqual(status['error'], 'existing error')
                self.assertEqual(status['key_error'], 'existing key error')
        self.session.finish(passed=False, error='startup failed')
        status = json.loads((self.session.directory / 'status.json').read_text())
        self.assertEqual(status['storage'], {'mode': 'persistent', 'previous_exit_unclean': True})
        self.assertEqual(status['state'], 'error')
        self.assertEqual(status['error'], 'startup failed')
        # Cocoa has no live bridge and need not inspect a profile notice.
        SHELL.publish_storage_notice(None, object())
    def test_storage_notice_rejects_invalid_values_without_publishing(self):
        original = (self.session.directory / 'status.json').read_bytes()
        for mode, previous in (('unknown', False), ('persistent', 1), ('persistent', 'false'),
                               ('persistent', None), ('disposable', True)):
            with self.subTest(mode=mode, previous=previous), self.assertRaises(ValueError):
                self.session.set_storage(mode=mode, previous_exit_unclean=previous)
            self.assertNotIn('storage', self.session.state)
            self.assertEqual((self.session.directory / 'status.json').read_bytes(), original)
    def test_existing_private_session_cannot_acquire_a_second_owner(self):
        original = (self.session.directory / 'status.json').read_bytes()
        self.write(self.event(type='release'))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            BRIDGE.Session(self.session.directory)
        self.assertEqual((self.session.directory / 'status.json').read_bytes(), original)
        self.assertEqual(len(list(self.session.events.glob('*.json'))), 1)
        unused = Path(self.temp.name) / 'existing-private'
        unused.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            BRIDGE.Session(unused)
        link = Path(self.temp.name) / 'session-link'
        link.symlink_to(self.session.directory, target_is_directory=True)
        with self.assertRaises(ValueError): BRIDGE.Session(link)
    def test_startup_heartbeat_is_fresh_without_claiming_guest_readiness(self):
        original = json.loads((self.session.directory / 'status.json').read_text())
        self.session.start_startup_heartbeat()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = json.loads((self.session.directory / 'status.json').read_text())
            if current['updated_ms'] > original['updated_ms']:
                break
            time.sleep(.05)
        else:
            self.fail('startup heartbeat did not refresh')
        self.assertFalse(current['ready'])
        self.assertEqual(current['state'], 'starting')
        self.assertEqual(current['frame_counter'], 0)
        self.assertEqual(current['frame_updated_ms'], 0)
        self.assertFalse((self.session.directory / 'frame.png').exists())
        self.session.stop_startup_heartbeat()
        self.assertFalse(self.session.heartbeat_thread.is_alive())
    def test_order_replay_and_controller_identity(self):
        self.write(self.event(2, type='release'))
        self.write(self.event(1, type='release'))
        event = self.session.next_event()
        self.assertEqual(event['seq'], 1)
        self.session.begin(event)
        event = self.session.next_event()
        self.assertEqual(event['seq'], 2)
        self.session.begin(event)
        self.write(self.event(1, type='pointer', action='down', x=10, y=10))
        self.assertIsNone(self.session.next_event())
        self.assertFalse(self.qmp.calls)
        self.assertEqual(self.session.state['event_ack'], 2)
        wrong = self.event(999, type='quit')
        wrong['controller_id'] = 'old-controller'
        self.write(wrong)
        self.assertIsNone(self.session.next_event())
        self.assertEqual(self.session.state['event_ack'], 2)
    def test_sequence_gap_releases_touch_and_rejects(self):
        self.session.begin(self.event(type='pointer', action='down', x=0, y=420))
        self.write(self.event(3, type='pointer', action='move', x=100, y=420))
        self.assertIsNone(self.session.next_event())
        self.assertFalse(self.session.down)
        self.assertEqual(self.session.state['event_result'], 'rejected')
        self.assertIn('sequence gap', self.session.state['key_error'])
    def test_input_transform_and_release_on_focus_loss(self):
        self.session.begin(self.event(type='pointer', action='down', x=479, y=863))
        self.assertEqual(self.qmp.calls[0][1]['events'], [
            {'type': 'abs', 'data': {'axis': 'x', 'value': 32767}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': 32767}},
            {'type': 'btn', 'data': {'button': 'left', 'down': True}}])
        self.session.begin(self.event(2, type='release'))
        self.assertFalse(self.session.down)
        self.assertFalse(self.qmp.calls[-1][1]['events'][-1]['data']['down'])
        for x in (-1, 480, 10 ** 400, float('nan'), True, '3'):
            with self.assertRaises(ValueError): BRIDGE.pointer_events(x, 1, True)
    def test_native_click_keeps_contact_until_guest_can_observe_it(self):
        self.session.begin(self.event(type='pointer', action='down', x=70, y=827))
        self.session.begin(self.event(2, type='pointer', action='up', x=70, y=827))
        self.assertTrue(self.session.down)
        self.assertEqual(self.session.state['event_ack'], 1)
        with patch.object(BRIDGE.time, 'monotonic', return_value=self.session.press_started + .09):
            self.session.step()
            self.session.step()
        self.assertFalse(self.session.down)
        self.assertEqual(self.session.state['event_ack'], 2)
    def test_lost_client_heartbeat_releases_touch(self):
        self.session.begin(self.event(type='pointer', action='down', x=20, y=20))
        self.heartbeat(age=4)
        self.session.check_pointer_liveness()
        self.assertFalse(self.session.down)
        self.assertIn('heartbeat lost', self.session.state['key_error'])
    def test_fresh_heartbeat_preserves_deliberately_held_touch(self):
        event = self.event(type='pointer', action='down', x=20, y=20)
        self.session.begin(event)
        self.session.pointer_updated = time.monotonic() - 4
        self.heartbeat()
        self.session.check_pointer_liveness()
        self.assertTrue(self.session.down)
    def test_new_input_needs_fresh_matching_heartbeat_but_release_does_not(self):
        heartbeat = self.heartbeat()
        heartbeat.unlink()
        self.session.begin(self.event(type='release'))
        self.assertEqual(self.session.state['event_ack'], 1)
        invalid = ({}, {'controller_id': 'previous-controller'},
                   {'updated_ms': int((time.time() + 60) * 1000)},
                   {'updated_ms': 10 ** 400}, {'updated_ms': True})
        for sequence, fields in enumerate(invalid, 2):
            with self.subTest(fields=fields):
                if fields:
                    self.heartbeat(**fields)
                self.write(self.event(sequence, type='key', key='q'))
                self.assertIsNone(self.session.next_event())
                self.assertIn('heartbeat lost', self.session.state['key_error'])
                self.assertFalse(self.qmp.calls)
        self.heartbeat(age=4)
        self.write(self.event(len(invalid) + 2, type='pointer', action='down', x=1, y=1))
        self.assertIsNone(self.session.next_event())
        self.assertFalse(self.session.down)
    def test_client_death_cancels_pending_keyboard_and_rejects_queued_input(self):
        self.session.begin(self.event(type='key', key='q'))
        self.session.step()
        self.assertIsNotNone(self.session.pending)
        self.write(self.event(2, type='pointer', action='down', x=20, y=20))
        self.heartbeat(age=4)
        self.session.check_pointer_liveness()
        self.assertIsNone(self.session.pending)
        self.assertFalse(self.session.steps)
        self.assertEqual(self.session.state['event_ack'], 1)
        self.assertEqual(self.session.state['event_result'], 'rejected')
        self.assertIsNone(self.session.next_event())
        self.assertEqual(self.session.state['event_ack'], 2)
        self.assertFalse(self.qmp.calls)
    def test_client_death_during_pending_gesture_releases_and_never_represses(self):
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.step()
        self.assertTrue(self.session.down)
        self.heartbeat(age=4)
        self.session.step()
        self.assertFalse(self.session.down)
        self.assertIsNone(self.session.pending)
        self.assertFalse(self.session.steps)
        count = len(self.qmp.calls)
        self.session.step()
        self.assertEqual(len(self.qmp.calls), count)
        self.assertEqual([item['accepted'] for item in self.audit()], [False])
    def test_expired_future_and_malformed_timestamps_never_execute(self):
        now = int(time.time() * 1000)
        invalid = (now - 9000, now + 60_000, 10 ** 400, None, True, '1000', 1.5, -1)
        for sequence, created in enumerate(invalid, 1):
            with self.subTest(created=created):
                self.write(self.event(sequence, type='key', key='q', created_ms=created))
                self.assertIsNone(self.session.next_event())
                self.assertEqual(self.session.state['event_result'], 'rejected')
                self.assertEqual(self.session.state['event_ack'], sequence)
        self.assertFalse(self.qmp.calls)
        self.assertIsNone(self.session.pending)
        self.write(self.event(len(invalid) + 1, type='pointer', action='down', x=20, y=20,
                              created_ms=now - 9000))
        self.assertIsNone(self.session.next_event())
        self.assertFalse(self.qmp.calls)
    def test_pending_work_is_rechecked_for_expiry(self):
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.pending['created_ms'] -= 9000
        self.session.step()
        self.assertIsNone(self.session.pending)
        self.assertFalse(self.qmp.calls)
        self.assertIn('expired', self.session.state['key_error'])
    def test_keyboard_is_real_touch_and_requires_recognized_layout(self):
        self.session.begin(self.event(type='key', key='q'))
        with patch.object(BRIDGE.time, 'monotonic', return_value=time.monotonic() + 3):
            self.session.step()
        self.assertEqual(self.session.state['event_result'], 'rejected')
        self.assertFalse(self.qmp.calls)
        self.session.state['keyboard_layout'] = 'lower'
        self.session.begin(self.event(2, type='key', key='q'))
        self.session.step()
        self.session.step()
        self.assertTrue(self.session.down)
        self.assertEqual(self.session.point, (24, 590))
        for key in ('Delete', '中', '1', 'F5'):
            self.session.release()
            with self.assertRaises(ValueError): self.session.begin(self.event(3, type='key', key=key))
    def test_uppercase_letter_waits_for_auto_lower_before_next_text(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='L'))
        queued = self.write(self.event(2, type='key', key='i'))
        for _ in range(3):
            self.due_step()  # Plan, contact, release.
        released = self.session.next_step - .18
        for delay in (.18, .24, .40, .50):
            self.observe_layout('upper')
            with patch.object(BRIDGE.time, 'monotonic', return_value=released + delay):
                self.session.step()
            self.assertIsNotNone(self.session.pending)
            self.assertIsNone(self.session.next_event())
            self.assertTrue(queued.exists())
            self.assertEqual(len(self.contacts()), 1)
        self.observe_layout('unknown')
        self.due_step()
        self.observe_layout('lower')
        with patch.object(BRIDGE.time, 'monotonic', return_value=released + .61):
            self.session.step()
            self.session.begin(self.session.next_event())
        for _ in range(4):
            self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [True, True])
        self.assertEqual(self.contacts(), [(round(x * 32767 / 479), round(y * 32767 / 863))
                                          for x, y in ((432, 670), (360, 590))])
        self.assertIsNone(self.session.layout_transition)
    def test_initial_lowercase_sends_shift_once_and_waits_for_desired_layout(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        self.due_step()
        self.due_step()
        self.assertAlmostEqual(self.session.next_step - self.session.press_started, .10)
        self.due_step()
        released = self.session.next_step - .30
        for delay, layout in ((.30, 'upper'), (.40, 'upper'), (.50, 'unknown'), (.60, 'upper')):
            self.observe_layout(layout)
            with patch.object(BRIDGE.time, 'monotonic', return_value=released + delay):
                self.session.step()
            self.assertEqual(len(self.contacts()), 1)
            self.assertFalse(self.session.down)
        self.observe_layout('lower')
        self.due_step()
        for _ in range(3):
            self.due_step()
        self.assertTrue(self.audit()[0]['accepted'])
        self.assertEqual(self.contacts(), [(round(x * 32767 / 479), round(y * 32767 / 863))
                                          for x, y in ((32, 750), (48, 670))])
    def test_uppercase_uppercase_waits_for_lower_then_one_shift(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='Q'))
        self.write(self.event(2, type='key', key='W'))
        for _ in range(3):
            self.due_step()
        self.observe_layout('upper')
        self.due_step()
        self.assertIsNone(self.session.next_event())
        self.observe_layout('lower')
        self.due_step()
        self.session.begin(self.session.next_event())
        for _ in range(3):
            self.due_step()
        for layout in ('lower', 'unknown', 'lower'):
            self.observe_layout(layout)
            self.due_step()
            self.assertEqual(len(self.contacts()), 2)
        self.observe_layout('upper')
        for _ in range(3):
            self.due_step()
        self.observe_layout('lower')
        self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [True, True])
        self.assertEqual([x for x, _ in self.contacts()], [round(x * 32767 / 479) for x in (24, 32, 72)])
    def test_expected_layout_seen_before_release_cannot_clear_transition(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='Q'))
        self.due_step()
        self.due_step()
        self.observe_layout('lower')  # The contact has not been released yet.
        self.due_step()
        self.due_step()
        self.assertIsNotNone(self.session.pending)
        self.assertIsNotNone(self.session.layout_transition)
        self.observe_layout('lower')
        self.due_step()
        self.assertTrue(self.audit()[0]['accepted'])
    def test_unconfirmed_shift_times_out_without_repeat_or_letter(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        expires = self.session.steps[0][2]
        for _ in range(3):
            self.due_step()
        for layout in ('upper', 'unknown', 'upper', 'unknown'):
            self.observe_layout(layout)
            self.due_step()
            self.assertEqual(len(self.contacts()), 1)
        self.observe_layout('lower')  # Even a desired frame cannot revive an expired request.
        with patch.object(BRIDGE.time, 'monotonic', return_value=expires):
            self.session.step()
        self.assertFalse(self.audit()[0]['accepted'])
        self.assertIn('case transition', self.audit()[0]['message'])
        self.assertFalse(self.session.steps)
        self.assertIsNotNone(self.session.layout_transition)
        self.session.step()
        self.assertEqual(len(self.contacts()), 1)
    def test_unsettled_uppercase_times_out_with_uncertain_completion_and_guard(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='L'))
        for _ in range(3):
            self.due_step()
        expires = self.session.layout_transition['expires']
        self.observe_layout('unknown')  # Includes an unrecognized Caps-lock state.
        self.due_step()
        with patch.object(BRIDGE.time, 'monotonic', return_value=expires):
            self.session.step()
        self.assertIn('completion is uncertain', self.audit()[0]['message'])
        self.assertFalse(self.audit()[0]['accepted'])
        self.session.begin(self.event(2, type='key', key='i'))
        self.observe_layout('upper')
        self.due_step()
        self.assertEqual(len(self.contacts()), 1)
        self.assertIsNotNone(self.session.layout_transition)
        self.observe_layout('lower')
        for _ in range(4):
            self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [False, True])
        self.assertEqual(len(self.contacts()), 2)
    def test_cancelled_shift_keeps_only_passive_guard_for_new_text(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        self.due_step()
        self.due_step()  # Cancel while the single Shift contact is held.
        self.observe_layout('lower')
        self.session.begin(self.event(2, type='cancel'))
        self.assertFalse(self.session.down)
        self.assertFalse(self.session.steps)
        self.assertIsNone(self.session.pending)
        self.session.begin(self.event(3, type='release'))
        self.assertIsNotNone(self.session.layout_transition)
        self.session.begin(self.event(4, type='key', key='b'))
        self.due_step()  # A pre-release desired frame is still stale.
        self.observe_layout('upper')
        self.due_step()
        self.assertEqual(len(self.contacts()), 1)
        self.observe_layout('lower')
        for _ in range(4):
            self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [False, True, True, True])
        self.assertEqual([x for x, _ in self.contacts()], [round(x * 32767 / 479) for x in (32, 288)])
    def test_cancelled_uppercase_keeps_guard_without_replaying_letter(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='L'))
        for _ in range(3):
            self.due_step()
        self.session.begin(self.event(2, type='cancel'))
        self.observe_layout('lower')
        self.session.step()
        self.assertEqual(len(self.contacts()), 1)
        self.assertIsNotNone(self.session.layout_transition)
        self.session.begin(self.event(3, type='key', key='i'))
        for _ in range(4):
            self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [False, True, True])
        self.assertEqual(len(self.contacts()), 2)
    def test_cancelled_transition_observed_while_idle_does_not_guard_reopened_keyboard(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        for _ in range(3):
            self.due_step()
        self.session.begin(self.event(2, type='cancel'))
        digest = BRIDGE.hashlib.sha256(self.qmp.pixels[550 * 480 * 3:]).hexdigest()
        with patch.dict(BRIDGE.LAYOUTS, {digest: 'upper'}):
            self.session.capture()
        self.assertIsNotNone(self.session.layout_transition)
        with patch.dict(BRIDGE.LAYOUTS, {digest: 'lower'}):
            self.session.capture()
        self.assertIsNone(self.session.layout_transition)
        self.assertEqual(len(self.contacts()), 1)
        with patch.dict(BRIDGE.LAYOUTS, {digest: 'upper'}):
            self.session.capture()  # A newly opened editor can auto-capitalize.
        self.session.begin(self.event(3, type='key', key='b'))
        for _ in range(3):
            self.due_step()
        self.assertEqual(len(self.contacts()), 2)  # One Shift for each explicit request.
        self.observe_layout('lower')
        for _ in range(4):
            self.due_step()
        self.assertEqual([record['accepted'] for record in self.audit()], [False, True, True])
        self.assertEqual([x for x, _ in self.contacts()], [round(x * 32767 / 479) for x in (32, 32, 288)])
    def test_lost_heartbeat_during_case_wait_releases_and_preserves_guard(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        self.due_step()
        self.due_step()
        self.heartbeat(age=4)
        self.session.step()
        self.assertFalse(self.session.down)
        self.assertFalse(self.session.steps)
        self.assertIsNone(self.session.pending)
        self.assertIsNotNone(self.session.layout_transition)
        self.heartbeat()
        self.session.begin(self.event(2, type='key', key='b'))
        self.observe_layout('upper')
        self.due_step()
        self.assertEqual(len(self.contacts()), 1)
    def test_event_expiry_during_case_wait_never_sends_letter(self):
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        for _ in range(3):
            self.due_step()
        self.session.pending['created_ms'] -= 9000
        self.observe_layout('lower')
        self.due_step()
        self.assertFalse(self.session.steps)
        self.assertIsNone(self.session.pending)
        self.assertIn('expired', self.audit()[0]['message'])
        self.assertEqual(len(self.contacts()), 1)
    def test_escape_is_right_edge_gesture_and_quit_releases(self):
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.step()
        self.assertEqual(self.session.point, (479, 420))
        self.assertEqual(self.session.steps[-1][1:4], (59, 420, False))
        self.assertFalse(self.session.begin(self.event(2, type='quit')))
        self.assertFalse(self.session.down)
        self.assertEqual(self.session.state['state'], 'stopping')
        self.assertEqual(self.session.state['event_ack'], 2)
        self.assertIsNone(self.session.pending)
        self.assertFalse(self.session.steps)
    def test_cancel_preempts_pending_keyboard_and_cancels_queued_prefix(self):
        self.session.begin(self.event(type='key', key='q'))
        for sequence in range(2, 12):
            self.write(self.event(sequence, type='key', key='w'))
        self.write(self.event(12, type='cancel', created_ms=int((time.time() - 60) * 1000)))
        # Controls are found even while a key is waiting for its two-second
        # layout deadline. All skipped sequences have explicit rejected acks.
        event = self.session.next_event()
        self.assertEqual(event['seq'], 12)
        self.assertTrue(self.session.begin(event))
        records = self.audit()
        self.assertEqual([item['event']['seq'] for item in records], list(range(1, 13)))
        self.assertEqual([item['accepted'] for item in records], [False] * 11 + [True])
        self.assertTrue(all('cancelled' in item['message'] for item in records[:-1]))
        self.assertIsNone(self.session.pending)
        self.assertFalse(self.session.steps)
        self.assertFalse(list(self.session.events.glob('*.json')))
        self.assertFalse(self.qmp.calls)
    def test_consecutive_release_key_pairs_preserve_every_typed_key(self):
        self.session.state['keyboard_layout'] = 'lower'
        for sequence, key in enumerate('qwe', 1):
            self.write(self.event(sequence * 2 - 1, type='release'))
            self.write(self.event(sequence * 2, type='key', key=key))
        for sequence in range(1, 7):
            event = self.session.next_event()
            self.assertEqual(event['seq'], sequence)
            self.session.begin(event)
            if event['type'] == 'key':
                # The next ordinary release is a keyboard ordering barrier,
                # not a request to discard this key or any subsequent text.
                self.assertIsNone(self.session.next_event())
                for _ in range(4):
                    with patch.object(BRIDGE.time, 'monotonic', return_value=self.session.next_step):
                        self.session.step()
                self.assertIsNone(self.session.pending)
        records = self.audit()
        self.assertEqual([item['event']['seq'] for item in records], list(range(1, 7)))
        self.assertTrue(all(item['accepted'] for item in records))
        contacts = [args['events'] for name, args in self.qmp.calls
                    if name == 'input-send-event' and args['events'][-1]['data']['down']]
        self.assertEqual([events[0]['data']['value'] for events in contacts],
                         [round(x * 32767 / 479) for x in (24, 72, 120)])
    def test_quit_preempts_held_gesture_and_later_input_is_not_executed(self):
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.step()
        self.write(self.event(2, type='key', key='q'))
        self.write(self.event(3, type='quit', created_ms=0))
        later = self.write(self.event(4, type='pointer', action='down', x=100, y=100))
        event = self.session.next_event()
        self.assertEqual(event['seq'], 3)
        self.assertFalse(self.session.begin(event))
        self.assertFalse(self.session.down)
        self.assertIsNone(self.session.pending)
        self.assertTrue(later.exists())
        self.assertEqual(self.session.state['state'], 'stopping')
        self.assertEqual([item['accepted'] for item in self.audit()], [False, False, True])
        self.assertEqual(len(self.qmp.calls), 2)
    def test_run_handles_quit_before_advancing_pending_gesture(self):
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.step()
        self.write(self.event(2, type='key', key='q'))
        self.write(self.event(3, type='quit'))
        def unexpected_work(*args):
            self.fail('Quit must finish before draining or validating another loop')
        self.session.run(self.qmp, unexpected_work, time.monotonic() + 2, unexpected_work)
        pointer_calls = [args for name, args in self.qmp.calls if name == 'input-send-event']
        self.assertEqual(len(pointer_calls), 2)
        self.assertTrue(pointer_calls[0]['events'][-1]['data']['down'])
        self.assertFalse(pointer_calls[1]['events'][-1]['data']['down'])
        self.assertFalse(self.session.state['ready'])
        self.assertEqual(self.session.state['event_ack'], 3)
    def test_invalid_urgent_events_cannot_skip_pending_sequence(self):
        self.session.begin(self.event(type='key', key='q'))
        invalid = (self.event(3, type='quit'),
                   self.event(2, type='quit', controller_id='wrong-controller'),
                   self.event(2, type='quit', created_ms=int((time.time() + 60) * 1000)),
                   self.event(2, type='quit', created_ms=None))
        for event in invalid:
            with self.subTest(event=event):
                path = self.write(event)
                self.assertIsNone(self.session.next_event())
                self.assertIsNotNone(self.session.pending)
                self.assertEqual(self.session.state['event_ack'], 0)
                self.assertNotEqual(self.session.state['state'], 'stopping')
                path.unlink()
        malformed = self.write(self.event(2, type='key', key='q'))
        malformed.write_text('{"controller_id":"unfinished')
        self.write(self.event(3, type='quit'))
        self.assertIsNone(self.session.next_event())
        self.assertIsNotNone(self.session.pending)
        self.assertFalse(self.qmp.calls)
    def test_control_cancellation_preserves_other_client_queue(self):
        self.session.begin(self.event(type='key', key='q'))
        other = self.write(self.event(1, type='key', key='w', client_id='anotherclient'))
        self.write(self.event(2, type='cancel'))
        event = self.session.next_event()
        self.session.begin(event)
        self.assertTrue(other.exists())
        self.assertNotIn('anotherclient', self.session.acks)
    def test_startup_quit_cancels_without_a_qmp_or_guest_launch(self):
        self.session.qmp = None
        self.session.start_startup_heartbeat()
        self.write(self.event(type='pointer', action='down', x=20, y=20))
        self.write(self.event(2, type='key', key='q'))
        self.write(self.event(3, type='quit'))
        with self.assertRaisesRegex(BRIDGE.StartupCancelled, 'during startup'):
            self.session.check_startup_cancel()
        status = json.loads((self.session.directory / 'status.json').read_text())
        self.assertEqual(status['state'], 'cancelled')
        self.assertFalse(status['ready'])
        self.assertFalse(status['passed'])
        self.assertFalse(self.session.heartbeat_thread.is_alive())
        self.assertEqual([item['accepted'] for item in self.audit()], [False, False, True])
        self.assertEqual(status['frame_counter'], 0)
        self.session.check_startup_cancel()
    def test_startup_does_not_execute_input_or_accept_invalid_quit(self):
        self.session.qmp = None
        self.write(self.event(type='pointer', action='down', x=20, y=20))
        wrong = self.write(self.event(2, type='quit', controller_id='wrong-controller'))
        self.session.check_startup_cancel()
        self.assertEqual(self.session.state['event_ack'], 0)
        self.assertEqual(self.session.state['state'], 'starting')
        wrong.unlink()
        self.write(self.event(3, type='quit'))
        self.session.check_startup_cancel()
        self.assertEqual(self.session.state['state'], 'starting')
    def test_audit_redacts_keys_and_does_not_copy_extra_payload_text(self):
        self.write(self.event(type='key', key='private secret typed text', extra='another private value'))
        self.assertIsNone(self.session.next_event())
        audit = (self.session.directory / 'input-audit.jsonl').read_text()
        self.assertNotIn('private secret typed text', audit)
        self.assertNotIn('another private value', audit)
        record = self.audit()[0]
        self.assertEqual(record['event']['key'], '[redacted]')
        self.assertEqual(record['event']['type'], 'key')
        self.assertEqual(record['event']['seq'], 1)
        self.assertIn('created_ms', record['event'])
        self.assertFalse(record['accepted'])
        self.session.begin(self.event(2, type='pointer', action='down', x=25, y=35))
        self.assertEqual((self.audit()[-1]['event']['x'], self.audit()[-1]['event']['y']), (25, 35))
        self.session.begin(self.event(3, type='release'))
        self.session.state['keyboard_layout'] = 'lower'
        self.session.begin(self.event(4, type='key', key='q'))
        for _ in range(4):
            with patch.object(BRIDGE.time, 'monotonic', return_value=self.session.next_step):
                self.session.step()
        record = self.audit()[-1]
        self.assertTrue(record['accepted'])
        self.assertEqual(record['event']['key'], '[redacted]')
        self.assertIsNone(self.session.key_timings)
        self.assertFalse((self.session.directory / 'performance.jsonl').exists())
    def test_key_metrics_separate_monotonic_queue_layout_shift_and_touch_phases(self):
        self.measured_session()
        clock = [100.0]
        original_call = self.qmp.call
        def timed_call(name, arguments=None):
            original_call(name, arguments)
            clock[0] += .002
        def due_step():
            clock[0] = self.session.next_step
            self.session.step()
        with patch.object(BRIDGE.time, 'monotonic_ns', side_effect=lambda: round(clock[0] * 1e9)), \
                patch.object(BRIDGE.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(self.qmp, 'call', side_effect=timed_call):
            self.write(self.event(type='key', key='Q', extra='private payload'))
            self.write(self.event(2, type='key', key='w'))
            first = self.session.next_event()
            self.assertEqual(len(self.session.key_timings), 2)
            clock[0] += .2
            self.session.begin(first)
            self.session.step()
            clock[0] += .3
            self.session.state['keyboard_layout'] = 'lower'
            self.session.step()
            self.session.step()  # Shift down, preserving the 100 ms contact.
            self.assertAlmostEqual(self.session.next_step - clock[0], .10)
            due_step()  # Shift up, preserving the 300 ms cooldown.
            self.assertAlmostEqual(self.session.next_step - clock[0], .30)
            self.observe_layout('upper')
            due_step()  # Recheck layout after Shift.
            due_step()  # Letter down.
            self.assertAlmostEqual(self.session.next_step - clock[0], .10)
            due_step()  # Letter up, preserving the 180 ms cooldown.
            self.assertAlmostEqual(self.session.next_step - clock[0], .18)
            self.observe_layout('lower')
            due_step()  # Completion follows cooldown and observed auto-lower.
            second = self.session.next_event()
            self.session.state['keyboard_layout'] = 'lower'
            self.session.begin(second)
            for _ in range(4):
                due_step()
        first, second = self.performance('keyboard')
        self.assertEqual(first['durations_ms'], {'queue_wait': 200, 'service': 988,
                                               'layout_wait': 300, 'case_switch': 404,
                                               'touchdown_qmp': 2, 'touchup_qmp': 2, 'completion': 0})
        self.assertEqual(second['durations_ms'], {'queue_wait': 1188, 'service': 284,
                                                'layout_wait': 0, 'case_switch': 0,
                                                'touchdown_qmp': 2, 'touchup_qmp': 2, 'completion': 0})
        phases = {item['phase']: item['mono_ns'] for item in first['phases']}
        self.assertEqual(phases['touchdown_finished'] - phases['touchdown_started'], 2_000_000)
        self.assertEqual(phases['touchup_finished'] - phases['touchup_started'], 2_000_000)
        self.assertEqual(first['completed_ns'] - phases['touchup_finished'], 180_000_000)
        self.assertEqual(first['input_kind'], 'keyboard')
        self.assertEqual(first['outcome'], 'accepted')
        self.assertEqual(first['dropped_phases'], 0)
        self.assertEqual(self.session.key_timings, {})
        self.assertTrue(all(set(record) == {'time_ms', 'event', 'accepted', 'message'} for record in self.audit()))
        serialized = (self.session.directory / 'performance.jsonl').read_text()
        for forbidden in ('private payload', '"key"', '"text"', '"Q"', '"w"'):
            self.assertNotIn(forbidden, serialized)
    def test_key_metrics_cover_cancelled_prefix_and_escape_without_layout_wait(self):
        self.measured_session()
        self.session.begin(self.event(type='key', key='Escape'))
        self.session.step()
        self.write(self.event(2, type='key', key='x'))
        self.write(self.event(3, type='cancel'))
        self.session.begin(self.session.next_event())
        gesture, queued = self.performance('keyboard')
        self.assertEqual(gesture['input_kind'], 'escape_gesture')
        self.assertEqual(gesture['outcome'], 'rejected')
        self.assertEqual(gesture['durations_ms']['layout_wait'], 0)
        self.assertEqual(gesture['durations_ms']['case_switch'], 0)
        self.assertEqual([item['phase'] for item in gesture['phases']],
                         ['service_started', 'touchdown_started', 'touchdown_finished',
                          'touchup_started', 'touchup_finished', 'completion_started'])
        self.assertEqual(queued['outcome'], 'rejected')
        self.assertIsNone(queued['service_started_ns'])
        self.assertIsNone(queued['durations_ms']['service'])
        self.assertIsNone(queued['durations_ms']['queue_wait'])
        self.assertFalse(self.session.key_timings)
        self.assertFalse(self.session.down)
    def test_key_metrics_keep_case_switch_open_until_observed_and_measure_auto_lower_wait(self):
        self.measured_session()
        clock = [100.0]
        with patch.object(BRIDGE.time, 'monotonic_ns', side_effect=lambda: round(clock[0] * 1e9)), \
                patch.object(BRIDGE.time, 'monotonic', side_effect=lambda: clock[0]):
            self.observe_layout('lower')
            event = self.event(type='key', key='Q')
            self.session.begin(event)
            self.session.step()
            self.session.step()
            clock[0] = 100.1
            self.session.step()
            clock[0] = 100.4
            self.observe_layout('lower')
            self.session.step()
            self.assertIn('case_switch_started_ns', self.session.key_timing(event))
            clock[0] = 100.8
            self.observe_layout('upper')
            self.session.step()
            self.session.step()
            clock[0] = 100.9
            self.session.step()
            clock[0] = self.session.next_step
            self.observe_layout('upper')
            self.session.step()
            self.assertIsNotNone(self.session.pending)
            clock[0] = 101.3
            self.observe_layout('lower')
            self.session.step()
        record, = self.performance('keyboard')
        self.assertEqual(record['outcome'], 'accepted')
        self.assertEqual(record['durations_ms']['case_switch'], 800)
        self.assertEqual(record['durations_ms']['layout_wait'], 620)
        self.assertEqual(record['durations_ms']['service'], 1300)
        phases = [item['phase'] for item in record['phases']]
        self.assertEqual(phases.count('case_switch_started'), 1)
        self.assertEqual(phases.count('case_switch_finished'), 1)
        self.assertEqual(phases.count('layout_wait_started'), 2)
        self.assertEqual(phases.count('layout_wait_finished'), 2)
        self.assertFalse(self.session.key_timings)
    def test_key_metrics_finish_cancelled_case_wait_without_releasing_a_later_letter(self):
        self.measured_session()
        self.observe_layout('upper')
        self.session.begin(self.event(type='key', key='a'))
        for _ in range(4):
            self.due_step()
        self.session.begin(self.event(2, type='cancel'))
        record, = self.performance('keyboard')
        self.assertEqual(record['outcome'], 'rejected')
        phases = [item['phase'] for item in record['phases']]
        self.assertEqual(phases.count('case_switch_started'), 1)
        self.assertNotIn('case_switch_finished', phases)
        self.assertNotIn('touchdown_started', phases)
        self.assertFalse(self.session.key_timings)
        self.assertEqual(len(self.contacts()), 1)
    def test_key_metrics_finish_layout_rejection_and_do_not_keep_removed_events(self):
        self.measured_session()
        self.write(self.event(type='key', key='q'))
        removed = self.write(self.event(2, type='key', key='w'))
        self.session.begin(self.session.next_event())
        self.session.step()
        removed.unlink()
        self.session.next_event()
        with patch.object(BRIDGE.time, 'monotonic', return_value=time.monotonic() + 3):
            self.session.step()
        removed_record, rejected = self.performance('keyboard')
        self.assertEqual(removed_record['outcome'], 'removed')
        self.assertEqual(rejected['outcome'], 'rejected')
        self.assertGreater(rejected['durations_ms']['layout_wait'], 0)
        self.assertFalse(self.session.key_timings)
        self.assertFalse(self.qmp.calls)
    def test_key_metrics_are_bounded_and_flushed_on_qmp_failure(self):
        self.measured_session()
        event = self.event(type='key', key='Escape')
        self.session.begin(event)
        for _ in range(BRIDGE.MAX_KEY_PHASES + 10):
            self.session.key_phase(event, 'test_phase')
        self.assertEqual(len(self.session.key_timing(event)['phases']), BRIDGE.MAX_KEY_PHASES)
        self.assertEqual(self.session.key_timing(event)['dropped_phases'], 11)
        for sequence in range(2, BRIDGE.MAX_EVENTS + 10):
            self.session.key_timing(self.event(sequence, type='key', key='q'))
        self.assertEqual(len(self.session.key_timings), BRIDGE.MAX_EVENTS + 1)
        # Leave a normal-sized trace for the failure assertion itself.
        self.session.key_timings = {}
        self.session.key_phase(event, 'service_started')
        original_call = self.qmp.call
        def fail_input(name, arguments=None):
            if name == 'input-send-event':
                raise RuntimeError('synthetic QMP failure')
            return original_call(name, arguments)
        with patch.object(self.qmp, 'call', side_effect=fail_input):
            with self.assertRaisesRegex(RuntimeError, 'synthetic QMP failure'):
                self.session.run(self.qmp, lambda _: None, time.monotonic() + 2, lambda: None)
        record, = self.performance('keyboard')
        self.assertEqual(record['outcome'], 'interrupted')
        self.assertIn('touchdown_failed', [item['phase'] for item in record['phases']])
        self.assertNotIn('touchdown_finished', [item['phase'] for item in record['phases']])
        self.assertFalse(self.session.key_timings)
    def test_capture_is_lossless_and_resumes_before_publication(self):
        from PIL import Image
        for _ in range(5): self.session.capture()
        self.assertEqual([x[0] for x in self.qmp.calls[:3]], ['stop', 'screendump', 'cont'])
        status = json.loads((self.session.directory / 'status.json').read_text())
        self.assertEqual(status['frame_counter'], 5)
        self.assertEqual(len(list(self.session.directory.glob('frame.[0-9]*.png'))), 3)
        with Image.open(self.session.directory / status['frame_file']) as image:
            self.assertEqual(image.tobytes(), self.qmp.pixels)
        self.assertEqual((self.session.directory / 'frame.png').read_bytes(),
                         (self.session.directory / status['frame_file']).read_bytes())
        proof = json.loads((self.session.directory / 'frame.provenance.json').read_text())
        self.assertTrue(proof['pixel_bytes_identical'])
        self.assertFalse((self.session.directory / 'performance.jsonl').exists())
        self.qmp.fail_capture = True
        with self.assertRaises(RuntimeError): self.session.capture()
        self.assertEqual(self.qmp.calls[-1][0], 'cont')
        self.assertEqual(json.loads((self.session.directory / 'status.json').read_text())['frame_counter'], 5)
    def test_detailed_performance_and_resources_are_opt_in(self):
        with patch.object(BRIDGE.Path, 'read_text', side_effect=AssertionError('unexpected resource read')):
            self.session.resources()
        self.session.metric('ignored', private='not persisted')
        self.assertFalse((self.session.directory / 'performance.jsonl').exists())
        measured = BRIDGE.Session(Path(self.temp.name) / 'measured', metrics=True)
        measured.qmp = self.qmp
        measured.capture()
        # Exercise Linux /proc parsing deterministically on every host; macOS
        # correctly has no real /proc controller sample to assert against.
        fields = ['0'] * 22
        fields[0], fields[11], fields[12], fields[21] = 'S', '17', '9', '4'
        process_stat = f'{os.getpid()} (fixture controller) ' + ' '.join(fields)
        with patch.object(BRIDGE.Path, 'read_text', autospec=True, return_value=process_stat) as read_stat:
            with patch.object(BRIDGE.os, 'sysconf', side_effect={'SC_PAGE_SIZE': 4096, 'SC_CLK_TCK': 100}.__getitem__):
                measured.resources()
        read_stat.assert_called_once_with(Path(f'/proc/{os.getpid()}/stat'))
        records = [json.loads(line) for line in (measured.directory / 'performance.jsonl').read_text().splitlines()]
        self.assertEqual([item['kind'] for item in records], ['capture', 'resources'])
        self.assertEqual(records[0]['frame_counter'], 1)
        self.assertIn('stages_ms', records[0])
        self.assertEqual(records[0]['keyboard_layout'], 'unknown')
        self.assertLessEqual(records[0]['capture_started_ns'], records[0]['sampled_ns'])
        self.assertLessEqual(records[0]['sampled_ns'], records[0]['mono_ns'])
        self.assertEqual(records[1]['tick_hz'], 100)
        self.assertEqual(records[1]['samples'], {'controller': {
            'pid': os.getpid(), 'cpu_ticks': 26, 'rss_bytes': 16384}})
    def test_capture_budget_includes_encoding_and_never_catches_up(self):
        self.assertAlmostEqual(BRIDGE.next_capture_deadline(10, 10.03), 10 + BRIDGE.FRAME_PERIOD)
        self.assertEqual(BRIDGE.next_capture_deadline(10, 10.2), 10.2)

    def test_poll_wait_respects_input_and_capture_deadlines(self):
        self.session.next_frame = 10.1
        self.session.next_status = self.session.next_validate = self.session.next_resources = 11
        self.assertEqual(self.session.wait_seconds(10), BRIDGE.IDLE_POLL_SECONDS)
        self.assertAlmostEqual(self.session.wait_seconds(10.099), .001)
        self.session.pending = self.event(type='key', key='q')
        self.session.next_step = 10.001
        self.assertAlmostEqual(self.session.wait_seconds(10), .001)
        self.assertEqual(self.session.wait_seconds(10.002), 0)

    def test_symlink_event_is_not_read(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_text(json.dumps(self.event(type='quit')))
        target = self.session.events / 'testclient1234.00000000000000000001.json'
        target.symlink_to(outside)
        self.assertIsNone(self.session.next_event())
        self.assertTrue(outside.exists())
        self.assertFalse(self.qmp.calls)
    def test_live_mode_retains_offline_and_bounded_gates(self):
        args = SimpleNamespace(host_backend='linux-offscreen', host_renderer='llvmpipe (LLVM 19.1.7, 256 bits)',
            systemui_attempts=30, network='off', audio='off', ca_certificates='off', profile=None,
            boot_animation=None, power='off', call_simulation='off', lockscreen='off', startup_waits='ready',
            interactive=True, exit_on_ready=False, exercise_keyboard=False, exercise_transitions=False,
            linux_live_session=self.session.directory, rotation=270, timeout=1800)
        command = ['qemu', '-display', 'none', '-nic', 'none', '-snapshot']
        with patch.object(SHELL.sys, 'platform', 'linux'):
            self.assertTrue(SHELL.validate_host_configuration(args, command))
            profile = SimpleNamespace(**(vars(args) | {'profile': Path('private-profile')}))
            self.assertTrue(SHELL.validate_host_configuration(profile, command))
            for changes in ({'linux_live_session': None}, {'interactive': False}, {'exit_on_ready': True},
                            {'network': 'user'}, {'audio': 'pulse'}, {'timeout': 1801}):
                with self.subTest(profile=changes), self.assertRaises(ValueError):
                    SHELL.validate_host_configuration(SimpleNamespace(**(vars(profile) | changes)), command)
            with self.assertRaises(ValueError):
                SHELL.validate_host_configuration(profile, command[:-1])
            for key, bad in (('network', 'user'), ('timeout', 1801), ('rotation', 0),
                             ('exit_on_ready', True), ('startup_waits', 'fixed')):
                with self.assertRaises(ValueError):
                    SHELL.validate_host_configuration(SimpleNamespace(**(vars(args) | {key: bad})), command)

if __name__ == '__main__': unittest.main()
