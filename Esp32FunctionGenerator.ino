#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <math.h>
#include <errno.h>
#include "driver/mcpwm_prelude.h"
#include "driver/gpio.h"
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "driver/dac_continuous.h"
#include "esp_rom_gpio.h"
#include "esp_system.h"
#include "soc/gpio_struct.h"
#include "soc/gpio_sig_map.h"

#if !CONFIG_IDF_TARGET_ESP32
#error "This generator requires the classic ESP32 with two MCPWM groups."
#endif

// Configure Wi-Fi over USB after flashing; saved NVS settings override these defaults.
const char* ssid = "";
const char* password = "";

WebServer server(80);
constexpr uint32_t BASE_CLOCK = 10000000;
struct Settings {
    double frequency = 1000, duty = 50, deadUs = 1;
    uint32_t onUs = 20, offUs = 80;
    String mode = "pulse";
    uint32_t pulseCount = 10, burstCount = 1, gapMs = 100;
    double waveHz = 100, amplitude = 50;
    bool enabled = false;
};
struct Timing {
    uint32_t resolution, period, compare, dead;
};
struct Output {
    int group, highPin, lowPin;
    mcpwm_oper_handle_t op = nullptr;
    mcpwm_timer_handle_t timer = nullptr;
    mcpwm_cmpr_handle_t comparator = nullptr;
    mcpwm_gen_handle_t high = nullptr, low = nullptr;
    uint32_t highSignal = 0, lowSignal = 0;
    SemaphoreHandle_t stopped = nullptr;
    bool timerRunning = false;
    Settings settings;
    Timing timing = {};
    rmt_channel_handle_t burstChannel = nullptr;
    rmt_encoder_handle_t burstEncoder = nullptr;
    rmt_symbol_word_t symbols[255];
    volatile bool burstDone = false;
    bool burstWaiting = false;
    bool internalTest = false;
    uint32_t completedBursts = 0, nextBurstMs = 0;
};
Output outputs[5];
constexpr uint32_t WAVE_SAMPLE_HZ = 40000;
constexpr uint32_t WAVE_SAMPLES = 4096;
uint8_t waveBuffer[WAVE_SAMPLES * 2];
dac_continuous_handle_t waveDac = nullptr;
uint32_t dacMask = 0;
bool dacEnabled = false;

// A small transport adapter lets USB commands use exactly the web validation/actions.
// Requests: FG <request-id> /path?key=value&...\n (URL-encoded UTF-8).
// Responses: FG {"id":...,"code":...,"data":...}\n. Boot logs have no FG prefix.
bool serialRequest = false;
uint32_t serialRequestId = 0;
String serialKeys[20], serialValues[20];
int serialArgumentCount = 0;

String jsonString(const String& value) {
    String result = "\"";
    const char* hex = "0123456789abcdef";
    for (unsigned int i = 0; i < value.length(); ++i) {
        uint8_t c = value[i];
        if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
        else if (c < 32) { result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15]; }
        else result += char(c);
    }
    return result + '"';
}

bool requestHasArg(const char* name) {
    if (!serialRequest) return server.hasArg(name);
    for (int i = 0; i < serialArgumentCount; ++i) if (serialKeys[i] == name) return true;
    return false;
}
String requestArg(const char* name) {
    if (!serialRequest) return server.arg(name);
    for (int i = 0; i < serialArgumentCount; ++i) if (serialKeys[i] == name) return serialValues[i];
    return "";
}
void respond(int code, const char* type, const String& body) {
    if (!serialRequest) {
        server.sendHeader("Cache-Control", "no-store");
        server.sendHeader("Access-Control-Allow-Origin", "*");
        server.send(code, type, body); return;
    }
    Serial.print("FG {\"id\":"); Serial.print(serialRequestId);
    Serial.print(",\"code\":"); Serial.print(code);
    Serial.print(",\"data\":"); Serial.print(String(type) == "application/json" ? body : jsonString(body));
    Serial.println('}');
}

// One NVS record saves credentials and addressing together; defaults remain the
// original sketch's credentials until the user explicitly saves a configuration.
struct NetworkSettings {
    uint32_t version;
    char ssid[33], password[65];
    uint8_t dhcp;
    uint8_t ip[4], gateway[4], subnet[4], dns[4];
};
NetworkSettings networkSettings = {};
bool networkReconnect = false;

