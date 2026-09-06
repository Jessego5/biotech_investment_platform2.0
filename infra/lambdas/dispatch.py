"""
This is the dispatcher, the first half of scheduled ingestion. A schedule fires
it and all it does is put one message on the queue per slice of the universe,
then finish; it never fetches anything itself. The work is split this way because
of timeouts: ingesting the universe takes minutes, well past what a Lambda is
allowed to run, so this function does only the part that takes milliseconds,
deciding the slices, and the queue hands the slow part to something with no such
limit. The queue is also what gives retries and a dead-letter queue for free, so
a slice that fails comes back rather than vanishing. Deployed flat by
infra/deploy.sh as dispatch.handler, and it reads QUEUE_URL and SHARD_COUNT from
the environment.
"""

import json
import os
from datetime import datetime, timezone

# SQS takes at most 10 entries per SendMessageBatch call
SQS_BATCH_LIMIT = 10


def run_id_from(event):
    """
    A single id shared by every slice of one run, so the resulting snapshots and
    logs can be tied back together. EventBridge stamps each scheduled event with
    the time it fired, which is already unique per run and identical across
    everything that run triggers, so prefer it over inventing our own.
    """
    fired_at = (event or {}).get("time")
    if fired_at:
        return fired_at
    # a manual invocation has no schedule time, so fall back to now
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shard_messages(shard_count, run_id):
    """
    One message per slice. The message is deliberately tiny: which slice, out of
    how many, and which run it belongs to. It carries no company data, because the
    worker can read companies.json itself and a queue message is the wrong place
    for a payload that might grow past the size limit.
    """
    if shard_count < 1:
        raise ValueError(f"shard_count must be at least 1, got {shard_count}")
    return [{"run_id": run_id, "shard_index": i, "shard_count": shard_count}
            for i in range(shard_count)]


def batched(items, size=SQS_BATCH_LIMIT):
    """Split a list into chunks small enough for one SendMessageBatch call."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def batch_entries(messages):
    """
    Turn messages into SendMessageBatch entries. The id only has to be unique
    within its own batch, and the shard index already is.
    """
    return [{"Id": str(m["shard_index"]), "MessageBody": json.dumps(m)}
            for m in messages]


def handler(event, context=None, client=None):
    """Fan the run out across the queue. Returns what it sent, for the logs."""
    queue_url = os.environ["QUEUE_URL"]
    shard_count = int(os.environ.get("SHARD_COUNT", 1))

    # import boto3 lazily (the Lambda runtime provides it) so the pure functions
    # above stay importable and testable without it
    if client is None:
        import boto3
        client = boto3.client("sqs")

    run_id = run_id_from(event)
    messages = shard_messages(shard_count, run_id)

    failed = []
    # send in batches, and collect any entries SQS rejected individually. a batch
    # call can succeed as a whole while still failing some of its entries.
    for chunk in batched(messages):
        response = client.send_message_batch(
            QueueUrl=queue_url, Entries=batch_entries(chunk))
        failed.extend(response.get("Failed", []))

    if failed:
        # raise so the invocation is recorded as a failure rather than quietly
        # dispatching a run that is missing slices
        raise RuntimeError(f"{len(failed)} of {len(messages)} messages failed: {failed}")

    print(f"dispatched run {run_id}: {shard_count} shards")
    return {"run_id": run_id, "dispatched": len(messages)}
