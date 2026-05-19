FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir websockets

COPY . /app

CMD ["python", "/app/soundtouch-proxy/radio-proxy.py"]