void loadNetworkSettings() {
    networkSettings.version = 1;
    strlcpy(networkSettings.ssid, ssid, sizeof(networkSettings.ssid));
    strlcpy(networkSettings.password, password, sizeof(networkSettings.password));
    networkSettings.dhcp = 1;
    Preferences prefs;
    if (!prefs.begin("fg-network", true)) return;
    NetworkSettings saved = {};
    if (prefs.getBytesLength("settings") == sizeof(saved) &&
        prefs.getBytes("settings", &saved, sizeof(saved)) == sizeof(saved) && saved.version == 1 &&
        saved.ssid[32] == '\0' && saved.password[64] == '\0' && saved.dhcp <= 1)
        networkSettings = saved;
    prefs.end();
}
void connectNetwork() {
    WiFi.disconnect();
    // STA.config uses an explicit ip/gateway/subnet order, including masks below /8.
    WiFi.STA.begin();
    bool configured = networkSettings.dhcp ? WiFi.STA.config() :
        WiFi.STA.config(IPAddress(networkSettings.ip), IPAddress(networkSettings.gateway),
                     IPAddress(networkSettings.subnet), IPAddress(networkSettings.dns));
    if (!configured) { Serial.println("Wi-Fi IP configuration failed; USB remains available."); return; }
    WiFi.begin(networkSettings.ssid, networkSettings.password);
}
String networkJson() {
    return String("{\"ssid\":") + jsonString(networkSettings.ssid) +
        ",\"passwordSet\":" + (networkSettings.password[0] ? "true" : "false") +
        ",\"dhcp\":" + (networkSettings.dhcp ? "true" : "false") +
        ",\"connected\":" + (WiFi.status() == WL_CONNECTED ? "true" : "false") +
        ",\"currentIP\":" + jsonString(WiFi.localIP().toString()) +
        ",\"currentGateway\":" + jsonString(WiFi.gatewayIP().toString()) +
        ",\"currentSubnet\":" + jsonString(WiFi.subnetMask().toString()) +
        ",\"currentDns\":" + jsonString(WiFi.dnsIP().toString()) +
        ",\"ip\":" + jsonString(IPAddress(networkSettings.ip).toString()) +
        ",\"gateway\":" + jsonString(IPAddress(networkSettings.gateway).toString()) +
        ",\"subnet\":" + jsonString(IPAddress(networkSettings.subnet).toString()) +
        ",\"dns\":" + jsonString(IPAddress(networkSettings.dns).toString()) + "}";
}
bool usableAddress(const IPAddress& ip) { return ip.type() == IPv4 && ip[0] > 0 && ip[0] < 224 && ip[0] != 127; }
void handleNetworkSet() {
    NetworkSettings next = networkSettings;
    String name = requestArg("ssid");
    String dhcp = requestArg("dhcp"), replace = requestArg("replacePassword");
    if (name.length() < 1 || name.length() > 32 || (dhcp != "0" && dhcp != "1") ||
        (replace != "0" && replace != "1")) {
        respond(400, "text/plain", "Enter an SSID (1-32 UTF-8 bytes) and valid network options."); return;
    }
    strlcpy(next.ssid, name.c_str(), sizeof(next.ssid));
    next.dhcp = dhcp == "1";
    if (replace == "1") {
        String pass = requestArg("password");
        bool valid = pass.length() == 0 || (pass.length() >= 8 && pass.length() <= 63);
        if (pass.length() == 64) {
            valid = true;
            for (unsigned int i = 0; i < pass.length(); ++i) if (!isxdigit((unsigned char)pass[i])) valid = false;
        }
        if (!requestHasArg("password") || !valid) {
            respond(400, "text/plain", "Password must be empty (open network), 8-63 bytes, or 64 hexadecimal digits."); return;
        }
        strlcpy(next.password, pass.c_str(), sizeof(next.password));
    }
    if (!next.dhcp) {
        IPAddress ip, gateway, subnet, dns;
        if (!ip.fromString(requestArg("ip")) || !gateway.fromString(requestArg("gateway")) ||
            !subnet.fromString(requestArg("subnet")) || subnet.type() != IPv4 || !dns.fromString(requestArg("dns")) ||
            !usableAddress(ip) || !usableAddress(gateway) || !usableAddress(dns)) {
            respond(400, "text/plain", "Enter valid IPv4 addresses for IP, gateway, subnet and DNS."); return;
        }
        uint32_t mask = 0, host = 0, router = 0;
        for (int i = 0; i < 4; ++i) { mask = (mask << 8) | subnet[i]; host = (host << 8) | ip[i]; router = (router << 8) | gateway[i]; }
        uint32_t inverse = ~mask;
        if (mask == 0 || inverse < 3 || (inverse & (inverse + 1)) != 0 ||
            (host & mask) != (router & mask) || (host & inverse) == 0 || (host & inverse) == inverse ||
            (router & inverse) == 0 || (router & inverse) == inverse || host == router) {
            respond(400, "text/plain", "Use a contiguous subnet mask and distinct host/gateway addresses on that subnet."); return;
        }
        for (int i = 0; i < 4; ++i) { next.ip[i] = ip[i]; next.gateway[i] = gateway[i]; next.subnet[i] = subnet[i]; next.dns[i] = dns[i]; }
    }
    Preferences prefs;
    if (!prefs.begin("fg-network", false)) { respond(500, "text/plain", "Cannot open Wi-Fi settings storage."); return; }
    size_t written = prefs.putBytes("settings", &next, sizeof(next));
    prefs.end();
    if (written != sizeof(next)) { respond(500, "text/plain", "Wi-Fi settings could not be saved."); return; }
    networkSettings = next;
    // Reply over USB before reconnecting. No reboot or output-setting changes.
    respond(200, "application/json", networkJson());
    networkReconnect = true;
}

