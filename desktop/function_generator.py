#!/usr/bin/env python3
"""Desktop USB and HTTP controller. Run with --demo for an offline preview."""
from __future__ import annotations

import argparse
import ipaddress
import math
import queue
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTabWidget,
    QVBoxLayout, QWidget,
)
from serial.tools import list_ports

from protocol import DeviceError, SerialClient, HttpClient
from demo import DemoClient

BLUE = '#245cad'
STYLE = '''
QMainWindow, QWidget#page { background: #eef2f7; color: #192638; }
QWidget { font-family: "DejaVu Sans", "Segoe UI", sans-serif; font-size: 13px; color: #192638; }
QFrame#card { background: white; border: 1px solid #d2dae5; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; border: none; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #506078; }
QLabel#cardTitle { font-size: 20px; font-weight: 700; }
QLabel#eyebrow { color: #245cad; font-size: 11px; font-weight: 700; }
QFrame#card QLabel#summary { background: #f1f5fa; border: none; border-radius: 7px; padding: 12px; color: #34465e; }
QLabel#notice { background: #fff3d5; color: #735720; padding: 12px; border-radius: 7px; }
QLabel#feedback { color: #946c10; font-size: 12px; }
QLabel#status { padding: 10px 0; color: #506078; }
QPushButton { background: #245cad; color: white; border: none; border-radius: 6px; padding: 10px 15px; font-weight: 600; }
QPushButton:hover { background: #1c4b91; }
QPushButton#stop { background: #b32d37; }
QPushButton#stop:hover { background: #92232c; }
QPushButton#secondary { background: #e8eef7; color: #245cad; }
QPushButton:disabled { background: #e1e6ee; color: #8a96a6; }
QLineEdit, QComboBox { background: white; border: 1px solid #aebccd; border-radius: 5px; padding: 8px; min-height: 18px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #245cad; }
QLineEdit:disabled, QComboBox:disabled { background: #f1f4f8; color: #8a96a6; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #9cabbf; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: #245cad; border: 3px solid #b5cae8; }
QCheckBox::indicator:disabled { background: #e1e6ee; border-color: #c8d2df; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; padding: 12px 20px; margin: 0 6px 12px 0; color: #506078; font-weight: 600; }
QTabBar::tab:selected { color: #245cad; border-bottom: 3px solid #245cad; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 10px; background: #eef2f7; }
QScrollBar::handle:vertical { background: #bdcadb; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


def card_layout(card):
    card.setObjectName('card')
    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return layout


class DeviceWorker(QThread):
    ready = Signal()
    result = Signal(str, object, object, object)
    failed = Signal(str, object, str)
    connection_error = Signal(str)

    def __init__(self, port, demo=False):
        super().__init__()
        self.port, self.demo = port, demo
        self.commands = queue.PriorityQueue()
        self.order = 0

    def submit(self, path, params=None, context=None):
        if path == '/stop':
            # A queued Apply must never re-enable an output after a later Stop.
            retained = []
            while True:
                try:
                    item = self.commands.get_nowait()
                except queue.Empty:
                    break
                if item[2] == '/stop':
                    retained.append(item)
                else:
                    self.failed.emit(item[2], item[4], 'Queued action cancelled by Stop.')
            for item in retained:
                self.commands.put(item)
        self.order += 1
        self.commands.put((0 if path == '/stop' else 1, self.order, path, params or {}, context))

    def run(self):
        client = None
        try:
            client = DemoClient() if self.demo else (HttpClient(self.port) if self.port.startswith('http://') else SerialClient(self.port))
            # Boot may take a moment on adapters which reset when opened. Retry reads only.
            for attempt in range(3):
                try:
                    initial = client.request('/state', timeout=3)
                    break
                except TimeoutError:
                    if attempt == 2:
                        raise
                    if self.isInterruptionRequested():
                        return
            network = client.request('/network')
            self.ready.emit()
            self.result.emit('/state', {}, initial, None)
            self.result.emit('/network', {}, network, None)
            next_poll, failures = time.monotonic() + 2, 0
            while not self.isInterruptionRequested():
                try:
                    _, _, path, params, context = self.commands.get(timeout=.1)
                except queue.Empty:
                    if time.monotonic() < next_poll:
                        continue
                    path, params, context = '/state', {}, None
                try:
                    data = client.request(path, params)
                    self.result.emit(path, params, data, context)
                    failures = 0
                    if path == '/state' and self.commands.empty() and not self.isInterruptionRequested():
                        self.result.emit('/network', {}, client.request('/network'), None)
                except (DeviceError, TimeoutError) as error:
                    self.failed.emit(path, context, str(error))
                    if isinstance(error, TimeoutError):
                        failures += 1
                        if failures >= 3:
                            raise ConnectionError('Device is not responding. Reconnect to retry.') from error
                next_poll = time.monotonic() + 2
        except Exception as error:
            self.connection_error.emit(str(error))
        finally:
            if client:
                client.close()


# name, label, minimum, maximum, integer-only, default
PAIR_FIELDS = [
    ('frequency', 'Frequency (Hz)', 0, 100000, False, '1000'),
    ('duty', 'Duty (%)', 0, 100, False, '50'),
    ('deadUs', 'Dead time (µs)', 0, 1000, False, '1'),
]
PULSE_FIELDS = [
    ('onUs', 'On time (µs)', 1, 30000, True, '20'),
    ('offUs', 'Off time (µs)', 1, 30000, True, '80'),
]
BURST_FIELDS = [
    ('pulseCount', 'Pulses per burst', 1, 255, True, '10'),
    ('burstCount', 'Number of bursts', 1, 1000, True, '1'),
    ('gapMs', 'Extra pause (ms)', 0, 60000, True, '100'),
]
ANALOG_FIELDS = [
    ('waveHz', 'Frequency (Hz)', 10, 5000, False, '100'),
    ('amplitude', 'Amplitude (%)', 0, 100, False, '50'),
]
MODES = [('Continuous pulse', 'pulse'), ('Pulse burst', 'burst'), ('Sine · analog', 'sine'),
         ('Triangle · analog', 'triangle'), ('Rectangle · analog', 'rectangle')]


class ChannelCard(QFrame):
    action = Signal(str, object, object)

    def __init__(self, index):
        super().__init__()
        self.index = index
        self.initialized, self.online, self.busy = False, False, False
        self.dirty, self.revision, self.loading = False, 0, False
        self.applied = None
        self.fields, self.rows = {}, {}
        self.setMinimumWidth(305)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = card_layout(self)
        layout.addWidget(label('COMPLEMENTARY OUTPUT' if index < 3 else 'MULTIFUNCTION OUTPUT', 'eyebrow'))
        header = QHBoxLayout()
        header.addWidget(label(f'Pair {index + 1}' if index < 3 else f'Waveform {index - 2}', 'cardTitle'))
        header.addStretch()
        self.badge = label('—')
        header.addWidget(self.badge)
        layout.addLayout(header)
        pins = [(18, 19), (21, 22), (23, 32), (25, -1), (26, -1)][index]
        layout.addWidget(label(f'High: GPIO{pins[0]}   /   Low: GPIO{pins[1]}' if index < 3 else f'Output: GPIO{pins[0]}', 'muted'))
        self.mode = QComboBox()
        for title, value in MODES:
            self.mode.addItem(title, value)
        if index >= 3:
            layout.addWidget(self.mode)
        self.mode.currentIndexChanged.connect(self.changed)
        specs = PAIR_FIELDS if index < 3 else PULSE_FIELDS + BURST_FIELDS + ANALOG_FIELDS
        for name, title, low, high, integer, default in specs:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(label(title))
            field = QLineEdit(default)
            field.setMaximumWidth(128)
            field.setToolTip(f'{low:g}–{high:g}' + ('; whole numbers' if integer else ''))
            row_layout.addWidget(field)
            field.textEdited.connect(self.changed)
            self.fields[name], self.rows[name] = field, row
            layout.addWidget(row)
        self.hint = label('', 'muted', True)
        layout.addWidget(self.hint)
        self.enabled = QCheckBox('Enable output')
        self.enabled.toggled.connect(self.changed)
        layout.addWidget(self.enabled)
        self.summary = label('Connect over USB or Wi-Fi to read applied settings.', 'summary', True)
        self.summary.setMinimumHeight(90)
        layout.addWidget(self.summary)
        self.feedback = label('Settings apply only when you press Apply.', 'feedback', True)
        layout.addWidget(self.feedback)
        layout.addStretch()
        actions = QHBoxLayout()
        self.apply_button = button('Apply channel', self.apply)
        self.stop_button = button('Stop', lambda: self.action.emit('/stop', {'id': str(index)}, None), 'stop')
        actions.addWidget(self.apply_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        self.start_button = button('Start bursts', lambda: self.action.emit('/burst', {'id': str(index)}, None))
        layout.addWidget(self.start_button)
        self.refresh_controls()

    def changed(self, *_):
        if self.loading:
            return
        self.dirty, self.revision = True, self.revision + 1
        self.feedback.setText('Changes not applied. Press Apply channel.')
        self.refresh_controls()

    def refresh_controls(self):
        mode = self.mode.currentData()
        if self.index >= 3:
            visible = {x[0] for x in (ANALOG_FIELDS if mode in ('sine', 'triangle', 'rectangle') else
                                      PULSE_FIELDS + (BURST_FIELDS if mode == 'burst' else []))}
            for name, row in self.rows.items():
                row.setVisible(name in visible)
        self.enabled.setVisible(self.index < 3 or mode != 'burst')
        self.start_button.setVisible(self.index >= 3 and mode == 'burst')
        self.mode.setEnabled(self.online)
        for field in self.fields.values():
            field.setEnabled(self.online)
        self.enabled.setEnabled(self.online)
        self.apply_button.setEnabled(self.online and not self.busy)
        self.stop_button.setEnabled(self.online)
        self.start_button.setEnabled(self.online and not self.busy and not self.dirty and
                                     self.applied is not None and self.applied['mode'] == 'burst')
        self.hint.setText('1–100000 Hz, or 0 to disable both pins.' if self.index < 3 else
                          'Apply settings, then Start bursts. Extra pause is approximate.' if mode == 'burst' else
                          '8-bit DAC · 10–5000 Hz · about 9.77 Hz steps.' if mode in ('sine', 'triangle', 'rectangle') else
                          'On / off time: 1–30000 µs each. Hardware pulse timing.')

    def parameters(self):
        mode = self.mode.currentData()
        specs = PAIR_FIELDS if self.index < 3 else ANALOG_FIELDS if mode in ('sine', 'triangle', 'rectangle') else PULSE_FIELDS + (BURST_FIELDS if mode == 'burst' else [])
        params = {'id': str(self.index), 'enabled': '1' if self.enabled.isChecked() and (self.index < 3 or mode != 'burst') else '0'}
        if self.index >= 3:
            params['mode'] = mode
        for name, title, low, high, integer, _ in specs:
            try:
                number = float(self.fields[name].text())
            except ValueError:
                number = float('nan')
            if not math.isfinite(number) or not low <= number <= high or (integer and not number.is_integer()):
                self.fields[name].setFocus()
                raise ValueError(f'{title}: enter {low:g}–{high:g}' + (' as a whole number.' if integer else '.'))
            if name == 'frequency' and 0 < number < 1:
                raise ValueError('Frequency must be 0 (off), or at least 1 Hz.')
            params[name] = str(int(number)) if integer else format(number, '.15g')
        return params

    def apply(self):
        try:
            params = self.parameters()
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.action.emit('/set', params, (self.index, self.revision))

    def update_state(self, state, load=False):
        self.applied = state
        self.badge.setText('● ON' if state['enabled'] else '● OFF')
        self.badge.setStyleSheet(f'color: {"#168060" if state["enabled"] else "#6c7b8e"}; font-weight: 700;')
        if self.index < 3:
            text = (f'Applied frequency: {state["actualHz"]:,.3f} Hz\n'
                    f'Duty before dead time: {state["actualDuty"]:.3f}%\n'
                    f'High / low on-time: {state["highDuty"]:.3f}% / {state["lowDuty"]:.3f}%\n'
                    f'Actual dead time: {state["actualDeadUs"]:.3f} µs')
            if state['duty'] in (0, 100):
                text = 'Constant output when enabled\n' + text.split('\n', 1)[1]
        elif state['mode'] in ('sine', 'triangle', 'rectangle'):
            text = (f'Applied mode: {state["mode"]}\nNominal actual frequency: {state["actualWaveHz"]:,.3f} Hz\n'
                    f'Amplitude: {state["amplitude"]:g}%')
        elif state['mode'] == 'burst':
            text = (f'Burst frequency: {state["actualHz"]:,.3f} Hz\n{state["pulseCount"]:g} pulses × '
                    f'{state["burstCount"]:g} bursts\nCompleted bursts: {state["completedBursts"]:g}')
        else:
            text = f'Actual frequency: {state["actualHz"]:,.3f} Hz\nActual duty: {state["actualDuty"]:.3f}%'
        self.summary.setText(text)
        if load or not self.initialized:
            self.loading = True
            for name, field in self.fields.items():
                field.setText(f'{state[name]:g}')
            self.mode.setCurrentIndex(max(0, self.mode.findData(state['mode'])))
            self.enabled.setChecked(state['enabled'])
            self.loading, self.dirty, self.initialized = False, False, True
            self.feedback.setText('Applied settings. Output ' + ('ON.' if state['enabled'] else 'OFF.'))
        elif not self.dirty:
            self.loading = True
            self.enabled.setChecked(state['enabled'])
            self.loading = False
        self.refresh_controls()


class NetworkCard(QFrame):
    action = Signal(str, object, object)

    def __init__(self):
        super().__init__()
        self.online, self.busy, self.initialized = False, False, False
        self.revision, self.loading, self.dirty = 0, False, False
        self.data = None
        layout = card_layout(self)
        layout.addWidget(label('SAVED ON THE ESP32', 'eyebrow'))
        layout.addWidget(label('Wi-Fi & IP settings', 'cardTitle'))
        layout.addWidget(label('Read or update the network over USB or HTTP. USB works even without Wi-Fi. Settings survive power-off.', 'muted', True))
        self.summary = label('Connect to read network status.', 'summary', True)
        layout.addWidget(self.summary)
        self.fields = {}
        grid = QGridLayout()
        for row, (key, title) in enumerate([('ssid', 'Wi-Fi network (SSID)'), ('password', 'New password'),
                                           ('ip', 'Static IP address'), ('gateway', 'Gateway'),
                                           ('subnet', 'Subnet mask'), ('dns', 'DNS server')]):
            field = QLineEdit()
            if key == 'password':
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setPlaceholderText('Existing password is kept')
            grid.addWidget(label(title), row, 0)
            grid.addWidget(field, row, 1)
            field.textEdited.connect(self.changed)
            self.fields[key] = field
        self.replace = QCheckBox('Replace saved password (empty = open network)')
        self.replace.toggled.connect(self.changed)
        self.show_password = QCheckBox('Show new password')
        self.show_password.toggled.connect(lambda show: self.fields['password'].setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password))
        self.dhcp = QCheckBox('Obtain IP address automatically (DHCP)')
        self.dhcp.setChecked(True)
        self.dhcp.toggled.connect(self.changed)
        layout.addLayout(grid)
        layout.addWidget(self.replace)
        layout.addWidget(self.show_password)
        layout.addWidget(self.dhcp)
        self.feedback = label('The saved password is never returned to the computer.', 'feedback', True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.read_button = button('Read saved settings', lambda: self.action.emit('/network', {}, ('read', self.revision)), 'secondary')
        self.save_button = button('Save & reconnect Wi-Fi', self.save)
        actions.addWidget(self.read_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        self.refresh_controls()

    def changed(self, *_):
        if self.loading:
            return
        self.revision += 1
        self.dirty = True
        self.feedback.setText('Network changes not saved.')
        self.refresh_controls()

    def refresh_controls(self):
        for key, field in self.fields.items():
            field.setEnabled(self.online and (key == 'ssid' or key == 'password' and self.replace.isChecked() or
                                             key in ('ip', 'gateway', 'subnet', 'dns') and not self.dhcp.isChecked()))
        for checkbox in (self.replace, self.show_password, self.dhcp):
            checkbox.setEnabled(self.online)
        self.read_button.setEnabled(self.online and not self.busy)
        self.save_button.setEnabled(self.online and not self.busy)

    def parameters(self):
        ssid = self.fields['ssid'].text()
        if not 1 <= len(ssid.encode('utf-8')) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
            raise ValueError('SSID must contain 1–32 UTF-8 bytes without control characters.')
        params = dict(ssid=ssid, dhcp='1' if self.dhcp.isChecked() else '0',
                      replacePassword='1' if self.replace.isChecked() else '0')
        if self.replace.isChecked():
            password = self.fields['password'].text()
            size = len(password.encode('utf-8'))
            is_hex = size == 64 and all(c in '0123456789abcdefABCDEF' for c in password)
            if not (size == 0 or 8 <= size <= 63 or is_hex) or any(ord(c) < 32 or ord(c) == 127 for c in password):
                raise ValueError('Password: empty for an open network, 8–63 UTF-8 bytes, or 64 hex digits.')
            params['password'] = password
        if not self.dhcp.isChecked():
            try:
                addresses = {key: str(ipaddress.IPv4Address(self.fields[key].text().strip()))
                             for key in ('ip', 'gateway', 'subnet', 'dns')}
                net = ipaddress.IPv4Network(f'{addresses["ip"]}/{addresses["subnet"]}', strict=False)
                ip, gateway, dns = (ipaddress.IPv4Address(addresses[k]) for k in ('ip', 'gateway', 'dns'))
                if str(net.netmask) != addresses['subnet'] or net.prefixlen < 1 or net.prefixlen > 30 or gateway not in net or ip == gateway or any(
                    x in (net.network_address, net.broadcast_address) for x in (ip, gateway)) or any(
                    x.is_multicast or x.is_loopback or int(x) >> 24 == 0 or int(x) >> 24 >= 224 for x in (ip, gateway, dns)):
                    raise ValueError()
            except ValueError:
                raise ValueError('Enter a valid static IP, contiguous subnet mask, gateway on the same subnet, and DNS server.') from None
            params.update(addresses)
        return params

    def save(self):
        try:
            params = self.parameters()
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.action.emit('/network/set', params, ('save', self.revision))

    def update_network(self, data, load=False):
        self.data = data
        self.summary.setText(f'{"Connected" if data["connected"] else "Not connected"} · {data["ssid"]}\n'
                             f'Current IP: {data["currentIP"]} · {"DHCP" if data["dhcp"] else "Static IP"}\n'
                             f'Gateway: {data["currentGateway"]} · DNS: {data["currentDns"]}\n'
                             f'Saved password: {"set (hidden)" if data["passwordSet"] else "none / open network"}')
        if load or not self.initialized:
            self.loading = True
            for key in ('ssid', 'ip', 'gateway', 'subnet', 'dns'):
                self.fields[key].setText(data[key])
            self.fields['password'].clear()
            self.replace.setChecked(False)
            self.dhcp.setChecked(data['dhcp'])
            self.loading, self.initialized, self.dirty = False, True, False
            self.feedback.setText('Saved settings read from ESP32. Password is hidden.')
        self.refresh_controls()


class Window(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo, self.worker, self.online, self.pending = demo, None, False, 0
        self.settings = QSettings('ESP32FunctionGenerator', 'USBController')
        self.setWindowTitle('ESP32 Function Generator' + (' · OFFLINE DEMO' if demo else ''))
        self.resize(1190, 980)
        self.setMinimumSize(760, 620)
        root = QWidget()
        root.setObjectName('page')
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 14)
        layout.setSpacing(12)
        self.setCentralWidget(root)
        layout.addWidget(label('ESP32 Function Generator', 'title'))
        layout.addWidget(label('Three independent high/low pairs · Two selectable waveform outputs', 'subtitle'))
        connection = QHBoxLayout()
        connection.addWidget(label('USB / WI-FI', 'eyebrow'))
        self.ports = QComboBox()
        self.ports.setEditable(True)
        self.ports.setMinimumWidth(240)
        self.ports.setToolTip('Select a serial port, or type an HTTP address such as http://192.168.1.50.')
        connection.addWidget(self.ports, 1)
        self.refresh_button = button('Refresh ports', self.refresh_ports, 'secondary')
        connection.addWidget(self.refresh_button)
        self.connect_button = button('Connect', self.toggle_connection)
        connection.addWidget(self.connect_button)
        connection.addWidget(label('115200 baud', 'muted'))
        self.web_button = button('Open web GUI ↗', self.open_web, 'secondary')
        self.stop_all = button('Stop all outputs', lambda: self.send('/stop', {'id': 'all'}, None), 'stop')
        layout.addLayout(connection)
        if demo:
            layout.addWidget(label('OFFLINE DEMO · Preview only. No hardware is connected; settings are simulated.', 'notice', True))
        self.status = label('Select a serial port or enter http://<ESP32-IP>. Close Serial Monitor for USB.', 'status', True)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.web_button)
        status_row.addWidget(self.stop_all)
        layout.addLayout(status_row)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        layout.addWidget(tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('page')
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(0, 0, 8, 12)
        self.grid.setSpacing(16)
        self.cards = [ChannelCard(i) for i in range(5)]
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // 3, i % 3)
            card.action.connect(self.send)
        note = QFrame()
        note_layout = card_layout(note)
        note_layout.addWidget(label('OUTPUT NOTES', 'eyebrow'))
        note_layout.addWidget(label('All outputs boot OFF', 'cardTitle'))
        note_layout.addWidget(label('Editing a field does not change the signal. Press Apply channel.\n\n'
                                   'Pair frequency 0 disables both sides. At 0% duty the low side stays HIGH; '
                                   'at 100% the high side stays HIGH when enabled.\n\n'
                                   'Analog outputs are 8-bit DAC signals centered near half supply, nominally 0–3.3 V. '
                                   'Changing an analog channel briefly restarts the other active analog channel.\n\n'
                                   'Applied values are calculated hardware settings, not scope measurements.', 'muted', True))
        note_layout.addStretch()
        self.grid.addWidget(note, 1, 2)
        self.panels = self.cards + [note]
        self.columns = 3
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        scroll.setWidget(content)
        tabs.addTab(scroll, 'Generator outputs')
        net_scroll = QScrollArea()
        net_scroll.setWidgetResizable(True)
        net_content = QWidget()
        net_content.setObjectName('page')
        net_layout = QVBoxLayout(net_content)
        net_layout.setContentsMargins(0, 0, 8, 16)
        self.network = NetworkCard()
        self.network.action.connect(self.send)
        net_layout.addWidget(self.network)
        net_layout.addWidget(label('Saving reconnects Wi-Fi without rebooting or changing the outputs. '
                                   'USB control remains available. Network credentials are stored on the device; '
                                   'the desktop app remembers only the serial port and window size.', 'muted', True))
        net_layout.addStretch()
        net_scroll.setWidget(net_content)
        tabs.addTab(net_scroll, 'Wi-Fi && network')
        layout.addWidget(label('GPIO pairs 18/19 · 21/22 · 23/32     |     Waveforms 25 · 26     |     USB works without Wi-Fi', 'muted', True))
        self.refresh_ports()
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.refresh_controls()
        if demo:
            QTimer.singleShot(0, self.toggle_connection)

    def refresh_ports(self):
        current = self.selected_port() or self.settings.value('port', '')
        self.ports.clear()
        for info in list_ports.comports():
            self.ports.addItem(f'{info.device} · {info.description}', info.device)
        found = self.ports.findData(current)
        if found >= 0:
            self.ports.setCurrentIndex(found)
        elif current:
            self.ports.setEditText(current)
        if self.demo:
            self.ports.setEditText('Offline preview')

    def selected_port(self):
        index = self.ports.currentIndex()
        if index >= 0 and self.ports.currentText() == self.ports.itemText(index):
            return self.ports.currentData() or self.ports.currentText().strip()
        return self.ports.currentText().strip()

    @Slot()
    def toggle_connection(self):
        if self.worker and self.worker.isRunning():
            self.disconnect_device()
            return
        port = self.selected_port()
        if not port and not self.demo:
            self.status.setText('Select a serial port or enter an http:// device address.')
            return
        if not self.demo:
            self.settings.setValue('port', port)
        # Reconnecting reads a fresh snapshot. Old form values cannot be applied to another device.
        for card in self.cards:
            card.initialized = False
        self.network.initialized = False
        self.pending = 0
        worker = DeviceWorker(port, self.demo)
        self.worker = worker
        worker.ready.connect(self.connected)
        worker.result.connect(self.receive)
        worker.failed.connect(self.failed)
        worker.connection_error.connect(self.connection_error)
        worker.finished.connect(self.worker_finished)
        self.status.setText('Connecting and reading device settings…')
        self.connect_button.setText('Cancel connection')
        self.ports.setEnabled(False)
        self.refresh_button.setEnabled(False)
        worker.start()

    @Slot()
    def connected(self):
        if self.worker and not self.worker.isInterruptionRequested():
            self.online = True
            self.connect_button.setText('Disconnect')
            self.status.setText('Offline demo ready.' if self.demo else 'Connected. Displays show applied settings.')
            self.refresh_controls()

    def disconnect_device(self):
        if self.worker:
            self.worker.requestInterruption()
        self.online = False
        self.connect_button.setEnabled(False)
        self.status.setText('Disconnecting… Outputs retain their last applied state.')
        self.refresh_controls()

    @Slot()
    def worker_finished(self):
        self.online, self.pending = False, 0
        self.connect_button.setEnabled(True)
        self.connect_button.setText('Connect')
        self.ports.setEnabled(True)
        self.refresh_button.setEnabled(True)
        if self.status.text().startswith('Disconnecting'):
            self.status.setText('Disconnected. Outputs retain their last applied state.')
        self.refresh_controls()

    @Slot(str)
    def connection_error(self, message):
        self.online = False
        self.status.setText('Connection lost: ' + message)
        self.refresh_controls()

    def refresh_controls(self):
        for card in self.cards:
            card.online, card.busy = self.online and card.initialized, self.pending > 0
            card.refresh_controls()
        self.network.online, self.network.busy = self.online and self.network.initialized, self.pending > 0
        self.network.refresh_controls()
        self.stop_all.setEnabled(self.online)
        ip = self.network.data and self.network.data.get('currentIP')
        self.web_button.setEnabled(bool(self.online and not self.demo and ip and ip != '0.0.0.0' and self.network.data['connected']))

    @Slot(str, object, object)
    def send(self, path, params, context):
        if not self.online or not self.worker or self.worker.isInterruptionRequested():
            return
        if path != '/stop' and self.pending:
            return
        self.pending += 1
        # Only revision metadata crosses back to the UI; no credentials are logged or saved on the PC.
        self.worker.submit(path, params, context)
        self.status.setText({'/set': 'Applying channel…', '/burst': 'Starting bursts…', '/stop': 'Stopping outputs…',
                             '/network': 'Reading saved settings…', '/network/set': 'Saving network settings…'}[path])
        self.refresh_controls()

    @Slot(str, object, object, object)
    def receive(self, path, params, data, context):
        if not self.worker or self.worker.isInterruptionRequested():
            return
        action = path not in ('/state', '/network') or context is not None
        if action:
            self.pending = max(0, self.pending - 1)
        if path.startswith('/network'):
            load = context is not None and context[1] == self.network.revision
            self.network.update_network(data, load)
            if path == '/network/set':
                # Clear a submitted password once acknowledged, unless the user has typed a new one.
                if load:
                    self.network.feedback.setText('Saved in ESP32 flash. Reconnecting Wi-Fi…')
                self.status.setText('Network settings saved on ESP32. Wi-Fi reconnecting; USB remains available.')
            elif context:
                self.status.setText('Saved network settings read from ESP32.')
        else:
            for state in data:
                card = self.cards[state['id']]
                load = path == '/set' and context == (card.index, card.revision)
                card.update_state(state, load)
            if action:
                self.status.setText('Channel settings applied.' if path == '/set' else 'Burst sequence started.' if path == '/burst' else 'Stop confirmed by device.')
        self.refresh_controls()

    @Slot(str, object, str)
    def failed(self, path, context, message):
        if path != '/state':
            self.pending = max(0, self.pending - 1)
        self.status.setText('Action not confirmed: ' + message)
        if path == '/set' and context:
            self.cards[context[0]].feedback.setText(message)
        elif path == '/network/set':
            self.network.feedback.setText(message)
        self.refresh_controls()

    def open_web(self):
        if self.network.data and self.network.data['connected'] and not self.demo:
            QDesktopServices.openUrl(QUrl('http://' + self.network.data['currentIP']))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'panels'):
            return
        columns = max(1, min(3, (self.width() - 72) // 330))
        if columns != self.columns:
            self.columns = columns
            for panel in self.panels:
                self.grid.removeWidget(panel)
            for i, panel in enumerate(self.panels):
                self.grid.addWidget(panel, i // columns, i % columns)
            for i in range(3):
                self.grid.setColumnStretch(i, 1 if i < columns else 0)

    def closeEvent(self, event):
        self.settings.setValue('geometry', self.saveGeometry())
        if self.worker and self.worker.isRunning():
            self.disconnect_device()
            # Keep the Qt event loop responsive until the bounded serial read finishes.
            self.worker.finished.connect(self.close)
            event.ignore()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Preview the interface without hardware')
    parser.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setFont(QFont('DejaVu Sans', 10))
    app.setStyleSheet(STYLE)
    window = Window(args.demo)
    window.show()
    if args.screenshot:
        QTimer.singleShot(1300, lambda: window.grab().save(str(args.screenshot)))
        QTimer.singleShot(1600, window.close)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
