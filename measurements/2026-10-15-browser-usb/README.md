# PC HTML controller verification — 2026-10-15

The firmware was unchanged. The page was served from localhost and exercised in Chrome 155 using Playwright. The physical ESP32-D0WD-V3 at `/dev/ttyUSB0` received the page's serial commands through a test-only Web Serial stream adapter, backed by pySerial. Production code uses native `navigator.serial` directly and contains no serial bridge or test endpoint. Native Chrome chooser selection was not automated.

All eight browser/hardware checks passed; see [results](results.txt):

1. Connect and read all five real channel states and network settings.
2. Apply and read back a pair frequency, preserve another channel's pending edit, restore the original setting. Applied frequency reflected hardware timer quantization.
3. Apply pulse, burst, sine, triangle and rectangle modes on both multifunction outputs while disabled; verify burst Start requires Apply.
4. Display firmware timing-validation errors without applying the rejected combination.
5. Read and save Wi-Fi settings on the same page. Keep the existing password hidden and unchanged; reject a short replacement password.
6. Preserve pending Wi-Fi edits during polling; explicitly reload saved settings.
7. Confirm Stop All and check a 390px-wide viewport without horizontal overflow.
8. Disconnect and reconnect, then confirm polling resumes and all outputs remain OFF.

No JavaScript page errors occurred. All external outputs stayed OFF; no external waveforms were emitted or measured. Original channel configuration, Wi-Fi credentials and DHCP mode were retained. The local test server and serial adapter were stopped after testing.

The seven serial-transport unit tests in `tests/test_web_serial.mjs` also passed. Firmware flash persistence across resets had already been verified separately in the [earlier USB/GUI hardware checks](../2026-10-15-usb-gui/README.md).

## Standalone HTML follow-up

`function-generator.html` now embeds all CSS and JavaScript and opens directly from disk, without a local server. Chrome 155 confirmed a secure `file://` context, native Web Serial availability, a successful call to request the USB chooser, no JavaScript errors and no external resource requests. Native chooser selection remains manual.

The eight browser/hardware checks above were repeated with the standalone `file://` page and the same test-only serial adapter; all passed again. See [standalone results](standalone-results.txt). All outputs were left OFF.
