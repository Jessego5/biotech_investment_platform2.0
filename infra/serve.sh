#!/usr/bin/env bash
#
# This deploys the serving stack: the frontend behind a public load balancer and
# the API beside it on the private network. It builds and pushes both images
# under a dated tag, reads the cluster and ECR repository out of the pipeline
# stack, and deploys serving.yaml on top, so infra/deploy.sh has to have run
# first. A dated tag rather than latest on purpose, because with latest the task
# definition does not change between deploys, so ECS never pulls and the stack
# updates successfully while still running the old image.
#
# The API is deliberately not published: nothing outside the VPC can resolve or
# reach it, because the frontend proxies every call through its own route
# handlers and no browser ever needs it. After the first deploy, allow the
# stack's ApiSecurityGroupId on 5432 in the database's own security group, or
# the tasks will start, pass their health check and fail every query.
#
#   ./infra/serve.sh prod 'postgresql+psycopg://...' arn:aws:secretsmanager:...
#
# Set PLATFORM=linux/arm64 on an Apple Silicon machine, and CERTIFICATE_ARN to
# serve HTTPS instead of plain HTTP.

set -euo pipefail

ENVIRONMENT="${1:-}"
DATABASE_URL="${2:-}"
OPENAI_SECRET_ARN="${3:-}"

if [[ -z "$ENVIRONMENT" || -z "$DATABASE_URL" || -z "$OPENAI_SECRET_ARN" ]]; then
    echo "usage: $0 <dev|prod> <database-url> <openai-secret-arn>" >&2
    echo >&2
    echo "The OpenAI key goes in as a Secrets Manager ARN, not a value, so it" >&2
    echo "never lands in a shell history, a parameter file or a stack event." >&2
    exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
CFN_DIR="$HERE/cloudformation"
PIPELINE_STACK="biotech-agent-pipeline-$ENVIRONMENT"
REGION="${AWS_REGION:-$(aws configure get region)}"

output() {
    aws cloudformation describe-stacks --stack-name "$1" \
        --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

echo "==> reading the pipeline stack"
CLUSTER="$(output "$PIPELINE_STACK" ClusterName)"
REPOSITORY_URI="$(output "$PIPELINE_STACK" RepositoryUri)"
if [[ -z "$CLUSTER" || "$CLUSTER" == "None" ]]; then
    echo "No cluster in $PIPELINE_STACK. Run infra/deploy.sh $ENVIRONMENT first." >&2
    exit 1
fi
echo "    cluster    $CLUSTER"
echo "    repository $REPOSITORY_URI"

# a tag per deploy. ":latest" is how you update a stack and get the old image
# back: the task definition does not change, so ECS never pulls.
TAG="$(date -u +%Y%m%d%H%M%S)"
API_IMAGE="$REPOSITORY_URI:api-$TAG"
WEB_IMAGE="$REPOSITORY_URI:web-$TAG"

echo "==> logging in to ECR"
aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "${REPOSITORY_URI%%/*}"

# --platform matters: a machine building on Apple silicon produces arm64 images,
# and Fargate refuses them unless the task definition asks for ARM64. Build for
# the architecture the stack is deployed with.
PLATFORM="${PLATFORM:-linux/amd64}"
ARCH="X86_64"
[[ "$PLATFORM" == "linux/arm64" ]] && ARCH="ARM64"

echo "==> building the API image ($PLATFORM)"
docker build --platform "$PLATFORM" -t "$API_IMAGE" "$ROOT/backend"
docker push "$API_IMAGE"

echo "==> building the frontend image ($PLATFORM)"
docker build --platform "$PLATFORM" -t "$WEB_IMAGE" "$ROOT"
docker push "$WEB_IMAGE"

echo "==> deploying the serving stack"
OVERRIDES=()
while IFS= read -r line; do
    OVERRIDES+=("$line")
done < <(
    python3 -c "
import json
# reuse the network the pipeline already deploys into, so the two stacks cannot
# disagree about which VPC they are in
keep = {'VpcId', 'SubnetIds', 'AssignPublicIp', 'SecUserAgent'}
with open('$CFN_DIR/params/$ENVIRONMENT.json') as f:
    for p in json.load(f):
        if p['ParameterKey'] in keep:
            key = p['ParameterKey']
            # serving.yaml takes two subnet lists: the load balancer needs public
            # ones in two zones, the tasks can sit anywhere reachable
            if key == 'SubnetIds':
                print(f\"PublicSubnetIds={p['ParameterValue']}\")
                print(f\"ServiceSubnetIds={p['ParameterValue']}\")
            else:
                print(f\"{key}={p['ParameterValue']}\")
"
)

aws cloudformation deploy \
    --stack-name "biotech-agent-serving-$ENVIRONMENT" \
    --template-file "$CFN_DIR/serving.yaml" \
    --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
        "${OVERRIDES[@]}" \
        "Environment=$ENVIRONMENT" \
        "ClusterName=$CLUSTER" \
        "ApiImage=$API_IMAGE" \
        "WebImage=$WEB_IMAGE" \
        "CpuArchitecture=$ARCH" \
        "DatabaseUrl=$DATABASE_URL" \
        "OpenAiSecretArn=$OPENAI_SECRET_ARN" \
        "${CERTIFICATE_ARN:+CertificateArn=$CERTIFICATE_ARN}"

echo
echo "==> done."
aws cloudformation describe-stacks \
    --stack-name "biotech-agent-serving-$ENVIRONMENT" \
    --query "Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}" \
    --output table

echo
echo "The load balancer speaks plain HTTP until you pass a certificate:"
echo "  CERTIFICATE_ARN=arn:aws:acm:... ./infra/serve.sh $ENVIRONMENT ..."
