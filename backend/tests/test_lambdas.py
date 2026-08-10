"""
These are the tests for the two Lambda functions that drive scheduled ingestion:
the dispatcher that puts one message per slice on the queue, and the runner that
turns a queued slice into a container task. Both are written so their real work is
plain data, so these check the messages and the RunTask call without any AWS
credentials, any boto3, or anything deployed. Run them with pytest.
"""

import json

import pytest

import dispatch
import runner


# - dispatch: building the messages

def test_one_message_per_shard():
    messages = dispatch.shard_messages(4, "2026-08-07T03:00:00Z")

    assert [m["shard_index"] for m in messages] == [0, 1, 2, 3]
    assert all(m["shard_count"] == 4 for m in messages)


def test_every_message_carries_the_same_run_id():
    # this is what lets one run's snapshots and logs be tied back together
    messages = dispatch.shard_messages(3, "2026-08-07T03:00:00Z")

    assert {m["run_id"] for m in messages} == {"2026-08-07T03:00:00Z"}


def test_messages_carry_no_company_data():
    # the worker reads companies.json itself. a payload here would grow with the
    # universe and eventually hit the message size limit.
    message = dispatch.shard_messages(1, "run")[0]

    assert set(message) == {"run_id", "shard_index", "shard_count"}


def test_a_shard_count_below_one_is_rejected():
    with pytest.raises(ValueError):
        dispatch.shard_messages(0, "run")


def test_run_id_uses_the_schedule_time():
    # every slice of one scheduled run gets the same id this way, for free
    assert dispatch.run_id_from({"time": "2026-08-07T03:00:00Z"}) == \
        "2026-08-07T03:00:00Z"


def test_run_id_falls_back_for_a_manual_invocation():
    # a hand-triggered run has no schedule time and must still get an id
    assert dispatch.run_id_from({}).endswith("Z")
    assert dispatch.run_id_from(None).endswith("Z")


# - dispatch: batching for SQS

def test_batches_respect_the_sqs_limit():
    messages = dispatch.shard_messages(25, "run")

    batches = dispatch.batched(messages)

    # SQS takes at most 10 entries per call
    assert [len(b) for b in batches] == [10, 10, 5]


def test_a_single_batch_is_not_split():
    assert len(dispatch.batched(dispatch.shard_messages(4, "run"))) == 1


def test_batch_entries_have_ids_unique_within_the_batch():
    entries = dispatch.batch_entries(dispatch.shard_messages(10, "run"))

    assert len({e["Id"] for e in entries}) == 10
    assert json.loads(entries[3]["MessageBody"])["shard_index"] == 3


class FakeSQS:
    def __init__(self, failed=()):
        self.batches = []
        self._failed = list(failed)

    def send_message_batch(self, QueueUrl, Entries):
        self.batches.append(Entries)
        return {"Failed": self._failed}


def test_dispatch_sends_every_shard(monkeypatch):
    monkeypatch.setenv("QUEUE_URL", "https://sqs/queue")
    monkeypatch.setenv("SHARD_COUNT", "12")
    client = FakeSQS()

    result = dispatch.handler({"time": "2026-08-07T03:00:00Z"}, client=client)

    assert result["dispatched"] == 12
    assert sum(len(b) for b in client.batches) == 12


def test_dispatch_fails_loudly_when_a_message_is_rejected(monkeypatch):
    # a run missing a slice is a silently incomplete ingest, which is worse than
    # a failed invocation someone can see
    monkeypatch.setenv("QUEUE_URL", "https://sqs/queue")
    monkeypatch.setenv("SHARD_COUNT", "4")
    client = FakeSQS(failed=[{"Id": "2", "Message": "nope"}])

    with pytest.raises(RuntimeError, match="failed"):
        dispatch.handler({}, client=client)


def test_dispatch_defaults_to_a_single_shard(monkeypatch):
    monkeypatch.setenv("QUEUE_URL", "https://sqs/queue")
    monkeypatch.delenv("SHARD_COUNT", raising=False)
    client = FakeSQS()

    assert dispatch.handler({}, client=client)["dispatched"] == 1


# - runner: reading the message

def test_parse_message_reads_the_slice():
    message = runner.parse_message(
        json.dumps({"run_id": "r", "shard_index": 2, "shard_count": 8}))

    assert message["shard_index"] == 2


@pytest.mark.parametrize("body", [
    '{"shard_index": 1}',
    '{"shard_count": 8}',
    '{}',
])
def test_parse_message_rejects_an_incomplete_message(body):
    with pytest.raises(ValueError):
        runner.parse_message(body)


# - runner: building the task

