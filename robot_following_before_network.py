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
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# Tracker output is used for display/position only while recently verified.
# Movement is allowed only when a fresh ArcFace result verifies Person_B.
VERIFICATION_MAX_AGE = 0.45
MAX_TRACK_SHIFT_PER_UPDATE = 100
MIN_FACE_WIDTH = 20
MAX_FACE_WIDTH = 500

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
    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
)
app.prepare(ctx_id=0, det_size=(320, 320))

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    cap.release()
    cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}")

latest_frame = None
latest_results = []
latest_results_time = 0.0
latest_results_seq = 0
frame_lock = threading.Lock()
result_lock = threading.Lock()
running = True

distance_history = deque(maxlen=DISTANCE_SMOOTHING_SAMPLES)
safety_controller = SafetyController()
motor_controller = MotorController()


def calculate_distance(face_width):
    if face_width <= 0:
        return None
    distance_history.append(KNOWN_FACE_WIDTH_CM * FOCAL_LENGTH / face_width)
    return float(np.median(distance_history))


def recognize_frame(frame):
    frame_height, frame_width = frame.shape[:2]
    frame_center_x = frame_width // 2
    results = []

    for face in app.get(frame):
        x1, y1, x2, y2 = face.bbox.astype(int)
        x1 = max(0, min(x1, frame_width - 1))
        y1 = max(0, min(y1, frame_height - 1))
        x2 = max(0, min(x2, frame_width))
        y2 = max(0, min(y2, frame_height))
        face_width = x2 - x1
        if face_width <= 0 or y2 <= y1:
            continue

        embedding = np.asarray(face.embedding, dtype=np.float32)
        norm = np.linalg.norm(embedding)
        if norm == 0:
            continue
        embedding /= norm

        best_person, best_score = "Unknown", -1.0
        for name, reference_embeddings in database.items():
            for reference in reference_embeddings:
                reference = np.asarray(reference, dtype=np.float32)
                reference_norm = np.linalg.norm(reference)
                if reference_norm == 0:
                    continue
                score = float(np.dot(embedding, reference / reference_norm))
                if score > best_score:
                    best_person, best_score = name, score

        person = best_person if best_score >= RECOGNITION_THRESHOLD else "Unknown"
        center_x = (x1 + x2) // 2
        error_x = center_x - frame_center_x
        if person == TARGET_PERSON:
            position = (
                "LEFT" if error_x < -CENTER_TOLERANCE
                else "RIGHT" if error_x > CENTER_TOLERANCE
                else "CENTER"
            )
        else:
            position = "NOT TARGET"

        results.append({
            "bbox": (x1, y1, x2, y2),
            "person": person,
            "score": best_score,
            "center_x": center_x,
            "face_width": face_width,
            "position": position,
            "error_x": error_x,
        })

    global latest_results, latest_results_time, latest_results_seq
    with result_lock:
        latest_results = results
        latest_results_time = time.time()
        latest_results_seq += 1


def recognition_worker():
    global running
    while running:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is None:
            time.sleep(0.01)
            continue

        started = time.time()
        try:
            recognize_frame(frame)
        except Exception as error:
            print("Recognition error:", error)

        delay = RECOGNITION_INTERVAL - (time.time() - started)
        if delay > 0:
            time.sleep(delay)


worker = threading.Thread(target=recognition_worker, daemon=True)
worker.start()

print("Robot-following simulation started")
print("Target:", TARGET_PERSON)
print("Focal length:", FOCAL_LENGTH, "px")
print("Physical motor control: DISABLED")
print("Press Q or ESC to exit")

