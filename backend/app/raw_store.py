"""
This file archives what the APIs actually returned, before we parse it down to the
handful of fields the database keeps. Every ingestion run writes one snapshot per
company under a dated key, and nothing ever overwrites an earlier date, so the
archive accumulates history instead of replacing it. That is the missing piece for
change over time: today's ingest still wipes and replaces the database rows, but
the snapshots behind them stay, so "what changed since last month" becomes a
question you can actually answer, and a field this version of the code ignores can
still be recovered later by re-parsing an old snapshot.

It writes to S3 when RAW_BUCKET is set, which is how it runs as a container task,
and to a local folder otherwise, so running locally needs no AWS account and no
credentials.
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
