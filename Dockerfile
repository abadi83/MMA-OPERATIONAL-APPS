# ═══════════════════════════════════════════════
# iScan Pro By MMA — Docker Image
# ═══════════════════════════════════════════════
# Build: docker build -t iscan-pro .
# Run:   docker run -p 8501:8501 iscan-pro
# ═══════════════════════════════════════════════

FROM python:3.12-slim

# Force UTF-8 encoding
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8

LABEL maintainer="MMA (Mitra Mulia Abadi)"
LABEL description="iScan Pro — Aplikasi scanning resi pengiriman"

# ── System dependencies ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── App directory ──
WORKDIR /app

# ── Python dependencies ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──
COPY . .

# ── Data directories (mounted as volumes in compose) ──
RUN mkdir -p /app/data /app/logs /app/Gudang_Arsip_Excel /app/Handover_Reports \
    /app/Sales_Reports /app/Packing_Videos /app/DB_Backup /app/static

# ── Expose Streamlit port ──
EXPOSE 8501

# ── Health check ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# ── Run Streamlit ──
CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.enableCORS=true", \
     "--server.enableXsrfProtection=false", \
     "--server.enableStaticServing=true", \
     "--server.maxUploadSize=200", \
     "--server.maxMessageSize=500", \
     "--browser.gatherUsageStats=false", \
     "--browser.serverPort=8501", \
     "--server.fileWatcherType=poll", \
     "--server.scriptHealthCheckEnabled=false", \
     "--logger.level=info"]
