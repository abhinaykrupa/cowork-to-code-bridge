# Contributing

Thanks for your interest. This is a small, single-author project; PRs and issues
are welcome and triaged best-effort.

## Ground rules

- **macOS only** for now. The daemon relies on `launchd` and Mac system tools.
  Cross-platform (systemd / Windows) support is a welcome contribution but is a
  bigger lift — open an issue first.
- **No new runtime dependencies.** The client and daemon are deliberately pure
  Python standard library. Keep them dependency-free.
- **Don't break the safety model.** The daemon must only run whitelisted scripts,
  must keep the token check, and must not open a network listener.
- **Keep crash-resilience intact.** Don't change the result-write → journal →
  inflight-clear → queue-move ordering in `daemon.py` without understanding the
  recovery logic (see `docs/architecture.md`).

## Dev setup

```bash
git clone https://github.com/abhinaykrupa/cowork-to-code-bridge
cd cowork-to-code-bridge
python3 -m pip install -e ".[dev]"   # pytest + ruff
```

## Running checks

```bash
pytest -q          # full test suite (unit + e2e + sync guards)
ruff check .       # lint
bash -n install.sh # shell syntax check
```

If you prefer shortcuts, the repository `Makefile` mirrors the core local workflow:

```bash
make install
make test
make lint
make uninstall
```

All of these run in CI on every PR (see `.github/workflows/ci.yml`). PRs should
keep the suite green.

## Two copies of the client — keep them in sync

There are intentionally two copies of the client:

- `cowork_to_code_bridge/client.py` — the importable package version.
- `bridge_client.py` (repo root) + `skill/cowork-to-code-bridge/bridge_client.py`
  — the single-file, stdlib-only copy that ships inside the global skill.

`tests/test_single_file_client.py` guards that the single-file copy stays
stdlib-only and that its `call_remote` / `call_remote_streaming` signatures match
the package. If you change the client API, update **all** copies and the guard
test will keep you honest. Same for `daemon/daemon.py`, which mirrors
`cowork_to_code_bridge/daemon.py`.

## Commit / PR conventions

- Conventional-ish prefixes (`feat:`, `fix:`, `docs:`) are appreciated.
- Describe *what changed and why*; note anything you verified manually.
- Bump the version in `pyproject.toml`, `.claude-plugin/plugin.json`, and the
  client `__version__` together for releases, and add a `CHANGELOG.md` entry.

## Security

If you find a security issue (e.g. a way to escape the script whitelist or bypass
the token), please open a private report rather than a public issue.
