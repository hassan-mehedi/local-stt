# CLAUDE.md

local-stt is offline speech-to-text for macOS and Linux: dictation into any app, file transcription and meeting recording. The Python package (`src/local_stt`) does all the audio and speech work. The macOS app (`app/`) is a Tauri window that runs the package as a child process (`stt engine`) and talks to it over a local HTTP API.

These rules apply to every change, by a person or an AI tool. If a task conflicts with a rule, stop and ask. Do not break the rule silently.

## Commands

```bash
pnpm -C app install                   # once, before the app commands
uv run pytest -q                      # Python tests
uvx ruff check .                      # lint, rules in pyproject.toml
pnpm -C app exec tsc --noEmit         # type-check the app
pnpm -C app tauri dev                 # run the app; the engine runs via `uv run stt engine`
./packaging/macos/build.sh            # signed app + dist/local-stt-<version>.dmg
packaging/set_version.sh 0.3.0        # the version, in all five files and both lockfiles
```

There is no CI. Run the tests, ruff and tsc yourself before you call a change done. For a change to the app UI, check it in a browser with Playwright too: start `uv run stt engine` (its first line has the port and token), run `pnpm -C app dev`, and open `http://localhost:1420/?port=<port>&token=<token>`.

## Layout

- `src/local_stt/<feature>/` holds one feature each: `audio/`, `cleanup/` (the optional AI rewrite and its Keychain key), `dictation/`, `engine/` (speech models), `meeting/`, `ui/` (HTTP server, tray shells).
- Top-level modules are the entry points and shared state: `cli.py`, `tray.py`, `headless.py` (`stt engine`), `config.py`, `store.py`, `permissions.py`, `desktop.py`, `export.py`.
- `app/src/` is the React UI: `screens/`, `components/`, `pill/`, `lib/`. `app/src-tauri/src/` is the Rust side: engine process, pill panel, tray.
- `src/local_stt/ui/static/` is the older browser UI that `stt tray` and `stt settings` serve on Linux and for source installs. The Mac app does not use it.
- `tests/` is flat, one `test_<module>.py` per module.

## Structure

- New code goes in the feature folder it belongs to. Create a new folder with a real name if none fits.
- Never use catch-all names for files or folders: `utils`, `helpers`, `misc`, `common`, `etc`.
- Before writing a helper, search the package for an existing one. Extend or parametrize it rather than copying it.
- HTTP routes (`ui/server.py`, `ui/app_api.py`) parse the request, call one function and return its result. The work lives in the feature module, such as `store.py` or `meeting/library.py`.
- Settings live in `config.py` and `config.toml`. Read environment variables only for secrets (`HF_TOKEN`) and platform detection (`WAYLAND_DISPLAY`).
- Keep functions under complexity 25 (ruff `C901`).

## Data

- History and the dictionary live in one SQLite file (`store.py`). Add a column to an existing table before you add a new table. Add a table only for data with its own lifecycle, or a one-to-many relation.
- `store.py` creates its tables with `CREATE TABLE IF NOT EXISTS`, which never changes an existing file. For a schema change, track the version with `PRAGMA user_version` and add the change as a step that runs on open, so existing history files keep working.

## Comments and docstrings

Never write:

- Ticket or issue references. Git history holds them.
- Section banners such as `# -- worker ----` or `/* -- layout -- */`. Modules and files do that job.
- Comments that repeat the code (`# loop over segments`).
- Docstrings longer than 2 lines.
- Commented-out code.
- Em dashes (U+2014) anywhere: code, comments, strings, docs, commit messages. Use a colon, a semicolon, a comma or a new sentence.

Write a comment only to explain why, in one or two lines:

- A platform quirk: `# MLX binds streams to the thread that created them.`
- A workaround for an outside tool: `# pw-record exits 1 on SIGINT, so the file is the only sign of success.`
- A thread or safety guard: `# the player asks for the audio and its waveform at once`

## Code quality

- Never `except Exception: pass`. Catch the narrowest exception. If you swallow a broad one, log it with `log.exception(...)`.
- Every network call has a timeout.
- Use `logging` in library code. `print` is only for CLI output (`cli.py`) and the engine's handshake line (`headless.py`).
- Main-thread rules on macOS are real: AppKit calls and pynput's keyboard layout stay on the main thread. MLX work stays on its one worker thread (`ParakeetMlxBackend`).

## Tests

- Write the test first, run it and see it fail for the right reason, then write the code.
- Name tests `test_<actor>_<action>_<outcome>`, for example `test_dictionary_snippet_eats_trailing_punctuation`. Older tests keep their names.
- Several inputs for one rule go in one `@pytest.mark.parametrize` table.
- No real network, microphone or model downloads in tests. Fake the backend or the recorder.
- Do not test constants, dataclass defaults or library behaviour.
- When a change makes a test redundant, delete it in the same change.

## Working rules

- Read the folder you are changing first and follow its patterns.
- Keep diffs small. No drive-by reformatting, renames or abstractions for later.
- Say why in your summary whenever you add a dependency, a table, a config key or a top-level module.
- Do not change the HTTP API's routes or response shapes unless the task asks for it. The app depends on them.
- Run the tests and report the real output. Never claim a test passes without running it.

## Change checklist

```
- [ ] Code is in the right feature folder; no catch-all names
- [ ] Routes stay thin; the work is in the feature module
- [ ] No new table, or the summary says why one was needed
- [ ] Test written first and seen failing
- [ ] uv run pytest, uvx ruff check . and tsc pass
- [ ] No ticket refs, banners, narrating comments, long docstrings or em dashes
```
