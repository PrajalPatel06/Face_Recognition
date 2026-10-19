import time

TARGET_LOST_STOP_TIME = 1.5


class SafetyController:

    def __init__(self):

        self.target_lost_since = None


    def process(
        self,
        target_found,
        target_command,
        distance_cm,
        camera_ok=True
    ):

        if not camera_ok:

            self.target_lost_since = None

            return "STOP"


        if not target_found:

            if self.target_lost_since is None:

                self.target_lost_since = time.time()

                return "STOP"


            lost_time = (
                time.time() -
                self.target_lost_since
            )


            if lost_time < TARGET_LOST_STOP_TIME:

                return "STOP"


            return "SEARCH"


        self.target_lost_since = None


        if distance_cm is None:

            return "STOP"


        if distance_cm <= 0:

            return "STOP"


        valid_commands = {
            "FORWARD",
            "BACKWARD",
            "TURN_LEFT",
            "TURN_RIGHT",
            "TURN_LEFT_FORWARD",
            "TURN_RIGHT_FORWARD",
            "TURN_LEFT_BACKWARD",
            "TURN_RIGHT_BACKWARD",
            "STOP"
        }


        if target_command not in valid_commands:

            return "STOP"


        return target_command