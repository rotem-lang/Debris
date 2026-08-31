VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help venv test lint fmt clean

help:
	@echo "make venv   - create $(VENV) and install dev dependencies"
	@echo "make test   - run the test suite"
	@echo "make lint   - ruff check + format check"
	@echo "make fmt    - apply ruff formatting"
	@echo "make clean  - remove build artifacts and caches"

$(PY):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

venv: $(PY)

test: $(PY)
	$(VENV)/bin/pytest -q

lint: $(PY)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

fmt: $(PY)
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
