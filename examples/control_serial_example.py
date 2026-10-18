#!/usr/bin/env python3
"""Control the ESP32 over serial. Default: read state without changing outputs."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from protocol import SerialClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', help='Serial port, for example /dev/ttyUSB0 or COM3')
    parser.add_argument('--run', action='store_true', help='Generate 1 kHz on Pair 1 for two seconds, then Stop All')
    args = parser.parse_args()
    client = SerialClient(args.port)
    try:
        # Some adapters reset on open. Retry only the initial read, never an action.
        for attempt in range(4):
            try:
                state = client.request('/state', timeout=3)
                break
            except TimeoutError:
                if attempt == 3:
                    raise
        print(json.dumps(state, indent=2))
        if args.run:
            try:
                # Identical command and parameter names for HTTP and serial.
                client.request('/set', {'id': 0, 'enabled': 1, 'frequency': 1000, 'duty': 50, 'deadUs': 1})
                time.sleep(2)
            finally:
                client.request('/stop', {'id': 'all'})
        print(json.dumps(client.request('/network'), indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
