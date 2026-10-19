
import pickle
import cv2
import numpy as np
import threading
import time
from collections import deque
from insightface.app import FaceAnalysis
from movement_logic import get_distance_zone, get_movement_command
from safety_controller import SafetyController
from motor_controller import MotorController

DATABASE_FILE = "embeddings/database_embeddings.pkl"
TARGET_PERSON = "Person_B"
RECOGNITION_THRESHOLD = 0.45
CENTER_TOLERANCE = 80
RECOGNITION_INTERVAL = 0.15
KNOWN_FACE_WIDTH_CM = 15.0
FOCAL_LENGTH = 573.3
DISTANCE_SMOOTHING_SAMPLES = 5
CAMERA_INDEX = 0

with open(DATABASE_FILE, "rb") as file:
    database = pickle.load(file)

if TARGET_PERSON not in database:
    raise ValueError(
        f"{TARGET_PERSON} was not found in the database. "
        f"Available people: {list(database.keys())}"
    )

print("Database loaded successfully")
print("Enrolled people:", list(database.keys()))
print("Selected target:", TARGET_PERSON)

app = FaceAnalysis(
    name="buffalo_l",
    providers=[
        "CUDAExecutionProvider",
        "CPUExecutionProvider"
    ]
)
app.prepare(ctx_id=0, det_size=(320, 320))

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    cap.release()
    cap = cv2.VideoCapture(CAMERA_INDEX)

if not cap.isOpened():
    raise RuntimeError(
        f"Could not open camera index {CAMERA_INDEX}"
    )

latest_frame = None
latest_results = []
frame_lock = threading.Lock()
result_lock = threading.Lock()
running = True

distance_history = deque(maxlen=DISTANCE_SMOOTHING_SAMPLES)
safety_controller = SafetyController()
motor_controller = MotorController()


def calculate_distance(face_width):
    if face_width <= 0:
        return None

    distance = KNOWN_FACE_WIDTH_CM * FOCAL_LENGTH / face_width
    distance_history.append(distance)

    return float(np.median(distance_history))


def recognize_frame(frame):
    frame_height, frame_width = frame.shape[:2]
    frame_center_x = frame_width // 2
    results = []

    faces = app.get(frame)

    for face in faces:
        x1, y1, x2, y2 = face.bbox.astype(int)

        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(frame_width, x2)
        y2 = min(frame_height, y2)

        face_width = x2 - x1
        if face_width <= 0 or y2 <= y1:
            continue

        embedding = np.asarray(face.embedding, dtype=np.float32)
        embedding_norm = np.linalg.norm(embedding)

        if embedding_norm == 0:
            continue

        embedding = embedding / embedding_norm
        best_person = "Unknown"
        best_score = -1.0

        for person_name, reference_embeddings in database.items():
            for reference in reference_embeddings:
                reference = np.asarray(reference, dtype=np.float32)
                reference_norm = np.linalg.norm(reference)

                if reference_norm == 0:
                    continue

                reference = reference / reference_norm
                score = float(np.dot(embedding, reference))

                if score > best_score:
                    best_score = score
                    best_person = person_name

        if best_score < RECOGNITION_THRESHOLD:
            person = "Unknown"
        else:
            person = best_person

        center_x = (x1 + x2) // 2
        error_x = center_x - frame_center_x

        if person == TARGET_PERSON:
            if error_x < -CENTER_TOLERANCE:
                position = "LEFT"
            elif error_x > CENTER_TOLERANCE:
                position = "RIGHT"
            else:
                position = "CENTER"
        else:
            position = "NOT TARGET"

        results.append({
            "bbox": (x1, y1, x2, y2),
            "person": person,
            "score": best_score,
            "center_x": center_x,
            "face_width": face_width,
            "position": position,
            "error_x": error_x
        })

    with result_lock:
        global latest_results
        latest_results = results


def recognition_worker():
    global running

    while running:
        with frame_lock:
            frame = (
                latest_frame.copy()
                if latest_frame is not None
                else None
            )

        if frame is None:
            time.sleep(0.01)
            continue

        start = time.time()

        try:
            recognize_frame(frame)
        except Exception as error:
            print("Recognition error:", error)

        remaining = RECOGNITION_INTERVAL - (time.time() - start)
        if remaining > 0:
            time.sleep(remaining)


worker = threading.Thread(
    target=recognition_worker,
    daemon=True
)
worker.start()

