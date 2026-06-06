FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir websockets

COPY soundtouch-radio/ /app/

CMD ["python", "/app/proxy/radio-proxy.py"]
