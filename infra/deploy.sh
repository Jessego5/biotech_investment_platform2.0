#!/usr/bin/env bash
#
# This deploys the ingestion pipeline for one environment. It packages the two
# Lambda functions, uploads them, and deploys both stacks in order, storage first
# because the pipeline imports from it, and re-running it is the normal way to
# ship a change since CloudFormation works out the difference. It does not build
# or push the container image, which is a separate step because it needs Docker
# and because the image changes far less often; build it for the architecture the
# stack is deployed with, since an Apple Silicon machine produces ARM64 and
# Fargate defaults to X86_64, failing at task start with "exec format error"
# rather than at build time.
#
# Fill in infra/cloudformation/params/<env>.json first: it ships with REPLACE_ME
# for the VPC, the subnets, the artifacts bucket and the SEC contact address, and
# the bucket has to exist already because this uploads into it.
#
#   ./infra/deploy.sh prod s3://my-deploy-artifacts 'postgresql+psycopg://...'
#
# Set OPENAI_SECRET_ARN as well if you want a scheduled run to embed the trials
# it just wrote.

set -euo pipefail

ENVIRONMENT="${1:-}"
ARTIFACTS_BUCKET="${2:-}"
DATABASE_URL="${3:-}"

if [[ -z "$ENVIRONMENT" || -z "$ARTIFACTS_BUCKET" || -z "$DATABASE_URL" ]]; then
    echo "usage: $0 <dev|prod> <s3://artifacts-bucket> <database-url>" >&2
    exit 1
fi

if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    echo "environment must be dev or prod, got: $ENVIRONMENT" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFN_DIR="$HERE/cloudformation"
BUCKET_NAME="${ARTIFACTS_BUCKET#s3://}"

# a new key per deploy, so updating the stack actually replaces the function code.
# pointing at an unchanged S3 key is the classic "I deployed but nothing changed":
# CloudFormation sees identical properties and does nothing.
CODE_KEY="lambdas-$(date -u +%Y%m%d%H%M%S).zip"

echo "==> packaging the Lambda functions"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
# deployed flat, which is why the handlers are dispatch.handler and runner.handler.
# no dependencies to vendor: both functions use only the standard library plus
# boto3, which the Lambda runtime already provides.
zip -j -q "$BUILD_DIR/lambdas.zip" "$HERE/lambdas/dispatch.py" "$HERE/lambdas/runner.py"

echo "==> uploading to s3://$BUCKET_NAME/$CODE_KEY"
aws s3 cp "$BUILD_DIR/lambdas.zip" "s3://$BUCKET_NAME/$CODE_KEY"

echo "==> deploying storage (archive and queue)"
# no --no-execute-changeset: this stack is nearly always a no-op after the first
# deploy, and CloudFormation treats "no changes" as success here
aws cloudformation deploy \
    --stack-name "biotech-agent-storage-$ENVIRONMENT" \
    --template-file "$CFN_DIR/storage.yaml" \
    --parameter-overrides "Environment=$ENVIRONMENT" \
    --no-fail-on-empty-changeset

echo "==> deploying pipeline (schedule, queue consumer, tasks)"
# read the committed parameters and turn them into the Key=Value form deploy wants.
# a read loop rather than mapfile, because macOS still ships bash 3.2 and mapfile
# is a bash 4 builtin, so mapfile would fail on the machine this is written on.
OVERRIDES=()
while IFS= read -r line; do
    OVERRIDES+=("$line")
done < <(
    python3 -c "
import json
with open('$CFN_DIR/params/$ENVIRONMENT.json') as f:
    for p in json.load(f):
        print(f\"{p['ParameterKey']}={p['ParameterValue']}\")
"
)

# Optional, and an environment variable rather than a fourth argument so the
# usage above keeps working. Without it the scheduled run still ingests, and the
# embed step fails loudly rather than leaving the vectors missing on a task that
# reported success.
#
#   OPENAI_SECRET_ARN=arn:aws:secretsmanager:... ./infra/deploy.sh prod ...
aws cloudformation deploy \
    --stack-name "biotech-agent-pipeline-$ENVIRONMENT" \
    --template-file "$CFN_DIR/pipeline.yaml" \
    --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
        "${OVERRIDES[@]}" \
        "LambdaCodeS3Bucket=$BUCKET_NAME" \
        "LambdaCodeS3Key=$CODE_KEY" \
        "DatabaseUrl=$DATABASE_URL" \
        ${OPENAI_SECRET_ARN:+"OpenAiSecretArn=$OPENAI_SECRET_ARN"}

echo
echo "==> done. stack outputs:"
aws cloudformation describe-stacks \
    --stack-name "biotech-agent-pipeline-$ENVIRONMENT" \
    --query "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}" \
    --output table

echo
echo "The schedule for $ENVIRONMENT is set by the template (dev is DISABLED on purpose)."
echo "To start a run by hand:"
echo "  aws lambda invoke --function-name biotech-agent-dispatch-$ENVIRONMENT /dev/stdout"
