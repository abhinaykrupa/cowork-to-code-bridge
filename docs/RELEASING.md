# Releasing to PyPI

This is the maintainer runbook for publishing a release to PyPI. The repo is
already prepped for **0.5.1** (the first PyPI release). Follow this once and the
tag-triggered workflow handles the rest.

> **One irreversible fact:** a PyPI version number is consumed forever on the
> first successful upload — it can never be reused, even after delete/yank. Get
> the first upload right. Everything else (OIDC 403s, failed builds) is recoverable.

---

## One-time setup on PyPI (Trusted Publishing, no tokens)

The project doesn't exist on PyPI yet, so you register a **pending publisher**.

1. **Log in / create an account** at <https://pypi.org>. **2FA is mandatory** —
   enable a TOTP app or security key and save the recovery codes, or you can't
   reach publishing settings.
2. Go to **<https://pypi.org/manage/account/publishing/>** (Account → Publishing).
   This account-level page is the *only* place to register a publisher for a
   project that doesn't exist yet (the project settings page 404s until first upload).
3. Under **"Add a new pending publisher"**, select the **GitHub** tab and fill
   these **exactly** (lowercase, hyphens not underscores):

   | Field | Value |
   |---|---|
   | PyPI Project Name | `cowork-to-code-bridge` |
   | Owner | `abhinaykrupa` |
   | Repository name | `cowork-to-code-bridge` |
   | Workflow name | `publish.yml`  ← **bare filename**, not a path |
   | Environment name | `pypi`  ← must match `environment: pypi` in publish.yml |

4. Click **Add**. It shows as a **pending** publisher — that's correct. It
   converts to a real project on the first successful upload.
5. **On GitHub** (separate from PyPI): repo **Settings → Environments → New
   environment → name it `pypi`**. Add yourself as a **required reviewer** so the
   irreversible upload pauses for one approval click — your abort point.
6. **Do not** create an API token or upload manually. The workflow is OIDC-only.

---

## Publishing a release

The repo is already on **0.5.1** (`pyproject.toml` + 4 mirrored version strings).
For future releases, bump all five version strings first (see "Version strings" below).

```bash
# 0. Clean tree on main
git status && git rev-parse HEAD

# 1. Sanity: no stray old version in shipped code
grep -rn '0\.5\.0' --include='*.py' --include='*.toml' --include='*.json' . \
  | grep -v egg-info | grep -iv changelog   # should print nothing

# 2. Build + validate locally (both must PASS)
rm -rf dist && python -m build && twine check dist/*

# 3. (Optional, recommended) dress rehearsal on Test PyPI — burns a throwaway version
#    twine upload --repository testpypi dist/*
#    then open the Test PyPI page and eyeball the hero image + doc links + sidebar URLs

# 4. Make sure the PyPI pending publisher + GitHub `pypi` environment exist (above)

# 5. Tag and push — this fires .github/workflows/publish.yml
git tag v0.5.1
git push origin v0.5.1

# 6. Watch it; approve the deployment if you set a required reviewer
gh run watch
```

If the run **403s with `invalid-publisher`**: it's a pending-publisher field
mismatch (almost always the Environment field blank, or underscores in the name),
**not** a code bug. Nothing was uploaded, so no version is burned. Fix the PyPI
form field and re-run the workflow from the Actions tab — no tag bump needed.

---

## After it publishes

```bash
# Confirm it's live and the version is right
curl -s https://pypi.org/pypi/cowork-to-code-bridge/json \
  | python -c 'import sys,json; print(json.load(sys.stdin)["info"]["version"])'   # -> 0.5.1

# Clean-room install + entry point check
python -m venv /tmp/cttcb-verify
/tmp/cttcb-verify/bin/pip install cowork-to-code-bridge==0.5.1
/tmp/cttcb-verify/bin/cowork-to-code-bridge-selfcheck
```

Then land the **install.sh version-floor pin** (deliberately deferred until
0.5.1 is live, or it would force every install to fall back to git):

- `install.sh`: add `PACKAGE_SPEC="cowork-to-code-bridge>=0.5.1"` and use it for
  the PyPI attempt, so a yanked/old cached release can't silently downgrade fresh
  installs. Confirm a clean machine prints **"installed from PyPI"**, not
  "falling back to GitHub".

Finally, add the PyPI badge to the README:

```markdown
[![PyPI](https://img.shields.io/pypi/v/cowork-to-code-bridge)](https://pypi.org/project/cowork-to-code-bridge/)
```

---

## Version strings (keep all five in lockstep)

A release bumps **all** of these to the same number:

- `pyproject.toml` → `version`
- `cowork_to_code_bridge/__init__.py` → `__version__`
- `bridge_client.py` → `__version__`
- `skill/cowork-to-code-bridge/bridge_client.py` → `__version__`
- `.claude-plugin/plugin.json` → `version`

The two `bridge_client.py` copies are sync-guarded by
`tests/test_single_file_client.py` — they must stay identical.
