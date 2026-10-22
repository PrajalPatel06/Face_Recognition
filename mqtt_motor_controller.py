"""
MQTT Motor Controller
=====================

Publishes movement commands to an MQTT broker for the ESP32
robot controller (``esp32_mqtt_robot_controller.ino``).  Implements
the same ``execute()`` / ``get_state()`` interface as
``MotorController`` for drop-in integration in ``robot_following.py``.

Command JSON payload (published to the command topic)::

    {
        "command":      "FORWARD",
        "sequence":     42,
        "session":      1234567,
        "timestamp":    1729589400.123,
        "source":       "laptop",
        "motor_enable": false
    }

- ``motor_enable`` is the laptop-side **arm switch**.  It is ``False``
  until ``set_armed(True)`` is called; the ESP32 never drives the
  motors while it is ``False``.
- ``session`` is random per controller instance, so the ESP32 resets
  its sequence check when the laptop script restarts.
- A message is published when the command (or arm state) changes,
  and otherwise as a heartbeat every ``heartbeat_interval`` seconds.
  The ESP32 stops the motors if heartbeats stop arriving.

All commands are published with **QoS 1** and **retain=False**.
An old ``FORWARD`` will never replay on reconnect.

``SEARCH`` and unknown commands are mapped to ``STOP`` (fail-safe).
"""

import json
import logging
import random
import ssl
import threading
import time

logger = logging.getLogger(__name__)

# ── paho-mqtt import (v1 and v2 compatible) ─────────────────
try:
    import paho.mqtt.client as mqtt

    try:
        from paho.mqtt.client import CallbackAPIVersion

        _HAS_CALLBACK_API = True
    except ImportError:
        _HAS_CALLBACK_API = False

    PAHO_AVAILABLE = True

except ImportError:
    PAHO_AVAILABLE = False

# ── Constants ───────────────────────────────────────────────

VALID_COMMANDS = frozenset({
    "STOP",
    "FORWARD",
    "BACKWARD",
    "TURN_LEFT",
    "TURN_RIGHT",
    "TURN_LEFT_FORWARD",
    "TURN_RIGHT_FORWARD",
    "TURN_LEFT_BACKWARD",
    "TURN_RIGHT_BACKWARD",
})

# Motor states (mirrors MotorController and the ESP32 COMMANDS table).
_MOTOR_STATES = {
    "STOP":                 ("STOP",      0, "STOP",      0),
    "FORWARD":              ("FORWARD",  70, "FORWARD",  70),
    "BACKWARD":             ("BACKWARD", 60, "BACKWARD", 60),
    "TURN_LEFT":            ("FORWARD",  30, "FORWARD",  70),
    "TURN_RIGHT":           ("FORWARD",  70, "FORWARD",  30),
    "TURN_LEFT_FORWARD":    ("FORWARD",  40, "FORWARD",  80),
    "TURN_RIGHT_FORWARD":   ("FORWARD",  80, "FORWARD",  40),
    "TURN_LEFT_BACKWARD":   ("BACKWARD", 40, "BACKWARD", 70),
    "TURN_RIGHT_BACKWARD":  ("BACKWARD", 70, "BACKWARD", 40),
}

# Must be well below the ESP32 WATCHDOG_TIMEOUT_MS (1000 ms).
DEFAULT_HEARTBEAT_INTERVAL = 0.2

# The ESP32 publishes status every 2 s; older than this = offline.
ESP32_STATUS_TIMEOUT = 5.0


# ── Controller ──────────────────────────────────────────────

