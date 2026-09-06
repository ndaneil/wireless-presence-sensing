FROM python:3.13-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 iputils-ping \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /service
COPY service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY service/ ./
USER 1000:1000
CMD ["python", "-m", "uvicorn", "app.main:app", "--uds", "/data/presence.sock", "--no-proxy-headers"]
