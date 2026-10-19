
import time

from movement_logic import get_distance_zone, get_movement_command
from safety_controller import SafetyController
from motor_controller import MotorController


def run_case(position, distance):
    zone = get_distance_zone(distance)
    requested = get_movement_command(position, distance)

    safety = SafetyController()
    target_found = position != "SEARCH"
    safe = safety.process(
        target_found,
        requested,
        distance,
        camera_ok=True
    )

    motor = MotorController()
    state = motor.execute(safe)

    print(
        f"{position:6} | {str(distance):>7} cm | "
        f"{zone:7} | {requested:22} | {safe:22} | "
        f"L={state['left_direction']} {state['left_speed']}% | "
        f"R={state['right_direction']} {state['right_speed']}%"
    )


def main():
    print("ROBOT MOVEMENT + SAFETY SIMULATION")
    print("-" * 120)
    print(
        f"{'Position':6} | {'Distance':>10} | {'Zone':7} | "
        f"{'Requested command':22} | {'Safe command':22} | Motor output"
    )
    print("-" * 120)

    cases = [
        ("LEFT", 150),
        ("CENTER", 150),
        ("RIGHT", 150),
        ("LEFT", 90),
        ("CENTER", 90),
        ("RIGHT", 90),
        ("LEFT", 40),
        ("CENTER", 40),
        ("RIGHT", 40),
        ("CENTER", 60),
        ("CENTER", 120),
        ("CENTER", None),
        ("INVALID", 90),
    ]

    for position, distance in cases:
        run_case(position, distance)

    print("\nTARGET-LOSS SAFETY TEST")
    print("-" * 40)

    safety = SafetyController()
    motor = MotorController()

    for elapsed in (0.0, 0.5, 1.0, 1.6):
        if elapsed > 0:
            time.sleep(elapsed - previous_elapsed)
        previous_elapsed = elapsed

        safe = safety.process(
            False,
            "SEARCH",
            None,
            camera_ok=True
        )
        state = motor.execute(safe)

        print(
            f"Elapsed: {elapsed:.1f}s | Safe command: {safe:6} | "
            f"Left: {state['left_direction']} {state['left_speed']}% | "
            f"Right: {state['right_direction']} {state['right_speed']}%"
        )

    print("\nCAMERA FAILURE TEST")
    safe = safety.process(
        False,
        "SEARCH",
        None,
        camera_ok=False
    )
    state = motor.execute(safe)
    print(f"Safe command: {safe} | Motor state: {state}")


if __name__ == "__main__":
    main()
