from network_motor_controller import NetworkMotorController

controller = NetworkMotorController(host="192.0.2.1", port=5005, timeout=1)

try:
    controller.execute("FORWARD")
except Exception as error:
    print("Connection error:", type(error).__name__)

print("Controller state:", controller.get_state())
