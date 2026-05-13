#!/usr/bin/env python3
"""Auto-crop the avatar photo to a face-centered headshot for SadTalker."""

import os
import sys
from pathlib import Path

AVATAR_DIR = Path(__file__).parent
PHOTO_IN = AVATAR_DIR / "photo.jpg"
PHOTO_OUT = AVATAR_DIR / "photo_cropped.jpg"


def crop_face(input_path: Path, output_path: Path, padding: float = 0.5):
    try:
        import cv2
    except ImportError:
        print("Error: opencv not installed. Run: pip install opencv-python")
        sys.exit(1)

    img = cv2.imread(str(input_path))
    if img is None:
        print(f"Error: Could not read {input_path}")
        sys.exit(1)

    h, w = img.shape[:2]

    # Try DNN face detector first (more accurate)
    face_box = None
    prototxt = cv2.data.haarcascades + "/../dnn/opencv_face_detector.pbtxt"
    model = cv2.data.haarcascades + "/../dnn/opencv_face_detector_uint8.pb"

    try:
        if os.path.exists(prototxt) and os.path.exists(model):
            net = cv2.dnn.readNet(model, prototxt)
            blob = cv2.dnn.blobFromImage(img, 1.0, (300, 300), (104, 117, 123))
            net.setInput(blob)
            detections = net.forward()
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.5:
                    x1 = int(detections[0, 0, i, 3] * w)
                    y1 = int(detections[0, 0, i, 4] * h)
                    x2 = int(detections[0, 0, i, 5] * w)
                    y2 = int(detections[0, 0, i, 6] * h)
                    face_box = (x1, y1, x2 - x1, y2 - y1)
                    break
    except Exception:
        pass

    # Fallback: Haar cascade
    if not face_box:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) > 0:
            # Pick largest face
            face_box = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]

    if face_box is None:
        print("Warning: No face detected. Cropping center of image instead.")
        # Crop top-center portion (where a face usually is in a portrait)
        crop_h = int(h * 0.45)
        crop_w = min(crop_h, w)
        x = (w - crop_w) // 2
        cropped = img[0:crop_h, x:x + crop_w]
    else:
        fx, fy, fw, fh = face_box
        # Add generous padding around the face
        pad_x = int(fw * padding)
        pad_y = int(fh * padding * 1.5)  # more padding above for forehead

        x1 = max(0, fx - pad_x)
        y1 = max(0, fy - pad_y)
        x2 = min(w, fx + fw + pad_x)
        y2 = min(h, fy + fh + pad_y)
        cropped = img[y1:y2, x1:x2]

    # Resize to 512x512 (SadTalker's preferred input size)
    resized = cv2.resize(cropped, (512, 512), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(output_path), resized, [cv2.IMWRITE_JPEG_QUALITY, 95])

    print(f"Cropped photo saved: {output_path}")
    print(f"Original: {w}x{h} -> Cropped: 512x512")
    print(f"\nUpdate avatar/config.json to use: photo_cropped.jpg")


def main():
    if not PHOTO_IN.exists():
        print(f"Error: {PHOTO_IN} not found.")
        print("Save your avatar photo to that path first.")
        sys.exit(1)

    crop_face(PHOTO_IN, PHOTO_OUT)

    # Auto-update config
    import json
    config_path = AVATAR_DIR / "config.json"
    with open(config_path) as f:
        config = json.load(f)
    config["source_photo"] = "avatar/photo_cropped.jpg"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print("Updated avatar/config.json to use cropped photo.")


if __name__ == "__main__":
    main()
