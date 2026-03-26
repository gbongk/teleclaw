FROM python:3.11-slim

# Claude Code CLI 설치를 위한 Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hub/ hub/
COPY relay_common.py relay-stop.py relay-tool-use.py .
COPY supervisor-wrapper.py svctl.py send_telegram.py .

# 데이터/로그 디렉토리
RUN mkdir -p /app/data /app/logs

# config.yaml은 볼륨으로 마운트
VOLUME ["/app/data", "/app/logs"]

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "hub"]
