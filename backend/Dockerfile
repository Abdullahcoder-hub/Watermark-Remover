FROM python:3.14-slim

WORKDIR /app

# System deps needed by later phases (OpenCV/Tesseract) are added when
# those phases land — kept minimal for Phase 1.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as a non-root user with minimal permissions.
RUN useradd --create-home --uid 1000 appuser
COPY app ./app
RUN mkdir -p uploads results && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
