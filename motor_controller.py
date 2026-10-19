class MotorController:

    def __init__(self):
        self.left_direction = "STOP"
        self.right_direction = "STOP"

        self.left_speed = 0
        self.right_speed = 0

    def stop(self):
        self.left_direction = "STOP"
        self.right_direction = "STOP"

        self.left_speed = 0
        self.right_speed = 0

    def forward(self):
        self.left_direction = "FORWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 70
        self.right_speed = 70

    def backward(self):
        self.left_direction = "BACKWARD"
        self.right_direction = "BACKWARD"

        self.left_speed = 60
        self.right_speed = 60

    def turn_left(self):
        self.left_direction = "FORWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 30
        self.right_speed = 70

    def turn_right(self):
        self.left_direction = "FORWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 70
        self.right_speed = 30

    def turn_left_forward(self):
        self.left_direction = "FORWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 40
        self.right_speed = 80

    def turn_right_forward(self):
        self.left_direction = "FORWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 80
        self.right_speed = 40

    def turn_left_backward(self):
        self.left_direction = "BACKWARD"
        self.right_direction = "BACKWARD"

        self.left_speed = 40
        self.right_speed = 70

    def turn_right_backward(self):
        self.left_direction = "BACKWARD"
        self.right_direction = "BACKWARD"

        self.left_speed = 70
        self.right_speed = 40

    def search(self):
        self.left_direction = "BACKWARD"
        self.right_direction = "FORWARD"

        self.left_speed = 50
        self.right_speed = 50

    def execute(self, command):

        if command == "FORWARD":
            self.forward()

        elif command == "BACKWARD":
            self.backward()

        elif command == "TURN_LEFT":
            self.turn_left()

        elif command == "TURN_RIGHT":
            self.turn_right()

        elif command == "TURN_LEFT_FORWARD":
            self.turn_left_forward()

        elif command == "TURN_RIGHT_FORWARD":
            self.turn_right_forward()

        elif command == "TURN_LEFT_BACKWARD":
            self.turn_left_backward()

        elif command == "TURN_RIGHT_BACKWARD":
            self.turn_right_backward()

        elif command == "SEARCH":
            self.search()

        else:
            self.stop()

        return self.get_state()

    def get_state(self):

        return {
            "left_direction": self.left_direction,
            "right_direction": self.right_direction,
            "left_speed": self.left_speed,
            "right_speed": self.right_speed
        }