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

# where to install from. the default is PyPI itself; point this at a mirror when
# building somewhere PyPI is slow, which is the difference between a fifteen
# minute build and an hour and a half on a throttled connection:
#   docker build --build-arg PIP_INDEX_URL=https://<mirror>/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple

# install dependencies first, in their own layer, so editing application code
# doesn't reinstall faiss and numpy on every build
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

# run as a non-root user. ingestion writes as it runs, snapshots and, when no
# DATABASE_URL is set, the SQLite file, so the app does need to own its directory.
RUN useradd --create-home --uid 1000 appuser

# WORKDIR created /app as root, and COPY --chown only sets ownership on the files
# it copies, not on the directory holding them. Without this the app can read its
# own code but cannot create a file beside it, which is what the SQLite fallback
# does when DATABASE_URL is unset. One directory, so no layer worth speaking of.
RUN chown appuser:appuser /app

# the snapshot archive, created here so the mount point exists in the image and
# is owned by the user that writes to it. A named volume takes its ownership
# from the image path it covers, and when that path does not exist Docker makes
# it root-owned: every archive write then failed with "Permission denied:
# /snapshots/raw" while ingestion carried on regardless, so a run looked healthy
# and kept no history at all.
RUN mkdir -p /snapshots && chown appuser:appuser /snapshots

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
