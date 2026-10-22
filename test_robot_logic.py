
from movement_logic import get_distance_zone, get_movement_command
from safety_controller import SafetyController
from motor_controller import MotorController


def test_distance_zones():
    assert get_distance_zone(150) == "FAR"
    assert get_distance_zone(120) == "FOLLOW"
    assert get_distance_zone(90) == "FOLLOW"
    assert get_distance_zone(60) == "FOLLOW"
    assert get_distance_zone(40) == "CLOSE"
    assert get_distance_zone(None) == "UNKNOWN"


def test_center_movement():
    assert get_movement_command("CENTER", 150) == "FORWARD"
    assert get_movement_command("CENTER", 90) == "STOP"
    assert get_movement_command("CENTER", 40) == "BACKWARD"


def test_left_movement():
    assert get_movement_command("LEFT", 150) == "TURN_LEFT_FORWARD"
    assert get_movement_command("LEFT", 90) == "TURN_LEFT"
    assert get_movement_command("LEFT", 40) == "TURN_LEFT_BACKWARD"


def test_right_movement():
    assert get_movement_command("RIGHT", 150) == "TURN_RIGHT_FORWARD"
    assert get_movement_command("RIGHT", 90) == "TURN_RIGHT"
    assert get_movement_command("RIGHT", 40) == "TURN_RIGHT_BACKWARD"


def test_unknown_position():
    assert get_movement_command("SEARCH", None) == "SEARCH"
    assert get_movement_command("INVALID", 90) == "STOP"


def test_safety_stops_on_target_loss():
    controller = SafetyController()
    assert controller.process(False, "FORWARD", None, True) == "STOP"


def test_safety_stops_on_invalid_distance():
    controller = SafetyController()
    assert controller.process(True, "FORWARD", None, True) == "STOP"
    assert controller.process(True, "FORWARD", 0, True) == "STOP"
    assert controller.process(True, "FORWARD", -10, True) == "STOP"


def test_safety_stops_on_camera_failure():
    controller = SafetyController()
    assert controller.process(True, "FORWARD", 100, False) == "STOP"


def test_safety_rejects_invalid_command():
    controller = SafetyController()
    assert controller.process(True, "INVALID", 100, True) == "STOP"


def test_motor_stop():
    motor = MotorController()
    state = motor.execute("STOP")
    assert state["left_direction"] == "STOP"
    assert state["right_direction"] == "STOP"
    assert state["left_speed"] == 0
    assert state["right_speed"] == 0


def test_motor_forward():
    motor = MotorController()
    state = motor.execute("FORWARD")
    assert state["left_direction"] == "FORWARD"
    assert state["right_direction"] == "FORWARD"
    assert state["left_speed"] == 70
    assert state["right_speed"] == 70


def test_motor_backward():
    motor = MotorController()
    state = motor.execute("BACKWARD")
    assert state["left_direction"] == "BACKWARD"
    assert state["right_direction"] == "BACKWARD"
    assert state["left_speed"] == 60
    assert state["right_speed"] == 60


def test_motor_search():
    motor = MotorController()
    state = motor.execute("SEARCH")
    assert state["left_direction"] == "BACKWARD"
    assert state["right_direction"] == "FORWARD"
    assert state["left_speed"] == 50
    assert state["right_speed"] == 50

import time
import safety_controller


def test_safety_stays_stopped_after_target_loss_timeout():
    original_timeout = safety_controller.TARGET_LOST_STOP_TIME
    safety_controller.TARGET_LOST_STOP_TIME = 0.1

    try:
        controller = SafetyController()
        assert controller.process(False, "FORWARD", None, True) == "STOP"

        time.sleep(0.15)

        assert controller.process(False, "SEARCH", None, True) == "STOP"
    finally:
        safety_controller.TARGET_LOST_STOP_TIME = original_timeout

        
def test_motor_turn_left():
    state = MotorController().execute("TURN_LEFT")
    assert state["left_direction"] == "FORWARD"
    assert state["right_direction"] == "FORWARD"
    assert state["left_speed"] == 30
    assert state["right_speed"] == 70


def test_motor_turn_right():
    state = MotorController().execute("TURN_RIGHT")
    assert state["left_direction"] == "FORWARD"
    assert state["right_direction"] == "FORWARD"
    assert state["left_speed"] == 70
    assert state["right_speed"] == 30


def test_motor_turn_left_forward():
    state = MotorController().execute("TURN_LEFT_FORWARD")
    assert state["left_speed"] == 40
    assert state["right_speed"] == 80


def test_motor_turn_right_forward():
    state = MotorController().execute("TURN_RIGHT_FORWARD")
    assert state["left_speed"] == 80
    assert state["right_speed"] == 40


def test_motor_turn_left_backward():
    state = MotorController().execute("TURN_LEFT_BACKWARD")
    assert state["left_direction"] == "BACKWARD"
    assert state["right_direction"] == "BACKWARD"
    assert state["left_speed"] == 40
    assert state["right_speed"] == 70


def test_motor_turn_right_backward():
    state = MotorController().execute("TURN_RIGHT_BACKWARD")
    assert state["left_direction"] == "BACKWARD"
    assert state["right_direction"] == "BACKWARD"
    assert state["left_speed"] == 70
    assert state["right_speed"] == 40


def test_motor_invalid_command_stops():
    state = MotorController().execute("INVALID_COMMAND")
    assert state["left_direction"] == "STOP"
    assert state["right_direction"] == "STOP"
    assert state["left_speed"] == 0
    assert state["right_speed"] == 0
