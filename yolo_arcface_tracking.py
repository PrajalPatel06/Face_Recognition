
import pickle
import time

import cv2
import numpy as np
from ultralytics import YOLO
from insightface.app import FaceAnalysis

DATABASE_FILE = "embeddings/database_embeddings.pkl"
YOLO_MODEL = "yolov8n.pt"

TARGET_PERSON = "Person_B"
RECOGNITION_THRESHOLD = 0.45
CAMERA_INDEX = 0

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
YOLO_CONFIDENCE = 0.40
YOLO_IMAGE_SIZE = 320
CENTER_TOLERANCE = 80

print("Loading face database...")

with open(DATABASE_FILE, "rb") as file:
    database = pickle.load(file)

print("Registered people:", list(database.keys()))
print("Target person:", TARGET_PERSON)

print("Loading YOLO...")

yolo = YOLO(YOLO_MODEL)

print("Loading InsightFace...")

face_app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

face_app.prepare(
    ctx_id=-1,
    det_size=(320, 320)
)

print("Models loaded successfully.")

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("ERROR: Could not open camera.")
    cap.release()
    raise SystemExit(1)


def recognize_face(face):
    embedding = np.asarray(face.embedding, dtype=np.float32)
    norm = np.linalg.norm(embedding)

    if norm <= 1e-12:
        return "Unknown", -1.0

    embedding /= norm

    best_person = "Unknown"
    best_score = -1.0

    for person_name, reference_embeddings in database.items():
        for reference in reference_embeddings:
            reference = np.asarray(reference, dtype=np.float32)
            reference_norm = np.linalg.norm(reference)

            if reference_norm <= 1e-12:
                continue

            reference = reference / reference_norm
            score = float(np.dot(embedding, reference))

            if score > best_score:
                best_score = score
                best_person = person_name

    if best_score < RECOGNITION_THRESHOLD:
        return "Unknown", best_score

    return best_person, best_score


def intersection_over_face(face_box, person_box):
    fx1, fy1, fx2, fy2 = face_box
    px1, py1, px2, py2 = person_box

    center_x = (fx1 + fx2) / 2
    center_y = (fy1 + fy2) / 2

    return (
        px1 <= center_x <= px2
        and py1 <= center_y <= py2
    )


previous_time = time.time()
fps = 0.0

print("YOLO + ArcFace tracking started.")
print("Motor control is disabled.")
print("Press Q or ESC to quit.")

try:
    while True:
        ret, frame = cap.read()

        if not ret:
            print("Camera read failed.")
            break

        height, width = frame.shape[:2]
        frame_center_x = width // 2

        yolo_result = yolo.predict(
            source=frame,
            classes=[0],
            conf=YOLO_CONFIDENCE,
            imgsz=YOLO_IMAGE_SIZE,
            verbose=False
        )[0]

        person_boxes = []

        if yolo_result.boxes is not None:
            for box in yolo_result.boxes:
                coords = tuple(
                    int(v)
                    for v in box.xyxy[0].cpu().numpy()
                )
                person_boxes.append(coords)

                x1, y1, x2, y2 = coords
                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (255, 160, 0),
                    2
                )

                cv2.putText(
                    frame,
                    "YOLO Person",
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 160, 0),
                    2
                )

        faces = face_app.get(frame)

        recognized_targets = []

        for face in faces:
            fx1, fy1, fx2, fy2 = map(
                int,
                face.bbox
            )

            if fx2 <= fx1 or fy2 <= fy1:
                continue

            person, score = recognize_face(face)

            associated = any(
                intersection_over_face(
                    (fx1, fy1, fx2, fy2),
                    person_box
                )
                for person_box in person_boxes
            )

            if person == TARGET_PERSON and associated:
                color = (0, 255, 0)
                label = f"TARGET {person} {score:.3f}"

                center_x = (fx1 + fx2) // 2
                error_x = center_x - frame_center_x

                if error_x < -CENTER_TOLERANCE:
                    position = "LEFT"
                elif error_x > CENTER_TOLERANCE:
                    position = "RIGHT"
                else:
                    position = "CENTER"

                recognized_targets.append({
                    "bbox": (fx1, fy1, fx2, fy2),
                    "center_x": center_x,
                    "position": position,
                    "score": score
                })

            elif person == "Unknown":
                color = (0, 0, 255)
                label = f"Unknown {score:.3f}"

            else:
                color = (255, 0, 255)
                label = f"{person} {score:.3f}"

            cv2.rectangle(
                frame,
                (fx1, fy1),
                (fx2, fy2),
                color,
                2
            )

            cv2.putText(
                frame,
                label,
                (fx1, max(20, fy1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2
            )

        if recognized_targets:
            target = max(
                recognized_targets,
                key=lambda item: (
                    item["bbox"][2] - item["bbox"][0]
                ) * (
                    item["bbox"][3] - item["bbox"][1]
                )
            )

            status = "TARGET VERIFIED"
            position = target["position"]
            target_x = target["center_x"]
            target_score = target["score"]
            status_color = (0, 255, 0)

        else:
            status = "NO VERIFIED TARGET - STOP"
            position = "SEARCH"
            target_x = -1
            target_score = 0.0
            status_color = (0, 0, 255)

        current_time = time.time()
        elapsed = current_time - previous_time

        if elapsed > 0:
            fps = 1.0 / elapsed

        previous_time = current_time

        cv2.line(
            frame,
            (frame_center_x, 0),
            (frame_center_x, height),
            (255, 255, 0),
            1
        )

        cv2.putText(
            frame,
            f"People: {len(person_boxes)}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Faces: {len(faces)}",
            (15, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Target: {TARGET_PERSON}",
            (15, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Position: {position}",
            (15, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 0),
            2
        )

        cv2.putText(
            frame,
            f"Target X: {target_x}",
            (15, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Score: {target_score:.3f}",
            (15, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Loop FPS: {fps:.1f}",
            (15, 210),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            status,
            (15, height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            status_color,
            2
        )

        cv2.imshow(
            "YOLO + ArcFace Target Verification",
            frame
        )

        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), 27):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    print("YOLO + ArcFace tracking stopped.")
 