FROM dhi.io/python:3.13-debian13-dev AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM dhi.io/python:3.13
WORKDIR /app
COPY --from=builder /opt/python/lib/python3.13/site-packages /opt/python/lib/python3.13/site-packages
COPY py_conf_sync.py .
ENTRYPOINT ["python", "/app/py_conf_sync.py"]
