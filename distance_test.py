import sys
import threading
import time
from collections import deque

import cv2
import numpy as np
from insightface.app import FaceAnalysis

KNOWN_DISTANCE_CM = 100.0
KNOWN_FACE_WIDTH_CM = 15.0

DETECTION_INTERVAL = 0.15

SMOOTHING_SAMPLES = 5


app = FaceAnalysis(
    name="buffalo_l",
    allowed_modules=["detection"],
    providers=["CPUExecutionProvider"]
)

app.prepare(
    ctx_id=-1,
    det_size=(320, 320)
)


cap = cv2.VideoCapture(0)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    print("Could not open camera")
    sys.exit()


latest_frame = None
latest_bbox = None

frame_lock = threading.Lock()
result_lock = threading.Lock()

running = True

focal_length = None

distance_history = deque(
    maxlen=SMOOTHING_SAMPLES
)


def detect_face(frame):

    global latest_bbox

    faces = app.get(frame)

    if len(faces) == 0:

        with result_lock:
            latest_bbox = None

        return


    face = max(
        faces,
        key=lambda x:
        (x.bbox[2] - x.bbox[0]) *
        (x.bbox[3] - x.bbox[1])
    )


    x1, y1, x2, y2 = face.bbox.astype(int)

    face_width = x2 - x1

    if face_width <= 0:

        with result_lock:
            latest_bbox = None

        return


    with result_lock:

        latest_bbox = (
            x1,
            y1,
            x2,
            y2
        )


def detection_worker():

    global running  # noqa: PLW0602

    while running:

        with frame_lock:

            if latest_frame is None:
                time.sleep(0.01)
                continue

            frame_copy = latest_frame.copy()


        start_time = time.time()


        try:

            detect_face(frame_copy)

        except Exception as error:  # noqa: BLE001

            print("Detection error:", error)


        processing_time = time.time() - start_time

        sleep_time = DETECTION_INTERVAL - processing_time

        if sleep_time > 0:

            time.sleep(sleep_time)


worker = threading.Thread(
    target=detection_worker,
    daemon=True
)

worker.start()


print()
print("Fast distance estimation started")
print("--------------------------------")
print("Stand exactly 100 cm from camera")
print("Press C to calibrate")
print("Press Q or ESC to quit")
print()


fps_start = time.time()
fps_frames = 0
display_fps = 0


while True:

    ret, frame = cap.read()

    if not ret:

        print("Could not read camera")
        break


    fps_frames += 1

    current_time = time.time()

    fps_elapsed = current_time - fps_start


    if fps_elapsed >= 1.0:

        display_fps = fps_frames / fps_elapsed

        fps_frames = 0

        fps_start = current_time


    with frame_lock:

        latest_frame = frame.copy()


    frame_height, frame_width = frame.shape[:2]


    with result_lock:

        bbox = latest_bbox


    distance_cm = None


    if bbox is not None:

        x1, y1, x2, y2 = bbox

        face_width = x2 - x1

        face_center_x = (x1 + x2) // 2

        face_center_y = (y1 + y2) // 2


        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )


        cv2.circle(
            frame,
            (face_center_x, face_center_y),
            5,
            (255, 0, 0),
            -1
        )


        cv2.putText(
            frame,
            f"Face width: {face_width}px",
            (x1, max(y1 - 10, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )


        if focal_length is not None and face_width > 0:

            raw_distance = (
                KNOWN_FACE_WIDTH_CM *
                focal_length /
                face_width
            )


            distance_history.append(
                raw_distance
            )


            distance_cm = float(
                np.median(
                    distance_history
                )
            )


            cv2.putText(
                frame,
                f"Distance: {distance_cm:.1f} cm",
                (x1, y2 + 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2
            )


    cv2.putText(
        frame,
        "DISTANCE TEST",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )


    if focal_length is None:

        instruction = (
            "Stand 100 cm away and press C"
        )

        instruction_color = (0, 255, 255)

    else:

        instruction = (
            "Calibration complete"
        )

        instruction_color = (0, 255, 0)


    cv2.putText(
        frame,
        instruction,
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        instruction_color,
        2
    )


    cv2.putText(
        frame,
        f"FPS: {display_fps:.1f}",
        (20, 105),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )


    if focal_length is not None:

        cv2.putText(
            frame,
            f"Focal length: {focal_length:.1f}",
            (20, 140),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2
        )


    cv2.imshow(
        "Fast Distance Test",
        frame
    )


    key = cv2.waitKey(1) & 0xFF


    if key == ord("c"):

        with result_lock:

            calibration_bbox = latest_bbox


        if calibration_bbox is not None:

            x1, y1, x2, y2 = calibration_bbox

            measured_width = x2 - x1


            if measured_width > 0:

                focal_length = (
                    measured_width *
                    KNOWN_DISTANCE_CM /
                    KNOWN_FACE_WIDTH_CM
                )


                distance_history.clear()


                print()
                print("Calibration complete")
                print("--------------------")
                print(
                    f"Measured face width: "
                    f"{measured_width} pixels"
                )
                print(
                    f"Focal length: "
                    f"{focal_length:.2f}"
                )
                print()


        else:

            print(
                "No face detected. "
                "Try again."
            )


    if key == ord("q") or key == 27:

        running = False
        break


    try:

        visible = cv2.getWindowProperty(
            "Fast Distance Test",
            cv2.WND_PROP_VISIBLE
        )

        if visible < 1:

            running = False
            break

    except:  # noqa: E722

        running = False
        break


running = False

time.sleep(0.2)

cap.release()

cv2.destroyAllWindows()

cv2.waitKey(1)

print("Distance test stopped")