.PHONY: install run check-openclaw lint typecheck test-unit test coverage build ci migrate migrate-up migrate-down alembic-check

install:
	python -m pip install -e '.[dev]'

run:
	OPSWARM_CONFIG=config/production.yaml uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088

check-openclaw:
	./scripts/check_openclaw.sh

lint:
	python -m ruff check . --exclude ".worktrees" --exclude "build" --exclude "dist*" --exclude "venv"
	python -m ruff format --check opsswarm/commands.py opsswarm/policy.py opsswarm/webhook.py

typecheck:
	python -m mypy

test-unit:
	python -m pytest -q -m unit

test:
	python -m pytest -q

coverage:
	python -m pytest -q --cov=opsswarm --cov-report=term-missing --cov-fail-under=90

build:
	python -m build

ci: lint typecheck test coverage build

# ---------------------------------------------------------------------------
# Issue #70 — Alembic HA migrations (ADR-030 § Migration Strategy)
# Requires: pip install -e '.[ha]'
# Requires: export HA_DATABASE_URL=postgresql://user:pass@host:5432/dbname
# ---------------------------------------------------------------------------

alembic-check:
	@python -c "import alembic; import sqlalchemy" 2>/dev/null || (echo "ERROR: Run 'pip install -e \".[ha]\"' first" && exit 1)
	alembic check

migrate: migrate-up

migrate-up:
	@python -c "import alembic; import sqlalchemy" 2>/dev/null || (echo "ERROR: Run 'pip install -e \".[ha]\"' first" && exit 1)
	@test -n "$$HA_DATABASE_URL" || (echo "ERROR: HA_DATABASE_URL is not set. Run: export HA_DATABASE_URL='postgresql://user:pass@host:5432/dbname'" && exit 1)
	alembic upgrade head

migrate-down:
	@python -c "import alembic; import sqlalchemy" 2>/dev/null || (echo "ERROR: Run 'pip install -e \".[ha]\"' first" && exit 1)
	@test -n "$$HA_DATABASE_URL" || (echo "ERROR: HA_DATABASE_URL is not set" && exit 1)
	alembic downgrade -1
