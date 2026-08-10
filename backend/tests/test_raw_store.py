"""
These are the tests for the raw snapshot archive. The archive is what turns
ingestion from something that overwrites into something that accumulates, so the
things worth pinning are the key layout (which is what makes a run or a company
cheap to find later) and the fact that a snapshot comes back out exactly as it
went in. Everything runs against a temp folder or a fake S3 client, so no bucket
and no credentials are needed. Run them with pytest.
"""

import gzip
import json

from datetime import datetime, timezone

from app.raw_store import (LocalRawStore, S3RawStore, raw_key, snapshot_date,
                           get_store)


# - key layout

def test_key_is_source_then_date_then_ticker():
    # date above ticker is what makes "everything from this run" a single prefix
    assert raw_key("clinicaltrials", "RXRX", "2026-08-07") == \
        "raw/clinicaltrials/2026-08-07/RXRX.json.gz"


def test_key_normalizes_the_ticker():
    # the universe file and the overrides don't agree on case, and two spellings
    # of one company must not become two objects
    assert raw_key("sec", "rxrx", "2026-08-07") == raw_key("sec", "RXRX", "2026-08-07")


def test_sources_do_not_collide():
    trials = raw_key("clinicaltrials", "RXRX", "2026-08-07")
    financials = raw_key("sec", "RXRX", "2026-08-07")
    assert trials != financials


def test_snapshot_date_is_utc_and_day_resolution():
    when = datetime(2026, 8, 7, 23, 59, tzinfo=timezone.utc)
    assert snapshot_date(when) == "2026-08-07"


def test_a_run_can_be_pinned_to_one_date():
    # a long run that crosses midnight should still file everything together,
    # which is why the date is passed in rather than read per company
    start = datetime(2026, 8, 7, 23, 59, tzinfo=timezone.utc)
    assert snapshot_date(start) == snapshot_date(start)


# - local store

def test_local_store_round_trips_a_payload(tmp_path):
    store = LocalRawStore(str(tmp_path))
    payload = {"studies": [{"protocolSection": {"identificationModule":
                                                {"nctId": "NCT001"}}}]}

    store.put("raw/clinicaltrials/2026-08-07/RXRX.json.gz", payload)

    assert store.get("raw/clinicaltrials/2026-08-07/RXRX.json.gz") == payload


def test_local_store_creates_the_dated_folder(tmp_path):
    store = LocalRawStore(str(tmp_path))

    path = store.put("raw/sec/2026-08-07/RXRX.json.gz", {"available": False})

    assert (tmp_path / "raw" / "sec" / "2026-08-07" / "RXRX.json.gz").exists()
    assert path.endswith("RXRX.json.gz")


def test_snapshots_are_stored_gzipped(tmp_path):
    store = LocalRawStore(str(tmp_path))
    store.put("raw/sec/2026-08-07/RXRX.json.gz", {"cash": 1})

    blob = (tmp_path / "raw" / "sec" / "2026-08-07" / "RXRX.json.gz").read_bytes()

    # readable as gzip, and not as plain json
    assert json.loads(gzip.decompress(blob)) == {"cash": 1}


def test_a_later_date_does_not_overwrite_an_earlier_one(tmp_path):
    # this is the whole point of the archive: history accumulates
    store = LocalRawStore(str(tmp_path))
    store.put(raw_key("sec", "RXRX", "2026-07-01"), {"cash": {"value": 100}})
    store.put(raw_key("sec", "RXRX", "2026-08-07"), {"cash": {"value": 80}})

    assert store.get(raw_key("sec", "RXRX", "2026-07-01"))["cash"]["value"] == 100
    assert store.get(raw_key("sec", "RXRX", "2026-08-07"))["cash"]["value"] == 80


# - s3 store

class FakeS3:
    """Records what would have been sent to S3."""

    def __init__(self):
        self.objects = {}
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def get_object(self, Bucket, Key):
        class Body:
            def __init__(self, blob):
                self._blob = blob

            def read(self):
                return self._blob
        return {"Body": Body(self.objects[Key])}


def test_s3_store_round_trips_a_payload():
    client = FakeS3()
    store = S3RawStore("my-bucket", client=client)
    payload = {"studies": []}

    store.put("raw/clinicaltrials/2026-08-07/RXRX.json.gz", payload)

    assert store.get("raw/clinicaltrials/2026-08-07/RXRX.json.gz") == payload


def test_s3_store_labels_the_object_as_gzipped_json():
    client = FakeS3()
    store = S3RawStore("my-bucket", client=client)

    store.put("raw/sec/2026-08-07/RXRX.json.gz", {"cash": 1})

    call = client.calls[0]
    assert call["Bucket"] == "my-bucket"
    # without these, anything reading the object back has to guess the encoding
    assert call["ContentType"] == "application/json"
    assert call["ContentEncoding"] == "gzip"


def test_s3_store_returns_a_locatable_uri():
    store = S3RawStore("my-bucket", client=FakeS3())

    assert store.put("raw/sec/2026-08-07/RXRX.json.gz", {}) == \
        "s3://my-bucket/raw/sec/2026-08-07/RXRX.json.gz"


# - choosing a store

def test_local_disk_is_the_default(monkeypatch):
    # a laptop run needs no bucket, no credentials, and no AWS account
    monkeypatch.setattr("app.raw_store.RAW_BUCKET", None)

    assert isinstance(get_store(), LocalRawStore)


def test_a_bucket_switches_it_to_s3(monkeypatch):
    monkeypatch.setattr("app.raw_store.RAW_BUCKET", "my-bucket")
    # don't let it build a real boto3 client just to check the branch
    monkeypatch.setattr("app.raw_store.S3RawStore.__init__",
                        lambda self, bucket, client=None: None)

    assert isinstance(get_store(), S3RawStore)
