FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8080
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY deploy-data/ ./data/processed/BAHKmi4F1L8_20261026-144540/
CMD ["python", "web_server.py", "--host", "0.0.0.0"]
