
import os
import cv2
import time
from pathlib import Path

_nvidia_root = Path(__file__).resolve().parent / ".venv" / "Lib" / "site-packages" / "nvidia"
_dll_handles = []

for _dll_folder in _nvidia_root.glob("*/bin"):
    _dll_path = str(_dll_folder.resolve())
    os.environ["PATH"] = _dll_path + os.pathsep + os.environ["PATH"]
    _dll_handles.append(os.add_dll_directory(_dll_path))

import onnxruntime as ort
from insightface.app import FaceAnalysis

CAMERA_INDEX = 0
FRAME_COUNT = 30

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

if not cap.isOpened():
    cap.release()
    cap = cv2.VideoCapture(CAMERA_INDEX)

if not cap.isOpened():
    print("ERROR: Could not open webcam.")
    print("Check that the webcam is connected and not being used by another app.")
    raise SystemExit(1)

print("Opening camera:", cap.isOpened())

app = ort.preload_dlls(directory="")

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
)

app.prepare(ctx_id=0, det_size=(320, 320))  

count = 0
start = time.perf_counter()

print(f"Running {FRAME_COUNT}-frame benchmark...")

try:
    while count < FRAME_COUNT:
        ret, frame = cap.read()

        if not ret:
            print("Camera read failed.")
            break

        app.get(frame)
        count += 1
finally:
    elapsed = time.perf_counter() - start
    cap.release()

print(f"Frames: {count}")
print(f"Time: {elapsed:.2f} sec")

if elapsed > 0:
    print(f"Processing FPS: {count / elapsed:.2f}")
else:
    print("Processing FPS: unavailable (elapsed time was zero).")

if count == 0:
    raise SystemExit(1)
print("Detection providers:", app.models["detection"].session.get_providers())
print("Recognition providers:", app.models["recognition"].session.get_providers())