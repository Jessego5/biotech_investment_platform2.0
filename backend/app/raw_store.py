"""
This archives what the APIs actually returned, before parsing them down to the
handful of fields the database keeps. Every ingestion run writes one snapshot per
company under a dated key and nothing ever overwrites an earlier date, so the
archive accumulates history instead of replacing it. That is what makes change
over time answerable: today's ingest still wipes and replaces the database rows,
but the snapshots behind them stay, so what changed since last month is a real
question, and a field this version of the code ignores can be recovered later by
re-parsing an old snapshot. It writes to S3 when RAW_BUCKET is set, which is how
it runs as a container task, and to a local folder otherwise, so running locally
needs no AWS account and no credentials. Imported by ingest.py and by changes.py,
which reads the snapshots back.
"""

import gzip
import json
import os
from datetime import datetime, timezone

# where snapshots go. RAW_BUCKET switches this from local disk to S3; RAW_PREFIX
# lets several environments share one bucket without colliding.
RAW_BUCKET = os.environ.get("RAW_BUCKET")
RAW_PREFIX = os.environ.get("RAW_PREFIX", "raw")
RAW_DIR = os.environ.get("RAW_DIR",
                         os.path.join(os.path.dirname(__file__), "..", "raw"))


def snapshot_date(when=None):
    """
    The date a snapshot is filed under, always UTC. Passing `when` in keeps this
    testable and keeps a single long ingestion run filed under one date even if
    it crosses midnight partway through.
    """
    return (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def code_version():
    """
    The commit the running code is at, or "unknown" outside a checkout.

    A snapshot is only comparable to another taken by the same rules. When the
    matching rules changed, Church & Dwight appeared to register thirty-four
    trials in four days, one of them a benzocaine study from 2007. It had
    always run them; we had only just started recognising its name. A diff
    cannot tell the world changing from us changing unless the snapshot says
    which code produced it.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=os.path.dirname(os.path.dirname(__file__)),
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def manifest_key(date):
    """Where a run records what produced it, alongside that run's companies."""
    return f"manifest/{date}.json"


def raw_key(source, ticker, date):
    """
    Where one company's snapshot lives, as source/date/ticker.

    Date sits above ticker on purpose: the common questions are "everything from
    this run" and "this company over time", and this layout answers the first
    with a single prefix listing, which is the cheap operation in S3. It also
    keeps one run's objects adjacent, which is what makes lifecycle rules and
    per-run cleanup straightforward.
    """
    return f"{RAW_PREFIX}/{source}/{date}/{ticker.upper()}.json.gz"


def _encode(payload):
    """Serialize a snapshot. Gzipped because these responses are mostly text and
    compress by roughly an order of magnitude, and storage here grows every run."""
    return gzip.compress(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _decode(blob):
    return json.loads(gzip.decompress(blob).decode("utf-8"))


class LocalRawStore:
    """Snapshots on local disk. The default, so local runs need no AWS at all."""

    def __init__(self, directory):
        self.directory = directory

    def put(self, key, payload):
        path = os.path.join(self.directory, key)
        # the key has slashes in it, so the date folder may not exist yet
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(_encode(payload))
        return path

    def get(self, key):
        with open(os.path.join(self.directory, key), "rb") as f:
            return _decode(f.read())


class S3RawStore:
    """Snapshots in S3. Used when RAW_BUCKET is set, which is the container case."""

    def __init__(self, bucket, client=None):
        self.bucket = bucket
        # import boto3 lazily so that local runs, the tests, and the API image
        # never need it installed just to import this module
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.client = client

    def put(self, key, payload):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=_encode(payload),
                               ContentType="application/json",
                               ContentEncoding="gzip")
        return f"s3://{self.bucket}/{key}"

    def get(self, key):
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return _decode(obj["Body"].read())


def get_store():
    """The store this environment is configured for."""
    if RAW_BUCKET:
        return S3RawStore(RAW_BUCKET)
    return LocalRawStore(RAW_DIR)


def _dates_local(directory, source):
    """Snapshot dates on local disk, newest first."""
    prefix = os.path.join(directory, RAW_PREFIX, source)
    if not os.path.isdir(prefix):
        return []
    return sorted((d for d in os.listdir(prefix)
                   if os.path.isdir(os.path.join(prefix, d))), reverse=True)


def _dates_s3(client, bucket, source):
    """
    Snapshot dates in S3, newest first. Listing with a delimiter returns the date
    folders themselves rather than every object under them, which matters because
    each date holds hundreds of companies.
    """
    paginator = client.get_paginator("list_objects_v2")
    dates = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{RAW_PREFIX}/{source}/",
                                   Delimiter="/"):
        for entry in page.get("CommonPrefixes", []):
            dates.add(entry["Prefix"].rstrip("/").rsplit("/", 1)[-1])
    return sorted(dates, reverse=True)


def snapshot_dates(source="clinicaltrials"):
    """
    Which dates the archive holds, newest first. This is what lets the app offer a
    comparison without being told in advance which runs exist.
    """
    if RAW_BUCKET:
        import boto3
        return _dates_s3(boto3.client("s3"), RAW_BUCKET, source)
    return _dates_local(RAW_DIR, source)


def _count_local(directory, source, date):
    path = os.path.join(directory, RAW_PREFIX, source, date)
    return len(os.listdir(path)) if os.path.isdir(path) else 0


def _count_s3(client, bucket, source, date):
    paginator = client.get_paginator("list_objects_v2")
    return sum(page.get("KeyCount", 0) for page in
               paginator.paginate(Bucket=bucket,
                                  Prefix=f"{RAW_PREFIX}/{source}/{date}/"))


def snapshot_coverage(source="clinicaltrials"):
    """
    How many companies each snapshot date holds, newest first.

    Not every run covers the universe: repairing a handful of companies writes a
    date with only those few in it. Comparing against one of those would report
    almost every company as absent rather than unchanged, so anything choosing a
    baseline needs to see the coverage rather than just the date.
    """
    if RAW_BUCKET:
        import boto3
        client = boto3.client("s3")
        return [(d, _count_s3(client, RAW_BUCKET, source, d))
                for d in _dates_s3(client, RAW_BUCKET, source)]
    return [(d, _count_local(RAW_DIR, source, d))
            for d in _dates_local(RAW_DIR, source)]
