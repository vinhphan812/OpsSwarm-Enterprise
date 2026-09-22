.PHONY: install test run check-openclaw
install:
	python -m pip install -e '.[dev]'
test:
	pytest -q
run:
	OPSWARM_CONFIG=config/production.yaml uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088
check-openclaw:
	./scripts/check_openclaw.sh
