import sys
import time
import threading

import cv2
from insightface.app import FaceAnalysis

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)
app.prepare(ctx_id=-1, det_size=(320, 320))

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("Could not open camera")
    sys.exit(1)

frame_lock = threading.Lock()
result_lock = threading.Lock()

latest_frame = None
latest_results = []
running = True


def detection_worker():
    global latest_results

    last_processed = None

    while running:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None

        if frame is None:
            time.sleep(0.01)
            continue

        start = time.perf_counter()
        faces = app.get(frame)

        results = []
        for face in faces:
            x1, y1, x2, y2 = face.bbox.astype(int)
            results.append((x1, y1, x2, y2))

        with result_lock:
            latest_results = results

        elapsed = time.perf_counter() - start
        time.sleep(max(0.01, 0.15 - elapsed))


print("Multi-face detection test started")
print("Press Q or ESC to quit")

worker = threading.Thread(target=detection_worker, daemon=True)
worker.start()

fps_start = time.perf_counter()
fps_frames = 0
display_fps = 0.0

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        with frame_lock:
            latest_frame = frame.copy()

        with result_lock:
            results = list(latest_results)

        for i, (x1, y1, x2, y2) in enumerate(results):
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"Face {i + 1}",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

        cv2.putText(
            frame,
            f"Faces: {len(results)}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
        )

        fps_frames += 1
        elapsed = time.perf_counter() - fps_start
        if elapsed >= 1.0:
            display_fps = fps_frames / elapsed
            fps_frames = 0
            fps_start = time.perf_counter()

        cv2.putText(
            frame,
            f"Display FPS: {display_fps:.1f}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2,
        )

        cv2.imshow("Multi Face Detection Test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break

finally:
    running = False
    worker.join(timeout=2.0)
    cap.release()
    cv2.destroyAllWindows()