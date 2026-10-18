# License and third-party dependencies

## Project license: MIT

The project's original firmware, controllers and documentation are released under the [MIT License](../LICENSE), as selected by the author. The copyright notice identifies “ESP32 Function Generator contributors” without inferring a personal name from a computer account.

MIT allows use, modification and redistribution, including commercial use. Copies or substantial portions must retain the copyright and license notice. Modified versions can be distributed without publishing their source. The license includes warranty and liability exclusions. See the [MIT license explanation](https://choosealicense.com/licenses/mit/) and the full text in this repository.

The author states that the project code is self-made. Third-party dependencies remain subject to their own terms; this project's MIT license does not relicense Qt, pySerial, Arduino or ESP-IDF.

## Dependencies and redistribution

| Dependency | Use here | Upstream licensing reference |
| --- | --- | --- |
| Arduino-ESP32 | Firmware framework and bundled libraries | [Core license: LGPL-2.1 text](https://github.com/espressif/arduino-esp32/blob/master/LICENSE.md) |
| ESP-IDF and components | MCPWM, RMT, DAC, GPIO and runtime | [ESP-IDF license and component notes](https://github.com/espressif/esp-idf/blob/master/LICENSE) |
| PySide6-Essentials / Qt for Python | Desktop QtCore/QtGui/QtWidgets | [Qt for Python licensing](https://doc.qt.io/qtforpython-6/commercial/index.html), [Qt module licensing](https://doc.qt.io/qt-6/licensing.html) |
| pySerial | Desktop USB serial | [BSD license and bundled-file notices](https://github.com/pyserial/pyserial/blob/master/LICENSE.txt) |

Upstream links are starting points; inspect the exact versions and components you distribute. Qt's community distribution uses LGPLv3/GPLv3 terms depending on component; commercial licensing is also offered. This project's permissive license would not remove those obligations. Consult [Qt's LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) before packaging the desktop program.

Publishing your own source with dependency installation instructions is the simplest first release. If you later distribute firmware binaries or a bundled desktop executable, review all included components, preserve their notices/license texts, and provide the source and relinking/replacement materials required by applicable licenses. Embedded firmware can contain statically linked LGPL code. A source link alone should not be assumed to satisfy every binary-distribution obligation.
