import threading
from collections import Counter
from pathlib import Path
import sys
import os
import re

_PIPELINE = None
_PIPELINE_LOCK = threading.Lock()


def _ensure_runtime_site_packages_on_path() -> None:
    """
    This repo ships a self-contained Python runtime under `runtime/site-packages`.
    In some environments the virtualenv is missing dependencies (e.g. `certifi`),
    which breaks `transformers` / `huggingface_hub` imports. Add the runtime
    site-packages to sys.path as a fallback.
    """

    runtime_site_packages = Path(__file__).resolve().parents[1] / "runtime" / "site-packages"
    runtime_site_packages_str = str(runtime_site_packages)

    if runtime_site_packages.exists() and runtime_site_packages_str not in sys.path:
        # Always insert at the front so transformers/huggingface_hub resolve from the same place.
        sys.path.insert(0, runtime_site_packages_str)

        # If these were already imported from elsewhere, we can end up mixing
        # `transformers` from runtime with `huggingface_hub` from the venv.
        # Clear them so the next import is consistent.
        prefixes = ("huggingface_hub", "transformers", "httpx", "httpcore", "certifi")
        for name in list(sys.modules.keys()):
            if name == "certifi" or name.startswith(prefixes):
                sys.modules.pop(name, None)


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_BAD_LOCAL_PROXY_RE = re.compile(r"(?i)(?:^|//)(?:localhost|127\.0\.0\.1):9\b")


def _clear_known_bad_proxy_env() -> None:
    """
    Many locked-down Windows dev environments inject a non-working local proxy
    (commonly 127.0.0.1:9), which breaks Hugging Face downloads.
    """

    for key in _PROXY_ENV_KEYS:
        value = (os.environ.get(key) or "").strip()
        if value and _BAD_LOCAL_PROXY_RE.search(value):
            os.environ.pop(key, None)


def _disable_huggingface_progress_bars():
    # Transformers uses tqdm-based progress bars while loading weights. In some
    # server/logging setups on Windows, writing/flushing stderr can raise:
    # OSError: [Errno 22] Invalid argument. Disabling progress bars avoids that.
    import os

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
    except Exception:
        # Best-effort: if transformers isn't importable yet (or API changed),
        # continue and let the caller surface the real error.
        pass


def _get_emotion_pipeline():
    _disable_huggingface_progress_bars()
    _ensure_runtime_site_packages_on_path()
    _clear_known_bad_proxy_env()

    # Ensure HF cache is writable (some corporate Windows images lock %USERPROFILE%\\.cache).
    cache_root = os.environ.get("ATS_HF_HOME", "").strip()
    if not cache_root:
        cache_root = str((Path(__file__).resolve().parents[1] / "hf_cache").resolve())
    try:
        os.makedirs(cache_root, exist_ok=True)
        os.environ["HF_HOME"] = cache_root
        os.environ["TRANSFORMERS_CACHE"] = os.path.join(cache_root, "transformers")
    except Exception:
        pass

    from transformers import pipeline

    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None:
            model_id = os.environ.get("ATS_HF_EMOTION_MODEL", "trpakov/vit-face-expression").strip()
            try:
                _PIPELINE = pipeline("image-classification", model=model_id)
            except Exception as exc:
                raise RuntimeError(
                    "Unable to load the Hugging Face emotion model. "
                    "Most common causes: (1) no outbound internet access to huggingface.co, "
                    "(2) corporate proxy/firewall blocking HTTPS, or (3) missing dependencies "
                    "in the Python environment. "
                    f"Model: {model_id!r}. "
                    "If you need offline usage, pre-download the model (so it's in the HF cache) "
                    "or set ATS_HF_EMOTION_MODEL to a local directory path containing the model files."
                ) from exc
    return _PIPELINE


def _get_face_detector():
    import cv2

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    return cv2.CascadeClassifier(cascade_path)


def _largest_face(faces):
    if len(faces) == 0:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def analyze_video_emotions(video_path, frame_step=5):
    import cv2
    from PIL import Image

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video file: {video_path}")

    detector = _get_face_detector()
    model = _get_emotion_pipeline()
    counts = Counter()
    frame_count = 0
    checked_frames = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            if frame_count % frame_step != 0:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            face = _largest_face(faces)
            if face is None:
                continue

            x, y, w, h = face
            crop = frame[y : y + h, x : x + w]
            rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_crop)

            result = model(pil_image)[0]
            counts[result["label"]] += 1
            checked_frames += 1
    finally:
        cap.release()

    total = sum(counts.values())
    if total == 0:
        return {
            "counts": {},
            "percentages": {},
            "dominant_emotion": "",
            "processed_frames": frame_count,
            "analyzed_frames": checked_frames,
        }

    percentages = {emotion: round((value / total) * 100, 2) for emotion, value in counts.items()}
    dominant = counts.most_common(1)[0][0]
    return {
        "counts": dict(counts),
        "percentages": percentages,
        "dominant_emotion": dominant,
        "processed_frames": frame_count,
        "analyzed_frames": checked_frames,
    }
