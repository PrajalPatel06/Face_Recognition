import time

from safety_controller import SafetyController

controller = SafetyController()


tests = [
    (True, "FORWARD", 150, True),
    (True, "TURN_LEFT", 80, True),
    (True, "STOP", 80, True),
    (True, "FORWARD", None, True),
    (False, "SEARCH", None, True),
    (False, "SEARCH", None, False),
]


print("Safety Controller Test")
print("----------------------")


for target_found, command, distance, camera_ok in tests:

    safe_command = controller.process(
        target_found,
        command,
        distance,
        camera_ok
    )

    print(
        f"Target: {target_found} | "
        f"Command: {command} | "
        f"Distance: {distance} | "
        f"Camera: {camera_ok} | "
        f"SAFE COMMAND: {safe_command}"
    )


print()
print("Testing target-loss timeout...")
print()


controller = SafetyController()


print(
    "Immediately after target loss:",
    controller.process(
        False,
        "SEARCH",
        None,
        True
    )
)


time.sleep(2)


print(
    "After 2 seconds:",
    controller.process(
        False,
        "SEARCH",
        None,
        True
    )
)