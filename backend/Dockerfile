# CUDA-enabled base so CuPy can use the GPU when the container is run with
# `--gpus all`. Falls back to NumPy automatically if no GPU is visible.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3-pip python3.11-dev \
        gdal-bin libgdal-dev g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
# GPU acceleration (optional): uncomment to bake CuPy into the image.
# RUN pip3 install --no-cache-dir cupy-cuda12x==13.3.0

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
