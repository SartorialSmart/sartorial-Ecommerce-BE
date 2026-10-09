# SartorialEcommerce backend — common commands.
#
# Packages are managed with `uv` (https://docs.astral.sh/uv/). `uv run` executes
# inside the project environment described by pyproject.toml + uv.lock, syncing
# it on demand, so there's no separate "activate the venv" step.
#
# The database comes from .env (USE_SQLITE / POSTGRES_*). With no .env at all the
# defaults fall through to Postgres on localhost; export USE_SQLITE=1 for a
# service-free SQLite run, and point REDIS_URL at a real server for a worker/beat
# (unset => locmem cache + inline Celery).

UV ?= uv
RUN := $(UV) run
MANAGE := $(RUN) python manage.py

# Defaults only when .env doesn't supply them — never shadow a checked-out .env,
# otherwise `make run` and `uv run manage.py ...` would disagree on the DB and
# the JWT signing key.
export DJANGO_SETTINGS_MODULE ?= config.settings.dev

.DEFAULT_GOAL := help
.PHONY: help install lock sync run worker beat shell migrate makemigrations \
        check superuser test test-cov lint format typecheck schema clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: sync ## Alias for `sync`

lock: ## Update uv.lock from pyproject.toml
	$(UV) lock

sync: ## Install/refresh the environment (incl. dev tools) from uv.lock
	$(UV) sync

run: ## Run the dev server (http://localhost:8000)
	$(MANAGE) runserver 0.0.0.0:8000

worker: ## Run a Celery worker
	$(RUN) celery -A config worker -l info

beat: ## Run Celery Beat (scheduled tasks)
	$(RUN) celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

shell: ## Open the Django shell
	$(MANAGE) shell

migrate: ## Apply database migrations
	$(MANAGE) migrate

makemigrations: ## Create new migrations from model changes
	$(MANAGE) makemigrations

check: ## Run Django system checks + migration drift check
	$(MANAGE) check
	$(MANAGE) makemigrations --check --dry-run

superuser: ## Create a superuser (admin role)
	$(MANAGE) createsuperuser

seed: ## Seed demo data (currencies + rates, catalog, coupons)
	$(MANAGE) seed_currencies
	$(MANAGE) seed_catalog
	$(MANAGE) seed_coupons

test: ## Run the test suite
	$(RUN) pytest

test-cov: ## Run tests with coverage
	$(RUN) pytest --cov=apps --cov-report=term-missing

lint: ## Lint with ruff + check formatting with black
	$(RUN) ruff check .
	$(RUN) black --check .

format: ## Auto-fix lint issues and format the code
	$(RUN) ruff check --fix .
	$(RUN) black .

typecheck: ## Static type-check with mypy
	$(RUN) mypy .

schema: ## Generate the OpenAPI schema to schema.yml
	$(MANAGE) spectacular --file schema.yml

clean: ## Remove caches and the local SQLite database
	rm -rf .pytest_cache .ruff_cache .mypy_cache db.sqlite3
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
