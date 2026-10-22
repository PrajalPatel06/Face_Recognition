"""
MQTT Configuration Loader
==========================

Loads MQTT broker settings from environment variables or a local
``.env.mqtt`` file.  Credentials are never hardcoded or committed.

Configuration priority
----------------------
1. Environment variables (highest)
2. ``.env.mqtt`` file in the project root
3. Built-in defaults (topic names and port only)

Required settings (no defaults)
-------------------------------
- ``MQTT_BROKER_HOST``
- ``MQTT_USERNAME``
- ``MQTT_PASSWORD``

See ``.env.mqtt.example`` for the full template.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────
DEFAULT_BROKER_PORT = 8883
DEFAULT_CLIENT_ID = "face_robot_laptop"
DEFAULT_USE_TLS = True

DEFAULT_TOPIC_COMMAND = "robot/face_following/command"
DEFAULT_TOPIC_STATUS = "robot/face_following/status"
DEFAULT_TOPIC_TELEMETRY = "robot/face_following/telemetry"


# ── Helpers ─────────────────────────────────────────────────

def _load_env_file(filepath):
    """Parse a simple ``KEY=VALUE`` file.  Ignores comments and blanks."""
    values = {}
    path = Path(filepath)

    if not path.is_file():
        return values

    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line_num, raw in enumerate(fh, 1):
                line = raw.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" not in line:
                    logger.warning(
                        ".env.mqtt line %d: missing '=', skipped.", line_num,
                    )
                    continue

                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                # Strip surrounding quotes.
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ("'", '"')
                ):
                    value = value[1:-1]

                values[key] = value

    except OSError as exc:
        logger.warning("Could not read %s: %s", filepath, exc)

    return values


def _get(env_dict, key, default=None):
    """Return the first available value: env-var → dict → default."""
    value = os.environ.get(key)
    if value is not None:
        return value

    value = env_dict.get(key)
    if value is not None:
        return value

    return default


# ── Public API ──────────────────────────────────────────────

def load_mqtt_config(env_file=None):
    """
    Load and validate MQTT configuration.

    Parameters
    ----------
    env_file : str or Path, optional
        Path to the ``.env.mqtt`` file.  Defaults to the project
        directory (same folder as this module).

    Returns
    -------
    dict
        Configuration dictionary with keys:
        ``broker_host``, ``broker_port``, ``username``, ``password``,
        ``client_id``, ``use_tls``, ``topic_command``,
        ``topic_status``, ``topic_telemetry``.

    Raises
    ------
    ValueError
        If any required field is missing.
    """
    if env_file is None:
        env_file = Path(__file__).resolve().parent / ".env.mqtt"

    env = _load_env_file(env_file)

    broker_host = _get(env, "MQTT_BROKER_HOST")
    broker_port_raw = _get(env, "MQTT_BROKER_PORT", str(DEFAULT_BROKER_PORT))
    username = _get(env, "MQTT_USERNAME")
    password = _get(env, "MQTT_PASSWORD")
    client_id = _get(env, "MQTT_CLIENT_ID", DEFAULT_CLIENT_ID)
    use_tls_raw = _get(env, "MQTT_USE_TLS", str(DEFAULT_USE_TLS))

    topic_command = _get(env, "MQTT_TOPIC_COMMAND", DEFAULT_TOPIC_COMMAND)
    topic_status = _get(env, "MQTT_TOPIC_STATUS", DEFAULT_TOPIC_STATUS)
    topic_telemetry = _get(env, "MQTT_TOPIC_TELEMETRY", DEFAULT_TOPIC_TELEMETRY)

    # Parse port.
    try:
        broker_port = int(broker_port_raw)
    except (ValueError, TypeError):
        raise ValueError(
            f"MQTT_BROKER_PORT must be an integer, got: {broker_port_raw!r}"
        )

    # Parse TLS flag.
    if isinstance(use_tls_raw, str):
        use_tls = use_tls_raw.lower() in ("true", "1", "yes")
    else:
        use_tls = bool(use_tls_raw)

    # Validate required fields.
    missing = []
    if not broker_host:
        missing.append("MQTT_BROKER_HOST")
    if not username:
        missing.append("MQTT_USERNAME")
    if not password:
        missing.append("MQTT_PASSWORD")

    if missing:
        raise ValueError(
            f"Missing required MQTT configuration: {', '.join(missing)}.  "
            f"Set them as environment variables or in .env.mqtt.  "
            f"See .env.mqtt.example for the template."
        )

    config = {
        "broker_host": broker_host,
        "broker_port": broker_port,
        "username": username,
        "password": password,
        "client_id": client_id,
        "use_tls": use_tls,
        "topic_command": topic_command,
        "topic_status": topic_status,
        "topic_telemetry": topic_telemetry,
    }

    # Log WITHOUT credentials.
    logger.info(
        "MQTT config: broker=%s:%d  tls=%s  client=%s",
        broker_host, broker_port, use_tls, client_id,
    )
    logger.info(
        "MQTT topics: cmd=%s  status=%s  telemetry=%s",
        topic_command, topic_status, topic_telemetry,
    )

    return config
