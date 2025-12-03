FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖：espeak-ng 用于英文/日文模型的分词，ffmpeg 供 pydub 处理音频
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（包括预先准备好的 models 目录）
COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

