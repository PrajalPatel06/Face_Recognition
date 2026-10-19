import sys

import cv2
import numpy as np
from insightface.app import FaceAnalysis

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(ctx_id=-1)

image = cv2.imread("test_face.jpg")

if image is None:
    print("Could not read test_face.jpg")
    sys.exit()

faces = app.get(image)

print("Faces detected:", len(faces))

for i, face in enumerate(faces):
    embedding = face.embedding

    print(f"\nFace {i + 1}")
    print("Bounding box:", face.bbox)
    print("Embedding shape:", embedding.shape)
    print("Embedding dimension:", len(embedding))
    print("Embedding norm:", np.linalg.norm(embedding))

cv2.imshow("InsightFace Test", image)
cv2.waitKey(0)
cv2.destroyAllWindows()