FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy src only; secrets will be mounted
COPY src ./src
COPY .env.example ./

# runtime
CMD ["python", "-m", "src.fiin_alerts.jobs.generate_and_send_alerts", "--dry-run"]
