# Live USB and Python GUI verification — 2026-10-15

Board: ESP32-D0WD-V3 revision 3.1, connected at `/dev/ttyUSB0`. Built and uploaded with Arduino ESP32 core 3.3.12, target `esp32:esp32:esp32`. Upload verification passed. Firmware uses 1,006,293 bytes of program storage and 63,128 bytes of static RAM.

All external outputs were kept disabled during configuration checks. Burst engine tests used the existing `test=1` option, which disconnects the RMT route and holds the external GPIO LOW. No external waveforms or analog voltages were measured.

## Serial and web checks

All 10 live checks passed; see [serial results](serial-results.txt).

- USB handshake, all five channel states, Stop All, network settings read, and stored password hidden.
- All three pairs: 1 Hz, 1 kHz and 100 kHz settings; 0%/100% duty; frequency zero. Values were applied and read back with outputs disabled.
- Both multifunction channels: pulse, burst, sine, triangle and rectangle settings, applied and read back while disabled.
- Invalid dead time, non-finite input, invalid pulse durations, invalid channel IDs, and invalid burst Apply rejected without state changes.
- Both RMT channels completed three concurrent internal bursts of 255 pulses at 1 µs on/off. Long internal burst sequences were cancelled using Stop All.
- Existing web page loaded. Web Apply was visible over USB, USB Apply was visible through `/state`, and web Stop All was confirmed over USB.
- The current DHCP lease address was saved as a static IP. IP/gateway/subnet/DNS survived a hardware reset, and the board reconnected using that address.
- A temporary unavailable SSID containing spaces, Unicode, `+`, `&` and `=` survived a reset. USB control remained available while Wi-Fi was unavailable.
- Original SSID, unchanged password and DHCP mode were restored and checked after another hardware reset.
- Invalid static addressing and a short replacement password were rejected without changing saved settings.

## Python GUI on real hardware

All six GUI checks passed; see [GUI results](gui-results.txt). The actual Qt widgets and serial worker were exercised against the connected ESP32, using Qt's offscreen platform for automation.

- Connect and initial read of all five channels and network settings.
- Apply a changed pair frequency, confirm readback, preserve another channel's pending edits, then restore the frequency.
- Select and Apply all five multifunction modes on both channels while disabled.
- Read and save Wi-Fi settings through the GUI; password remained hidden and unchanged.
- Stop All acknowledged by the board; background polling continued.
- GUI closed cleanly and released the serial port.

Final state: original output settings restored, all outputs OFF, original Wi-Fi SSID/password restored, DHCP enabled, connected at `192.168.178.55`. Saved static-address fields retain the successfully tested current-network values as a template; they are inactive while DHCP is enabled. No firmware changes were needed during these live checks.
