import sys

import cv2

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Camera could not be opened")
    sys.exit()

print("Press S to capture your face")
print("Press Q to quit")

while True:
    ret, frame = cap.read()

    if not ret:
        print("Failed to read frame")
        break

    cv2.imshow("Capture Face", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("s"):
        cv2.imwrite("test_face.jpg", frame)
        print("Face image saved as test_face.jpg")
        break

    if key == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()