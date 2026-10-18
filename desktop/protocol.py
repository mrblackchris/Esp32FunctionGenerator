"""Shared HTTP/TCP-IP and serial clients. No Qt dependency."""
from __future__ import annotations

import json
import time
from urllib.parse import urlencode

try:
    import serial
except ImportError:
    serial = None  # HTTP needs only the standard library.

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DeviceError(Exception):
    """The device rejected a command; the serial connection is still usable."""


class SerialClient:
    def __init__(self, port: str):
        if serial is None:
            raise RuntimeError('Serial control requires pySerial: python -m pip install pyserial')

        # Set these before opening to avoid deliberately resetting an ESP32.
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=2)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.sequence = 0
        self.buffer = bytearray()

    def close(self):
        self.serial.close()

    def request(self, path: str, params: dict | None = None, timeout: float = 6):
        self.sequence = self.sequence % 999999999 + 1
        query = '?' + urlencode(params) if params else ''
        message = f'FG {self.sequence} {path}{query}\n'.encode('utf-8')
        if len(message) > 1537:
            raise DeviceError('Command is too long for the firmware (1536 bytes).')
        self.serial.write(message)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.buffer.extend(self.serial.read(max(1, min(self.serial.in_waiting, 8192))))
            while b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                if not line.startswith(b'FG '):
                    continue  # Ignore boot and diagnostic messages.
                try:
                    response = json.loads(line[3:])
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(response, dict) or response.get('id') != self.sequence:
                    continue  # A late response must never acknowledge a newer command.
                if response.get('code') != 200:
                    raise DeviceError(str(response.get('data', 'Device rejected command.')))
                if 'data' not in response:
                    raise DeviceError('Incomplete device response. Update the firmware.')
                return response['data']
            if len(self.buffer) > 16384:
                self.buffer.clear()
        raise TimeoutError('No matching USB response. Check the cable, port and updated firmware. '
                           'The command may have been applied; check device status before retrying.')


class HttpClient:
    """HTTP over TCP/IP, using the same request(path, params) API as SerialClient."""

    def __init__(self, address: str):
        from urllib.parse import urlsplit
        if '://' not in address:
            address = 'http://' + address
        parsed = urlsplit(address)
        if parsed.scheme != 'http' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Use an HTTP device address, for example http://192.168.1.50')
        self.address = address.rstrip('/')

    def close(self):
        pass

    def request(self, path: str, params: dict | None = None, timeout: float = 6):
        if path not in ('/state', '/network', '/set', '/burst', '/stop', '/network/set'):
            raise ValueError('Unknown command path')
        reading = path in ('/state', '/network')
        if reading and params:
            raise ValueError('Read commands do not accept parameters')
        data = None if reading else urlencode(params or {}).encode('utf-8')
        request = Request(self.address + path, data=data, method='GET' if reading else 'POST',
                          headers={'Content-Type': 'application/x-www-form-urlencoded', 'Cache-Control': 'no-store'})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            raise DeviceError(error.read().decode('utf-8', errors='replace')) from error
        except (URLError, TimeoutError, OSError) as error:
            raise TimeoutError('HTTP action not confirmed. It may have been applied; read state before retrying.') from error