bool analogMode(const String& mode) {
    return mode == "sine" || mode == "triangle" || mode == "rectangle";
}
double actualWaveHz(const Settings& settings) {
    return lround(settings.waveHz * WAVE_SAMPLES / WAVE_SAMPLE_HZ) * double(WAVE_SAMPLE_HZ) / WAVE_SAMPLES;
}

void disconnect(Output& out) {
    for (int pin : {out.highPin, out.lowPin}) {
        if (pin < 0) continue;
        gpio_set_level((gpio_num_t)pin, 0);
        esp_rom_gpio_connect_out_signal(pin, SIG_GPIO_OUT_IDX, false, false);
        gpio_set_direction((gpio_num_t)pin, GPIO_MODE_OUTPUT);
    }
}

bool onStopped(mcpwm_timer_handle_t, const mcpwm_timer_event_data_t*, void* context) {
    auto* out = static_cast<Output*>(context);
    BaseType_t wake = pdFALSE;
    xSemaphoreGiveFromISR(out->stopped, &wake);
    return wake == pdTRUE;
}

// Select a divider of the established 10 MHz group clock so even 1 Hz
// fits the 16-bit counter. Pulse outputs retain exact 1 us resolution.
bool planTiming(int index, const Settings& s, Timing& t, String& error) {
    if (index >= 3) {
        t = {1000000, s.onUs + s.offUs, s.onUs, 0};
        return true;
    }
    const uint32_t dividers[] = {1,2,4,5,8,10,16,20,25,40,50,80,100,125,160,200,250};
    double hz = s.frequency > 0 ? s.frequency : 1;
    t.resolution = 0;
    for (uint32_t divider : dividers) {
        uint32_t resolution = BASE_CLOCK / divider;
        uint32_t period = lround(resolution / hz);
        if (period >= 2 && period <= 60000) {
            t.resolution = resolution;
            t.period = period;
            break;
        }
    }
    if (!t.resolution) { error = "Frequency cannot be represented by the hardware timer."; return false; }
    t.compare = lround(t.period * s.duty / 100.0);
    t.dead = s.deadUs > 0 ? uint32_t(ceil(s.deadUs * t.resolution / 1000000.0 - 1e-9)) : 0;
    if (s.frequency > 0 && s.duty > 0 && s.duty < 100 &&
        (t.compare <= t.dead || t.period - t.compare <= t.dead)) {
        error = "Duty and dead time leave no pulse. Reduce dead time/frequency or move duty closer to 50%.";
        return false;
    }
    // Constant 0%/100% is generated directly at the GPIO, not at compare endpoints.
    if (t.compare == 0) t.compare = 1;
    if (t.compare >= t.period) t.compare = t.period - 1;
    return true;
}

void stopTimer(Output& out) {
    if (!out.timerRunning) return;
    while (xSemaphoreTake(out.stopped, 0) == pdTRUE) {}
    ESP_ERROR_CHECK(mcpwm_timer_start_stop(out.timer, MCPWM_TIMER_STOP_EMPTY));
    uint32_t waitMs = uint32_t(ceil(1000.0 * out.timing.period / out.timing.resolution)) + 200;
    if (xSemaphoreTake(out.stopped, pdMS_TO_TICKS(waitMs)) != pdTRUE) {
        Serial.println("Timer stop timed out; outputs disconnected. Restarting.");
        ESP.restart();
    }
    out.timerRunning = false;
}

void connect(Output& out) {
    if (!out.settings.enabled || (out.lowPin >= 0 && out.settings.frequency == 0) ||
        (out.lowPin < 0 && out.settings.mode != "pulse")) return;
    if (out.lowPin >= 0 && (out.settings.duty == 0 || out.settings.duty == 100)) {
        // disconnect() has already left both GPIOs low.
        gpio_set_level((gpio_num_t)(out.settings.duty == 100 ? out.highPin : out.lowPin), 1);
        return;
    }
    esp_rom_gpio_connect_out_signal(out.highPin, out.highSignal, false, false);
    if (out.lowPin >= 0)
        esp_rom_gpio_connect_out_signal(out.lowPin, out.lowSignal, false, false);
}