def config():
    return {
        "cluster": "biotech",
        "task_definition": "biotech-ingest:3",
        "container_name": "ingest",
        "subnets": ["subnet-a", "subnet-b"],
        "security_groups": ["sg-1"],
        "assign_public_ip": "ENABLED",
    }


def test_the_task_runs_ingestion_not_the_api():
    # the image's default command serves the API, so it has to be overridden
    override = runner.container_overrides({"shard_index": 0, "shard_count": 1},
                                          "ingest")

    assert override["command"] == ["python", "ingest.py"]
    assert override["name"] == "ingest"


def test_the_shard_is_passed_as_environment():
    # environment rather than arguments, because that is what ingest.py reads
    # when it runs as a task
    override = runner.container_overrides(
        {"shard_index": 2, "shard_count": 8, "run_id": "r"}, "ingest")
    env = {e["name"]: e["value"] for e in override["environment"]}

    assert env["SHARD_INDEX"] == "2"
    assert env["SHARD_COUNT"] == "8"
    assert env["RUN_ID"] == "r"


def test_environment_values_are_strings():
    # ECS rejects the call outright if any value is a number
    override = runner.container_overrides({"shard_index": 2, "shard_count": 8},
                                          "ingest")

    assert all(isinstance(e["value"], str) for e in override["environment"])


def test_run_task_params_are_a_complete_fargate_call():
    params = runner.run_task_params({"shard_index": 1, "shard_count": 4}, config())

    assert params["launchType"] == "FARGATE"
    assert params["count"] == 1
    net = params["networkConfiguration"]["awsvpcConfiguration"]
    assert net["subnets"] == ["subnet-a", "subnet-b"]
    # without this the task can't reach ClinicalTrials.gov or SEC from a public subnet
    assert net["assignPublicIp"] == "ENABLED"


def test_config_splits_the_comma_separated_lists(monkeypatch):
    # a Lambda environment variable can only hold a string
    monkeypatch.setenv("CLUSTER", "biotech")
    monkeypatch.setenv("TASK_DEFINITION", "biotech-ingest:3")
    monkeypatch.setenv("SUBNETS", "subnet-a,subnet-b")
    monkeypatch.setenv("SECURITY_GROUPS", "sg-1")

    resolved = runner.config_from_env()

    assert resolved["subnets"] == ["subnet-a", "subnet-b"]
    assert resolved["security_groups"] == ["sg-1"]
    assert resolved["container_name"] == "ingest"


# - runner: handling a batch

class FakeECS:
    def __init__(self, failures_for=()):
        self.started = []
        self._failures_for = set(failures_for)

    def run_task(self, **kwargs):
        env = {e["name"]: e["value"] for e in
               kwargs["overrides"]["containerOverrides"][0]["environment"]}
        index = env["SHARD_INDEX"]
        self.started.append(index)
        if index in self._failures_for:
            return {"failures": [{"reason": "no capacity"}]}
        return {"tasks": [{"taskArn": f"arn:task/{index}"}]}


def sqs_event(*shards):
    return {"Records": [
        {"messageId": f"msg-{i}",
         "body": json.dumps({"run_id": "r", "shard_index": i, "shard_count": 4})}
        for i in shards
    ]}


def set_runner_env(monkeypatch):
    monkeypatch.setenv("CLUSTER", "biotech")
    monkeypatch.setenv("TASK_DEFINITION", "biotech-ingest:3")
    monkeypatch.setenv("SUBNETS", "subnet-a")
    monkeypatch.setenv("SECURITY_GROUPS", "sg-1")


def test_runner_starts_one_task_per_message(monkeypatch):
    set_runner_env(monkeypatch)
    client = FakeECS()

    result = runner.handler(sqs_event(0, 1, 2), client=client)

    assert client.started == ["0", "1", "2"]
    assert result["batchItemFailures"] == []


def test_only_the_failing_message_comes_back(monkeypatch):
    # without per-message reporting the whole batch redelivers and the slices
    # that did start would run twice
    set_runner_env(monkeypatch)
    client = FakeECS(failures_for={"1"})

    result = runner.handler(sqs_event(0, 1, 2), client=client)

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-1"}]


def test_a_malformed_message_fails_only_itself(monkeypatch):
    set_runner_env(monkeypatch)
    client = FakeECS()
    event = {"Records": [
        {"messageId": "bad", "body": "not json"},
        {"messageId": "good",
         "body": json.dumps({"shard_index": 1, "shard_count": 4})},
    ]}

    result = runner.handler(event, client=client)

    assert result["batchItemFailures"] == [{"itemIdentifier": "bad"}]
    # the valid message still got its task
    assert client.started == ["1"]


def test_an_empty_batch_is_not_an_error(monkeypatch):
    set_runner_env(monkeypatch)

    assert runner.handler({"Records": []}, client=FakeECS()) == \
        {"batchItemFailures": []}
