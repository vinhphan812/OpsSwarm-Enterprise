.PHONY: install run check-openclaw lint typecheck test-unit test coverage build ci

install:
	python -m pip install -e '.[dev]'

run:
	OPSWARM_CONFIG=config/production.yaml uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088

check-openclaw:
	./scripts/check_openclaw.sh

lint:
	python -m ruff check .
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
