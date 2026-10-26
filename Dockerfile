FROM python:3.10-slim

# LibreOffice (writer only) converts the Ministry of Health .doc rota to HTML; curl fetches the data snapshot.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-core fonts-dejavu-core curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data && chmod +x scripts/start.sh

ENV PORT=8000 DATABASE_URL=sqlite:///data/simera.db SCHEDULER=1 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["scripts/start.sh"]