fps_start = time.time()
fps_frames = 0
display_fps = 0.0
seen_seq = 0
last_verified_time = 0.0
last_verified_box = None
last_verified_score = 0.0
tracker = None
tracker_ok = False
tracker_box = None
last_verified_position = "SEARCH"

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            safe_command = safety_controller.process(False, "STOP", None, False)
            motor_controller.execute(safe_command)
            print("Camera read failed; STOP command issued.")
            break

        now = time.time()
        with frame_lock:
            latest_frame = frame.copy()

        fps_frames += 1
        elapsed = now - fps_start
        if elapsed >= 1.0:
            display_fps = fps_frames / elapsed
            fps_frames = 0
            fps_start = now

        with result_lock:
            results = list(latest_results)
            result_time = latest_results_time
            result_seq = latest_results_seq

        # Only new recognition results may refresh identity verification.
        new_recognition_result = result_seq != seen_seq
        if new_recognition_result:
            seen_seq = result_seq
            candidates = [r for r in results if r["person"] == TARGET_PERSON]
            if candidates:
                candidate = max(
                    candidates,
                    key=lambda r: (r["bbox"][2] - r["bbox"][0])
                    * (r["bbox"][3] - r["bbox"][1]),
                )
                new_box = candidate["bbox"]
                new_center = (
                    (new_box[0] + new_box[2]) // 2,
                    (new_box[1] + new_box[3]) // 2,
                )

                # Reinitialize on every verified detection to correct drift.
                # If a detector result jumps implausibly, don't trust the old tracker.
                if last_verified_box is not None:
                    old_center = (
                        (last_verified_box[0] + last_verified_box[2]) // 2,
                        (last_verified_box[1] + last_verified_box[3]) // 2,
                    )
                    shift = float(np.hypot(
                        new_center[0] - old_center[0],
                        new_center[1] - old_center[1],
                    ))
                    if shift > MAX_TRACK_SHIFT_PER_UPDATE:
                        tracker = None
                        tracker_ok = False

                last_verified_box = new_box
                last_verified_time = result_time
                last_verified_score = candidate["score"]
                last_verified_position = candidate["position"]

                x1, y1, x2, y2 = new_box
                box_w, box_h = x2 - x1, y2 - y1
                if MIN_FACE_WIDTH <= box_w <= MAX_FACE_WIDTH and box_h > 0:
                    try:
                        tracker = cv2.TrackerCSRT_create()
                        tracker.init(frame, (x1, y1, box_w, box_h))
                        tracker_ok = True
                        tracker_box = new_box
                    except cv2.error:
                        tracker = None
                        tracker_ok = False
                else:
                    tracker = None
                    tracker_ok = False
            else:
                # Do not extend verification on a non-target/unknown result.
                pass

        # CSRT may smooth position between recognition passes; fresh ArcFace boxes
        # re-anchor it frequently to prevent long-term drift.
        if tracker is not None and tracker_ok:
            try:
                ok, box = tracker.update(frame)
                if ok:
                    x, y, box_w, box_h = [int(v) for v in box]
                    if (
                        MIN_FACE_WIDTH <= box_w <= MAX_FACE_WIDTH
                        and box_h > 0
                        and 0 <= x < frame.shape[1]
                        and 0 <= y < frame.shape[0]
                    ):
                        tracker_box = (
                            x, y,
                            min(frame.shape[1], x + box_w),
                            min(frame.shape[0], y + box_h),
                        )
                    else:
                        tracker_ok = False
                else:
                    tracker_ok = False
            except cv2.error:
                tracker_ok = False

        verification_age = now - last_verified_time if last_verified_time else float("inf")
        target_fresh = last_verified_time > 0 and verification_age <= VERIFICATION_MAX_AGE

        target_box = None
        target_distance = None
        target_zone = "UNKNOWN"
        target_command = "STOP"
        target_position = "SEARCH"
        target_x = 0
        target_error = 0

        if target_fresh and last_verified_box is not None:
            # Prefer latest verified face box over tracker box to avoid drift.
            # Tracker is only a short-term visual fallback, not identity evidence.
            box = (
                last_verified_box
                if new_recognition_result
                else (tracker_box if tracker_ok and tracker_box is not None else last_verified_box)
            )
            # Use tracker for display/position only when it is close to last verified box.
            if tracker_ok and tracker_box is not None:
                bx1, by1, bx2, by2 = tracker_box
                vx1, vy1, vx2, vy2 = last_verified_box
                verified_cx, verified_cy = (vx1 + vx2) // 2, (vy1 + vy2) // 2
                tracked_cx, tracked_cy = (bx1 + bx2) // 2, (by1 + by2) // 2
                if np.hypot(tracked_cx - verified_cx, tracked_cy - verified_cy) < 70:
                    box = tracker_box
                else:
                    box = last_verified_box
                    tracker = None
                    tracker_ok = False

            x1, y1, x2, y2 = box
            face_width = x2 - x1
            target_x = (x1 + x2) // 2
            target_error = target_x - frame.shape[1] // 2
            target_position = (
                "LEFT" if target_error < -CENTER_TOLERANCE
                else "RIGHT" if target_error > CENTER_TOLERANCE
                else "CENTER"
            )
            target_distance = calculate_distance(face_width)
            target_zone = get_distance_zone(target_distance)
            target_command = get_movement_command(target_position, target_distance)
            target_box = box

            # Fail safe: only issue movement when the last fresh recognition
            # result itself verified Person_B. Tracker output alone cannot do this.
            if verification_age <= RECOGNITION_INTERVAL * 2.5:
                safe_command = safety_controller.process(
                    True, target_command, target_distance, True
                )
            else:
                safe_command = safety_controller.process(
                    False, "STOP", None, True
                )
        else:
            last_verified_time = 0.0
            last_verified_box = None
            tracker = None
            tracker_ok = False
            tracker_box = None
            distance_history.clear()
            safe_command = safety_controller.process(False, "SEARCH", None, True)

        motor_state = motor_controller.execute(safe_command)

        for result in results:
            x1, y1, x2, y2 = result["bbox"]
            if result["person"] == TARGET_PERSON:
                color = (0, 255, 0)
                label = f"VERIFIED: {TARGET_PERSON} {result['score']:.3f}"
            elif result["person"] == "Unknown":
                color = (0, 0, 255)
                label = f"Unknown {result['score']:.3f}"
            else:
                color = (255, 0, 255)
                label = f"{result['person']} {result['score']:.3f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame, label, (x1, max(25, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2,
            )

        if target_box is not None:
            x1, y1, x2, y2 = target_box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(
                frame, "TRACKED Person_B", (x1, min(y2 + 22, frame.shape[0] - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2,
            )

        height, width = frame.shape[:2]
        cv2.line(frame, (width // 2, 0), (width // 2, height), (255, 255, 0), 1)
        distance_text = f"{target_distance:.1f} cm" if target_distance is not None else "---"
        status = "TARGET VERIFIED" if target_box is not None and verification_age <= RECOGNITION_INTERVAL * 2.5 else "TARGET NOT VERIFIED - STOP"
        status_color = (0, 255, 0) if status == "TARGET VERIFIED" else (0, 0, 255)

        overlay = [
            f"Target: {TARGET_PERSON}",
            f"Position: {target_position}",
            f"Target X: {target_x}  Error X: {target_error}",
            f"Distance: {distance_text}",
            f"Zone: {target_zone}",
            f"Faces: {len(results)}  FPS: {display_fps:.1f}",
            f"Decision: {target_command}",
            f"SAFE COMMAND: {safe_command}",
            f"L MOTOR: {motor_state['left_direction']} {motor_state['left_speed']}%",
            f"R MOTOR: {motor_state['right_direction']} {motor_state['right_speed']}%",
            f"Verification age: {verification_age:.2f}s",
        ]
        for index, text in enumerate(overlay):
            cv2.putText(
                frame, text, (15, 24 + index * 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2,
            )

        cv2.putText(
            frame, status, (15, height - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.58, status_color, 2,
        )
        cv2.imshow("Person_B Robot Following Simulation", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        try:
            if cv2.getWindowProperty(
                "Person_B Robot Following Simulation", cv2.WND_PROP_VISIBLE
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