void apply(int index, const Settings& settings, const Timing& timing) {
    Output& out = outputs[index];
    disconnect(out);
    stopTimer(out);
    if (out.timer) {
        ESP_ERROR_CHECK(mcpwm_timer_disable(out.timer));
        ESP_ERROR_CHECK(mcpwm_del_timer(out.timer));
        out.timer = nullptr;
    }
    mcpwm_timer_config_t tc = {};
    tc.group_id = out.group;
    tc.clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT;
    tc.resolution_hz = timing.resolution;
    tc.count_mode = MCPWM_TIMER_COUNT_MODE_UP;
    tc.period_ticks = timing.period;
    ESP_ERROR_CHECK(mcpwm_new_timer(&tc, &out.timer));
    ESP_ERROR_CHECK(mcpwm_operator_connect_timer(out.op, out.timer));
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(out.high,
        MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_HIGH)));
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(out.high,
        MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, out.comparator, MCPWM_GEN_ACTION_LOW)));
    ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(out.comparator, timing.compare));
    if (out.lowPin >= 0) {
        // When dead time is zero, bypass each path and use explicit inverse
        // actions. The driver's bypass mode does not apply invert_output.
        ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(out.low,
            MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_LOW)));
        ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(out.low,
            MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, out.comparator, MCPWM_GEN_ACTION_HIGH)));
        mcpwm_dead_time_config_t dt = {};
        dt.posedge_delay_ticks = timing.dead;
        ESP_ERROR_CHECK(mcpwm_generator_set_dead_time(out.high, out.high, &dt));
        dt = {};
        dt.negedge_delay_ticks = timing.dead;
        dt.flags.invert_output = true;
        ESP_ERROR_CHECK(mcpwm_generator_set_dead_time(timing.dead ? out.high : out.low, out.low, &dt));
    }
    mcpwm_timer_event_callbacks_t callbacks = {};
    callbacks.on_stop = onStopped;
    ESP_ERROR_CHECK(mcpwm_timer_register_event_callbacks(out.timer, &callbacks, &out));
    out.settings = settings;
    out.timing = timing;
    ESP_ERROR_CHECK(mcpwm_timer_enable(out.timer));
    ESP_ERROR_CHECK(mcpwm_timer_start_stop(out.timer, MCPWM_TIMER_START_NO_STOP));
    out.timerRunning = true;
    connect(out);
}

void setupOutputs() {
    const int highPins[] = {18,21,23,25,26};
    const int lowPins[] = {19,22,32,-1,-1};
    for (int i = 0; i < 5; ++i) {
        outputs[i].group = i < 3 ? 0 : 1;
        outputs[i].highPin = highPins[i]; outputs[i].lowPin = lowPins[i];
        outputs[i].stopped = xSemaphoreCreateBinary();
        configASSERT(outputs[i].stopped);
        disconnect(outputs[i]);
    }
    // Seed each group at 40 kHz timer resolution. On classic ESP32 this
    // establishes a 10 MHz group clock, supporting timer dividers 1..250.
    // Retain the group through its operators after deleting the seed timer.
    for (int group = 0; group < 2; ++group) {
        mcpwm_timer_handle_t seed;
        mcpwm_timer_config_t tc = {};
        tc.group_id = group;
        tc.clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT;
        tc.resolution_hz = 40000;
        tc.count_mode = MCPWM_TIMER_COUNT_MODE_UP;
        tc.period_ticks = 40000;
        ESP_ERROR_CHECK(mcpwm_new_timer(&tc, &seed));
        for (auto& out : outputs) {
            if (out.group != group) continue;
            mcpwm_operator_config_t oc = {};
            oc.group_id = group;
            ESP_ERROR_CHECK(mcpwm_new_operator(&oc, &out.op));
        }
        ESP_ERROR_CHECK(mcpwm_del_timer(seed));
    }
    for (int i = 0; i < 5; ++i) {
        auto& out = outputs[i];
        mcpwm_comparator_config_t cc = {}; // Immediate writes while output is disconnected.
        ESP_ERROR_CHECK(mcpwm_new_comparator(out.op, &cc, &out.comparator));
        mcpwm_generator_config_t gc = {};
        gc.gen_gpio_num = out.highPin;
        ESP_ERROR_CHECK(mcpwm_new_generator(out.op, &gc, &out.high));
        out.highSignal = GPIO.func_out_sel_cfg[out.highPin].func_sel;
        if (out.lowPin >= 0) {
            gc.gen_gpio_num = out.lowPin;
            ESP_ERROR_CHECK(mcpwm_new_generator(out.op, &gc, &out.low));
            out.lowSignal = GPIO.func_out_sel_cfg[out.lowPin].func_sel;
        }
        disconnect(out);
        Timing timing;
        String error;
        configASSERT(planTiming(i, out.settings, timing, error));
        apply(i, out.settings, timing);
    }
}


void stopDac() {
    if (waveDac) {
        if (dacEnabled) ESP_ERROR_CHECK(dac_continuous_disable(waveDac));
        ESP_ERROR_CHECK(dac_continuous_del_channels(waveDac));
        waveDac = nullptr;
    }
    dacEnabled = false;
    for (int i = 3; i < 5; ++i)
        if (dacMask & (1U << (i - 3))) disconnect(outputs[i]);
    dacMask = 0;
}

