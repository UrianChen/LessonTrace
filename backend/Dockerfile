FROM python:3.12.12-slim

# ffmpeg：抽音轨、转 HLS；fonts-dejavu-core：生成示例录像时画字幕用
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# api：先初始化（建表、建桶、建账号、导入示例课，均可重复执行）再启动
CMD ["sh", "-c", "python -m scripts.init_db && python -m scripts.seed_demo && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
