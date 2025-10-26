# ==== Build base ====
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System-Tools (curl für Healthchecks), und saubere Locale
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root User
RUN useradd -ms /bin/bash appuser

WORKDIR /app

# Abhängigkeiten zuerst (Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Code
# -> Lege hier deine beiden Dateien rein: app.py (Main) & kiosk.py (Kiosk)
COPY app.py kiosk.py /app/

# DB-Verzeichnis für das gemountete Volume
RUN mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

# Healthcheck Script (optional)
# pingt Port & Pfad an, die zur jeweiligen App passen (überschreiben wir im Compose)
# Standard: Header nur als Placeholder (wird pro Service geändert)
ENV HEALTHCHECK_URL="http://127.0.0.1:5000/"
HEALTHCHECK --interval=20s --timeout=3s --start-period=15s --retries=5 \
  CMD curl -fsS "$HEALTHCHECK_URL" || exit 1

# Tini als init-Prozess (sauberes Signal-Handling)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Standard-Cmd: Main-App (kann im Compose überschrieben werden)
CMD ["gunicorn", "-b", "0.0.0.0:5000", "--workers=2", "--threads=4", "--timeout=60", "app:app"]
