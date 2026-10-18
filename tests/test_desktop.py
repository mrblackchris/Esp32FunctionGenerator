"""Run: QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from demo import DemoClient
from function_generator import ChannelCard, NetworkCard, DeviceWorker, Window
from protocol import SerialClient, DeviceError

APP = QApplication.instance() or QApplication([])
SETTINGS_DIRECTORY = tempfile.TemporaryDirectory(prefix='fg-test-settings-')
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, SETTINGS_DIRECTORY.name)


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.incoming = bytearray()
        self.writes = []
        self.port = None
        self.closed = False
        self.reply = lambda seq: {'id': seq, 'code': 200, 'data': {'ok': True}}

    def open(self):
        pass

    def close(self):
        self.closed = True

    @property
    def in_waiting(self):
        return min(len(self.incoming), 9)  # Deliberately split JSON and UTF-8 across reads.

    def write(self, data):
        self.writes.append(data)
        seq = int(data.split(b' ')[1])
        self.incoming.extend(b'Function generator boot\nFG not-json\n')
        self.incoming.extend(json.dumps({'id': seq + 1, 'code': 200, 'data': 'stale'}).join(['FG ', '\n']).encode())
        reply = self.reply(seq)
        if reply is not None:
            self.incoming.extend(('FG ' + json.dumps(reply, ensure_ascii=False) + '\n').encode())
        return len(data)

    def read(self, size):
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch('protocol.serial.Serial', FakeSerial)
        self.patch.start()
        self.client = SerialClient('TEST')

    def tearDown(self):
        self.client.close()
        self.patch.stop()

    def test_fragmented_json_and_late_response(self):
        self.assertEqual(self.client.request('/state'), {'ok': True})
        self.assertFalse(self.client.serial.dtr)
        self.assertFalse(self.client.serial.rts)

    def test_wifi_special_characters_roundtrip(self):
        params = {'ssid': 'Lab & café=1+2', 'password': ' space&=+%秘密 ', 'dhcp': '1'}
        self.client.serial.reply = lambda seq: {'id': seq, 'code': 200, 'data': {'ssid': params['ssid']}}
        self.assertEqual(self.client.request('/network/set', params)['ssid'], params['ssid'])
        command = self.client.serial.writes[0].decode().strip()
        decoded = parse_qs(command.split('?', 1)[1])
        self.assertEqual(decoded['ssid'], [params['ssid']])
        self.assertEqual(decoded['password'], [params['password']])

    def test_device_validation_error(self):
        self.client.serial.reply = lambda seq: {'id': seq, 'code': 400, 'data': 'Invalid settings'}
        with self.assertRaisesRegex(DeviceError, 'Invalid settings'):
            self.client.request('/set', {'id': '0'})
        self.assertEqual(len(self.client.serial.writes), 1)

    def test_timeout_does_not_repeat_mutation(self):
        self.client.serial.reply = lambda _: None
        with self.assertRaisesRegex(TimeoutError, 'may have been applied'):
            self.client.request('/burst', {'id': '3'}, timeout=.01)
        self.assertEqual(len(self.client.serial.writes), 1)

    def test_oversized_request_not_written(self):
        with self.assertRaises(DeviceError):
            self.client.request('/network/set', {'ssid': 'x' * 2000})
        self.assertEqual(self.client.serial.writes, [])


class FormTests(unittest.TestCase):
    def setUp(self):
        self.demo = DemoClient()
        self.state = self.demo.request('/state')
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()

    def card(self, index):
        card = ChannelCard(index)
        card.online = True
        card.update_state(self.state[index])
        self.widgets.append(card)
        return card

    def network(self):
        card = NetworkCard()
        card.online = True
        card.update_network(self.demo.request('/network'))
        self.widgets.append(card)
        return card

    def test_pair_poll_preserves_pending_edits(self):
        card = self.card(0)
        card.fields['frequency'].setText('2345')
        card.changed()
        self.state[0]['frequency'] = 500
        self.state[0]['actualHz'] = 500
        card.update_state(self.state[0])
        self.assertEqual(card.fields['frequency'].text(), '2345')
        self.assertIn('500.000', card.summary.text())
        self.assertTrue(card.dirty)

    def test_channel_limits(self):
        card = self.card(0)
        for value in ('nan', 'inf', '-1', '100001', '.5', ''):
            card.fields['frequency'].setText(value)
            with self.assertRaises(ValueError):
                card.parameters()
        card.fields['frequency'].setText('0')
        self.assertEqual(card.parameters()['frequency'], '0')

    def test_all_modes_and_burst_requires_apply(self):
        card = self.card(3)
        for mode in ('pulse', 'burst', 'sine', 'triangle', 'rectangle'):
            card.mode.setCurrentIndex(card.mode.findData(mode))
            params = card.parameters()
            self.assertEqual(params['mode'], mode)
            self.assertIn('waveHz' if mode in ('sine', 'triangle', 'rectangle') else 'onUs', params)
        card.mode.setCurrentIndex(card.mode.findData('burst'))
        card.enabled.setChecked(True)
        self.assertEqual(card.parameters()['enabled'], '0')
        self.assertFalse(card.start_button.isEnabled())
        applied = self.state[3] | {'mode': 'burst', 'enabled': False}
        card.update_state(applied, load=True)
        self.assertTrue(card.start_button.isEnabled())
        card.changed()
        self.assertFalse(card.start_button.isEnabled())
        card.fields['pulseCount'].setText('1.5')
        with self.assertRaises(ValueError):
            card.parameters()

    def test_password_kept_unless_explicitly_replaced(self):
        card = self.network()
        card.fields['password'].setText('not-submitted')
        self.assertNotIn('password', card.parameters())
        card.replace.setChecked(True)
        card.fields['password'].clear()
        self.assertEqual(card.parameters()['password'], '')  # Explicit open network.
        card.fields['password'].setText('short')
        with self.assertRaises(ValueError):
            card.parameters()

    def test_static_address_validation_and_saved_reload(self):
        card = self.network()
        card.dhcp.setChecked(False)
        for key, value in dict(ip='192.168.5.30', gateway='192.168.5.1', subnet='255.255.255.0', dns='1.1.1.1').items():
            card.fields[key].setText(value)
        params = card.parameters()
        self.assertEqual(params['dhcp'], '0')
        for key, bad in [('gateway', '192.168.6.1'), ('subnet', '255.0.255.0'), ('subnet', '0.0.0.255'), ('ip', '192.168.5.255'), ('ip', '127.0.0.1')]:
            original = card.fields[key].text()
            card.fields[key].setText(bad)
            with self.assertRaises(ValueError):
                card.parameters()
            card.fields[key].setText(original)
        card.fields['ssid'].setText('Pending network')
        card.changed()
        card.update_network(self.demo.request('/network'))
        self.assertEqual(card.fields['ssid'].text(), 'Pending network')
        card.update_network(self.demo.request('/network'), load=True)
        self.assertEqual(card.fields['ssid'].text(), 'Your Wi-Fi network')
        self.assertFalse(card.replace.isChecked())

    def test_ssid_byte_limits(self):
        card = self.network()
        card.fields['ssid'].setText('é' * 17)
        with self.assertRaises(ValueError):
            card.parameters()

    def test_stop_cancels_queued_apply(self):
        worker = DeviceWorker('TEST')
        cancelled = []
        worker.failed.connect(lambda path, context, message: cancelled.append(path))
        worker.submit('/set', {'id': '0', 'enabled': '1'}, (0, 1))
        worker.submit('/stop', {'id': 'all'})
        self.assertEqual(cancelled, ['/set'])
        self.assertEqual(worker.commands.get_nowait()[2], '/stop')
        self.assertTrue(worker.commands.empty())


class WindowTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(15)
        self.assertTrue(predicate())

    def test_typed_port_overrides_selected_port_and_layout_resizes(self):
        window = Window()
        window.ports.clear()
        window.ports.addItem('/dev/ttyUSB0 · Detected board', '/dev/ttyUSB0')
        self.assertEqual(window.selected_port(), '/dev/ttyUSB0')
        window.ports.setEditText('/dev/ttyACM7')
        self.assertEqual(window.selected_port(), '/dev/ttyACM7')
        window.show()
        window.resize(820, 900)
        QTest.qWait(20)
        self.assertEqual(window.columns, 2)
        window.close()

    def test_worker_ui_apply_stop_network_and_shutdown(self):
        window = Window(demo=True)
        window.show()
        try:
            self.wait_for(lambda: window.cards[0].initialized)
            card = window.cards[0]
            # Apply channel 0 while preserving an edit on channel 1.
            other = window.cards[1]
            other.fields['frequency'].setText('1234')
            other.changed()
            card.fields['frequency'].setText('2000')
            card.changed()
            card.apply()
            # Editing while Apply is in flight must also preserve the newer edit.
            card.fields['frequency'].setText('3000')
            card.changed()
            self.wait_for(lambda: window.pending == 0)
            self.assertEqual(card.applied['frequency'], 2000)
            self.assertEqual(card.fields['frequency'].text(), '3000')
            self.assertTrue(card.dirty)
            card.apply()
            self.wait_for(lambda: window.pending == 0)
            self.assertEqual(card.applied['frequency'], 3000)
            self.assertFalse(card.dirty)
            self.assertEqual(other.fields['frequency'].text(), '1234')
            self.assertTrue(other.dirty)
            window.send('/stop', {'id': 'all'}, None)
            self.wait_for(lambda: window.pending == 0)
            self.assertTrue(all(not c.applied['enabled'] for c in window.cards))
            network = window.network
            network.fields['ssid'].setText('Updated SSID')
            network.changed()
            network.save()
            self.wait_for(lambda: window.pending == 0)
            self.assertEqual(network.data['ssid'], 'Updated SSID')
            self.assertFalse(network.dirty)
        finally:
            window.close()
            self.wait_for(lambda: not window.worker.isRunning(), timeout=7)
            window.close()


def tearDownModule():
    # Destroy Qt widgets while QApplication is still alive. Interpreter teardown
    # otherwise leaves signal/parent ownership cleanup to an undefined order.
    import gc
    from shiboken6 import delete, isValid
    for widget in APP.topLevelWidgets():
        if isValid(widget):
            widget.close()
            if isValid(widget):
                delete(widget)
    APP.processEvents()
    gc.collect()


if __name__ == '__main__':
    unittest.main()
