# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this is

A Frappe app (installed in a bench at `../..`, Frappe v16) that records the screen and/or camera in the browser and produces a share link immediately. Two halves:

- `frappe_recorder/` — Python backend: three DocTypes plus whitelisted HTTP methods.
- `frontend/` — Vue 3 + frappe-ui + Tailwind SPA, built by Vite into the Python package.

## Commands

Bench commands run from the bench root (`../..`); replace `<site>` with a site that has the app installed.

```bash
# Backend tests
bench --site <site> set-config allow_tests true          # once per site
bench --site <site> run-tests --app frappe_recorder
bench --site <site> run-tests --module frappe_recorder.frappe_recorder.doctype.screen_recording.test_screen_recording
bench --site <site> run-tests --module frappe_recorder.frappe_recorder.doctype.screen_recording.test_screen_recording --test test_guest_cannot_record

# After changing a DocType JSON
bench --site <site> migrate

# Frontend (from frontend/)
yarn dev      # Vite on :8080, proxies API calls to the bench; open http://<site>:8080/recorder
yarn build    # or, from the bench root: bench build --app frappe_recorder

# Lint / format (ruff, ruff-format, prettier, eslint)
pre-commit run --all-files
```

- The Vite dev server needs `"ignore_csrf": 1` in the site config.
- There are no frontend tests. Backend tests are in `test_screen_recording.py` and `test_recorder_ai_settings.py`.
- CI runs the tests on pushes to `develop` and on pull requests; the linter workflow adds Frappe semgrep rules and pip-audit.

## Architecture

### One SPA, two URL prefixes

`hooks.py` `website_route_rules` send both `/recorder/<path>` and `/r/<path>` to the `recorder` www page. `www/recorder.py` supplies boot data (CSRF token, site name, user); `www/recorder.html` is **generated** by `yarn build`, along with `public/frontend/` — both are gitignored, so never edit them and expect a fresh checkout to 404 until the frontend is built.

`frontend/src/router.js` owns the routes: `/recorder` (Record), `/recorder/library`, `/recorder/settings` (System Manager only) and `/r/:token` (Watch, public). The `beforeEach` guard redirects guests to `/login` for everything except the Watch route.

### Access control lives in `api.py`, not in DocType permissions

All three DocTypes grant permissions only to System Manager. Regular users never touch them through the Desk or `frappe.client`; every operation goes through `frappe_recorder/api.py`, which writes with `ignore_permissions=True` after doing its own check:

- `_get_owned_doc(token)` — logged in, and `doc.owner` or a System Manager.
- `_get_viewable_doc(token)` — anyone if `is_public`, otherwise the owner or a System Manager.

A new endpoint must go through one of these helpers. Recordings are addressed by their 12-character `token` (the share-link secret), never by the document name (`REC-#####`). `_serialize` returns a reduced field set to non-owners — keep owner-only fields (file size, `is_public`) inside its `is_owner` block.

### Recording pipeline (chunked upload)

The share link has to exist before the upload finishes, so recording is three calls:

1. `create_recording` inserts the doc with status `Recording` and reserves the token and `video_file` name.
2. `upload_chunk` appends bytes to the file. Chunks are strictly ordered by `chunks_received`: a repeated index is acknowledged and ignored (client retry), a skipped index is an error. The row is locked for the write, and the file is truncated to `bytes_received` first, so a retry never duplicates bytes.
3. `finalize_recording` sets status `Ready`, saves the thumbnail, and adds the video to the File Manager (`try_add_to_file_manager`). Filing failures are logged, not raised, so the recording still finishes; `file` stays empty and the daily task retries.

The client side is `frontend/src/composables/useRecorder.js`, a state machine (`idle → countdown → recording ⇄ paused → finishing`, plus `failed`). `MediaRecorder` emits a blob every 2 s; `pumpUploads` sends them one request at a time, in order, batching whatever queued up meanwhile, retrying with backoff but giving up on any 4xx. All chunks are also kept in memory so a failed upload can still be downloaded locally. Discarding, or navigating away inside the app, deletes the server-side recording; closing or reloading the tab only shows the `beforeunload` warning and leaves it in `Recording`.

