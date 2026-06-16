FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2, cryptography, and native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc g++ libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (--prefer-binary avoids compiling from source when wheels exist)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt psycopg2-binary

# Copy application code
COPY api/ api/
COPY analyse/ analyse/
COPY appelAPIs/ appelAPIs/
COPY frontend/ frontend/
COPY fit_builder/ fit_builder/
COPY serveur/ serveur/

# Référentiel national des stades d'athlétisme (lecture seule, partagé entre
# utilisateurs). Suivi par git via une exception .gitignore pour être présent
# dans le contexte de build Railway.
COPY data/stades_athle.json data/stades_athle.json

# Railway injects PORT; default to 8000
ENV PORT=8000
ENV APP_ENV=production

EXPOSE ${PORT}

# mkdir at runtime (not build time) so it works with mounted volumes
CMD mkdir -p data && uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
