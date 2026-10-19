
import json
import socket
import threading


class NetworkMotorController:
    COMMANDS = {
        "STOP": ("STOP", 0, "STOP", 0),
        "FORWARD": ("FORWARD", 70, "FORWARD", 70),
        "BACKWARD": ("BACKWARD", 60, "BACKWARD", 60),
        "TURN_LEFT": ("FORWARD", 30, "FORWARD", 70),
        "TURN_RIGHT": ("FORWARD", 70, "FORWARD", 30),
        "TURN_LEFT_FORWARD": ("FORWARD", 40, "FORWARD", 80),
        "TURN_RIGHT_FORWARD": ("FORWARD", 80, "FORWARD", 40),
        "TURN_LEFT_BACKWARD": ("BACKWARD", 40, "BACKWARD", 70),
        "TURN_RIGHT_BACKWARD": ("BACKWARD", 70, "BACKWARD", 40),
        "SEARCH": ("BACKWARD", 50, "FORWARD", 50),
    }

    def __init__(self, host="192.168.1.17", port=5005, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.lock = threading.Lock()
        self.left_direction = "STOP"
        self.right_direction = "STOP"
        self.left_speed = 0
        self.right_speed = 0

    def execute(self, command):
        if command not in self.COMMANDS:
            raise ValueError(f"Unsupported movement command: {command}")

        left_direction, left_speed, right_direction, right_speed = (
            self.COMMANDS[command]
        )

        payload = {
            "command": command,
            "left_direction": left_direction,
            "left_speed": left_speed,
            "right_direction": right_direction,
            "right_speed": right_speed,
        }

        with self.lock:
            try:
                with socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                ) as connection:
                    connection.settimeout(self.timeout)
                    connection.sendall(
                        (json.dumps(payload) + "\n").encode("utf-8")
                    )
                    response = connection.makefile("r", encoding="utf-8").readline()
                    result = json.loads(response)

                    if not result.get("ok"):
                        raise RuntimeError("Pi rejected the command")

                self.left_direction = left_direction
                self.left_speed = left_speed
                self.right_direction = right_direction
                self.right_speed = right_speed
                return self.get_state()

            except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
                self.left_direction = "STOP"
                self.left_speed = 0
                self.right_direction = "STOP"
                self.right_speed = 0
                raise

    def stop(self):
        return self.execute("STOP")

    def get_state(self):
        return {
            "left_direction": self.left_direction,
            "right_direction": self.right_direction,
            "left_speed": self.left_speed,
            "right_speed": self.right_speed,
        }