`composables/compositor.js` handles Screen + Camera mode by drawing both onto a canvas and recording the canvas track. Its frame loop is driven by a Web Worker timer on purpose — `requestAnimationFrame` stalls when the tab is in the background, which is exactly when people are presenting.

`tasks.close_abandoned_recordings` (daily) rescues recordings stuck in `Recording` for 12+ hours: kept as `Ready` (and filed) if any bytes arrived, deleted otherwise. It also files `Ready` recordings whose `file` is still empty.

### File storage and streaming

Paths come from helpers in `doctype/screen_recording/screen_recording.py`:

- Videos: `private/files/recording-<token>.<ext>` — private, served only through `api.stream` (so switching sharing off really revokes access). `stream` supports HTTP Range for seeking. They sit directly in `private/files` because Frappe's `File` resolves and deletes files by basename only.
- Thumbnails: `public/files/recorder/<token>.jpg` (plain files).

While recording, the video is a plain file. On finalize, `add_to_file_manager` registers it as a private `File` document in `Home/Recordings`, attached to the recording and linked from its `file` field. It sets `flags.copy_from_existing_file` (so File does not read the whole video into memory or apply the upload size limit) and computes `content_hash` itself in chunks. `on_trash` deletes that File (with `force`, since the recording still links to it) and the local files. Because of the link, the File cannot be deleted on its own from the File Manager.

Google Drive storage was removed; `patches/v1/move_videos_to_file_manager` moved older videos out of `private/files/recorder` and deleted the `Google Drive Settings` DocType. The old `drive_*`/`source` columns may remain in existing databases, unused.

### Transcripts and AI notes (`ai.py`, `frontend/src/ai/`)

The models run in the **recording owner's browser**, not on the server, so the feature works on any host (including shared Frappe Cloud plans) with no Python dependencies and no API keys.

- `src/ai/whisper.worker.js` runs Whisper through `@huggingface/transformers` (WebGPU, else WASM); `src/ai/llm.worker.js` hosts WebLLM; `src/ai/engine.js` drives both: it downloads the video from `api.stream`, decodes its audio at 16 kHz, transcribes in 5-minute blocks, and splits long transcripts into parts for the ~4K-token browser models. `components/AiPanel.vue` is the Watch page UI (Assistant · Highlights · Transcript · SOP).
- The server only stores and serves results: `save_transcript` / `save_insights` / `save_sop` (owner, via `_get_owned_doc`) clean what the browser sends; `get_ai` (via `_get_viewable_doc`) is what viewers read. Text is stored as JSON/Markdown in Long Text fields on `Screen Recording`, with independent `transcript_status` / `insights_status` / `sop_status`.
- The prompts live once, in `ai.PROMPTS` (Python format strings), and reach the browser through `get_ai_config`; `engine.fill` fills them the same way.
- `frontend/package.json` replaces `sharp` and `onnxruntime-node` with empty stubs (`frontend/stubs/`): transformers.js only needs them in Node, and installing them downloads native binaries.

### Frontend API layer

`frontend/src/api.js` is the single place that names backend methods; pages call `api.*` rather than `call()` directly. `upload_chunk` uses raw `fetch` with `FormData` and `window.csrf_token` because the body is binary. `session` is a shared reactive object populated once by `loadSession()`.

`Recording Folder` (a plain DocType with a parent link and `is_group`, not a Frappe tree/`NestedSet`) and the `folder` link on `Screen Recording` exist in the schema but nothing in `api.py` or the frontend uses them yet.

## Conventions

- Python: tabs, double quotes, 110-column lines (ruff config in `pyproject.toml`). User-facing strings go through `_()`.
- Frontend: no semicolons, single quotes (`frontend/.prettierrc.json`); the existing files use 2-space indent and long lines. That file does not set indent or width, and the root `.editorconfig` prescribes tabs and 99 columns for `*.js`/`*.vue`, which Prettier also reads — so `pre-commit run --all-files` may reformat `frontend/src` to tabs. Check the diff before committing a formatting run.
- `@` aliases `frontend/src`.
