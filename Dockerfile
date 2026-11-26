FROM python:3.12-slim
WORKDIR /editor
COPY editor/ ./
USER nobody
CMD ["python", "-m", "http.server", "8000"]