size_t buildWaveBuffer(uint32_t mask) {
    size_t position = 0;
    // Integer cycles make the 4096-sample circular buffer seamless. Both
    // channels may have different cycle counts and waveform shapes.
    for (uint32_t n = 0; n < WAVE_SAMPLES; ++n) {
        for (int i = 3; i < 5; ++i) {
            if (!(mask & (1U << (i - 3)))) continue;
            const auto& settings = outputs[i].settings;
            uint32_t cycles = lround(settings.waveHz * WAVE_SAMPLES / WAVE_SAMPLE_HZ);
            double phase = double((n * cycles) % WAVE_SAMPLES) / WAVE_SAMPLES;
            double value;
            if (settings.mode == "sine") value = sin(2 * PI * phase);
            else if (settings.mode == "triangle") value = 1 - 4 * fabs(phase - 0.5);
            else value = phase < 0.5 ? 1 : -1;
            waveBuffer[position++] = uint8_t(lround(127.5 + value * 127.5 * settings.amplitude / 100));
        }
    }
    return position;
}

dac_continuous_config_t makeDacConfig(uint32_t mask) {
    unsigned count = __builtin_popcount(mask);
    dac_continuous_config_t config = {};
    config.chan_mask = (dac_channel_mask_t)mask;
    config.desc_num = 10; // Room for 16-bit expansion and the final split DMA buffers.
    config.buf_size = 2048;
    config.freq_hz = WAVE_SAMPLE_HZ * count;
    config.clk_src = DAC_DIGI_CLK_SRC_DEFAULT;
    config.chan_mode = count == 2 ? DAC_CHANNEL_MODE_ALTER : DAC_CHANNEL_MODE_SIMUL;
    return config;
}

esp_err_t refreshDac() {
    stopDac();
    unsigned count = 0;
    for (int i = 3; i < 5; ++i) {
        if (outputs[i].settings.enabled && analogMode(outputs[i].settings.mode)) {
            dacMask |= 1U << (i - 3);
            ++count;
        }
    }
    if (!count) return ESP_OK;
    size_t position = buildWaveBuffer(dacMask);
    auto config = makeDacConfig(dacMask);
    esp_err_t err = dac_continuous_new_channels(&config, &waveDac);
    if (err == ESP_OK) {
        err = dac_continuous_enable(waveDac);
        dacEnabled = err == ESP_OK;
    }
    if (err == ESP_OK) {
        size_t loaded = 0;
        err = dac_continuous_write_cyclically(waveDac, waveBuffer, position, &loaded);
        if (err == ESP_OK && loaded != position) err = ESP_ERR_INVALID_SIZE;
    }
    if (err != ESP_OK) {
        stopDac();
        for (int i = 3; i < 5; ++i) {
            if (analogMode(outputs[i].settings.mode)) {
                outputs[i].settings.enabled = false;
                disconnect(outputs[i]);
            }
        }
    }
    return err;
}

void probeDacResources() {
    // Reserve and release each DAC configuration without enabling the DAC
    // or driving an analog voltage. Validate DMA/I2S allocation at boot.
    for (uint32_t mask : {1U, 2U, 3U}) {
        auto config = makeDacConfig(mask);
        dac_continuous_handle_t probe = nullptr;
        esp_err_t err = dac_continuous_new_channels(&config, &probe);
        if (err != ESP_OK) {
            Serial.printf("DAC resource check failed for mask %lu: %s\n", mask, esp_err_to_name(err));
            return;
        }
        ESP_ERROR_CHECK(dac_continuous_del_channels(probe));
    }
    Serial.println("DAC single/dual-channel resource checks passed (outputs not enabled).");
}

bool onBurstDone(rmt_channel_handle_t, const rmt_tx_done_event_data_t*, void* context) {
    static_cast<Output*>(context)->burstDone = true;
    return false;
}

void stopBurst(Output& out) {
    if (out.burstChannel) {
        ESP_ERROR_CHECK(rmt_disable(out.burstChannel));
        ESP_ERROR_CHECK(rmt_del_channel(out.burstChannel));
        out.burstChannel = nullptr;
    }
    if (out.burstEncoder) {
        ESP_ERROR_CHECK(rmt_del_encoder(out.burstEncoder));
        out.burstEncoder = nullptr;
    }
    out.burstDone = false;
    out.burstWaiting = false;
}

esp_err_t sendBurst(Output& out) {
    out.burstDone = false;
    out.burstWaiting = false;
    rmt_transmit_config_t config = {};
    config.loop_count = 0; // Classic ESP32 has no hardware finite-loop counter.
    config.flags.eot_level = 0;
    return rmt_transmit(out.burstChannel, out.burstEncoder, out.symbols,
                        out.settings.pulseCount * sizeof(rmt_symbol_word_t), &config);
}

