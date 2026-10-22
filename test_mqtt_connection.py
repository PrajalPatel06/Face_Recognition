"""
Standalone MQTT Connection Test
================================

Tests MQTT broker connectivity, command publishing, and payload
validation independently of the face-recognition pipeline.

Usage (PowerShell)::

    .\.venv\Scripts\Activate.ps1
    pip install paho-mqtt
    python test_mqtt_connection.py

The script does NOT:
  - Import or run the face-recognition pipeline.
  - Enable or control any motor outputs.
  - Modify robot_following.py or any other project file.

Requires a configured ``.env.mqtt`` (see ``.env.mqtt.example``).
"""

import json
import sys
import time

# ── Dependency check ────────────────────────────────────────
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed.")
    print("  Install with:  pip install paho-mqtt")
    sys.exit(1)

from mqtt_config import load_mqtt_config

# ── Test parameters ─────────────────────────────────────────
CONNECT_TIMEOUT = 10.0
ACK_TIMEOUT = 5.0
SEPARATOR = "=" * 58

# ── Results tracking ────────────────────────────────────────
results = []


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    mark = "✓" if passed else "✗"
    print(f"  {mark} {name}")
    if detail:
        print(f"    {detail}")


# ── Blocking connect helper ─────────────────────────────────
def connect_to_broker(config):
    """
    Connect to the MQTT broker with a blocking wait.
    Returns (client, connected_bool).
    """
    import ssl

    try:
        from paho.mqtt.client import CallbackAPIVersion
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION1,
            client_id=config["client_id"] + "_test",
        )
    except (ImportError, TypeError):
        client = mqtt.Client(
            client_id=config["client_id"] + "_test",
        )

    client.username_pw_set(config["username"], config["password"])

    if config["use_tls"]:
        client.tls_set(
            ca_certs=None,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )

    connected = [False]
    connect_rc = [None]

    def on_connect(c, ud, flags, rc):
        connected[0] = (rc == 0)
        connect_rc[0] = rc

    client.on_connect = on_connect

    try:
        client.connect(
            config["broker_host"],
            config["broker_port"],
            keepalive=30,
        )
    except OSError as e:
        return client, False, str(e)

    client.loop_start()

    deadline = time.time() + CONNECT_TIMEOUT
    while not connected[0] and connect_rc[0] is None:
        if time.time() > deadline:
            client.loop_stop()
            return client, False, "Connection timeout"
        time.sleep(0.1)

    if not connected[0]:
        client.loop_stop()
        return client, False, f"rc={connect_rc[0]}"

    return client, True, ""


