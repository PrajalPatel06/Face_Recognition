import pickle
import sys

import cv2
import numpy as np
from insightface.app import FaceAnalysis

DATABASE_FILE = "embeddings/database_embeddings.pkl"
THRESHOLD = 0.45

with open(DATABASE_FILE, "rb") as file:
    database = pickle.load(file)

print("Database loaded successfully")
print("People:", list(database.keys()))

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

if len(faces) == 0:
    print("No face detected")
    sys.exit()

for face in faces:

    query_embedding = face.embedding.astype(np.float32)
    query_embedding = query_embedding / np.linalg.norm(query_embedding)

    best_person = "Unknown"
    best_score = -1.0

    print("\nSimilarity Scores")
    print("----------------")

    for person_name, embeddings in database.items():

        for index, reference_embedding in enumerate(embeddings):

            reference_embedding = np.asarray(
                reference_embedding,
                dtype=np.float32
            )

            reference_embedding = (
                reference_embedding /
                np.linalg.norm(reference_embedding)
            )

            score = float(
                np.dot(query_embedding, reference_embedding)
            )

            print(
                f"{person_name} image {index + 1}: "
                f"{score:.10f}"
            )

            if score > best_score:
                best_score = score
                best_person = person_name

    if best_score >= THRESHOLD:
        status = "Potential Match"
    else:
        best_person = "Unknown"
        status = "Unknown"

    print("\nRecognition Result")
    print("------------------")
    print("Candidate:", best_person)
    print("Similarity:", f"{best_score:.10f}")
    print("Status:", status)

    x1, y1, x2, y2 = face.bbox.astype(int)

    cv2.rectangle(
        image,
        (x1, y1),
        (x2, y2),
        (0, 255, 0),
        2
    )

    label = f"{best_person} | {best_score:.6f}"

    cv2.putText(
        image,
        label,
        (x1, max(y1 - 10, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2
    )

cv2.imshow("Recognition Test", image)
cv2.waitKey(0)
cv2.destroyAllWindows()