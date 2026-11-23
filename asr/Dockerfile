FROM python:3.12.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# torch 的 pip 包自带 CUDA 和 cuDNN 动态库；让 faster-whisper（CTranslate2）也能找到它们
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib \
    HF_HOME=/models \
    TORCH_HOME=/models/torch \
    PYTHONUNBUFFERED=1

COPY server.py .
EXPOSE 9000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
