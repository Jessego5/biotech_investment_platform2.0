"""
These are the tests for the CloudFormation templates. A template is only found to
be wrong when a deploy fails halfway and rolls back, which is a slow and expensive
way to discover a typo, so these check the things that are checkable without an AWS
account: that both templates parse, that every name they refer to actually exists,
and above all that what pipeline.yaml imports is exactly what storage.yaml exports,
since a mismatch there fails at deploy time with a message that names neither
stack. They read the real template files. Run them with pytest.
"""

import json
import os
import re

import pytest
import yaml

CFN_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                       "infra", "cloudformation")

# names CloudFormation resolves itself, so a reference to one is always valid
PSEUDO_PARAMETERS = {
    "AWS::AccountId", "AWS::NoValue", "AWS::NotificationARNs", "AWS::Partition",
    "AWS::Region", "AWS::StackId", "AWS::StackName", "AWS::URLSuffix",
}


class CfnLoader(yaml.SafeLoader):
    """A YAML loader that understands CloudFormation's !Ref / !GetAtt shorthand."""


def _construct_tag(loader, tag_suffix, node):
    """Turn !Thing into its long form, so everything can be walked uniformly."""
    key = "Ref" if tag_suffix == "Ref" else f"Fn::{tag_suffix}"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        # !GetAtt takes dotted shorthand but means a two-element list
        if key == "Fn::GetAtt":
            value = value.split(".")
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {key: value}


CfnLoader.add_multi_constructor("!", _construct_tag)


def load_template(name):
    with open(os.path.join(CFN_DIR, name)) as f:
        return yaml.load(f, Loader=CfnLoader)


