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

A dump is ready at `dumps/readbase-corpus.dump` — 2.7 GB compressed, from a
4,090 MB database. Eleven tables, the `vector` extension, and both of the
migrations run so far. Verified by restoring its schema into a scratch database.

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
  dumps/readbase-corpus.dump
```

Expect this to take a while and to want disk headroom on the instance. Run it
from something with bandwidth to spare — 2.7 GB over a domestic uplink is the
slowest part of the whole deploy.

### Checking it landed

```sql
SELECT count(*) FROM companies;      -- 787
SELECT count(*) FROM filings;        -- 3,614
SELECT count(*) FROM filing_chunks;  -- 334,624
SELECT count(*) FROM trials;         -- 30,823
```

Those four are also what the banner reads from `/stats`, so a wrong number here
shows up on the page rather than staying hidden.

### Then build the vector index

The dump predates the index, so a fresh restore has none and every semantic
lookup reads all 334,624 vectors — 2.2 GB per question. This is the single
largest thing that decides the instance size, so it is worth doing before
choosing one rather than after.

```bash
DATABASE_URL='postgresql+psycopg://…' python backend/migrate_vector_index.py
```

Slow, and safe to re-run: each index is built only if it is missing. Pass
`--dry-run` first for the sizes.

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
- **No WAF or rate limit.** The `/ask` guard caps who can spend, not how fast.
  A determined holder of the key can still run up a bill.
