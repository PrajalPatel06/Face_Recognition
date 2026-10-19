from motor_controller import MotorController

motor = MotorController()


commands = [
    "FORWARD",
    "BACKWARD",
    "TURN_LEFT",
    "TURN_RIGHT",
    "TURN_LEFT_FORWARD",
    "TURN_RIGHT_FORWARD",
    "TURN_LEFT_BACKWARD",
    "TURN_RIGHT_BACKWARD",
    "SEARCH",
    "STOP"
]


print("Differential Motor Controller Test")
print("----------------------------------")


for command in commands:

    state = motor.execute(command)

    print(
        f"Command: {command:22} | "
        f"Left: {state['left_direction']:8} "
        f"{state['left_speed']:3}% | "
        f"Right: {state['right_direction']:8} "
        f"{state['right_speed']:3}%"
    )