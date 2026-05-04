FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY py_conf_sync.py .
ENTRYPOINT ["python", "/app/py_conf_sync.py"]
