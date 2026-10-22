// ============================================================
// secrets_example.h — TEMPLATE, safe to commit
// ============================================================
// Copy this file to "secrets.h" in the same folder and fill in
// your values.  secrets.h is gitignored and is NEVER printed to
// Serial or published over MQTT.
//
// The values must match your laptop's .env.mqtt file.
// ============================================================
#pragma once

// ── Wi-Fi (2.4 GHz only — the ESP32 cannot join 5 GHz) ─────
static const char* WIFI_SSID     = "YOUR_WIFI_SSID";
static const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// ── MQTT broker ─────────────────────────────────────────────
// HiveMQ Cloud example host: abc123.s1.eu.hivemq.cloud
static const char*    MQTT_HOST = "YOUR_BROKER_HOST";
static const uint16_t MQTT_PORT = 8883;
static const char*    MQTT_USER = "YOUR_MQTT_USERNAME";
static const char*    MQTT_PASS = "YOUR_MQTT_PASSWORD";

// 1 = TLS (cloud brokers, port 8883)
// 0 = plain TCP (local Mosquitto on your LAN, port 1883)
#define MQTT_USE_TLS 1
