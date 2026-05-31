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
2. In README, swap the `<img src="./docs/demo.svg">` for `./docs/demo.gif`.
3. Delete `docs/demo.svg` (it was the placeholder).
