import cv2

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
print("Camera opened:", cap.isOpened())

if cap.isOpened():
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame")
            break

        cv2.imshow("Live Webcam Test", frame)

        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
            break

cap.release()
cv2.destroyAllWindows()