esp_err_t startBurst(int index, bool internalTest) {
    auto& out = outputs[index];
    disconnect(out);
    stopBurst(out);
    out.completedBursts = 0;
    out.internalTest = internalTest;
    out.settings.enabled = false;
    rmt_tx_channel_config_t config = {};
    config.gpio_num = (gpio_num_t)out.highPin;
    config.clk_src = RMT_CLK_SRC_DEFAULT;
    config.resolution_hz = 1000000;
    // 255 pulse symbols plus an EOF fit in memory without an ISR refill.
    config.mem_block_symbols = 256;
    config.trans_queue_depth = 1;
    esp_err_t err = rmt_new_tx_channel(&config, &out.burstChannel);
    if (err != ESP_OK) return err;
    rmt_copy_encoder_config_t encoderConfig = {};
    err = rmt_new_copy_encoder(&encoderConfig, &out.burstEncoder);
    rmt_tx_event_callbacks_t callbacks = {};
    callbacks.on_trans_done = onBurstDone;
    if (err == ESP_OK) err = rmt_tx_register_event_callbacks(out.burstChannel, &callbacks, &out);
    if (err == ESP_OK) err = rmt_enable(out.burstChannel);
    if (err != ESP_OK) {
        // rmt_disable() requires enabled state; this channel has not enabled.
        if (out.burstEncoder) rmt_del_encoder(out.burstEncoder);
        rmt_del_channel(out.burstChannel);
        out.burstChannel = nullptr; out.burstEncoder = nullptr;
        disconnect(out);
        return err;
    }
    // Keep the external pad LOW while exercising the RMT engine internally.
    if (internalTest) disconnect(out);
    for (uint32_t n = 0; n < out.settings.pulseCount; ++n) {
        out.symbols[n] = {};
        out.symbols[n].level0 = 1; out.symbols[n].duration0 = out.settings.onUs;
        out.symbols[n].level1 = 0; out.symbols[n].duration1 = out.settings.offUs;
    }
    err = sendBurst(out);
    if (err != ESP_OK) { stopBurst(out); disconnect(out); return err; }
    out.settings.enabled = true;
    return ESP_OK;
}

void serviceBursts() {
    for (int i = 3; i < 5; ++i) {
        auto& out = outputs[i];
        if (!out.burstChannel || !out.settings.enabled) continue;
        if (out.burstDone) {
            out.burstDone = false;
            ++out.completedBursts;
            if (out.completedBursts >= out.settings.burstCount) {
                stopBurst(out);
                disconnect(out);
                out.settings.enabled = false;
                continue;
            }
            out.burstWaiting = true;
            out.nextBurstMs = millis() + out.settings.gapMs;
        }
        if (out.burstWaiting && int32_t(millis() - out.nextBurstMs) >= 0) {
            esp_err_t err = sendBurst(out);
            if (err != ESP_OK) {
                Serial.printf("Burst transmit failed: %s\n", esp_err_to_name(err));
                stopBurst(out); disconnect(out); out.settings.enabled = false;
            }
        }
    }
}

void stopOutput(int index) {
    auto& out = outputs[index];
    out.settings.enabled = false;
    if (index >= 3) stopBurst(out);
    disconnect(out);
    if (index >= 3 && analogMode(out.settings.mode)) ESP_ERROR_CHECK(refreshDac());
}

esp_err_t applyMultifunction(int index, const Settings& settings, const Timing& timing) {
    auto& out = outputs[index];
    bool rebuildAnalog = analogMode(out.settings.mode) || analogMode(settings.mode);
    stopBurst(out);
    if (rebuildAnalog) stopDac();
    Settings off = settings;
    off.enabled = false;
    apply(index, off, timing);
    out.settings = settings;
    out.completedBursts = 0;
    if (settings.mode == "pulse") connect(out);
    if (rebuildAnalog) return refreshDac();
    return ESP_OK;
}

bool number(const char* name, double minimum, double maximum, double& value) {
    if (!requestHasArg(name)) return false;
    String input = requestArg(name);
    char* end;
    errno = 0;
    value = strtod(input.c_str(), &end);
    return end != input.c_str() && *end == '\0' && errno == 0 && isfinite(value) && value >= minimum && value <= maximum;
}

