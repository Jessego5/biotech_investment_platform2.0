# The commands worth remembering. Everything here runs offline except `ingest`
# and `embed`, which fetch from SEC and ClinicalTrials.gov and cost money at
# OpenAI, so those are never part of `make check`.

VENV := backend/venv/bin

.PHONY: help
help:  ## show this
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t22

.PHONY: dev
dev:  ## bring up Postgres, the API and the frontend locally
	docker compose up -d --build
	@echo "http://localhost:3000"

.PHONY: down
down:  ## stop the local stack, keeping the database volume
	docker compose down

.PHONY: test
test:  ## both suites, offline
	cd backend && $(CURDIR)/$(VENV)/python -m pytest -q
	npm test

.PHONY: lint
lint:  ## types and lint on the frontend
	npx tsc --noEmit
	npx eslint app components lib

.PHONY: check
check: lint test  ## what CI runs

.PHONY: eval
eval:  ## the grounded-answer suite; needs OPENAI_API_KEY, costs a few cents
	cd backend && $(CURDIR)/$(VENV)/python evaluate.py

.PHONY: eval-retrieval
eval-retrieval:  ## the retrieval suite against the stored query set; free
	cd backend && $(CURDIR)/$(VENV)/python eval_retrieval.py

.PHONY: schema
schema:  ## report columns the database is missing, and add them
	cd backend && $(CURDIR)/$(VENV)/python migrate_schema.py --dry-run
