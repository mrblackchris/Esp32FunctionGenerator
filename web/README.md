# Shared browser controller

The same generated interface runs on the ESP32 homepage and locally, with USB serial or Wi-Fi HTTP control. All five output cards and the Wi-Fi/IP controls are on one page. The channel markup, mode controls and applied-value summaries come from the existing firmware page.

## Open the single HTML file

Open **[function-generator.html](../function-generator.html)** from the project root in desktop Chrome or Edge. It contains all styling and JavaScript inside the file. You can copy it anywhere and open it directly with a `file://` URL. No server, shell script, Python, Node, packages or internet connection are required.

Choose **USB serial**, click **Connect**, and select the ESP32 port; or choose **Wi-Fi / HTTP**, enter `http://<device-IP>` and Connect. Close Arduino Serial Monitor and the Python GUI first so the port is available. Upload the updated firmware, including `web_page.h`, to enable all current HTTP endpoints.

Direct file opening was checked in Chrome 155: the file is a secure context, Web Serial is available, the Connect button requests the native device chooser, and no external resources are loaded. Browser/device policies may still restrict USB access. In that case, the optional localhost launcher remains available:

```bash
python3 web/serve.py
```

This serves the same self-contained page at **http://127.0.0.1:8000**. It uses Python's standard library only to serve files, not to access USB. `--port 8001` selects another port and `--no-browser` suppresses automatic browser opening. Ctrl+C stops the optional server.

## One-page controls

- **USB connection:** Connect, Disconnect, connection status and Stop All.
- **Wi-Fi & IP settings:** current SSID, connection state, IP, DHCP/static mode, gateway, subnet, DNS and whether a password is stored. Expand **Edit saved Wi-Fi and IP settings** to change them.
- **Output cards:** the same frequency, duty, dead-time, pulse, burst and DAC settings as the ESP32 web page, including Apply, Start bursts, Stop and applied timing summaries.

Fields do not change the outputs until Apply. A burst needs Apply followed by Start bursts. Polling updates applied values and burst progress while preserving pending edits. Applying one channel preserves edits on the other channels. Stop cancels queued Apply commands; an action already executing on the ESP32 must finish before Stop is processed. A timed-out mutation is never automatically repeated.

Network settings are read from and saved on the ESP32, not in browser storage. **Reload saved settings** replaces pending network edits. The saved password stays hidden and is kept unless **Replace saved password** is checked. Replacing it with an empty field explicitly selects an open network. Input combinations are validated by the same firmware handlers used by the Python controller.

Saving reconnects Wi-Fi without rebooting or reconfiguring waveform outputs. Saved credentials and DHCP/static addressing survive power-off. USB remains available when Wi-Fi is disconnected. Disconnecting or closing the page leaves the last applied output state in place; press Stop All first if desired. Some USB adapters reset the ESP32 when opened; the page retries its initial read-only handshake while the board starts.

## Files and checks

- `../function-generator.html`: the complete standalone controller to open or copy.
- `index.html`: an identical standalone copy, also usable through the optional server.
- `page.template.html`, `style.css`, `channel-forms.js`, `serial.mjs`, `http.mjs`, `app.mjs`: development sources. These files are not needed alongside the standalone HTML.
- `build_standalone.py`: rebuilds both HTML files after a source change: `python3 web/build_standalone.py`.
- `serve.py`: optional standard-library localhost file server, with no serial bridge.

Run transport regression checks with Node (needed for development checks only):

```bash
node --test tests/test_web_serial.mjs
```

Seven tests cover fragmented UTF-8 replies, stale IDs, URL-encoded credentials, command serialization, firmware validation errors, queued Stop/Apply behavior, timeouts without replay, request-size limits, cleanup and reconnect.

Chrome automation also exercised this page against the connected ESP32 through a test-only serial stream adapter: setting/readback, every multifunction mode with outputs disabled, validation feedback, network read/save, edit preservation, Stop All, a 390px viewport, and disconnect/reconnect with resumed polling. That adapter was used only by the test harness; it is absent from the shipped page. Chrome's native USB device chooser still requires the user's selection and was not automated. See [browser live-check results](../measurements/2026-10-15-browser-usb/README.md).

Reference: [Chrome Web Serial API documentation](https://developer.chrome.com/docs/capabilities/serial).

## Shared API

See [CONTROL_API.md](../docs/CONTROL_API.md) for command names, Python examples and browser network permissions. The build also generates `../web_page.h`, embedded by the sketch. Opening the ESP32 homepage connects automatically to its own address. Network settings can be read and saved over either connection.
