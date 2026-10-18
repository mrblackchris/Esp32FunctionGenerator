# Getting started

## Hardware and limits

Use a classic ESP32 development board, a USB data cable, and an oscilloscope for physical verification. The previously tested board was an ESP32-D0WD-V3. ESP32-S2/S3/C3 and other variants are not supported by this sketch: it requires the classic chip's MCPWM resources and GPIO25/26 DACs.

| UI channel | Protocol ID | Output pins | Engine |
| --- | --- | --- | --- |
| Pair 1 | 0 | GPIO18 high, GPIO19 low | MCPWM |
| Pair 2 | 1 | GPIO21 high, GPIO22 low | MCPWM |
| Pair 3 | 2 | GPIO23 high, GPIO32 low | MCPWM |
| Multifunction 1 | 3 | GPIO25 | MCPWM, RMT or DAC |
| Multifunction 2 | 4 | GPIO26 | MCPWM, RMT or DAC |

Connect instrument ground to ESP32 GND. These are 3.3 V logic and low-current, unbuffered DAC outputs, not power outputs or calibrated 50-ohm sources. Do not connect a load that exceeds the board's electrical ratings. All channels start OFF; closing a controller does not stop a running output. Stop is software controlled. A power stage needs independent hardware shutdown.

## Build and upload with Arduino IDE

1. Install Arduino IDE and add Espressif's board manager URL in Preferences:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.
2. In Boards Manager install **esp32 by Espressif Systems**. The project previously recorded successful compilation with **3.3.12**; use that version to reproduce those checks. Core 2.x is unsupported; other 3.x versions require verification.
3. Keep the sketch in a directory named `Esp32FunctionGenerator`, matching `Esp32FunctionGenerator.ino`. Rename the downloaded/extracted directory if necessary.
4. Open the sketch, select **ESP32 Dev Module** for a compatible generic classic ESP32 board (or the appropriate classic ESP32 board), and choose its USB port. No extra Arduino libraries need installation.
5. Keep external power circuitry disconnected, then verify and upload. This replaces the board firmware. Open Serial Monitor at **115200 baud** to inspect startup, then close it before connecting another controller.

For Arduino CLI, run from the sketch directory after installing the CLI:

```bash
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.12 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli board list
arduino-cli upload --fqbn esp32:esp32:esp32 --port /dev/ttyUSB0 .
```

Replace the port with your device's port, such as `/dev/ttyACM0` or `COM3`. Espressif's [Arduino installation guide](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html) covers platform setup.

## Connect over USB first

Open [function-generator.html](../function-generator.html) in desktop Chrome or Edge, choose **USB serial** and click **Connect**, and choose the ESP32. Only one serial controller can use the port at a time. If browser policy blocks direct-file USB access, run `python3 web/serve.py` from the project root and open the localhost address it prints. See the [browser guide](../web/README.md).

For the Python alternative, follow the [desktop guide](../desktop/README.md). It requires Python 3.10+ and the packages in `desktop/requirements.txt`.

On a fresh device the sketch has empty Wi-Fi defaults. Use the USB controller's network settings to enter SSID and password and save. DHCP is the simplest initial option. The saved record overrides sketch defaults and survives reboot and normal uploads. A full flash erase clears it. USB remains usable without Wi-Fi.

Once connected to Wi-Fi, open `http://<device-IP>/` using the address shown by the USB controller or serial log. That page is served by the ESP32 itself. It does not require the PC HTML file. Network configuration is available through USB or HTTP; saving over Wi-Fi can require reconnecting to a changed address. The HTTP interface has no authentication or TLS; use a trusted local network and do not expose it to the internet.

## First output

With a scope attached to GPIO18 and GND, configure Pair 1 for 1000 Hz, 50% duty and 1 µs dead time. Select Enable and Apply. Confirm the measured signal, then press Stop All and confirm LOW. Verify both pins and dead time before connecting a complementary driver. At 0% or 100% duty one pin stays HIGH while enabled; frequency 0 or disabling holds both LOW.

The [main README](../README.md) documents all mode ranges, frequency quantization and shared-DAC behavior. Historical [measurement records](../measurements/) distinguish software checks from physical measurements; they are not a verification of every channel or analog waveform.

For Python scripting and local HTML Wi-Fi control see the [unified control API](CONTROL_API.md). Keep the generated `web_page.h` with the sketch when copying source.
