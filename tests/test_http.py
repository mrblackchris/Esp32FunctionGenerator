"""HTTP client integration against a local server; no ESP32 or Qt required."""
import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from protocol import HttpClient, DeviceError


class Handler(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.calls.append(('GET', self.path, {}))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'ssid': 'example'} if self.path == '/network' else []).encode())
    def do_POST(self):
        params = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(), keep_blank_values=True)
        self.calls.append(('POST', self.path, params))
        self.send_response(400 if params.get('id') == ['bad'] else 200)
        self.end_headers()
        self.wfile.write(b'Invalid channel' if params.get('id') == ['bad'] else b'[]')


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
    def setUp(self):
        Handler.calls.clear()
        self.client = HttpClient(f'http://127.0.0.1:{self.server.server_port}')
    def test_common_read_and_mutation_contract(self):
        self.assertEqual(self.client.request('/state'), [])
        params = {'id': 0, 'enabled': 0, 'frequency': 1000, 'duty': 50, 'deadUs': 1}
        self.assertEqual(self.client.request('/set', params), [])
        self.assertEqual(Handler.calls[-1], ('POST', '/set', {k: [str(v)] for k, v in params.items()}))
        self.assertEqual(self.client.request('/network'), {'ssid': 'example'})
    def test_credentials_encoded_and_error_not_replayed(self):
        self.client.request('/network/set', {'ssid': 'A & + ü', 'password': 'x&=+ y'})
        self.assertEqual(Handler.calls[-1][2]['ssid'], ['A & + ü'])
        with self.assertRaisesRegex(DeviceError, 'Invalid channel'):
            self.client.request('/stop', {'id': 'bad'})
        self.assertEqual(len(Handler.calls), 2)
    def test_address_validation(self):
        for address in ['https://device', 'http://device/path', 'http://user:pass@device']:
            with self.assertRaises(ValueError):
                HttpClient(address)
