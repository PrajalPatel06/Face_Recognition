from movement_logic import get_distance_zone, get_movement_command

test_cases = [
    ("LEFT", 150),
    ("CENTER", 150),
    ("RIGHT", 150),
    ("LEFT", 90),
    ("CENTER", 90),
    ("RIGHT", 90),
    ("LEFT", 40),
    ("CENTER", 40),
    ("RIGHT", 40),
    ("SEARCH", None)
]


print("Robot Movement Test")
print("-------------------")


for position, distance in test_cases:

    zone = get_distance_zone(distance)

    command = get_movement_command(
        position,
        distance
    )

    print(
        f"Position: {position:6} | "
        f"Distance: {distance!s:>5} cm | "
        f"Zone: {zone:7} | "
        f"Command: {command}"
    )