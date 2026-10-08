# Checks run LOCALLY (GitHub Actions only builds/publishes releases).
#   make check         lint + shell syntax/tests + pytest + selfcheck smoke  (pre-push gate)
#   make e2e           real install.sh + uninstaller in clean Docker containers
#   make brew-audit    brew audit --strict on the Homebrew formula
#   make check-matrix  pytest on every installed Python 3.10 / 3.11 / 3.12
#   make hooks         enable .githooks/pre-push (runs `make check` before push)

VENV := .venv
# Prefer the repo venv; fall back to whatever python3 is on PATH.
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
PIP := $(PYTHON) -m pip
BIN := $(dir $(abspath $(PYTHON)))
# Put the venv's bin first so console scripts used by tests resolve to it.
export PATH := $(BIN):$(PATH)

SHELL_SCRIPTS := install.sh daemon/uninstall.sh scripts/lib/platform.sh \
  scripts/lib/daemon_service.sh scripts/ci-wsl-smoke.sh scripts/e2e-install.sh \
  $(wildcard examples/allowed_scripts/*.sh) \
  tests/test_reverse_inbox.sh tests/test_platform_detection.sh tests/test_manual_daemon.sh

E2E_IMAGE ?= python:3.12-slim
MATRIX_PYTHONS ?= 3.10 3.11 3.12

.PHONY: install venv test lint shell-check shell-tests selfcheck check e2e brew-audit \
  check-matrix hooks uninstall

install:
	$(PIP) install -e ".[dev]"

# Create .venv (needs Python >= 3.10) and install dev extras.
venv:
	@test -x $(VENV)/bin/python || { \
	  py=$$(for p in python3.12 python3.11 python3.10 python3; do command -v $$p && break; done); \
	  echo "creating $(VENV) with $$py"; "$$py" -m venv $(VENV); }
	$(VENV)/bin/python -m pip install -q -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

shell-check:
	@for s in $(SHELL_SCRIPTS); do bash -n $$s || exit 1; done; echo "shell syntax OK"

# These self-skip off Linux where they need to (test_manual_daemon.sh).
shell-tests:
	bash tests/test_reverse_inbox.sh
	bash tests/test_platform_detection.sh
	bash tests/test_manual_daemon.sh

selfcheck:
	$(PYTHON) -m cowork_to_code_bridge.selfcheck --smoke

# Everything ci.yml + selfcheck.yml ran, for the current OS/Python.
check: lint shell-check shell-tests test selfcheck
	@echo "make check: OK"

# Port of install-e2e.yml: real install.sh + uninstaller, both layouts, each in a fresh
# non-root container (no systemd user bus -> exercises the manual setsid path).
# Needs a running Docker daemon; skips (exit 0) with a message if absent.
# Repo is mounted read-only and copied; HOME and /tmp are tmpfs, so nothing touches
# the host and it still works when the Docker VM's disk is nearly full.
# The stock python image has no cron, so the @reboot-cron bits are exercised only if
# E2E_IMAGE provides `crontab` (the installer treats cron as optional).
e2e:
	@command -v docker >/dev/null 2>&1 || { echo "SKIP e2e: docker CLI not installed"; exit 0; }; \
	docker info >/dev/null 2>&1 || { echo "SKIP e2e: Docker daemon not running (start Docker Desktop/colima, then re-run make e2e)"; exit 0; }; \
	for layout in default hardened; do \
	  echo "=== e2e layout: $$layout (image $(E2E_IMAGE)) ==="; \
	  docker run --rm --user 1000:1000 -e HOME=/home/tester \
	    --tmpfs /tmp:exec --tmpfs /home/tester:uid=1000,exec,size=512m \
	    -v "$(CURDIR)":/src:ro $(E2E_IMAGE) \
	    bash -c 'cp -r /src "$$HOME/repo" && cd "$$HOME/repo" && command -v crontab >/dev/null || echo "NOTE: no crontab in image; @reboot cron path not exercised"; REPO="$$HOME/repo" bash scripts/e2e-install.sh '$$layout \
	  || { echo "e2e FAILED (layout: $$layout)"; exit 1; }; \
	done; echo "make e2e: OK"

# Port of homebrew-audit.yml. Skips (exit 0) if Homebrew is not installed.
brew-audit:
	@command -v brew >/dev/null 2>&1 || { echo "SKIP brew-audit: Homebrew not installed"; exit 0; }; \
	tap_dir="$$(brew --repository)/Library/Taps/local/homebrew-tap/Formula"; \
	mkdir -p "$$tap_dir" && cp packaging/homebrew/cowork-to-code-bridge.rb "$$tap_dir/"; \
	brew audit --strict local/tap/cowork-to-code-bridge; rc=$$?; \
	rm -f "$$tap_dir/cowork-to-code-bridge.rb"; t=$$(dirname "$$tap_dir"); rmdir "$$tap_dir" "$$t" "$$(dirname "$$t")" 2>/dev/null; exit $$rc

# pytest across every available Python in MATRIX_PYTHONS (uv preferred, else pythonX.Y).
# Each version gets its own throwaway venv in .venv-matrix/ (gitignored).
check-matrix:
	@ran=0; for v in $(MATRIX_PYTHONS); do \
	  if command -v uv >/dev/null 2>&1 && uv python find --no-project $$v >/dev/null 2>&1; then \
	    py=$$(uv python find --no-project $$v); \
	  elif command -v python$$v >/dev/null 2>&1; then py=$$(command -v python$$v); \
	  else echo "SKIP python $$v: not installed"; continue; fi; \
	  echo "=== python $$v ($$py) ==="; \
	  "$$py" -m venv .venv-matrix/$$v >/dev/null && \
	  .venv-matrix/$$v/bin/python -m pip install -q -e ".[dev]" && \
	  .venv-matrix/$$v/bin/python -m ruff check . && \
	  .venv-matrix/$$v/bin/python -m pytest -q || { echo "check-matrix FAILED on $$v"; exit 1; }; \
	  ran=$$((ran+1)); \
	done; [ $$ran -gt 0 ] || { echo "check-matrix: no matching Python found"; exit 1; }; \
	echo "make check-matrix: OK ($$ran versions)"

hooks:
	git config core.hooksPath .githooks
	@echo "git hooks enabled: .githooks/pre-push runs 'make check' (skip once: git push --no-verify)"

uninstall:
	cowork-to-code-bridge-uninstall --yes || $(PYTHON) -m pip uninstall -y cowork-to-code-bridge
