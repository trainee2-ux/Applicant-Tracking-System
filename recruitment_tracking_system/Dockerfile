FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for: pytesseract (tesseract-ocr), pdf2image (poppler-utils),
# and opencv-python (libglib2.0-0/libgl1).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libglib2.0-0 \
    libgl1 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Use CPU-only PyTorch wheels to avoid downloading CUDA/NVIDIA packages.
# Other dependencies still come from PyPI.
RUN python -m pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple -r requirements.txt

COPY . .

EXPOSE 8000

# Use gunicorn for server deployments (works with Docker on Windows Server using Linux containers).
CMD ["gunicorn", "recruitment_tracking_system.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
