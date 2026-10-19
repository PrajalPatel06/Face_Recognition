import pickle
import cv2
import numpy as np
import threading
import time

from insightface.app import FaceAnalysis


# ============================================================
# CONFIGURATION
# ============================================================

DATABASE_FILE = "embeddings/database_embeddings.pkl"

TARGET_PERSON = "Person_A"

RECOGNITION_THRESHOLD = 0.45

CENTER_TOLERANCE = 80

# Recognition runs in background.
# Higher value = less CPU usage.
RECOGNITION_INTERVAL = 0.20

CAMERA_INDEX = 1

FRAME_WIDTH = 640
FRAME_HEIGHT = 480


# ============================================================
# LOAD DATABASE
# ============================================================

with open(DATABASE_FILE, "rb") as file:
    database = pickle.load(file)

print("Database loaded successfully")
print("People:", list(database.keys()))
print("Target:", TARGET_PERSON)


# ============================================================
# LOAD INSIGHTFACE
# ============================================================

print("Loading InsightFace...")

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(
    ctx_id=-1,
    det_size=(320, 320)
)

print("InsightFace ready")


# ============================================================
# CAMERA
# ============================================================

cap = cv2.VideoCapture(CAMERA_INDEX)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

# Try to reduce webcam buffering
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("ERROR: Could not open camera")
    print("Try changing CAMERA_INDEX from 0 to 1")
    exit()

print("Camera opened successfully")


# ============================================================
# SHARED VARIABLES
# ============================================================

latest_frame = None
latest_results = []

frame_lock = threading.Lock()
result_lock = threading.Lock()

running = True


# ============================================================
# RECOGNITION
# ============================================================

def recognize_frame(frame):

    global latest_results

    frame_height, frame_width = frame.shape[:2]

    frame_center_x = frame_width // 2

    faces = app.get(frame)

    results = []

    for face in faces:

        x1, y1, x2, y2 = face.bbox.astype(int)

        if x2 <= x1 or y2 <= y1:
            continue

        face_center_x = (x1 + x2) // 2
        face_center_y = (y1 + y2) // 2

        # ----------------------------------------------------
        # FACE EMBEDDING
        # ----------------------------------------------------

        query_embedding = face.embedding.astype(np.float32)

        query_norm = np.linalg.norm(query_embedding)

        if query_norm == 0:
            continue

        query_embedding = query_embedding / query_norm

        # ----------------------------------------------------
        # DATABASE MATCHING
        # ----------------------------------------------------

        best_person = "Unknown"
        best_score = -1.0

        for person_name, embeddings in database.items():

            for reference_embedding in embeddings:

                reference_embedding = np.asarray(
                    reference_embedding,
                    dtype=np.float32
                )

                reference_norm = np.linalg.norm(
                    reference_embedding
                )

                if reference_norm == 0:
                    continue

                reference_embedding = (
                    reference_embedding /
                    reference_norm
                )

                score = float(
                    np.dot(
                        query_embedding,
                        reference_embedding
                    )
                )

                score = float(
                    np.clip(score, -1.0, 1.0)
                )

                if score > best_score:
                    best_score = score
                    best_person = person_name

        # ----------------------------------------------------
        # IDENTITY
        # ----------------------------------------------------

        if best_score >= RECOGNITION_THRESHOLD:
            person = best_person
        else:
            person = "Unknown"

        # ----------------------------------------------------
        # TARGET POSITION
        # ----------------------------------------------------

        error_x = face_center_x - frame_center_x

        if person == TARGET_PERSON:

            if error_x < -CENTER_TOLERANCE:
                position = "LEFT"

            elif error_x > CENTER_TOLERANCE:
                position = "RIGHT"

            else:
                position = "CENTER"

        else:
            position = "NOT TARGET"

        # ----------------------------------------------------
        # SAVE RESULT
        # ----------------------------------------------------

        results.append(
            {
                "bbox": (x1, y1, x2, y2),
                "person": person,
                "score": best_score,
                "center_x": face_center_x,
                "center_y": face_center_y,
                "error_x": error_x,
                "position": position
            }
        )

    # Update shared result
    with result_lock:
        latest_results = results


# ============================================================
# BACKGROUND RECOGNITION WORKER
# ============================================================

def recognition_worker():

    global running

    while running:

        with frame_lock:

            if latest_frame is None:
                time.sleep(0.01)
                continue

            frame_copy = latest_frame.copy()

        start_time = time.time()

        try:

            recognize_frame(frame_copy)

        except Exception as error:

            print("Recognition error:", error)

        processing_time = time.time() - start_time

        sleep_time = (
            RECOGNITION_INTERVAL -
            processing_time
        )

        if sleep_time > 0:
            time.sleep(sleep_time)


# ============================================================
# START RECOGNITION THREAD
# ============================================================

worker = threading.Thread(
    target=recognition_worker,
    daemon=True
)

worker.start()


# ============================================================
# DISPLAY
# ============================================================

