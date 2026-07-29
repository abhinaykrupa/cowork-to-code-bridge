# Demo GIF — recording shot list (internal)

Goal: a ~25–35s clip for the top of the README that shows the *one-message* magic:
ask in a Claude chat → a real Claude Code agent builds + runs something on your
machine → result comes back. Replace `docs/demo.svg` with the exported GIF/MP4.

**Tools:** [Kap](https://getkap.co) or CleanShot (screen→GIF), or asciinema +
`agg` for a pure-terminal version. Keep it < 4 MB so GitHub inlines it.

## The shot (one take, no edits needed)

1. **Open a fresh Cowork chat.** Window cropped tight, dark theme, large font.
2. **Type and send:**
   > build me a tiny Flask app in ~/demo, install deps, run it, and confirm the / route returns JSON — then stop the server
3. **Let it run.** The valuable footage is Claude narrating as it goes:
   creating files → venv → pip install → starting server → curl → `{"status":"ok"}`
   → cleanup. (Streaming makes this visible — that's the point.)
4. **End on the success line** ("Built and verified…"). Hold 1s. Stop recording.

## Tips
- Pre-create nothing; the empty start sells that it's real.
- If pip install is slow, you can trim that dead time, but keep one "installing…"
  beat so viewers see real work happening.
- Add a 1-line caption overlay at the start: *"One message. Claude builds it on my Mac."*
- Export as GIF (loops, autoplays on GitHub) — that beats MP4 for READMEs.

## After recording
1. Save as `docs/demo.gif`.
2. In README, point the hero `<img>` at `docs/demo.gif`.

**Status: done.** The recording landed in `docs/demo.gif` (860×520, 37 frames)
and the README hero points at it. `docs/demo.svg` is kept as the fallback
still — it is no longer referenced by the README, but it stays in the repo so
the pre-recording placeholder is available if the GIF ever needs re-cutting.

`tests/test_readme_demo_asset.py` guards the wiring: the hero image must
reference an asset that actually exists in `docs/`, so the README can't drift
back to pointing at a placeholder (or at a file nobody committed).
