# Deploying Readbase

Three stacks. `storage` and `pipeline` already existed and run the ingestion;
`serving` is what answers a request.

Only the frontend is reachable from the internet. The API sits on a private
Cloud Map name that resolves nowhere outside the VPC, because every call the
browser makes goes through the frontend's own route handlers — so no browser
ever needs the API. The shared secret on `/ask` sits behind that as a second
line rather than the only one.

---

## The prerequisite: a database with the corpus in it

`deploy.sh` and `serve.sh` both take `DATABASE_URL` as an argument. The corpus
lives outside these stacks and nothing serves without it.

A dump is ready at `dumps/biobase-corpus.dump` — 4.8 GB compressed, from a
7.1 GB database, taken 2026-09-05. Eleven tables, the `vector` extension, both
vector spaces (`embedding` and `embedding_ctx`), the full-text index and both
HNSW indexes.

It replaces `readbase-corpus.dump`, which was a schema behind: no
`embedding_ctx` column and no indexes beyond the original btrees. Restoring
that one gives a database the current code cannot use the contextual space on,
and `create_all` will not add the column — it creates missing tables, not
missing columns. Delete the old dump once this one has landed somewhere.

It is gitignored and excluded from both Docker build contexts. Leave it that
way: a 1 GB backup in the build context has already broken one image build with
`no space left on device`.

### Standing up the target

RDS Postgres 15.2 or later, which is where `pgvector` became available. The
extension has to exist before the restore, and creating it needs `rds_superuser`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then restore. `--no-owner --no-acl` because the dump came from a local role
that does not exist on RDS:

```bash
pg_restore \
  --host <instance>.rds.amazonaws.com --username <master> \
  --dbname biotech --no-owner --no-acl --jobs 4 \
  dumps/biobase-corpus.dump
```

Expect this to take a while and to want disk headroom on the instance — the
restored database is 7.1 GB, of which 2.8 GB is the HNSW indexes. Run it from
something with bandwidth to spare: 4.8 GB over a domestic uplink is the slowest
part of the whole deploy by a wide margin, and copying the dump to an EC2 box
in the same region first means waiting once rather than on every retry.

### Checking it landed

```sql
SELECT count(*) FROM companies;      -- 787
SELECT count(*) FROM filings;        -- 3,614
SELECT count(*) FROM filing_chunks;  -- 334,624
SELECT count(*) FROM trials;         -- 30,823
```

Those four are also what the banner reads from `/stats`, so a wrong number here
shows up on the page rather than staying hidden.

### The vector index comes with the dump

`pg_restore` rebuilds it on the way in, which is most of why the restore takes
as long as it does — and worth it, because `--jobs` builds indexes in parallel
where running the migration afterwards is one at a time. Without an index every
semantic lookup reads all 334,624 vectors: 4,763 ms against 2 ms, measured.

For a database that predates it — the old dump, or one restored before
2026-09-05 — build it explicitly. Safe to re-run either way: each index is
created only if it is missing.

```bash
DATABASE_URL='postgresql+psycopg://…' python backend/migrate_vector_index.py
```

Pass `--dry-run` first for the sizes.

On the instance that will serve, raise `--build-memory` to whatever it has
spare. Below the size of the graph, about 2 GB here, pgvector builds in two
passes and spills to disk.

**Running Postgres in a container needs `shm_size` raised.** A parallel index
build sizes its shared memory segments from `maintenance_work_mem`, Docker
gives a container 64 MB of `/dev/shm`, and the failure is a `DiskFull` naming
shared memory while the disk has room. `docker-compose.yml` sets 2 GB. RDS does
not have this problem.

---

## The OpenAI key

Into Secrets Manager, not a parameter file:

```bash
aws secretsmanager create-secret \
  --name readbase/prod/openai --secret-string 'sk-…'
```

Keep the ARN. `serve.sh` takes it and passes it to ECS by reference, so the key
never appears in a template, a parameter file or a stack event.

The `/ask` secret is not supplied — `serving.yaml` generates it, both services
read the same one, and rotating it is a stack update.

---

## Deploying

```bash
# ingestion: archive, queue, schedule, batch task
./infra/deploy.sh prod s3://<artifacts-bucket> 'postgresql+psycopg://…'

# serving: load balancer, frontend, API
./infra/serve.sh prod 'postgresql+psycopg://…' arn:aws:secretsmanager:…:readbase/prod/openai
```

`serve.sh` builds and pushes both images under a dated tag, reads the cluster
and repository out of the pipeline stack, and deploys `serving.yaml` on top.

