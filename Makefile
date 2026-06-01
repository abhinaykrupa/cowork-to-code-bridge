PYTHON ?= python3
PIP := $(PYTHON) -m pip

.PHONY: install test lint uninstall

install:
	$(PIP) install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .

uninstall:
	cowork-to-code-bridge-uninstall --yes || $(PYTHON) -m pip uninstall -y cowork-to-code-bridge
