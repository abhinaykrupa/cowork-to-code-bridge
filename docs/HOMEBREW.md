# Homebrew install (macOS)

Homebrew distributes software through **formulas** — small Ruby files that describe
how to download and install a package. Formulas for third-party projects live in a
**tap**: a separate GitHub repo named `homebrew-<name>`. Homebrew maps
`abhinaykrupa/homebrew-tap` to the tap name `abhinaykrupa/tap`.

The bridge is more than a pip package: `install.sh` also creates
`~/.cowork-to-code-bridge/`, whitelisted scripts, a launchd daemon, a bridge token,
and the Cowork skill. The Homebrew formula downloads a pinned release tarball and
runs that installer non-interactively.

**Linux and WSL2:** keep using the [curl one-liner](../README.md#install--two-pastes-total).
The formula is macOS-only (`launchd`).

---

## Install (production tap)

Once the maintainer publishes [abhinaykrupa/homebrew-tap](https://github.com/abhinaykrupa/homebrew-tap):

```bash
brew install abhinaykrupa/tap/cowork-to-code-bridge
```

No separate `brew tap` is required — Homebrew auto-taps on first install.

---

## Install (demo tap, before production tap exists)

Contributor demo tap for issue #37:

```bash
brew tap EagleEye-0101/tap
brew install cowork-to-code-bridge
```

Production target: `abhinaykrupa/tap`. The demo tap uses the same formula as
[`packaging/homebrew/cowork-to-code-bridge.rb`](../packaging/homebrew/cowork-to-code-bridge.rb).

---

## Maintainer: create the production tap (one-time)

1. Create a public repo **`abhinaykrupa/homebrew-tap`** (exact name — Homebrew expects
   the `homebrew-` prefix).
2. Copy the canonical formula from this repo:

   ```text
   packaging/homebrew/cowork-to-code-bridge.rb  →  Formula/cowork-to-code-bridge.rb
   ```

3. Add a minimal `README.md` to the tap repo with:

   ```bash
   brew install abhinaykrupa/tap/cowork-to-code-bridge
   ```

4. Users can install immediately; no PyPI or manual `curl | bash` required on Mac.

---

## Version bump checklist (manual)

On each new GitHub release (e.g. `v0.5.1`):

1. Download the release tarball and compute SHA256:

   ```bash
   curl -fsSL -o /tmp/cowork-to-code-bridge-0.5.1.tar.gz \
     https://github.com/abhinaykrupa/cowork-to-code-bridge/archive/refs/tags/v0.5.1.tar.gz
   shasum -a 256 /tmp/cowork-to-code-bridge-0.5.1.tar.gz
   ```

2. Update **`packaging/homebrew/cowork-to-code-bridge.rb`** in this repo:
   - `url` → new tag tarball
   - `sha256` → new hash
   - `version` → new semver (without `v` prefix)

3. Copy the updated formula to **`abhinaykrupa/homebrew-tap`** (`Formula/cowork-to-code-bridge.rb`).

4. Run locally (macOS):

   ```bash
   brew audit --strict packaging/homebrew/cowork-to-code-bridge.rb
   ```

---

## Upgrade and reinstall

`brew reinstall cowork-to-code-bridge` re-runs `post_install` / `install.sh`.
The installer is idempotent: an existing `BRIDGE_TOKEN` in `~/.cowork-to-code-bridge/.env`
is preserved.

---

## Optional: auto-bump tap on release

Not wired by default. When `abhinaykrupa/homebrew-tap` exists and a maintainer token
(or cross-repo `GITHUB_TOKEN` policy) is configured, a workflow on
`release: published` could:

1. Download the new tag tarball and compute `sha256`.
2. Patch `Formula/cowork-to-code-bridge.rb` in the tap repo.
3. Open a PR (same pattern as [`.github/workflows/publish.yml`](../.github/workflows/publish.yml)
   for PyPI).

Until then, use the manual checklist above.

---

## Uninstall

```bash
cowork-to-code-bridge-uninstall
```

Or:

```bash
curl -fsSL https://raw.githubusercontent.com/abhinaykrupa/cowork-to-code-bridge/main/daemon/uninstall.sh | bash
```

Then remove the formula if desired:

```bash
brew uninstall cowork-to-code-bridge
```
