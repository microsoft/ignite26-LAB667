FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT42_HOST=0.0.0.0 \
    AGENT42_PORT=8042

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY tools.py server.py ./

EXPOSE 8042

CMD ["python", "server.py"]