String stateJson() {
    String result = "[";
    for (int i = 0; i < 5; ++i) {
        if (i) result += ',';
        auto& out = outputs[i];
        const auto& s = out.settings;
        const auto& t = out.timing;
        bool active = s.enabled && (i >= 3 || s.frequency > 0);
        result += "{\"id\":" + String(i) + ",\"highPin\":" + String(out.highPin) + ",\"lowPin\":" + String(out.lowPin);
        result += ",\"enabled\":" + String(active ? "true" : "false");
        result += ",\"mode\":\"" + s.mode + "\"";
        result += ",\"pulseCount\":" + String(s.pulseCount) + ",\"burstCount\":" + String(s.burstCount) + ",\"gapMs\":" + String(s.gapMs);
        result += ",\"completedBursts\":" + String(out.completedBursts);
        result += ",\"internalTest\":" + String(out.internalTest ? "true" : "false");
        result += ",\"waveHz\":" + String(s.waveHz, 3) + ",\"actualWaveHz\":" + String(actualWaveHz(s), 6);
        result += ",\"amplitude\":" + String(s.amplitude, 3);
        result += ",\"frequency\":" + String(s.frequency, 3) + ",\"duty\":" + String(s.duty, 3);
        result += ",\"deadUs\":" + String(s.deadUs, 3) + ",\"onUs\":" + String(s.onUs) + ",\"offUs\":" + String(s.offUs);
        result += ",\"actualHz\":" + String(double(t.resolution) / t.period, 6);
        result += ",\"tickUs\":" + String(1000000.0 / t.resolution, 3);
        result += ",\"actualDeadUs\":" + String(1000000.0 * t.dead / t.resolution, 3);
        double duty = (i < 3 && (s.duty == 0 || s.duty == 100)) ? s.duty : 100.0 * t.compare / t.period;
        double highDuty = duty, lowDuty = 0;
        if (i < 3) {
            if (s.frequency == 0) highDuty = lowDuty = 0;
            else if (s.duty == 0 || s.duty == 100) { highDuty = s.duty; lowDuty = 100 - s.duty; }
            else {
                highDuty = 100.0 * (t.compare - t.dead) / t.period;
                lowDuty = 100.0 * (t.period - t.compare - t.dead) / t.period;
            }
        }
        result += ",\"highDuty\":" + String(highDuty, 3) + ",\"lowDuty\":" + String(lowDuty, 3);
        result += ",\"actualDuty\":" + String(duty, 3) + "}";
    }
    return result + ']';
}

void handleSet() {
    double id;
    if (!number("id", 0, 4, id) || floor(id) != id || !requestHasArg("enabled") ||
        (requestArg("enabled") != "0" && requestArg("enabled") != "1")) {
        respond(400, "text/plain", "Invalid channel or enable setting."); return;
    }
    int index = int(id);
    Settings s = outputs[index].settings;
    s.enabled = requestArg("enabled") == "1";
    bool valid;
    if (index < 3) {
        valid = number("frequency", 0, 100000, s.frequency) && (s.frequency == 0 || s.frequency >= 1) &&
            number("duty", 0, 100, s.duty) && number("deadUs", 0, 1000, s.deadUs);
    } else {
        s.mode = requestHasArg("mode") ? requestArg("mode") : "pulse";
        valid = s.mode == "pulse" || s.mode == "burst" || analogMode(s.mode);
        if (valid && analogMode(s.mode)) {
            valid = number("waveHz", 10, 5000, s.waveHz) && number("amplitude", 0, 100, s.amplitude);
        } else if (valid) {
            double on, off;
            valid = number("onUs", 1, 30000, on) && number("offUs", 1, 30000, off) && floor(on) == on && floor(off) == off;
            if (valid) { s.onUs = on; s.offUs = off; }
            if (valid && s.mode == "burst") {
                double pulses, bursts, gap;
                valid = number("pulseCount", 1, 255, pulses) && floor(pulses) == pulses &&
                    number("burstCount", 1, 1000, bursts) && floor(bursts) == bursts &&
                    number("gapMs", 0, 60000, gap) && floor(gap) == gap && !s.enabled;
                if (valid) { s.pulseCount = pulses; s.burstCount = bursts; s.gapMs = gap; }
            }
        }
    }
    Timing t;
    String error;
    if (!valid || !planTiming(index, s, t, error)) {
        respond(400, "text/plain", error.length() ? error : "Invalid settings. Check the displayed ranges."); return;
    }
    esp_err_t err = ESP_OK;
    if (index < 3) apply(index, s, t);
    else err = applyMultifunction(index, s, t);
    if (err != ESP_OK) {
        respond(500, "text/plain", String("Output could not start: ") + esp_err_to_name(err)); return;
    }
    respond(200, "application/json", stateJson());
}

#include "web_page.h"

void handleBurst() {
        double id;
        if (!number("id", 3, 4, id) || floor(id) != id || outputs[int(id)].settings.mode != "burst") {
            respond(400, "text/plain", "Apply burst mode first."); return;
        }
        esp_err_t err = startBurst(int(id), requestArg("test") == "1");
        if (err != ESP_OK) {
            respond(500, "text/plain", String("Burst could not start: ") + esp_err_to_name(err)); return;
        }
        respond(200, "application/json", stateJson());
}

void handleStop() {
        if (requestArg("id") == "all") {
            for (auto& out : outputs) { disconnect(out); out.settings.enabled = false; }
            for (int i = 3; i < 5; ++i) stopBurst(outputs[i]);
            stopDac();
            for (auto& out : outputs) disconnect(out);
        } else {
            double id;
            if (!number("id", 0, 4, id) || floor(id) != id) {
                respond(400, "text/plain", "Invalid channel."); return;
            }
            stopOutput(int(id));
        }
        respond(200, "application/json", stateJson());
}

