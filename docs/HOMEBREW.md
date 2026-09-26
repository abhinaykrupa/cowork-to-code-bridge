# Homebrew install (macOS)

```bash
brew install abhinaykrupa/tap/cowork-to-code-bridge
cowork-to-code-bridge-setup
```

No separate `brew tap` is needed — Homebrew taps
[abhinaykrupa/homebrew-tap](https://github.com/abhinaykrupa/homebrew-tap) on first install.

**Why two commands.** `brew install` only puts files in Homebrew's prefix: the
pinned release tarball, plus a `cowork-to-code-bridge-setup` command.
`cowork-to-code-bridge-setup` is the explicit second step. It runs the same
`install.sh` as the curl one-liner — creates `~/.cowork-to-code-bridge/`, the
allowlisted scripts, a bridge token, the Cowork skill and a launchd agent — and
prints the connect line to paste into Cowork. Registering a background agent in
your home directory is not something a formula should do silently during
`brew install`, and Homebrew 7 no longer runs arbitrary scripts from
`post_install` anyway.

The Python package installed by setup comes from the **same tarball** the
formula pinned, so the version always matches `brew info`.

**Linux and WSL2:** use the [curl one-liner](../README.md#install--two-pastes-total).
The formula is macOS-only (`launchd`).

## Upgrading

```bash
brew upgrade cowork-to-code-bridge && cowork-to-code-bridge-setup
```

Setup is idempotent: it keeps your token and scripts and restarts the daemon on
the new version.

## Uninstalling

```bash
cowork-to-code-bridge-uninstall
brew uninstall cowork-to-code-bridge
```

## How the tap stays current

The tap repo has a scheduled workflow that checks the latest release of this
repo every six hours, hashes its release tarball, and updates the formula with
the tap's own token — no cross-repo credentials involved.
[`packaging/homebrew/cowork-to-code-bridge.rb`](../packaging/homebrew/cowork-to-code-bridge.rb)
in this repo is the source the tap formula was created from, and the
`homebrew-audit` CI job runs `brew audit --strict` against it on every change.