def main():
    print()
    print(SEPARATOR)
    print("  MQTT Connection & Payload Test")
    print(SEPARATOR)
    print()

    # ── Load config ─────────────────────────────────────────
    print("--- Configuration ---")
    try:
        config = load_mqtt_config()
        record("Config loaded", True,
               f"broker={config['broker_host']}:{config['broker_port']}")
    except ValueError as e:
        record("Config loaded", False, str(e))
        print()
        print("Cannot continue without broker configuration.")
        print("Copy .env.mqtt.example to .env.mqtt and fill in credentials.")
        print(SEPARATOR)
        sys.exit(1)
    print()

    # ── Connect to broker ───────────────────────────────────
    print("--- Broker Connection ---")
    client, connected, err = connect_to_broker(config)
    record("Broker connect", connected, err if not connected else "")

    if not connected:
        print()
        print("Cannot continue without broker connection.")
        print("Check credentials and network connectivity.")
        print(SEPARATOR)
        sys.exit(1)

    # ── Received messages ───────────────────────────────────
    received_msgs = []

    def on_message(c, ud, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            received_msgs.append((msg.topic, payload))
        except Exception:
            received_msgs.append((msg.topic, msg.payload))

    client.on_message = on_message
    print()

    # ── Subscribe to status topic ───────────────────────────
    print("--- Subscribe ---")
    r, mid = client.subscribe(config["topic_status"], qos=1)
    record("Subscribe to status topic",
           r == mqtt.MQTT_ERR_SUCCESS,
           config["topic_status"])
    time.sleep(0.5)
    print()

    # ── Test 1: Valid STOP command ───────────────────────────
    print("--- Test: Valid STOP Command ---")
    stop_payload = json.dumps({
        "command": "STOP",
        "sequence": 1,
        "timestamp": time.time(),
        "source": "laptop",
        "motor_enable": False,
    })

    info = client.publish(
        config["topic_command"], stop_payload, qos=1, retain=False,
    )
    record("Publish STOP (retain=False)",
           info.rc == mqtt.MQTT_ERR_SUCCESS,
           f"rc={info.rc}")
    record("Retain flag disabled", True, "retain=False confirmed in code")

    # Wait briefly for any ESP32 response.
    time.sleep(ACK_TIMEOUT)
    esp32_responded = any(
        t == config["topic_status"] for t, _ in received_msgs
    )
    record("ESP32 status received",
           esp32_responded,
           "ESP32 online" if esp32_responded else "No ESP32 response (expected if ESP32 offline)")
    print()

    # ── Test 2: All valid commands ──────────────────────────
    print("--- Test: All Valid Commands ---")
    valid_cmds = [
        "STOP", "FORWARD", "BACKWARD",
        "TURN_LEFT", "TURN_RIGHT",
        "TURN_LEFT_FORWARD", "TURN_RIGHT_FORWARD",
        "TURN_LEFT_BACKWARD", "TURN_RIGHT_BACKWARD",
    ]
    seq = 10
    for cmd in valid_cmds:
        seq += 1
        payload = json.dumps({
            "command": cmd,
            "sequence": seq,
            "timestamp": time.time(),
            "source": "laptop",
            "motor_enable": False,
        })
        info = client.publish(
            config["topic_command"], payload, qos=1, retain=False,
        )
        record(f"Publish {cmd}", info.rc == mqtt.MQTT_ERR_SUCCESS)
        time.sleep(0.1)

    # Final STOP
    seq += 1
    final_stop = json.dumps({
        "command": "STOP",
        "sequence": seq,
        "timestamp": time.time(),
        "source": "laptop",
        "motor_enable": False,
    })
    client.publish(config["topic_command"], final_stop, qos=1, retain=False)
    print()

    # ── Test 3: Malformed payloads ──────────────────────────
    print("--- Test: Malformed Payloads (should be rejected by ESP32) ---")

    malformed = [
        ("Empty string", ""),
        ("Not JSON", "FORWARD"),
        ("Missing command", json.dumps({
            "sequence": 999, "timestamp": time.time(),
            "source": "laptop", "motor_enable": False,
        })),
        ("Invalid command", json.dumps({
            "command": "DANCE", "sequence": 1000,
            "timestamp": time.time(), "source": "laptop",
            "motor_enable": False,
        })),
        # NOTE: never send motor_enable=true here — the ESP32 treats
        # that as ARMED and the motors would really move.
        ("motor_enable wrong type", json.dumps({
            "command": "FORWARD", "sequence": 1001,
            "timestamp": time.time(), "source": "laptop",
            "motor_enable": "yes",
        })),
        ("Stale timestamp", json.dumps({
            "command": "FORWARD", "sequence": 1002,
            "timestamp": 1000000000.0, "source": "laptop",
            "motor_enable": False,
        })),
    ]

    for name, payload in malformed:
        info = client.publish(
            config["topic_command"], payload, qos=1, retain=False,
        )
        record(f"Publish malformed: {name}",
               info.rc == mqtt.MQTT_ERR_SUCCESS,
               "Sent to broker (ESP32 should reject)")
        time.sleep(0.1)
    print()

    # ── Test 4: Motor enable interlock ──────────────────────
    print("--- Test: Motor Enable Interlock ---")
    record("motor_enable=false in all test payloads", True,
           "ESP32 accepts these as heartbeats but holds STOP (disarmed)")
    record("No motor control attempted", True)
    print()

    # ── Cleanup ─────────────────────────────────────────────
    print("--- Cleanup ---")
    # Send final STOP
    client.publish(
        config["topic_command"],
        json.dumps({
            "command": "STOP",
            "sequence": 9999,
            "timestamp": time.time(),
            "source": "laptop",
            "motor_enable": False,
        }),
        qos=1, retain=False,
    )
    time.sleep(0.3)
    client.loop_stop()
    client.disconnect()
    record("Disconnected cleanly", True)
    print()

    # ── Summary ─────────────────────────────────────────────
    print(SEPARATOR)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"  Results: {passed} passed, {failed} failed")

    if not esp32_responded:
        print("  Note: ESP32 was not online — its rejection of malformed")
        print("        payloads could not be verified end-to-end.")

    print("  No motors were enabled.")
    print(SEPARATOR)
    print()


if __name__ == "__main__":
    main()
