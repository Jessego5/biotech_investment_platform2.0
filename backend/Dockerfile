# One image, two jobs. The API and the ingestion batch share the same code and the
# same database config, so they ship together and differ only in the command they
# start with, which means there is no second image to drift from this one. The
# default here serves the API; docker-compose.yml and the ECS task definition both
# override it with "python ingest.py" to run ingestion instead.

FROM python:3.12-slim

# don't write .pyc files, and don't buffer stdout, so the ingestion progress lines
# show up in the log stream as they happen instead of all at once when it exits
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# install dependencies first, in their own layer, so editing application code
# doesn't reinstall faiss and numpy on every build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# run as a non-root user. ingestion writes as it runs, snapshots and, when no
# DATABASE_URL is set, the SQLite file, so the app does need to own its directory.
RUN useradd --create-home --uid 1000 appuser

# copy with ownership already set. a chown -R afterwards would rewrite every file
# into a second layer, roughly doubling the size the application contributes.
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# the API is up once it answers on /. this is what tells a container scheduler the
# difference between "started" and "actually serving". uses stdlib rather than
# adding curl to the image just for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

# the default job is the API. override the command to run ingestion instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