print()
print("======================================")
print("Laptop Face Recognition Started")
print("======================================")
print("Target:", TARGET_PERSON)
print("Camera:", CAMERA_INDEX)
print("Resolution:", FRAME_WIDTH, "x", FRAME_HEIGHT)
print("Recognition interval:", RECOGNITION_INTERVAL)
print()
print("Press Q or ESC to quit")
print()


display_start_time = time.time()
display_frame_count = 0
display_fps = 0.0


# ============================================================
# MAIN CAMERA LOOP
# ============================================================

while True:

    ret, frame = cap.read()

    if not ret:

        print("ERROR: Could not read camera frame")
        break

    display_frame_count += 1

    # --------------------------------------------------------
    # FPS
    # --------------------------------------------------------

    current_time = time.time()

    elapsed = current_time - display_start_time

    if elapsed >= 1.0:

        display_fps = (
            display_frame_count /
            elapsed
        )

        display_frame_count = 0

        display_start_time = current_time

    # --------------------------------------------------------
    # SHARE FRAME WITH RECOGNITION THREAD
    # --------------------------------------------------------

    with frame_lock:
        latest_frame = frame.copy()

    # --------------------------------------------------------
    # FRAME INFORMATION
    # --------------------------------------------------------

    frame_height, frame_width = frame.shape[:2]

    frame_center_x = frame_width // 2
    frame_center_y = frame_height // 2

    # --------------------------------------------------------
    # GET RECOGNITION RESULTS
    # --------------------------------------------------------

    with result_lock:
        results = list(latest_results)

    # --------------------------------------------------------
    # FIND TARGET
    # --------------------------------------------------------

    target = None

    for result in results:

        if result["person"] != TARGET_PERSON:
            continue

        if target is None:

            target = result

        else:

            current_x1, current_y1, current_x2, current_y2 = (
                result["bbox"]
            )

            target_x1, target_y1, target_x2, target_y2 = (
                target["bbox"]
            )

            current_area = (
                current_x2 - current_x1
            ) * (
                current_y2 - current_y1
            )

            target_area = (
                target_x2 - target_x1
            ) * (
                target_y2 - target_y1
            )

            if current_area > target_area:
                target = result

    # --------------------------------------------------------
    # DRAW FACE RESULTS
    # --------------------------------------------------------

    for result in results:

        x1, y1, x2, y2 = result["bbox"]

        person = result["person"]

        score = result["score"]

        center_x = result["center_x"]
        center_y = result["center_y"]

        position = result["position"]

        # Target
        if person == TARGET_PERSON:

            box_color = (0, 255, 0)

            label = (
                f"TARGET: {person} | "
                f"{score:.3f}"
            )

        # Unknown
        elif person == "Unknown":

            box_color = (0, 0, 255)

            label = (
                f"Unknown | "
                f"{score:.3f}"
            )

        # Other known person
        else:

            box_color = (255, 0, 255)

            label = (
                f"{person} | "
                f"{score:.3f}"
            )

        # Bounding box
        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            box_color,
            2
        )

        # Center point
        cv2.circle(
            frame,
            (center_x, center_y),
            5,
            (255, 255, 0),
            -1
        )

        # Name
        cv2.putText(
            frame,
            label,
            (x1, max(y1 - 10, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            box_color,
            2
        )

        # Position
        if person == TARGET_PERSON:

            cv2.putText(
                frame,
                position,
                (x1, y2 + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

    # --------------------------------------------------------
    # CENTER CROSSHAIR
    # --------------------------------------------------------

    cv2.line(
        frame,
        (frame_center_x, 0),
        (frame_center_x, frame_height),
        (255, 255, 0),
        2
    )

    cv2.line(
        frame,
        (0, frame_center_y),
        (frame_width, frame_center_y),
        (255, 255, 0),
        1
    )

    # --------------------------------------------------------
    # TARGET STATUS
    # --------------------------------------------------------

    if target is not None:

        target_position = target["position"]

        target_error = target["error_x"]

        target_score = target["score"]

        target_x = target["center_x"]

        status = "TARGET FOUND"

        status_color = (0, 255, 0)

    else:

        target_position = "SEARCH"

        target_error = 0

        target_score = 0

        target_x = 0

        status = "TARGET LOST"

        status_color = (0, 0, 255)

    # --------------------------------------------------------
    # INFORMATION PANEL
    # --------------------------------------------------------

    cv2.putText(
        frame,
        f"Target: {TARGET_PERSON}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Position: {target_position}",
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Target X: {target_x}",
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Error X: {target_error}",
        (20, 135),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Faces: {len(results)}",
        (20, 170),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Recognition: {target_score:.3f}",
        (20, 205),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        f"Display FPS: {display_fps:.1f}",
        (20, 240),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )

    cv2.putText(
        frame,
        status,
        (20, 275),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        status_color,
        2
    )

    # --------------------------------------------------------
    # SHOW
    # --------------------------------------------------------

    cv2.imshow(
        "Laptop Face Recognition + Target Tracking",
        frame
    )

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q") or key == 27:
        running = False
        break


# ============================================================
# CLEANUP
# ============================================================

running = False

time.sleep(0.2)

cap.release()

cv2.destroyAllWindows()

cv2.waitKey(1)

print("System stopped")