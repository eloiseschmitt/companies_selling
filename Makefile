PYTHON ?= python3
RUFF ?= ruff
MYPY ?= mypy
COVERAGE ?= coverage

.PHONY: format lint type test coverage quality

format:
	$(RUFF) format .

lint:
	$(RUFF) check .

type:
	$(MYPY) .

test:
	$(PYTHON) -m unittest discover -s tests

coverage:
	$(COVERAGE) run -m unittest discover -s tests
	$(COVERAGE) report -m

quality: lint type test
