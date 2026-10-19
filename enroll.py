import os
import pickle

import cv2
import numpy as np
from insightface.app import FaceAnalysis

DATABASE_PATH = "database"
OUTPUT_FILE = "embeddings/database_embeddings.pkl"

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(ctx_id=-1)

database = {}

for person_name in os.listdir(DATABASE_PATH):
    person_path = os.path.join(DATABASE_PATH, person_name)

    if not os.path.isdir(person_path):
        continue

    embeddings = []

    for image_name in os.listdir(person_path):
        image_path = os.path.join(person_path, image_name)

        image = cv2.imread(image_path)

        if image is None:
            continue

        faces = app.get(image)

        if len(faces) == 0:
            print(f"No face found: {image_path}")
            continue

        face = max(
            faces,
            key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])
        )

        embedding = face.embedding.astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        embeddings.append(embedding)

        print(f"Processed: {image_path}")

    if embeddings:
        database[person_name] = embeddings
        print(f"{person_name}: {len(embeddings)} embedding(s)")

os.makedirs("embeddings", exist_ok=True)

with open(OUTPUT_FILE, "wb") as file:
    pickle.dump(database, file)

print("\nDatabase created successfully.")
print(f"Saved to: {OUTPUT_FILE}")
print(f"People enrolled: {len(database)}")