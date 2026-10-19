from ultralytics import YOLO
import cv2
import time

MODEL_NAME = "yolov8n.pt"
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
CONFIDENCE_THRESHOLD = 0.40

print("Loading YOLO model...")
model = YOLO(MODEL_NAME)
print("YOLO model loaded successfully.")

cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("ERROR: Could not open camera.")
    print("Try changing CAMERA_INDEX to 0.")
    raise SystemExit(1)

print("Camera opened. Press Q or ESC to exit.")

previous_time = time.time()
fps = 0.0

try:
    while True:
        ret, frame = cap.read()

        if not ret:
            print("ERROR: Could not read camera frame.")
            break

        results = model.predict(
            source=frame,
            classes=[0],
            conf=CONFIDENCE_THRESHOLD,
            imgsz=320,
            verbose=False
        )

        annotated_frame = results[0].plot()

        current_time = time.time()
        elapsed = current_time - previous_time

        if elapsed > 0:
            fps = 1.0 / elapsed

        previous_time = current_time

        person_count = len(results[0].boxes)

        cv2.putText(
            annotated_frame,
            f"People detected: {person_count}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2
        )

        cv2.putText(
            annotated_frame,
            f"FPS: {fps:.1f}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2
        )

        cv2.imshow("YOLO Person Detection Test", annotated_frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q") or key == 27:
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    print("YOLO test stopped.")