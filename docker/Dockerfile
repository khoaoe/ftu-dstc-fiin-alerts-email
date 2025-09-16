FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Ho_Chi_Minh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy src only; secrets will be mounted
COPY src ./src
COPY .env.example ./

# runtime
CMD ["python", "-m", "src.fiin_alerts.jobs.generate_and_send_alerts", "--dry-run"]
