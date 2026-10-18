#!/usr/bin/env python3
"""Serve only the browser controller on localhost. USB access happens in the browser."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Permissions-Policy', 'serial=(self)')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(directory)))
    except OSError as error:
        parser.exit(1, f'Cannot start the controller: {error}. Try --port 8001.\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'ESP32 USB controller: {url}', flush=True)
    print('Open in desktop Chrome or Edge, then click Connect USB. Ctrl+C stops the server.', flush=True)
    if not args.no_browser:
        threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