print()
print("Robot-following simulation started")
print("Target:", TARGET_PERSON)
print("Focal length:", FOCAL_LENGTH, "px")
print("Physical motor control: DISABLED")
print("Press Q or ESC to exit")

fps_start = time.time()
fps_frames = 0
display_fps = 0.0
last_target_seen = False

try:
    while True:
        ret, frame = cap.read()

        if not ret:
            safe_command = safety_controller.process(
                False, "STOP", None, False
            )
            motor_controller.execute(safe_command)
            print("Camera read failed; STOP command issued.")
            break

        with frame_lock:
            latest_frame = frame.copy()

        fps_frames += 1
        elapsed = time.time() - fps_start

        if elapsed >= 1.0:
            display_fps = fps_frames / elapsed
            fps_frames = 0
            fps_start = time.time()

        with result_lock:
            results = list(latest_results)

        target_candidates = [
            item for item in results
            if item["person"] == TARGET_PERSON
        ]

        target = None
        if target_candidates:
            target = max(
                target_candidates,
                key=lambda item: (
                    item["bbox"][2] - item["bbox"][0]
                ) * (
                    item["bbox"][3] - item["bbox"][1]
                )
            )

        target_distance = None
        target_zone = "UNKNOWN"
        target_command = "STOP"
        target_position = "SEARCH"
        target_x = 0
        target_error = 0

        if target is not None:
            target_position = target["position"]
            target_x = target["center_x"]
            target_error = target["error_x"]

            target_distance = calculate_distance(
                target["face_width"]
            )

            target_zone = get_distance_zone(target_distance)
            target_command = get_movement_command(
                target_position,
                target_distance
            )

            safe_command = safety_controller.process(
                True,
                target_command,
                target_distance,
                True
            )
            last_target_seen = True

        else:
            if last_target_seen:
                distance_history.clear()
            last_target_seen = False

            safe_command = safety_controller.process(
                False,
                "SEARCH",
                None,
                True
            )

        motor_state = motor_controller.execute(safe_command)

        for result in results:
            x1, y1, x2, y2 = result["bbox"]
            person = result["person"]
            score = result["score"]

            if person == TARGET_PERSON:
                color = (0, 255, 0)
                label = f"TARGET: {person} {score:.3f}"
            elif person == "Unknown":
                color = (0, 0, 255)
                label = f"Unknown {score:.3f}"
            else:
                color = (255, 0, 255)
                label = f"{person} {score:.3f}"

            cv2.rectangle(
                frame, (x1, y1), (x2, y2), color, 2
            )
            cv2.putText(
                frame, label, (x1, max(25, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2
            )

            if person == TARGET_PERSON:
                cv2.putText(
                    frame, result["position"],
                    (x1, min(y2 + 25, frame.shape[0] - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0), 2
                )

        height, width = frame.shape[:2]
        cv2.line(
            frame, (width // 2, 0),
            (width // 2, height), (255, 255, 0), 1
        )

        distance_text = (
            f"{target_distance:.1f} cm"
            if target_distance is not None
            else "---"
        )

        status = "TARGET VERIFIED" if target else "TARGET NOT VERIFIED"
        status_color = (0, 255, 0) if target else (0, 0, 255)

        overlay = [
            f"Target: {TARGET_PERSON}",
            f"Position: {target_position}",
            f"Target X: {target_x}  Error X: {target_error}",
            f"Distance: {distance_text}",
            f"Zone: {target_zone}",
            f"Faces: {len(results)}  FPS: {display_fps:.1f}",
            f"Decision: {target_command}",
            f"SAFE COMMAND: {safe_command}",
            f"L MOTOR: {motor_state['left_direction']} "
            f"{motor_state['left_speed']}%",
            f"R MOTOR: {motor_state['right_direction']} "
            f"{motor_state['right_speed']}%"
        ]

        for index, text in enumerate(overlay):
            cv2.putText(
                frame, text, (15, 25 + index * 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58,
                (255, 255, 255), 2
            )

        cv2.putText(
            frame, status, (15, height - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65,
            status_color, 2
        )

        cv2.imshow("Person_B Robot Following Simulation", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break

        try:
            if cv2.getWindowProperty(
                "Person_B Robot Following Simulation",
                cv2.WND_PROP_VISIBLE
            ) < 1:
                break
        except cv2.error:
            break

except KeyboardInterrupt:
    print("Stopping simulation...")

finally:
    running = False
    worker.join(timeout=1.0)
    cap.release()
    cv2.destroyAllWindows()
    print("Robot-following simulation stopped.")
