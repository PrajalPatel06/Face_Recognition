import cv2
import time
from insightface.app import FaceAnalysis

cap = cv2.VideoCapture("/dev/video0")

print("Opening camera:", cap.isOpened())

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(ctx_id=-1, det_size=(160, 160))

count = 0
start = time.time()

print("Running 30-frame benchmark...")

while count < 30:
    ret, frame = cap.read()

    if not ret:
        print("Camera read failed")
        break

    app.get(frame)
    count += 1

elapsed = time.time() - start

print(f"Frames: {count}")
print(f"Time: {elapsed:.2f} sec")
print(f"Processing FPS: {count / elapsed:.2f}")

cap.release()