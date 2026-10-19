FAR_DISTANCE = 120
FOLLOW_DISTANCE = 60

def get_distance_zone(distance_cm):

    if distance_cm is None:
        return "UNKNOWN"

    if distance_cm > FAR_DISTANCE:
        return "FAR"

    if distance_cm < FOLLOW_DISTANCE:
        return "CLOSE"

    return "FOLLOW"


def get_movement_command(position, distance_cm):

    distance_zone = get_distance_zone(distance_cm)

    if distance_zone == "UNKNOWN":
        return "SEARCH"

    if position == "LEFT":

        if distance_zone == "FAR":
            return "TURN_LEFT_FORWARD"

        if distance_zone == "FOLLOW":
            return "TURN_LEFT"

        if distance_zone == "CLOSE":
            return "TURN_LEFT_BACKWARD"


    if position == "CENTER":

        if distance_zone == "FAR":
            return "FORWARD"

        if distance_zone == "FOLLOW":
            return "STOP"

        if distance_zone == "CLOSE":
            return "BACKWARD"


    if position == "RIGHT":

        if distance_zone == "FAR":
            return "TURN_RIGHT_FORWARD"

        if distance_zone == "FOLLOW":
            return "TURN_RIGHT"

        if distance_zone == "CLOSE":
            return "TURN_RIGHT_BACKWARD"


    if position == "SEARCH":
        return "SEARCH"


    return "STOP"