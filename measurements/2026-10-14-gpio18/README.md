# GPIO18 physical PWM check — 2026-10-14

PicoScope 2205A channel A, DC coupling, ±5 V input range, 0.64 µs sample interval, 16000 samples per capture. CSV voltages are measured at the scope input; probe attenuation has not been applied.

| Requested frequency | Requested duty | Measured frequency | Measured complete-cycle duty |
| --- | --- | --- | --- |
| 1000 Hz | 50% | 1000.036 Hz | 49.922% |
| 1000 Hz | 25% | 1000.000 Hz | 24.896% |

Dead time was configured to 1 µs, so expected high-side duties are 49.9% and 24.9%. Measured high level at the scope input was approximately 0.338 V; if the probe is ×10, this corresponds to approximately 3.38 V at GPIO18. Probe attenuation still needs confirmation. The original scope range limits voltage precision at this input amplitude.

Stop returned channel A to approximately zero volts with no transitions. Original Pair 1 settings (1000 Hz, 50%, 1 µs dead time) were restored with output disabled. Other channels were not enabled. Firmware was not changed. GPIO19 and complementary dead time were not captured, so the measurement verifies GPIO18 only.

The initial device state reported all channels disabled. To produce PWM through the page, tick Enable output on Pair 1 and press Apply channel. Make sure the browser shows the ON badge.