int hexDigit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
bool decodeArgument(const String& input, String& output) {
    output = "";
    for (unsigned int i = 0; i < input.length(); ++i) {
        char c = input[i];
        if (c == '%') {
            if (i + 2 >= input.length()) return false;
            int high = hexDigit(input[i + 1]), low = hexDigit(input[i + 2]);
            if (high < 0 || low < 0) return false;
            c = char(high * 16 + low); i += 2;
        } else if (c == '+') c = ' ';
        if ((uint8_t)c < 32 || c == 127) return false;
        output += c;
    }
    return true;
}
void dispatchSerial(const String& line) {
    if (!line.startsWith("FG ")) return;
    serialRequest = true; serialRequestId = 0; serialArgumentCount = 0;
    int space = line.indexOf(' ', 3);
    String id = space < 0 ? "" : line.substring(3, space);
    bool valid = id.length() > 0 && id.length() <= 9;
    for (unsigned int i = 0; i < id.length(); ++i) if (!isDigit(id[i])) valid = false;
    if (valid) serialRequestId = strtoul(id.c_str(), nullptr, 10);
    if (!valid || serialRequestId == 0) {
        respond(400, "text/plain", "Invalid request ID."); serialRequest = false; return;
    }
    String path = line.substring(space + 1);
    int query = path.indexOf('?');
    if (query >= 0) {
        String args = path.substring(query + 1); path = path.substring(0, query);
        int start = 0;
        while (start < int(args.length())) {
            int end = args.indexOf('&', start); if (end < 0) end = args.length();
            String pair = args.substring(start, end);
            int equals = pair.indexOf('=');
            if (serialArgumentCount >= 20 || equals <= 0 ||
                !decodeArgument(pair.substring(0, equals), serialKeys[serialArgumentCount]) ||
                !decodeArgument(pair.substring(equals + 1), serialValues[serialArgumentCount])) { valid = false; break; }
            for (int i = 0; i < serialArgumentCount; ++i)
                if (serialKeys[i] == serialKeys[serialArgumentCount]) valid = false;
            if (!valid) break;
            ++serialArgumentCount; start = end + 1;
        }
    }
    if (!valid) respond(400, "text/plain", "Malformed or duplicate URL-encoded arguments.");
    else if (path == "/state") respond(200, "application/json", stateJson());
    else if (path == "/set") handleSet();
    else if (path == "/stop") handleStop();
    else if (path == "/burst") handleBurst();
    else if (path == "/network") respond(200, "application/json", networkJson());
    else if (path == "/network/set") handleNetworkSet();
    else respond(404, "text/plain", "Unknown serial command.");
    // Do not retain credentials in the parser after the response.
    for (int i = 0; i < 20; ++i) { serialKeys[i] = ""; serialValues[i] = ""; }
    serialRequest = false;
}
void serviceSerial() {
    static String line;
    static bool overflow = false;
    // Bound work per loop so incoming traffic cannot starve burst servicing.
    for (int budget = 0; budget < 256 && Serial.available(); ++budget) {
        char c = Serial.read();
        if (c == '\r') continue;
        if (c == '\n') {
            if (!overflow) dispatchSerial(line);
            else Serial.println("FG {\"id\":0,\"code\":400,\"data\":\"Command exceeds 1536 bytes.\"}");
            line = ""; overflow = false;
        } else if (!overflow) {
            if (line.length() >= 1536) { line = ""; overflow = true; }
            else line += c;
        }
    }
}

void setup() {
    Serial.setRxBufferSize(2048);
    Serial.begin(115200);
    Serial.printf("Function generator boot; reset reason=%d\n", int(esp_reset_reason()));
    setupOutputs();
    probeDacResources();
    Serial.println("Five hardware channels configured; ALL outputs OFF.");
    WiFi.mode(WIFI_STA);
    loadNetworkSettings();
    connectNetwork();
    server.on("/", HTTP_GET, [] { server.sendHeader("Cache-Control", "no-store"); server.send_P(200, "text/html", PAGE); });
    server.on("/state", HTTP_GET, [] { server.sendHeader("Cache-Control", "no-store"); respond(200, "application/json", stateJson()); });
    server.on("/network", HTTP_GET, [] { respond(200, "application/json", networkJson()); });
    server.on("/network/set", HTTP_POST, handleNetworkSet);
    server.onNotFound([] {
        if (server.method() == HTTP_OPTIONS) {
            server.sendHeader("Access-Control-Allow-Origin", "*");
            server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
            server.sendHeader("Access-Control-Allow-Private-Network", "true");
            server.send(204);
        } else respond(404, "text/plain", "Unknown command.");
    });
    server.on("/set", HTTP_POST, handleSet);
    server.on("/burst", HTTP_POST, handleBurst);
    server.on("/stop", HTTP_POST, handleStop);
    server.begin();
}
void loop() {
    serviceBursts();
    server.handleClient();
    serviceSerial();
    if (networkReconnect) { networkReconnect = false; connectNetwork(); }
    static bool reported = false;
    if (!reported && WiFi.status() == WL_CONNECTED) {
        Serial.print("Function generator: http://"); Serial.println(WiFi.localIP()); reported = true;
    }
    delay(1);
}
