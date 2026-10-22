/*
 * ESP32 MQTT Robot Controller — Motor Driver Firmware
 * ===================================================
 *
 * The laptop does all image processing (webcam + InsightFace in
 * robot_following.py) and publishes a movement command over MQTT.
 * This ESP32 subscribes to those commands and drives two DC motors
 * through an L298N H-bridge.
 *
 *   Webcam -> Laptop (face recognition) -> MQTT broker -> ESP32 -> L298N -> motors
 *
 * Required Arduino libraries (Library Manager):
 *   - PubSubClient  (Nick O'Leary,     >= 2.8)
 *   - ArduinoJson   (Benoit Blanchon,  >= 7.0)
 *
 * Board:  ESP32 Dev Module   (works on ESP32 Arduino core 2.x and 3.x)
 * Baud:   115200
 *
 * Setup:  copy secrets_example.h -> secrets.h and fill in Wi-Fi + MQTT.
 *
 * ───────────────────────────────────────────────────────────
 * Safety — the motors only move when ALL of these are true
 * ───────────────────────────────────────────────────────────
 *   1. MOTOR_ENABLE is 1 in this file (compile-time lock).
 *   2. The laptop has ARMED the motors (SPACE key in
 *      robot_following.py) -> payload "motor_enable": true.
 *   3. A valid command arrived less than WATCHDOG_TIMEOUT_MS ago.
 *      The laptop sends a heartbeat every 200 ms, so if the laptop
 *      script crashes, Wi-Fi drops or the broker goes away the
 *      robot stops within 1 second.
 *   4. Wi-Fi and MQTT are connected (any disconnect -> STOP).
 *
 *   FIRST TEST WITH THE WHEELS OFF THE GROUND.
 *
 * ───────────────────────────────────────────────────────────
 * MQTT Topics
 * ───────────────────────────────────────────────────────────
 *   Subscribe: robot/face_following/command   (QoS 1)
 *   Publish:   robot/face_following/status    (retained, with LWT)
 *
 * Command JSON (incoming, from mqtt_motor_controller.py):
 *   {
 *     "command":      "FORWARD",
 *     "sequence":     42,
 *     "session":      1234567,      (optional; new value = laptop restarted)
 *     "timestamp":    1729589400.123,
 *     "source":       "laptop",
 *     "motor_enable": true          (laptop arm switch)
 *   }
 *
 * Status JSON (outgoing):
 *   {
 *     "online": true, "state": "FORWARD", "armed": true,
 *     "motor_enable": true, "last_seq": 42, "uptime_ms": 120000,
 *     "wifi_rssi": -55, "watchdog_ok": true
 *   }
 *   On an unexpected disconnect the broker publishes {"online":false}.
 *
 * ───────────────────────────────────────────────────────────
 * L298N wiring
 * ───────────────────────────────────────────────────────────
 *   Default (EN_JUMPERS_ON = 1): jumper caps stay ON ENA and ENB,
 *   nothing goes to GPIO 25/14.  Speed is PWM'd on the IN pins.
 *
 *   IN1 (Left  A)    -> GPIO 26
 *   IN2 (Left  B)    -> GPIO 27
 *   IN3 (Right A)    -> GPIO 12     (*) see note below
 *   IN4 (Right B)    -> GPIO 13
 *   L298N GND        -> ESP32 GND   (common ground is REQUIRED)
 *
 *   Alternative (EN_JUMPERS_ON = 0): remove the caps and wire
 *   ENA -> GPIO 25, ENB -> GPIO 14.  Each jumper header has an
 *   ENA/ENB pin AND a 5V pin — wiring a GPIO to the 5V pin
 *   destroys the ESP32.  Measure first: the pin you use must read
 *   0 V with the battery connected and the ESP32 unplugged.
 *
 *   Power the motors from the battery via the L298N 12V terminal.
 *   Do NOT power the motors from the ESP32 5V/3V3 pins.
 *
 *   (*) GPIO 12 is a boot strapping pin.  The L298N input does not
 *       pull it high, so it works, but if your ESP32 ever fails to
 *       boot with the driver connected, move IN3 to GPIO 33 and
 *       change PIN_IN3 below.
 *
 *   If a wheel spins the wrong way, flip LEFT_INVERT / RIGHT_INVERT
 *   below instead of re-wiring.  Use the Serial bench test: open the
 *   Serial Monitor (115200, "Newline") and type FORWARD, TURN_LEFT,
 *   STOP ... each command runs for 1 second.
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

#if __has_include(<esp_arduino_version.h>)
#include <esp_arduino_version.h>
#endif
#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 1
#endif

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "secrets.h not found: copy secrets_example.h to secrets.h and fill in your Wi-Fi/MQTT credentials."
#endif

// ============================================================
// COMPILE-TIME SAFETY LOCK
// ============================================================
// 0 = communication test only, motor pins are never touched.
// 1 = motors may run (still requires the laptop to ARM them).
#define MOTOR_ENABLE 1

// ============================================================
// MQTT Topics
// ============================================================
static const char* TOPIC_COMMAND = "robot/face_following/command";
static const char* TOPIC_STATUS  = "robot/face_following/status";
static const char* STATUS_OFFLINE = "{\"online\":false}";

// ============================================================
// TLS Root CA — ISRG Root X1 (Let's Encrypt), used by HiveMQ Cloud.
// SHA-256 fingerprint:
//   96:BC:EC:06:26:49:76:F3:74:60:77:9A:CF:28:C5:A7:
//   CF:E8:A3:C0:AA:E1:1A:8F:FC:EE:05:C0:BD:DF:08:C6
// Valid until 2035-06-04.  Replace it if your broker uses another CA.
// ============================================================
#if MQTT_USE_TLS
static const char* ROOT_CA = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
)EOF";
#endif

// ============================================================
// Timing
// ============================================================
// Laptop heartbeat is 200 ms; 5 missed heartbeats -> STOP.
static const unsigned long WATCHDOG_TIMEOUT_MS   = 1000;
static const unsigned long STATUS_INTERVAL_MS    = 2000;
static const unsigned long MQTT_RETRY_MS         = 5000;
static const unsigned long WIFI_RETRY_MS         = 10000;
static const unsigned long NTP_WAIT_MS           = 8000;
// Commands older than this (laptop clock vs NTP) are rejected.
static const double        COMMAND_MAX_AGE_S     = 5.0;

// ============================================================
// L298N GPIO Pin Assignments — verify against YOUR wiring
// ============================================================
// 1 = jumper caps ON ENA/ENB, speed PWM on IN1..IN4 (4 wires).
// 0 = caps removed, ENA/ENB wired to GPIO 25/14 (6 wires).
#define EN_JUMPERS_ON 1

static const int PIN_ENA = 25;   // unused when EN_JUMPERS_ON = 1
static const int PIN_IN1 = 26;
static const int PIN_IN2 = 27;
static const int PIN_ENB = 14;   // unused when EN_JUMPERS_ON = 1
static const int PIN_IN3 = 12;
static const int PIN_IN4 = 13;
static const int PIN_LED = 2;    // on-board LED on most DevKit boards

// Flip if a side spins backwards on FORWARD.
static const bool LEFT_INVERT  = false;
static const bool RIGHT_INVERT = false;

// Global speed cap (percent).  Start low (e.g. 60) on the first run.
static const int SPEED_SCALE_PERCENT = 100;

static const int PWM_FREQ       = 1000;
static const int PWM_RESOLUTION = 8;          // duty 0..255
static const int PWM_MAX_DUTY   = (1 << PWM_RESOLUTION) - 1;

// One H-bridge channel.  The ch* LEDC channel numbers are only
// used on core 2.x (core 3.x assigns channels per pin itself).
struct MotorSide {
    int pinA, pinB, pinEn;
    int chA, chB, chEn;
    bool invert;
};

static const MotorSide LEFT_SIDE  = {PIN_IN1, PIN_IN2, PIN_ENA, 0, 1, 4, LEFT_INVERT};
static const MotorSide RIGHT_SIDE = {PIN_IN3, PIN_IN4, PIN_ENB, 2, 3, 5, RIGHT_INVERT};

// ============================================================
// Command table — signed speed percent per side (+fwd / -rev).
// Mirrors _MOTOR_STATES in mqtt_motor_controller.py.
// ============================================================
struct MotorCommand {
    const char* name;
    int left;
    int right;
};

static const MotorCommand COMMANDS[] = {
    {"STOP",                  0,   0},
    {"FORWARD",              70,  70},
    {"BACKWARD",            -60, -60},
    {"TURN_LEFT",            30,  70},
    {"TURN_RIGHT",           70,  30},
    {"TURN_LEFT_FORWARD",    40,  80},
    {"TURN_RIGHT_FORWARD",   80,  40},
    {"TURN_LEFT_BACKWARD",  -40, -70},
    {"TURN_RIGHT_BACKWARD", -70, -40},
};
static const int NUM_COMMANDS = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

// ============================================================
// Global State
// ============================================================
#if MQTT_USE_TLS
WiFiClientSecure netClient;
#else
WiFiClient netClient;
#endif
PubSubClient mqttClient(netClient);

char mqttClientId[32];

String currentState        = "STOP";
bool laptopArmed           = false;
unsigned long lastCmdTime  = 0;
long lastSequence          = -1;
uint32_t lastSession       = 0;
bool watchdogTriggered     = false;
unsigned long lastStatusMs = 0;
unsigned long lastMqttTry  = 0;
unsigned long lastWifiTry  = 0;
unsigned long wifiUpSince  = 0;
bool mqttWasUp             = false;
bool timeSynced            = false;

// ============================================================
// Motor Control
// ============================================================
const MotorCommand* findCommand(const char* name) {
    for (int i = 0; i < NUM_COMMANDS; i++) {
        if (strcmp(name, COMMANDS[i].name) == 0) return &COMMANDS[i];
    }
    return nullptr;
}

void pwmSetup(int pin, int channel) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    (void)channel;
    ledcAttach(pin, PWM_FREQ, PWM_RESOLUTION);
#else
    ledcSetup(channel, PWM_FREQ, PWM_RESOLUTION);
    ledcAttachPin(pin, channel);
#endif
}

void pwmWrite(int pin, int channel, int duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    (void)channel;
    ledcWrite(pin, duty);
#else
    (void)pin;
    ledcWrite(channel, duty);
#endif
}

// percent: -100..100, positive = forward
void driveSide(const MotorSide& side, int percent) {
#if MOTOR_ENABLE
    if (side.invert) percent = -percent;
    percent = constrain(percent, -100, 100);

    int duty = abs(percent) * SPEED_SCALE_PERCENT / 100;
    duty = duty * PWM_MAX_DUTY / 100;

#if EN_JUMPERS_ON
    // EN is held high by the jumper: PWM the IN pin for the wanted
    // direction and hold the other one LOW.  Both LOW = stop.
    pwmWrite(side.pinA, side.chA, percent > 0 ? duty : 0);
    pwmWrite(side.pinB, side.chB, percent < 0 ? duty : 0);
#else
    if (percent > 0) {
        digitalWrite(side.pinA, HIGH); digitalWrite(side.pinB, LOW);
    } else if (percent < 0) {
        digitalWrite(side.pinA, LOW);  digitalWrite(side.pinB, HIGH);
    } else {
        digitalWrite(side.pinA, LOW);  digitalWrite(side.pinB, LOW);
        duty = 0;
    }
    pwmWrite(side.pinEn, side.chEn, duty);
#endif
#else
    (void)side; (void)percent;
#endif
}

void setupMotorPins() {
#if MOTOR_ENABLE
#if EN_JUMPERS_ON
    pwmSetup(PIN_IN1, LEFT_SIDE.chA);
    pwmSetup(PIN_IN2, LEFT_SIDE.chB);
    pwmSetup(PIN_IN3, RIGHT_SIDE.chA);
    pwmSetup(PIN_IN4, RIGHT_SIDE.chB);
    Serial.println("[MOTOR] Mode: EN jumpers ON, PWM on IN1..IN4.");
#else
    pinMode(PIN_IN1, OUTPUT);
    pinMode(PIN_IN2, OUTPUT);
    pinMode(PIN_IN3, OUTPUT);
    pinMode(PIN_IN4, OUTPUT);
    pwmSetup(PIN_ENA, LEFT_SIDE.chEn);
    pwmSetup(PIN_ENB, RIGHT_SIDE.chEn);
    Serial.println("[MOTOR] Mode: PWM on ENA/ENB (GPIO 25/14).");
#endif
    stopMotors();
    Serial.println("[MOTOR] Pins configured (MOTOR_ENABLE=1).");
#else
    Serial.println("[MOTOR] Outputs DISABLED (MOTOR_ENABLE=0).");
#endif
}

void stopMotors() {
    driveSide(LEFT_SIDE, 0);
    driveSide(RIGHT_SIDE, 0);
}

// Unknown names fall back to STOP.
void applyCommand(const char* name) {
    const MotorCommand* cmd = findCommand(name);
    if (cmd == nullptr) cmd = &COMMANDS[0];

    driveSide(LEFT_SIDE,  cmd->left);
    driveSide(RIGHT_SIDE, cmd->right);

    if (currentState != cmd->name) {
        Serial.print("[MOTOR] ");
        Serial.print(currentState);
        Serial.print(" -> ");
        Serial.print(cmd->name);
        Serial.print("  (L=");
        Serial.print(cmd->left);
        Serial.print("% R=");
        Serial.print(cmd->right);
        Serial.println("%)");
    }
    currentState = cmd->name;
}

// ============================================================
// Publish Status
// ============================================================
void publishStatus() {
    if (!mqttClient.connected()) return;

    JsonDocument doc;
    doc["online"]       = true;
    doc["state"]        = currentState;
    doc["armed"]        = laptopArmed && MOTOR_ENABLE;
    doc["motor_enable"] = (bool)MOTOR_ENABLE;
    doc["last_seq"]     = lastSequence;
    doc["uptime_ms"]    = millis();
    doc["wifi_rssi"]    = WiFi.RSSI();
    doc["watchdog_ok"]  = !watchdogTriggered;

    char buf[256];
    serializeJson(doc, buf, sizeof(buf));
    mqttClient.publish(TOPIC_STATUS, buf, true);  // retained
    lastStatusMs = millis();
}

// ============================================================
// MQTT Callback
// ============================================================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    (void)topic;

    if (length > 512) {
        Serial.println("[MQTT] Payload too large, rejected.");
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.print("[MQTT] JSON parse error: ");
        Serial.println(err.c_str());
        return;
    }

    // ── Validate fields and types ────────────────────────
    if (!doc["command"].is<const char*>() ||
        !doc["sequence"].is<long>() ||
        !doc["timestamp"].is<double>() ||
        !doc["source"].is<const char*>() ||
        !doc["motor_enable"].is<bool>()) {
        Serial.println("[MQTT] REJECTED: missing or mistyped fields.");
        return;
    }

    const char* command = doc["command"];
    long sequence       = doc["sequence"];
    double timestamp    = doc["timestamp"];
    bool motorEnable    = doc["motor_enable"];
    uint32_t session    = doc["session"] | (uint32_t)0;

    if (findCommand(command) == nullptr) {
        Serial.print("[MQTT] REJECTED unknown command: ");
        Serial.println(command);
        return;
    }

    // ── New laptop session -> restart sequence numbering ─
    if (session != lastSession) {
        Serial.print("[MQTT] New laptop session ");
        Serial.println(session);
        lastSession  = session;
        lastSequence = -1;
    }

    // ── Reject old / duplicate sequence ──────────────────
    if (sequence <= lastSequence) {
        Serial.print("[MQTT] REJECTED old/dup seq=");
        Serial.print(sequence);
        Serial.print(" (last=");
        Serial.print(lastSequence);
        Serial.println(")");
        return;
    }

    // ── Reject stale timestamp (only once NTP is synced) ─
    if (timeSynced) {
        time_t now;
        time(&now);
        double age = (double)now - timestamp;
        if (age > COMMAND_MAX_AGE_S || age < -COMMAND_MAX_AGE_S) {
            Serial.print("[MQTT] REJECTED stale command, age=");
            Serial.print(age, 1);
            Serial.println("s (check the laptop clock)");
            return;
        }
    }

    // ── Accept ───────────────────────────────────────────
    lastSequence = sequence;
    lastCmdTime  = millis();

    bool wasArmed = laptopArmed;
    bool hadWatchdog = watchdogTriggered;
    String before = currentState;

    laptopArmed       = motorEnable;
    watchdogTriggered = false;

    if (laptopArmed != wasArmed) {
        Serial.println(laptopArmed ? "[ARM] Laptop ARMED motors."
                                   : "[ARM] Laptop DISARMED motors.");
    }

    // Disarmed commands still count as heartbeats but never move.
    applyCommand((laptopArmed && MOTOR_ENABLE) ? command : "STOP");

    if (currentState != before || laptopArmed != wasArmed || hadWatchdog) {
        publishStatus();
    }
}

// ============================================================
// Serial bench test — type a command name, it runs for
// WATCHDOG_TIMEOUT_MS.  For checking motor wiring/direction.
// ============================================================
void handleSerial() {
    static char line[32];
    static int len = 0;

    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\r') continue;

        if (c != '\n') {
            if (len < (int)sizeof(line) - 1) line[len++] = toupper(c);
            continue;
        }

        line[len] = '\0';
        len = 0;
        if (line[0] == '\0') continue;

        if (findCommand(line) == nullptr) {
            Serial.print("[SERIAL] Unknown command: ");
            Serial.println(line);
            continue;
        }

#if MOTOR_ENABLE
        Serial.print("[SERIAL] Bench test: ");
        Serial.println(line);
        applyCommand(line);
        lastCmdTime = millis();
        watchdogTriggered = false;
#else
        Serial.println("[SERIAL] MOTOR_ENABLE=0, bench test ignored.");
#endif
    }
}

// ============================================================
// Wi-Fi / NTP / MQTT
// ============================================================
void startWiFi() {
    Serial.println("[WiFi] Connecting...");   // SSID/password not printed
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastWifiTry = millis();
}

void checkTimeSync() {
    if (timeSynced) return;
    time_t now;
    time(&now);
    if (now > 1700000000) {   // after Nov 2023 -> NTP has answered
        timeSynced = true;
        Serial.println("[NTP] Time synced; stale-command check active.");
    }
}

void connectMQTT() {
#if MQTT_USE_TLS
    // TLS certificate checks need the real time.  Give NTP a few
    // seconds after Wi-Fi comes up before the first attempt.
    if (!timeSynced && millis() - wifiUpSince < NTP_WAIT_MS) return;
#endif

    // connect() can block for a few seconds (TLS handshake);
    // never let a bench-test command keep running through it.
    applyCommand("STOP");

    lastMqttTry = millis();
    Serial.print("[MQTT] Connecting to broker...");

    bool ok = mqttClient.connect(
        mqttClientId, MQTT_USER, MQTT_PASS,
        TOPIC_STATUS, 1, true, STATUS_OFFLINE);   // LWT

    if (!ok) {
        Serial.print(" failed, rc=");
        Serial.print(mqttClient.state());
        Serial.println(".  Retry in 5s.");
        return;
    }

    Serial.println(" connected.");
    mqttWasUp = true;

    // Always start from a known-safe state after (re)connecting.
    applyCommand("STOP");
    laptopArmed       = false;
    lastSequence      = -1;
    lastCmdTime       = 0;
    watchdogTriggered = false;

    mqttClient.subscribe(TOPIC_COMMAND, 1);
    Serial.print("[MQTT] Subscribed: ");
    Serial.println(TOPIC_COMMAND);

    publishStatus();
}

void updateLed(bool connected) {
    // Solid = connected and ready; blinking = waiting for network.
    bool on = connected || ((millis() / 250) % 2 == 0);
    digitalWrite(PIN_LED, on ? HIGH : LOW);
}

// ============================================================
// Setup
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println();
    Serial.println("========================================");
    Serial.println("  ESP32 MQTT Robot Controller");
    Serial.println("========================================");

    pinMode(PIN_LED, OUTPUT);
    setupMotorPins();

    snprintf(mqttClientId, sizeof(mqttClientId), "esp32_robot_%06lX",
             (unsigned long)(ESP.getEfuseMac() & 0xFFFFFF));

    startWiFi();
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");

#if MQTT_USE_TLS
    netClient.setCACert(ROOT_CA);
#endif

    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
    mqttClient.setBufferSize(1024);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setKeepAlive(15);
    mqttClient.setSocketTimeout(5);

    Serial.print("[Watchdog] Timeout: ");
    Serial.print(WATCHDOG_TIMEOUT_MS);
    Serial.println(" ms");
#if MOTOR_ENABLE
    Serial.println("Motor outputs ENABLED (laptop must ARM them).");
#else
    Serial.println("Motor outputs DISABLED.");
#endif
    Serial.println("Bench test: type FORWARD / TURN_LEFT / STOP ...");
    Serial.println("========================================");
}

// ============================================================
// Main Loop
// ============================================================
void checkWatchdog() {
    if (lastCmdTime > 0 && !watchdogTriggered &&
        millis() - lastCmdTime > WATCHDOG_TIMEOUT_MS) {
        watchdogTriggered = true;
        applyCommand("STOP");
        Serial.print("[Watchdog] No command for ");
        Serial.print(millis() - lastCmdTime);
        Serial.println(" ms -> STOP.");
        publishStatus();
    }
}

// Called once on each Wi-Fi / MQTT drop (not every loop, so the
// Serial bench test still works while offline).
void enterSafeState(const char* reason) {
    Serial.print("[SAFE] ");
    Serial.print(reason);
    Serial.println(" -> STOP, disarmed.");
    laptopArmed = false;
    lastCmdTime = 0;
    applyCommand("STOP");
}

void loop() {
    unsigned long now = millis();

    handleSerial();
    checkWatchdog();

    // ── Wi-Fi ────────────────────────────────────────────
    if (WiFi.status() != WL_CONNECTED) {
        if (wifiUpSince != 0) {
            wifiUpSince = 0;
            mqttWasUp = false;
            enterSafeState("Wi-Fi lost");
        }

        if (now - lastWifiTry >= WIFI_RETRY_MS) {
            Serial.println("[WiFi] Retrying...");
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            lastWifiTry = now;
        }
        updateLed(false);
        delay(10);
        return;
    }

    if (wifiUpSince == 0) {
        wifiUpSince = now == 0 ? 1 : now;
        Serial.print("[WiFi] Connected, IP: ");
        Serial.print(WiFi.localIP());
        Serial.print("  RSSI: ");
        Serial.print(WiFi.RSSI());
        Serial.println(" dBm");
    }
    checkTimeSync();

    // ── MQTT ─────────────────────────────────────────────
    if (!mqttClient.connected()) {
        if (mqttWasUp) {
            mqttWasUp = false;
            enterSafeState("MQTT disconnected");
        }

        if (lastMqttTry == 0 || now - lastMqttTry >= MQTT_RETRY_MS) {
            connectMQTT();
        }
        updateLed(false);
        delay(10);
        return;
    }

    mqttClient.loop();
    updateLed(true);

    // ── Periodic status ──────────────────────────────────
    if (millis() - lastStatusMs >= STATUS_INTERVAL_MS) {
        publishStatus();
    }
}