Before either script runs, `infra/cloudformation/params/prod.json` needs real
values: `VpcId`, `SubnetIds`, `LambdaCodeS3Bucket` and `SecUserAgent` all ship
as `REPLACE_ME`. Two subnets in **different availability zones** — the load
balancer requires two, and `serve.sh` hands the same list to the tasks. They
have to be public, because `AssignPublicIp` is `ENABLED` and the tasks pull
from ECR, read Secrets Manager and call OpenAI; private subnets with no NAT
gateway give you tasks that never start. The artifacts bucket must already
exist: `deploy.sh` uploads into it and does not create it.

### Then let the API reach the database

The database is not in these stacks, so nothing in CloudFormation can open a
path to it. Take `ApiSecurityGroupId` from the serving stack's outputs and
allow it on 5432 in the RDS instance's own security group.

Skip this and the failure is quiet: the tasks start, pass their health check on
`/` — which does not touch the database on purpose — and fail every query.

### Updating the corpus after it is up

Nothing here is write-once. The pipeline stack exists to refresh it, and every
row is derived — from SEC, ClinicalTrials.gov and the FDA — so there is no
state on the server that cannot be rebuilt. To start a run by hand:

```bash
aws lambda invoke --function-name biotech-agent-dispatch-prod /dev/stdout
```

Schema changes are hand-written scripts, not a migration framework. `init_db()`
is `create_all`, which creates missing **tables** and not missing **columns** —
so a new column in `models.py` does nothing to a live database, silently. That
is what left `embedding_ctx` out of the old dump. The pattern to follow is
`migrate_vector_index.py` and the `backfill_*.py` scripts: idempotent, with a
`--dry-run`.

Deploys are rolling — `MinimumHealthyPercent: 100`, `MaximumPercent: 200` — so
both versions of the code run against the same database for the length of one
deploy. A schema change has to be safe for both: add the column, deploy the
code that uses it, remove the old one in a later deploy.

### Ingestion is off

`pipeline.yaml` ships with the prod schedule `DISABLED`. The task it starts
reads an ingest image from ECR, and `serve.sh` pushes only `api-<timestamp>`
and `web-<timestamp>` — so with it enabled, a first deploy fires at 06:00 UTC
into a tag nothing has pushed, once a day, with no ingestion behind it.

Push an ingest image, set `ScheduleState: ENABLED` for prod, update the stack.

Give it the OpenAI key when you do. Ingesting a company replaces its trial rows
and drops their vectors; `ingest.py` carries across the ones whose text has not
changed, and the task then runs `embed_trials.py` for what is genuinely new.
Without a key that second half exits non-zero rather than leaving the task green
and the vectors missing — but a failing daily task is still a failing daily task.

```bash
OPENAI_SECRET_ARN=arn:aws:secretsmanager:…:readbase/prod/openai \
  ./infra/deploy.sh prod s3://<artifacts-bucket> 'postgresql+psycopg://…'
```

A dated tag rather than `:latest` on purpose. With `:latest` the task definition
does not change between deploys, so ECS never pulls, and the stack updates
successfully while running the old image.

Building on Apple silicon produces `arm64`. Fargate refuses it unless the task
definition asks for `ARM64`, and `serve.sh` keeps the two in step:

```bash
PLATFORM=linux/arm64 ./infra/serve.sh prod …   # Graviton, cheaper
```

### HTTPS

The listener is plain HTTP until a certificate is passed. Fine for a first
deploy on the load balancer's own hostname; not fine for anything a person is
asked to trust.

```bash
CERTIFICATE_ARN=arn:aws:acm:… ./infra/serve.sh prod …
```

With one, port 80 stops serving and only redirects.

---

## Running the whole thing locally first

The compose stack is the same two images the serving stack ships, so this
exercises what gets deployed rather than something that resembles it:

```bash
export OPENAI_API_KEY=…  SEC_USER_AGENT='you@example.com'
export READBASE_API_KEY="$(openssl rand -hex 24)"   # optional; see below
docker compose up -d --build
open http://localhost:3000
```

With `READBASE_API_KEY` set on both services, `/ask` requires it and a direct
call to the API without it returns 401. Unset on both, `/ask` stays open, which
is what a local run wants and why the test suite needs no configuration.

---

## What is not covered

- **No autoscaling.** `DesiredCount` is 1 per service. Fine to start, and the
  first thing to raise.
- **No custom domain.** The output is the load balancer's own hostname. A Route
  53 alias and an ACM certificate are the next step.
- **No RDS in the templates.** The database is a parameter, deliberately: its
  lifecycle should not be tied to a stack that gets torn down and rebuilt.
- **No WAF.** `/ask` has a daily budget counted in the database — 500 questions
  per UTC day for everyone together, set by `AskDailyBudget` — and a per-caller
  burst limit in the frontend's route handler. The budget is the one that
  holds; the per-caller limit is fairness, since anyone can change address.
  Neither stops traffic arriving, they stop it being expensive. **Set a monthly
  limit in the OpenAI dashboard as well**: it is the only ceiling that survives
  a bug in this code, and this code is what would have the bug.
