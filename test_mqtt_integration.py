r"""
Offline Integration Tests for MQTT Motor Controller
=====================================================

These tests run WITHOUT an MQTT broker, ESP32, or camera.
They verify:

- ``mqtt_config.py``: loading, defaults, validation.
- ``mqtt_motor_controller.py``: command mapping, motor state,
  payload schema, SEARCH → STOP, unknown → STOP.
- ``safety_controller.py``: stop conditions preserved.
- ``movement_logic.py``: pipeline unchanged.

Run with::

    .\.venv\Scripts\Activate.ps1
    pip install paho-mqtt pytest
    python -m pytest test_mqtt_integration.py -v
"""

import json
import os
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from movement_logic import get_distance_zone, get_movement_command
from safety_controller import SafetyController


# ============================================================
# mqtt_config tests
# ============================================================

class TestMqttConfig:

    def test_load_from_env_vars(self):
        from mqtt_config import load_mqtt_config

        env = {
            "MQTT_BROKER_HOST": "test.broker.local",
            "MQTT_BROKER_PORT": "1883",
            "MQTT_USERNAME": "testuser",
            "MQTT_PASSWORD": "testpass",
            "MQTT_USE_TLS": "false",
        }

        with patch.dict(os.environ, env, clear=False):
            cfg = load_mqtt_config(env_file="/nonexistent")

        assert cfg["broker_host"] == "test.broker.local"
        assert cfg["broker_port"] == 1883
        assert cfg["username"] == "testuser"
        assert cfg["password"] == "testpass"
        assert cfg["use_tls"] is False
        assert cfg["topic_command"] == "robot/face_following/command"
        assert cfg["topic_status"] == "robot/face_following/status"

    def test_load_from_env_file(self, tmp_path):
        from mqtt_config import load_mqtt_config

        env_file = tmp_path / ".env.mqtt"
        env_file.write_text(
            "MQTT_BROKER_HOST=file.broker.local\n"
            "MQTT_BROKER_PORT=8883\n"
            "MQTT_USERNAME=fileuser\n"
            "MQTT_PASSWORD=filepass\n"
            "MQTT_USE_TLS=true\n",
            encoding="utf-8",
        )

        # Clear env vars that would override.
        env_clear = {
            k: None for k in [
                "MQTT_BROKER_HOST", "MQTT_BROKER_PORT",
                "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_USE_TLS",
            ]
        }

        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing MQTT env vars.
            for k in env_clear:
                os.environ.pop(k, None)

            cfg = load_mqtt_config(env_file=str(env_file))

        assert cfg["broker_host"] == "file.broker.local"
        assert cfg["broker_port"] == 8883
        assert cfg["use_tls"] is True

    def test_missing_required_fields_raises(self):
        from mqtt_config import load_mqtt_config

        env_clear = [
            "MQTT_BROKER_HOST", "MQTT_USERNAME", "MQTT_PASSWORD",
            "MQTT_BROKER_PORT", "MQTT_USE_TLS",
        ]

        with patch.dict(os.environ, {}, clear=False):
            for k in env_clear:
                os.environ.pop(k, None)

            with pytest.raises(ValueError, match="Missing required"):
                load_mqtt_config(env_file="/nonexistent")

    def test_invalid_port_raises(self):
        from mqtt_config import load_mqtt_config

        env = {
            "MQTT_BROKER_HOST": "h",
            "MQTT_USERNAME": "u",
            "MQTT_PASSWORD": "p",
            "MQTT_BROKER_PORT": "not_a_number",
        }

        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(ValueError, match="integer"):
                load_mqtt_config(env_file="/nonexistent")

    def test_env_vars_override_file(self, tmp_path):
        from mqtt_config import load_mqtt_config

        env_file = tmp_path / ".env.mqtt"
        env_file.write_text(
            "MQTT_BROKER_HOST=file.host\n"
            "MQTT_USERNAME=fileuser\n"
            "MQTT_PASSWORD=filepass\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {
            "MQTT_BROKER_HOST": "env.host",
            "MQTT_USERNAME": "envuser",
            "MQTT_PASSWORD": "envpass",
        }, clear=False):
            cfg = load_mqtt_config(env_file=str(env_file))

        # Env var takes priority.
        assert cfg["broker_host"] == "env.host"
        assert cfg["username"] == "envuser"

    def test_default_topics(self):
        from mqtt_config import load_mqtt_config

        env = {
            "MQTT_BROKER_HOST": "h",
            "MQTT_USERNAME": "u",
            "MQTT_PASSWORD": "p",
        }

        with patch.dict(os.environ, env, clear=False):
            for k in ["MQTT_TOPIC_COMMAND", "MQTT_TOPIC_STATUS", "MQTT_TOPIC_TELEMETRY"]:
                os.environ.pop(k, None)
            cfg = load_mqtt_config(env_file="/nonexistent")

        assert cfg["topic_command"] == "robot/face_following/command"
        assert cfg["topic_status"] == "robot/face_following/status"
        assert cfg["topic_telemetry"] == "robot/face_following/telemetry"

    def test_quoted_values_in_env_file(self, tmp_path):
        from mqtt_config import load_mqtt_config

        env_file = tmp_path / ".env.mqtt"
        env_file.write_text(
            'MQTT_BROKER_HOST="quoted.host"\n'
            "MQTT_USERNAME='single_quoted'\n"
            "MQTT_PASSWORD=unquoted\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=False):
            for k in ["MQTT_BROKER_HOST", "MQTT_USERNAME", "MQTT_PASSWORD"]:
                os.environ.pop(k, None)
            cfg = load_mqtt_config(env_file=str(env_file))

        assert cfg["broker_host"] == "quoted.host"
        assert cfg["username"] == "single_quoted"
        assert cfg["password"] == "unquoted"


# ============================================================
# MqttMotorController tests (mocked paho-mqtt)
# ============================================================

def _make_controller_with_mocks(connected=True, armed=False):
    """Create an MqttMotorController with a mocked paho client."""
    from mqtt_motor_controller import MqttMotorController, PAHO_AVAILABLE
    import paho.mqtt.client as mqtt_mod

    fake_config = {
        "broker_host": "test.local",
        "broker_port": 1883,
        "username": "u",
        "password": "p",
        "client_id": "test",
        "use_tls": False,
        "topic_command": "robot/face_following/command",
        "topic_status": "robot/face_following/status",
        "topic_telemetry": "robot/face_following/telemetry",
    }

    # Patch the mqtt.Client class to avoid real network calls.
    with patch.object(mqtt_mod, "Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.connect = MagicMock()
        mock_instance.loop_start = MagicMock()
        mock_instance.loop_stop = MagicMock()
        mock_instance.disconnect = MagicMock()
        mock_instance.subscribe = MagicMock()

        # publish() returns a MagicMock with rc=0
        pub_result = MagicMock()
        pub_result.rc = 0
        mock_instance.publish = MagicMock(return_value=pub_result)

        mock_instance.username_pw_set = MagicMock()

        MockClient.return_value = mock_instance

        ctrl = MqttMotorController(config=fake_config, armed=armed)
        ctrl._connected = connected
        ctrl._client = mock_instance

    return ctrl, mock_instance


class TestMqttMotorController:

    def test_valid_commands_produce_correct_state(self):
        ctrl, _ = _make_controller_with_mocks(armed=True)

        state = ctrl.execute("FORWARD")
        assert state["left_direction"] == "FORWARD"
        assert state["left_speed"] == 70

        state = ctrl.execute("TURN_LEFT")
        assert state["left_speed"] == 30
        assert state["right_speed"] == 70

        state = ctrl.execute("STOP")
        assert state["left_speed"] == 0
        assert state["right_speed"] == 0

        ctrl.close()

    def test_search_maps_to_stop(self):
        ctrl, mock = _make_controller_with_mocks()

        state = ctrl.execute("SEARCH")
        assert state["left_speed"] == 0
        assert state["right_speed"] == 0

        # Verify the published JSON has command=STOP, not SEARCH.
        call_args = mock.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["command"] == "STOP"

        ctrl.close()

    def test_unknown_command_maps_to_stop(self):
        ctrl, mock = _make_controller_with_mocks()

        state = ctrl.execute("DANCE")
        assert state["left_direction"] == "STOP"
        assert state["left_speed"] == 0

        payload = json.loads(mock.publish.call_args[0][1])
        assert payload["command"] == "STOP"

        ctrl.close()

    def test_empty_command_maps_to_stop(self):
        ctrl, _ = _make_controller_with_mocks()
        state = ctrl.execute("")
        assert state["left_direction"] == "STOP"
        ctrl.close()

    def test_payload_schema(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl.execute("FORWARD")

        call_args = mock.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        kwargs = call_args[1] if len(call_args) > 1 else {}

        # Topic
        assert topic == "robot/face_following/command"

        # Required fields
        assert payload["command"] == "FORWARD"
        assert isinstance(payload["sequence"], int)
        assert payload["sequence"] >= 1
        assert isinstance(payload["timestamp"], float)
        assert payload["source"] == "laptop"
        assert payload["motor_enable"] is False

        # QoS and retain
        assert kwargs.get("qos") == 1
        assert kwargs.get("retain") is False

        ctrl.close()

    def test_sequence_increments(self):
        ctrl, mock = _make_controller_with_mocks()

        ctrl.execute("FORWARD")
        p1 = json.loads(mock.publish.call_args[0][1])

        ctrl.execute("BACKWARD")
        p2 = json.loads(mock.publish.call_args[0][1])

        assert p2["sequence"] > p1["sequence"]

        ctrl.close()

    def test_motor_enable_false_until_armed(self):
        ctrl, mock = _make_controller_with_mocks()
        assert ctrl.armed is False

        for cmd in ["STOP", "FORWARD", "BACKWARD", "TURN_LEFT", "TURN_RIGHT"]:
            ctrl.execute(cmd)
            payload = json.loads(mock.publish.call_args[0][1])
            assert payload["motor_enable"] is False, (
                f"motor_enable should be False for {cmd}"
            )

        ctrl.close()

    def test_retain_always_false(self):
        ctrl, mock = _make_controller_with_mocks()

        for cmd in ["STOP", "FORWARD", "BACKWARD"]:
            ctrl.execute(cmd)
            kwargs = mock.publish.call_args[1]
            assert kwargs.get("retain") is False, (
                f"retain should be False for {cmd}"
            )

        ctrl.close()

    def test_disconnected_state_reports_stop(self):
        ctrl, _ = _make_controller_with_mocks(connected=False)

        state = ctrl.execute("FORWARD")
        assert state["left_direction"] == "STOP"
        assert state["left_speed"] == 0

        ctrl.close()

    def test_get_state_matches_execute(self):
        ctrl, _ = _make_controller_with_mocks()
        returned = ctrl.execute("BACKWARD")
        stored = ctrl.get_state()
        assert returned == stored
        ctrl.close()

    def test_close_is_safe(self):
        ctrl, _ = _make_controller_with_mocks()
        ctrl.close()
        ctrl.close()  # Idempotent


# ============================================================
# Arm switch, heartbeat, session, ESP32 status
# ============================================================

def _payloads(mock):
    return [json.loads(c[0][1]) for c in mock.publish.call_args_list]


class TestArmingAndHeartbeat:

    def test_disarmed_reports_stop_state(self):
        ctrl, mock = _make_controller_with_mocks(armed=False)
        state = ctrl.execute("FORWARD")

        # Command is still sent (as a heartbeat) but motors are locked.
        assert _payloads(mock)[-1]["command"] == "FORWARD"
        assert _payloads(mock)[-1]["motor_enable"] is False
        assert state["left_speed"] == 0
        assert state["right_speed"] == 0
        ctrl.close()

    def test_arming_sets_motor_enable_true(self):
        ctrl, mock = _make_controller_with_mocks()
        assert ctrl.set_armed(True) is True

        state = ctrl.execute("FORWARD")
        assert _payloads(mock)[-1]["motor_enable"] is True
        assert state["left_speed"] == 70
        ctrl.close()

    def test_arm_toggle_publishes_immediately(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl.execute("FORWARD")
        ctrl.set_armed(True)
        ctrl.execute("FORWARD")
        ctrl.set_armed(False)
        ctrl.execute("FORWARD")

        enables = [p["motor_enable"] for p in _payloads(mock)]
        assert enables == [False, True, False]
        ctrl.close()

    def test_unchanged_command_is_rate_limited(self):
        ctrl, mock = _make_controller_with_mocks()

        for _ in range(30):            # one camera second at 30 FPS
            ctrl.execute("FORWARD")

        assert mock.publish.call_count == 1
        ctrl.close()

    def test_changed_command_publishes_immediately(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl.execute("FORWARD")
        ctrl.execute("TURN_LEFT")
        ctrl.execute("STOP")

        cmds = [p["command"] for p in _payloads(mock)]
        assert cmds == ["FORWARD", "TURN_LEFT", "STOP"]
        ctrl.close()

    def test_heartbeat_resends_after_interval(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl.heartbeat_interval = 0.05

        ctrl.execute("STOP")
        time.sleep(0.07)
        ctrl.execute("STOP")

        assert mock.publish.call_count == 2
        seqs = [p["sequence"] for p in _payloads(mock)]
        assert seqs[1] > seqs[0]
        ctrl.close()

    def test_default_heartbeat_beats_esp32_watchdog(self):
        from mqtt_motor_controller import DEFAULT_HEARTBEAT_INTERVAL

        esp32_watchdog_s = 1.0   # WATCHDOG_TIMEOUT_MS in the .ino
        assert DEFAULT_HEARTBEAT_INTERVAL * 3 < esp32_watchdog_s

    def test_session_is_constant_and_unique(self):
        ctrl1, mock1 = _make_controller_with_mocks()
        ctrl2, _ = _make_controller_with_mocks()

        ctrl1.execute("FORWARD")
        ctrl1.execute("STOP")
        sessions = {p["session"] for p in _payloads(mock1)}

        assert len(sessions) == 1
        session = sessions.pop()
        assert isinstance(session, int)
        assert 1 <= session < 2**31   # fits the ESP32's uint32_t
        assert ctrl1._session != ctrl2._session
        ctrl1.close()
        ctrl2.close()

    def test_reconnect_resends_current_command(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl.execute("FORWARD")
        ctrl._on_connect(mock, None, {}, 0)
        ctrl.execute("FORWARD")

        assert mock.publish.call_count == 2
        ctrl.close()

    def test_close_sends_disarmed_stop(self):
        ctrl, mock = _make_controller_with_mocks(armed=True)
        ctrl.execute("FORWARD")
        ctrl.close()

        last = _payloads(mock)[-1]
        assert last["command"] == "STOP"
        assert last["motor_enable"] is False
        assert ctrl.armed is False


def _status_msg(payload, retain=False):
    msg = MagicMock()
    msg.payload = json.dumps(payload).encode("utf-8")
    msg.retain = retain
    return msg


class TestEsp32Status:

    def test_offline_before_any_status(self):
        ctrl, _ = _make_controller_with_mocks()
        assert ctrl.esp32_status()["online"] is False
        ctrl.close()

    def test_live_status_marks_online(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl._on_message(mock, None, _status_msg(
            {"online": True, "state": "STOP", "wifi_rssi": -55}
        ))

        status = ctrl.esp32_status()
        assert status["online"] is True
        assert status["state"] == "STOP"
        assert status["wifi_rssi"] == -55
        ctrl.close()

    def test_retained_status_does_not_prove_liveness(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl._on_message(mock, None, _status_msg(
            {"online": True, "state": "STOP"}, retain=True,
        ))
        assert ctrl.esp32_status()["online"] is False
        ctrl.close()

    def test_last_will_marks_offline(self):
        ctrl, mock = _make_controller_with_mocks()
        ctrl._on_message(mock, None, _status_msg({"online": True}))
        ctrl._on_message(mock, None, _status_msg({"online": False}))
        assert ctrl.esp32_status()["online"] is False
        ctrl.close()

    def test_stale_status_marks_offline(self):
        import mqtt_motor_controller as mmc

        ctrl, mock = _make_controller_with_mocks()
        ctrl._on_message(mock, None, _status_msg({"online": True}))
        ctrl._esp32_status_time -= mmc.ESP32_STATUS_TIMEOUT + 1
        assert ctrl.esp32_status()["online"] is False
        ctrl.close()

    def test_bad_status_payload_ignored(self):
        ctrl, mock = _make_controller_with_mocks()
        msg = MagicMock()
        msg.payload = b"not json"
        msg.retain = False
        ctrl._on_message(mock, None, msg)
        assert ctrl.esp32_status()["online"] is False
        ctrl.close()


# ============================================================
# Python and ESP32 command tables must agree
# ============================================================

class TestFirmwareTableSync:

    INO = (
        Path(__file__).resolve().parent
        / "esp32_mqtt_robot_controller"
        / "esp32_mqtt_robot_controller.ino"
    )

    def _firmware_table(self):
        import re

        text = self.INO.read_text(encoding="utf-8")
        rows = re.findall(
            r'\{"([A-Z_]+)",\s*(-?\d+),\s*(-?\d+)\}', text,
        )
        return {name: (int(l), int(r)) for name, l, r in rows}

    def test_firmware_speeds_match_python(self):
        from mqtt_motor_controller import _MOTOR_STATES

        firmware = self._firmware_table()
        assert set(firmware) == set(_MOTOR_STATES)

        for name, (ld, ls, rd, rs) in _MOTOR_STATES.items():
            sign = {"FORWARD": 1, "BACKWARD": -1, "STOP": 0}
            assert firmware[name] == (sign[ld] * ls, sign[rd] * rs), name


# ============================================================
# All valid movement commands are mapped
# ============================================================

class TestCommandCoverage:

    def test_all_pipeline_commands_handled(self):
        """Every command from movement_logic must be accepted."""
        from mqtt_motor_controller import VALID_COMMANDS

        pipeline_cmds = {
            "STOP", "FORWARD", "BACKWARD",
            "TURN_LEFT", "TURN_RIGHT",
            "TURN_LEFT_FORWARD", "TURN_RIGHT_FORWARD",
            "TURN_LEFT_BACKWARD", "TURN_RIGHT_BACKWARD",
        }
        assert pipeline_cmds == VALID_COMMANDS

    def test_search_is_not_in_valid_commands(self):
        from mqtt_motor_controller import VALID_COMMANDS
        assert "SEARCH" not in VALID_COMMANDS


# ============================================================
# Safety controller integration
# ============================================================

class TestSafetyIntegration:

    def test_target_lost_produces_stop(self):
        sc = SafetyController()
        assert sc.process(False, "FORWARD", None, True) == "STOP"

    def test_camera_failure_produces_stop(self):
        sc = SafetyController()
        assert sc.process(True, "FORWARD", 100, False) == "STOP"

    def test_invalid_distance_produces_stop(self):
        sc = SafetyController()
        assert sc.process(True, "FORWARD", None, True) == "STOP"
        assert sc.process(True, "FORWARD", 0, True) == "STOP"
        assert sc.process(True, "FORWARD", -5, True) == "STOP"

    def test_unknown_command_produces_stop(self):
        sc = SafetyController()
        assert sc.process(True, "DANCE", 100, True) == "STOP"

    def test_safety_stays_stopped_after_timeout(self):
        import safety_controller
        orig = safety_controller.TARGET_LOST_STOP_TIME
        safety_controller.TARGET_LOST_STOP_TIME = 0.05
        try:
            sc = SafetyController()
            assert sc.process(False, "SEARCH", None, True) == "STOP"
            time.sleep(0.1)
            assert sc.process(False, "SEARCH", None, True) == "STOP"
        finally:
            safety_controller.TARGET_LOST_STOP_TIME = orig

    def test_search_never_returned_by_safety(self):
        """The modified safety controller never returns SEARCH."""
        sc = SafetyController()
        # Target lost — various states
        assert sc.process(False, "SEARCH", None, True) == "STOP"
        time.sleep(0.01)
        assert sc.process(False, "SEARCH", None, True) == "STOP"
        # Camera failure
        assert sc.process(False, "SEARCH", None, False) == "STOP"


# ============================================================
# Movement logic unchanged
# ============================================================

class TestMovementLogicUnchanged:

    def test_distance_zones(self):
        assert get_distance_zone(150) == "FAR"
        assert get_distance_zone(90) == "FOLLOW"
        assert get_distance_zone(40) == "CLOSE"
        assert get_distance_zone(None) == "UNKNOWN"

    def test_center_commands(self):
        assert get_movement_command("CENTER", 150) == "FORWARD"
        assert get_movement_command("CENTER", 90) == "STOP"
        assert get_movement_command("CENTER", 40) == "BACKWARD"

    def test_left_commands(self):
        assert get_movement_command("LEFT", 150) == "TURN_LEFT_FORWARD"
        assert get_movement_command("LEFT", 90) == "TURN_LEFT"
        assert get_movement_command("LEFT", 40) == "TURN_LEFT_BACKWARD"

    def test_right_commands(self):
        assert get_movement_command("RIGHT", 150) == "TURN_RIGHT_FORWARD"
        assert get_movement_command("RIGHT", 90) == "TURN_RIGHT"
        assert get_movement_command("RIGHT", 40) == "TURN_RIGHT_BACKWARD"
