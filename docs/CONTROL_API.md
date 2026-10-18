# Unified control API

All controllers use the same paths, parameter names and channel JSON data. Wi-Fi uses **HTTP over TCP/IP on port 80**, not a raw TCP socket. Serial uses a newline-framed envelope at 115200 baud. Both firmware transports call the same validation and action handlers.

## Ways to connect

| Controller | Connection |
| --- | --- |
| ESP32 homepage | Open `http://<ESP32-IP>/`; connects to its host automatically |
| Local `function-generator.html` | Choose USB serial or Wi-Fi / HTTP, enter device address and Connect |
| Python desktop GUI | Select a serial port or type `http://<ESP32-IP>` in the connection field |
| Python scripts | `HttpClient(address)` or `SerialClient(port)`, then identical `request(path, params)` calls |

The homepage and local page are generated from the same web sources. Upload the updated firmware once to get the shared homepage, HTTP network endpoints and cross-origin support. Keep `web_page.h` alongside the sketch.

For local browser Wi-Fi control, the PC and ESP32 must be able to reach each other. If direct-file requests are blocked, use `python3 web/serve.py` and open `http://127.0.0.1:8000`. Allow local-network access when the browser requests it. Browser policy can still block access; use the ESP32 homepage or Python HTTP client in that case. See [Chrome's local-network access documentation](https://developer.chrome.com/blog/local-network-access).

USB browser control requires desktop Chrome/Edge and an available serial port. Close other serial programs first. A fresh board's Wi-Fi is configured through USB; it does not create its own access point.

## Commands

| Path | HTTP method | Parameters | Successful data |
| --- | --- | --- | --- |
| `/state` | GET | None | Five-channel array |
| `/set` | POST | `id`, `enabled`, and mode settings below | Five-channel array |
| `/burst` | POST | `id=3` or `4`; optional diagnostic `test=1` | Five-channel array |
| `/stop` | POST | `id=0..4` or `all` | Five-channel array |
| `/network` | GET | None | Network object, without password |
| `/network/set` | POST | Network fields below | Saved network object |

IDs 0–2 are Pair 1–3; IDs 3–4 are Multifunction 1–2. Booleans are encoded as `0` or `1`. HTTP POST bodies use `application/x-www-form-urlencoded`; serial query arguments use the same URL encoding.

For pair `/set`, send `frequency` (0 for off or 1–100000 Hz), `duty` (0–100%) and `deadUs` (0–1000 µs, subject to pulse widths), plus `id` and `enabled`.

For multifunction `/set`, send `id`, `enabled` and `mode`:

- `pulse`: integer `onUs`, `offUs`, each 1–30000.
- `burst`: `onUs`, `offUs`, integer `pulseCount` (1–255), `burstCount` (1–1000), `gapMs` (0–60000), and **`enabled=0`**. Apply configures; a subsequent `/burst` starts the sequence.
- `sine`, `triangle`, `rectangle`: `waveHz` (10–5000) and `amplitude` (0–100).

For `/network/set`, send `ssid`, `dhcp=0|1`, `replacePassword=0|1`; include `password` if replacing it. For static addressing also send `ip`, `gateway`, `subnet`, `dns`. The firmware validates before saving to flash. Password is never returned. Saving acknowledges persistence before reconnecting Wi-Fi. An HTTP client may lose connection and need the new address; USB remains available.

## Identical Python commands

```python
# From examples/ the scripts import these clients from desktop/protocol.py.
client.request('/state')
client.request('/set', {
    'id': 0, 'enabled': 1, 'frequency': 1000, 'duty': 50, 'deadUs': 1,
})
client.request('/stop', {'id': 'all'})
```

Run from the project root:

```bash
# Standard-library only; reads state and network configuration.
python3 examples/control_wifi_example.py 192.168.1.50

# Serial requires pySerial (no Qt needed).
python3 -m pip install pyserial
python3 examples/control_serial_example.py /dev/ttyUSB0
```

On Windows use `py` and a port such as `COM3`. Add **`--run`** to either script to enable Pair 1 at 1 kHz, 50% duty and 1 µs dead time for two seconds, followed by Stop All. This stops any other running channels too. The scripts attempt Stop All even if the run is interrupted or Apply times out; a failed connection can prevent confirmation. Verify the outputs with a scope.

## Wire format and errors

HTTP returns JSON data directly on success and an error message with a non-200 status on failure. Serial wraps the same data or error message with request ID and status:

```text
FG 1 /state
FG 2 /set?id=0&enabled=0&frequency=1000&duty=50&deadUs=1
FG 3 /stop?id=all
FG {"id":3,"code":200,"data":[...]}
```

Each serial request/reply ends with newline. IDs are 1–999999999. Requests have a 1536-byte limit before newline and at most 20 arguments. Boot logs have no `FG ` prefix. Clients match IDs and ignore unrelated lines.

Both Python clients return parsed data or raise `DeviceError` on device rejection. Communication failures leave action completion uncertain; read `/state` before retrying. Mutating commands are never automatically replayed. Browser and desktop queues serialize requests and prioritize Stop over older queued mutations; Stop cannot interrupt an already executing command.

Output settings are shared device state: whichever controller applies last wins. Controllers are not locked against each other. Closing a connection does not stop outputs. Stop depends on the processor and communication link.

The HTTP API has no authentication or TLS, and permits cross-origin access for the local HTML controller. Use it on a trusted local network. The MIT license on original code does not alter dependency terms.
