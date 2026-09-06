"""
This is the runner, the second half of scheduled ingestion. The queue delivers a
message naming one slice and this starts a container task for it and returns in
milliseconds, no matter how long the ingestion actually takes. The container is
the same image the API runs from, with the command overridden to ingest and then
embed, and the shard passed in as environment, which is why ingest.py and
embed_trials.py both read SHARD_INDEX and SHARD_COUNT from there. Deployed flat
by infra/deploy.sh as runner.handler.
"""

import json
import os


def parse_message(body):
    """Read a queue message, failing loudly if it isn't the shape we expect."""
    message = json.loads(body)
    missing = [k for k in ("shard_index", "shard_count") if k not in message]
    if missing:
        raise ValueError(f"message is missing {missing}: {body}")
    return message


def container_overrides(message, container_name):
    """
    What this task should do differently from the image's default. The image
    normally starts the API, so the command is overridden to run ingestion, and
    the slice is passed as environment because that is what a task definition
    override can carry.
    """
    return {
        "name": container_name,
        "command": ["python", "ingest.py"],
        "environment": [
            {"name": "SHARD_INDEX", "value": str(message["shard_index"])},
            {"name": "SHARD_COUNT", "value": str(message["shard_count"])},
            # tag the task with its run so its logs can be tied to the others
            {"name": "RUN_ID", "value": str(message.get("run_id", ""))},
        ],
    }


def run_task_params(message, config):
    """
    The full RunTask call for one slice, built as plain data so it can be checked
    without talking to AWS.
    """
    return {
        "cluster": config["cluster"],
        "taskDefinition": config["task_definition"],
        "launchType": "FARGATE",
        "count": 1,
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": config["subnets"],
                "securityGroups": config["security_groups"],
                # a task in a public subnet needs a public IP to reach the SEC and
                # ClinicalTrials.gov at all; one behind a NAT gateway must not have one
                "assignPublicIp": config["assign_public_ip"],
            }
        },
        "overrides": {
            "containerOverrides": [
                container_overrides(message, config["container_name"])
            ]
        },
    }


def config_from_env():
    """Read the task settings this function was deployed with."""
    return {
        "cluster": os.environ["CLUSTER"],
        "task_definition": os.environ["TASK_DEFINITION"],
        "container_name": os.environ.get("CONTAINER_NAME", "ingest"),
        # comma-separated, because that is all a Lambda environment variable can hold
        "subnets": os.environ["SUBNETS"].split(","),
        "security_groups": os.environ["SECURITY_GROUPS"].split(","),
        "assign_public_ip": os.environ.get("ASSIGN_PUBLIC_IP", "ENABLED"),
    }


def handler(event, context=None, client=None):
    """
    Start one task per queued slice. Returns the message ids that failed, which is
    the response shape SQS partial batch reporting expects: those come back for
    another attempt, and the rest are deleted from the queue.
    """
    # import boto3 lazily (the Lambda runtime provides it) so the pure functions
    # above stay importable and testable without it
    if client is None:
        import boto3
        client = boto3.client("ecs")

    config = config_from_env()

    failures = []
    for record in event.get("Records", []):
        try:
            message = parse_message(record["body"])
            response = client.run_task(**run_task_params(message, config))
            # ECS can accept the call and still refuse to place the task, for
            # example when there is no capacity. that is a failure, not a success.
            if response.get("failures"):
                raise RuntimeError(f"ECS refused the task: {response['failures']}")
            print(f"started shard {message['shard_index']} of "
                  f"{message['shard_count']} for run {message.get('run_id')}")
        except Exception as e:
            # fail only this message, so the slices that did start aren't rerun
            print(f"shard failed to start: {e}")
            failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failures}