class MqttMotorController:
    """
    Publish movement commands via MQTT.

    Drop-in replacement for ``MotorController``.  Uses ``paho-mqtt``
    with a background network loop so ``execute()`` never blocks the
    camera pipeline for more than a few milliseconds.

    Parameters
    ----------
    config : dict
        Output of ``mqtt_config.load_mqtt_config()``.
    heartbeat_interval : float
        Seconds between repeated publishes of an unchanged command.
    armed : bool
        Initial arm state.  Defaults to ``False`` (motors locked).
    """

    def __init__(
        self,
        config,
        heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL,
        armed=False,
    ):
        if not PAHO_AVAILABLE:
            raise ImportError(
                "paho-mqtt is required.  Install with:  pip install paho-mqtt"
            )

        self.config = config
        self.heartbeat_interval = heartbeat_interval
        self._session = random.randint(1, 2**31 - 1)
        self._sequence = 0
        self._lock = threading.Lock()
        self._connected = False
        self._connected_event = threading.Event()
        self._armed = bool(armed)
        self._last_logged_cmd = None
        self._consecutive_errors = 0
        self._last_published = None
        self._last_publish_time = 0.0
        self._esp32_status = {}
        self._esp32_status_time = 0.0

        # Motor-state tracking (same keys as MotorController).
        self.left_direction = "STOP"
        self.right_direction = "STOP"
        self.left_speed = 0
        self.right_speed = 0

        # ── Create MQTT client ──────────────────────────────
        cid = config["client_id"]

        if _HAS_CALLBACK_API:
            self._client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION1,
                client_id=cid,
            )
        else:
            self._client = mqtt.Client(client_id=cid)

        self._client.username_pw_set(config["username"], config["password"])

        # TLS — use the system CA bundle; never disable verification.
        if config["use_tls"]:
            self._client.tls_set(
                ca_certs=None,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)

        # ── Connect (non-blocking; paho keeps retrying) ─────
        try:
            self._client.connect_async(
                config["broker_host"],
                config["broker_port"],
                keepalive=30,
            )
            self._client.loop_start()
            logger.info(
                "MQTT connecting to %s:%d …",
                config["broker_host"], config["broker_port"],
            )
        except (OSError, ValueError) as exc:
            logger.error("MQTT initial connection failed: %s", exc)

    # ── Callbacks ───────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            self._consecutive_errors = 0
            self._last_published = None   # resend current command now
            self._connected_event.set()
            logger.info("MQTT connected to broker.")
            client.subscribe(self.config["topic_status"], qos=1)
        else:
            self._connected = False
            logger.error("MQTT connection refused (rc=%d).", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        self._connected_event.clear()
        if rc == 0:
            logger.info("MQTT disconnected cleanly.")
        else:
            logger.warning(
                "MQTT unexpected disconnect (rc=%d).  Auto-reconnecting.", rc,
            )

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Bad status message: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        self._esp32_status = payload

        # A retained message may be hours old, so it proves nothing
        # about liveness; only live messages refresh the timestamp.
        if not getattr(message, "retain", False):
            self._esp32_status_time = time.time()

        logger.debug("ESP32 status: %s", payload.get("state", "?"))

    # ── Public interface ────────────────────────────────────

    @property
    def armed(self):
        return self._armed

    def set_armed(self, armed):
        """Arm or disarm the motors.  Takes effect on the next publish."""
        armed = bool(armed)
        if armed != self._armed:
            self._armed = armed
            logger.warning("Motors %s.", "ARMED" if armed else "DISARMED")
        return self._armed

    def wait_until_connected(self, timeout=5.0):
        """Block up to *timeout* seconds for the broker connection."""
        return self._connected_event.wait(timeout)

    @property
    def connected(self):
        return self._connected

    def esp32_status(self):
        """
        Return the latest ESP32 status plus an ``online`` flag.

        ``online`` is True only if a live (non-retained) status
        arrived within ``ESP32_STATUS_TIMEOUT`` seconds and the ESP32
        did not report ``"online": false`` (its MQTT last will).
        """
        status = dict(self._esp32_status)
        fresh = (time.time() - self._esp32_status_time) <= ESP32_STATUS_TIMEOUT
        status["online"] = (
            self._connected and fresh and status.get("online", True) is not False
        )
        return status

    def execute(self, command):
        """
        Validate *command*, publish it via MQTT, return motor-state dict.

        Unknown commands and ``SEARCH`` are mapped to ``STOP``.
        Network errors are logged but do **not** raise — the camera
        loop continues uninterrupted.
        """
        # ── Validate ────────────────────────────────────────
        if command not in VALID_COMMANDS:
            if command == "SEARCH":
                logger.debug("SEARCH mapped to STOP (safety policy).")
            else:
                logger.warning("Unknown command '%s' → STOP.", command)
            command = "STOP"

        armed = self._armed

        # ── Update local motor state ────────────────────────
        # While disarmed the ESP32 holds the motors stopped, so
        # report that rather than the requested command.
        ld, ls, rd, rs = _MOTOR_STATES[command if armed else "STOP"]
        self.left_direction = ld
        self.left_speed = ls
        self.right_direction = rd
        self.right_speed = rs

        if not self._connected:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                logger.warning(
                    "MQTT not connected; '%s' not sent.", command,
                )
            # Can't confirm delivery → report STOP locally.
            self._set_stopped()
            return self.get_state()

        # ── Rate limit: publish on change or heartbeat ──────
        now = time.time()
        key = (command, armed)
        if (
            key == self._last_published
            and now - self._last_publish_time < self.heartbeat_interval
        ):
            return self.get_state()

        self._publish(command, armed, now)
        return self.get_state()

    def stop(self):
        """Convenience: send STOP."""
        return self.execute("STOP")

    def close(self):
        """Publish final STOP and disconnect cleanly."""
        try:
            if self._connected:
                self._armed = False
                self._publish("STOP", False, time.time())
                time.sleep(0.15)  # allow message to drain
        except Exception:
            pass

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

        self._set_stopped()
        logger.info("MqttMotorController closed.")

    def get_state(self):
        """Return motor-state dict (same shape as MotorController)."""
        return {
            "left_direction": self.left_direction,
            "right_direction": self.right_direction,
            "left_speed": self.left_speed,
            "right_speed": self.right_speed,
        }

    # ── Internals ───────────────────────────────────────────

    def _set_stopped(self):
        self.left_direction = "STOP"
        self.right_direction = "STOP"
        self.left_speed = 0
        self.right_speed = 0

    def _publish(self, command, armed, now):
        with self._lock:
            self._sequence += 1
            seq = self._sequence

        payload = json.dumps({
            "command": command,
            "sequence": seq,
            "session": self._session,
            "timestamp": now,
            "source": "laptop",
            "motor_enable": armed,
        })

        try:
            info = self._client.publish(
                self.config["topic_command"],
                payload,
                qos=1,
                retain=False,
            )
        except Exception as exc:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 5:
                logger.error("MQTT publish error: %s", exc)
            self._set_stopped()
            return

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 5:
                logger.error("MQTT publish rc=%d.", info.rc)
            self._set_stopped()
            return

        if self._consecutive_errors > 0:
            logger.info("MQTT publish restored.")
        self._consecutive_errors = 0
        self._last_published = (command, armed)
        self._last_publish_time = now

        # Log only on change (avoid per-heartbeat spam).
        if (command, armed) != self._last_logged_cmd:
            logger.info(
                "Published: %s  armed=%s  seq=%d", command, armed, seq,
            )
            self._last_logged_cmd = (command, armed)
