# Publishing on GitHub

## Prepare the first release

- Include the root [MIT license](../LICENSE) in the release. See [LICENSING.md](LICENSING.md) for third-party dependency terms.
- Check original-code ownership and any copied assets or snippets.
- Review files for passwords, personal network details and local paths. The sketch now ships with empty Wi-Fi defaults; users configure Wi-Fi over USB. Saved credentials on your own board are separate from source files.
- Keep `.venv`, caches, build output and the legacy `FuncGenerator.zip` out of the repository. The legacy ZIP was removed during repository cleanup because it may have contained older credentials. Rebuild any downloadable archive from reviewed sources. If the old password has been shared publicly, change it.
- Follow [GETTING_STARTED.md](GETTING_STARTED.md) from a clean copy. Keep the sketch directory named `Esp32FunctionGenerator`.
- Run the checks below and record the actual environment/results. Keep historical measurement claims distinct from checks performed for this release.

## Local validation

From the project root, with Python 3.10+ and Node.js installed:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r desktop/requirements.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_web*.mjs
python3 web/build_standalone.py
node --check web/app.mjs
node --check web/serial.mjs
node --check web/channel-forms.js
arduino-cli compile --fqbn esp32:esp32:esp32 .
```

Install the pinned Arduino core as described in the getting-started guide. Rebuilding should reproduce both HTML files and `web_page.h`; review any differences before committing. Desktop dependencies are bounded ranges, not a frozen lockfile: record the actual versions for a release.

Preview the Python GUI with `.venv/bin/python desktop/function_generator.py --demo`. For hardware validation, begin with external power hardware disconnected: verify all outputs OFF on boot, command readback, Stop All, and persistence of USB-configured network settings. Check actual waveforms on a scope before claiming electrical accuracy. A simulated test passing does not establish physical timing, complementary dead time or DAC voltage accuracy.

## Create the repository

The supplied working folder has no Git repository initialized. After reviewing files, run:

```bash
git init -b main
git add .
git status --short
git diff --cached --stat
git diff --cached
```

Inspect the staged content, including measurement logs, before committing. `.gitignore` does not remove anything already tracked; use `git rm --cached <path>` if needed. Previously committed credentials also require history cleanup before publication; deleting them from the latest file is insufficient.

```bash
git commit -m "Prepare ESP32 function generator release"
```

Create an empty repository on GitHub named `Esp32FunctionGenerator` without automatically adding a README or license. Replace `YOUR_USERNAME` below with your account or organization:

```bash
git remote add origin https://github.com/YOUR_USERNAME/Esp32FunctionGenerator.git
git push -u origin main
```

Suggested description: “Classic ESP32 function generator with complementary PWM, pulse bursts, dual DAC waveforms, and USB/Wi-Fi controllers.” Suggested topics: `esp32`, `arduino`, `function-generator`, `pwm`, `dac`, `web-serial`, `pyside6`.

## Tag and publish a version

Choose a version that reflects the experimental hardware status; `v0.1.0` is a reasonable first version. After validation, tag the exact reviewed commit:

```bash
git tag -a v0.1.0 -m "First public release"
git push origin v0.1.0
```

Create a GitHub Release for that tag. Describe supported hardware, installation instructions, actual tool/dependency versions, completed tests, known limitations and the selected license. Mark it as a prerelease if validation is incomplete.

GitHub supplies source archives for the tag. Optionally attach the generated `function-generator.html` so users can download the USB controller directly. Keep the firmware source and documentation in the repository. Include compiled firmware or bundled Python binaries only after adding board/flash instructions and satisfying the applicable third-party redistribution requirements.

Existing limitations to mention: classic ESP32 only, unbuffered/uncalibrated DACs, quantized analog frequencies, approximate inter-burst gaps, shared DAC playback restarts, software-dependent Stop and unauthenticated local HTTP control. Physical GPIO18 PWM records exist; comprehensive pin/dead-time/DAC measurements are still needed.

## Unified-interface validation (2026-10-18)

The unified HTTP/serial implementation compiled for `esp32:esp32:esp32` using core 3.3.12: 1,028,701 bytes flash and 63,128 bytes global RAM. All 17 Python tests (desktop/serial plus HTTP integration) and 10 JavaScript transport tests passed. Qt test cleanup explicitly destroys remaining widgets while QApplication is alive.

A headless Chrome check against a simulated HTTP device verified local-file connection, channel Apply, Stop All, Disconnect, and automatic connection of the generated ESP32 homepage with all five forms and no JavaScript errors. Generated HTML/header reproducibility and documentation links were checked. These changes were not uploaded to or validated on physical hardware; existing measurement records describe earlier firmware.
