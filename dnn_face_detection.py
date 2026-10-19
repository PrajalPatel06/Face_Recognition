import sys

import cv2
import numpy as np

PROTOTXT = "models/deploy.prototxt"
MODEL = "models/res10_300x300_ssd_iter_140000.caffemodel"

net = cv2.dnn.readNetFromCaffe(PROTOTXT, MODEL)

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Camera could not be opened")
    sys.exit()

print("DNN face detection started. Press Q to quit.")

while True:
    ret, frame = cap.read()

    if not ret:
        print("Failed to read frame")
        break

    height, width = frame.shape[:2]

    blob = cv2.dnn.blobFromImage(
        frame,
        1.0,
        (300, 300),
        (104.0, 177.0, 123.0)
    )

    net.setInput(blob)
    detections = net.forward()

    face_count = 0

    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]

        if confidence < 0.60:
            continue

        box = detections[0, 0, i, 3:7] * np.array(
            [width, height, width, height]
        )

        start_x, start_y, end_x, end_y = box.astype(int)

        start_x = max(0, start_x)
        start_y = max(0, start_y)
        end_x = min(width - 1, end_x)
        end_y = min(height - 1, end_y)

        face_count += 1

        cv2.rectangle(
            frame,
            (start_x, start_y),
            (end_x, end_y),
            (0, 255, 0),
            2
        )

        label = f"Face {face_count}: {confidence:.2f}"

        cv2.putText(
            frame,
            label,
            (start_x, max(start_y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2
        )

    cv2.putText(
        frame,
        f"Faces: {face_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )

    cv2.imshow("DNN Face Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()