def walk(node):
    """Every dict anywhere in the template, so intrinsics can be found wherever
    they were used."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def find_intrinsic(template, key):
    """Every use of one intrinsic function, as a list of its arguments."""
    return [node[key] for node in walk(template) if set(node) == {key}]


def declared_names(template):
    """Everything a !Ref in this template is allowed to point at."""
    return (set(template.get("Parameters", {}))
            | set(template.get("Resources", {}))
            | PSEUDO_PARAMETERS)


def sub_variables(argument):
    """
    The ${...} names in an Fn::Sub, minus the ones it defines itself. The list
    form of Fn::Sub carries a map of local variables that don't have to exist as
    parameters or resources.
    """
    if isinstance(argument, list):
        body, local = argument[0], set(argument[1] or {})
    else:
        body, local = argument, set()
    found = set(re.findall(r"\$\{([^}]+)\}", body))
    # ${Resource.Attribute} is an attribute reference; the resource is what has to exist
    return {v.split(".")[0] for v in found if not v.startswith("!")} - local


TEMPLATES = ["storage.yaml", "pipeline.yaml"]


# - both templates

@pytest.mark.parametrize("name", TEMPLATES)
def test_template_parses_and_has_the_required_sections(name):
    template = load_template(name)

    assert template["AWSTemplateFormatVersion"] == "2010-09-09"
    assert template["Description"]
    assert template["Resources"]


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_ref_points_at_something_that_exists(name):
    template = load_template(name)
    known = declared_names(template)

    unknown = {r for r in find_intrinsic(template, "Ref")
               if isinstance(r, str) and r not in known}

    assert not unknown, f"{name} refers to undeclared names: {unknown}"


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_sub_variable_resolves(name):
    template = load_template(name)
    known = declared_names(template)

    unknown = set()
    for argument in find_intrinsic(template, "Fn::Sub"):
        unknown |= {v for v in sub_variables(argument) if v not in known}

    assert not unknown, f"{name} substitutes undeclared names: {unknown}"


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_getatt_names_a_real_resource(name):
    template = load_template(name)
    resources = set(template["Resources"])

    unknown = {a[0] for a in find_intrinsic(template, "Fn::GetAtt")
               if a[0] not in resources}

    assert not unknown, f"{name} reads attributes of undeclared resources: {unknown}"


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_resource_declares_a_type(name):
    template = load_template(name)

    missing = [k for k, v in template["Resources"].items() if "Type" not in v]

    assert not missing, f"{name} has resources with no Type: {missing}"


# - the seam between the two stacks

def test_pipeline_imports_exactly_what_storage_exports():
    # a mismatch here is the classic cross-stack failure: the deploy stops with
    # "No export named ..." and names neither the template nor the typo
    storage, pipeline = load_template("storage.yaml"), load_template("pipeline.yaml")

    exported = {output["Export"]["Name"]["Fn::Sub"]
                for output in storage["Outputs"].values()}
    imported = {value["Fn::Sub"]
                for value in find_intrinsic(pipeline, "Fn::ImportValue")}

    assert imported <= exported, f"pipeline imports what storage never exports: {imported - exported}"


def test_the_archive_survives_its_stack_being_deleted():
    # re-running ingestion gets today's data, never last month's, so the bucket
    # must outlive the stack that happened to create it
    bucket = load_template("storage.yaml")["Resources"]["RawBucket"]

    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"


def test_the_archive_is_private_and_encrypted():
    bucket = load_template("storage.yaml")["Resources"]["RawBucket"]["Properties"]

    assert all(bucket["PublicAccessBlockConfiguration"].values())
    assert bucket["BucketEncryption"]


def test_failed_slices_land_in_a_dead_letter_queue():
    storage = load_template("storage.yaml")["Resources"]
    redrive = storage["IngestQueue"]["Properties"]["RedrivePolicy"]

    assert redrive["deadLetterTargetArn"] == {"Fn::GetAtt": ["IngestDeadLetterQueue", "Arn"]}
    assert redrive["maxReceiveCount"] == {"Ref": "MaxReceiveCount"}


# - the pipeline's wiring

def test_both_environments_are_configured():
    mappings = load_template("pipeline.yaml")["Mappings"]["EnvironmentConfig"]

    assert set(mappings) == {"dev", "prod"}
    # every environment has to define every setting, or a deploy fails on a
    # missing map key rather than falling back to anything
    assert set(mappings["dev"]) == set(mappings["prod"])


def test_no_schedule_fetches_from_sec_without_someone_turning_it_on():
    # A dev stack must not quietly run a full universe fetch against SEC on a
    # timer. Prod is off for a different reason: the scheduled task reads an
    # ingest image from ECR that serve.sh does not push, so a first deploy with
    # this ENABLED is a daily failure and nothing else. Turning it on is a
    # deliberate edit once the image is there.
    mappings = load_template("pipeline.yaml")["Mappings"]["EnvironmentConfig"]

    assert mappings["dev"]["ScheduleState"] == "DISABLED"
    assert mappings["prod"]["ScheduleState"] == "DISABLED"


def test_every_findinmap_reads_a_map_that_exists():
    template = load_template("pipeline.yaml")
    mappings = template["Mappings"]

    for map_name, _, key in find_intrinsic(template, "Fn::FindInMap"):
        assert map_name in mappings, f"no such mapping: {map_name}"
        # the second level is the environment, which is a Ref, so check the
        # setting name against every environment
        for environment, settings in mappings[map_name].items():
            assert key in settings, f"{map_name}.{environment} has no {key}"


def test_the_runner_starts_the_container_the_task_definition_declares():
    # the runner overrides the container by name, and a mismatch means ECS
    # rejects the RunTask call at runtime, not at deploy time
    pipeline = load_template("pipeline.yaml")["Resources"]
    declared = pipeline["IngestTaskDefinition"]["Properties"]["ContainerDefinitions"][0]["Name"]
    configured = pipeline["RunnerFunction"]["Properties"]["Environment"]["Variables"]["CONTAINER_NAME"]

    assert declared == configured == "ingest"


def test_the_queue_reports_failures_per_message():
    # this is what makes the runner's batchItemFailures response mean anything
    mapping = load_template("pipeline.yaml")["Resources"]["QueueToRunner"]["Properties"]

    assert mapping["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    assert mapping["BatchSize"] == 1


def test_the_lambda_handlers_match_the_deployed_modules():
    # the handler string points at a file in the zip, and getting it wrong fails
    # only when the function is first invoked
    pipeline = load_template("pipeline.yaml")["Resources"]

    assert pipeline["DispatchFunction"]["Properties"]["Handler"] == "dispatch.handler"
    assert pipeline["RunnerFunction"]["Properties"]["Handler"] == "runner.handler"

    lambda_dir = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "lambdas")
    assert os.path.exists(os.path.join(lambda_dir, "dispatch.py"))
    assert os.path.exists(os.path.join(lambda_dir, "runner.py"))


def test_the_visibility_timeout_covers_the_runner_timeout():
    # a message redelivered while the runner is still working on it starts the
    # same slice twice
    storage = load_template("storage.yaml")
    pipeline = load_template("pipeline.yaml")

    visibility = storage["Parameters"]["QueueVisibilityTimeout"]["Default"]
    runner_timeout = pipeline["Resources"]["RunnerFunction"]["Properties"]["Timeout"]

    assert visibility >= runner_timeout


def test_the_database_url_is_a_secret_not_a_plain_variable():
    pipeline = load_template("pipeline.yaml")
    container = pipeline["Resources"]["IngestTaskDefinition"]["Properties"] \
        ["ContainerDefinitions"][0]

    # it must arrive via Secrets, so the password isn't readable in the task definition
    assert any(s["Name"] == "DATABASE_URL" for s in container["Secrets"])
    assert not any(e["Name"] == "DATABASE_URL" for e in container["Environment"])
    assert pipeline["Parameters"]["DatabaseUrl"]["NoEcho"] is True


# - the parameter files

@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_parameter_files_match_the_templates_parameters(environment):
    with open(os.path.join(CFN_DIR, "params", f"{environment}.json")) as f:
        provided = {p["ParameterKey"]: p["ParameterValue"] for p in json.load(f)}

    template = load_template("pipeline.yaml")
    declared = template["Parameters"]

    # nothing in the file that the template doesn't take
    assert set(provided) <= set(declared), \
        f"{environment}.json sets parameters the template has no use for"

    # everything without a default is supplied, except the secret
    required = {name for name, spec in declared.items() if "Default" not in spec}
    assert required - set(provided) == {"DatabaseUrl"}

    assert provided["Environment"] == environment


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_no_secret_is_committed_in_a_parameter_file(environment):
    # DatabaseUrl is passed on the command line on purpose. these files are in git.
    with open(os.path.join(CFN_DIR, "params", f"{environment}.json")) as f:
        keys = {p["ParameterKey"] for p in json.load(f)}

    assert "DatabaseUrl" not in keys
