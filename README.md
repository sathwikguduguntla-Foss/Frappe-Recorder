<div align="center" markdown="1">

<a href="https://github.com/sathwikguduguntla-Foss/Frappe-Recorder">
    <img src="https://raw.githubusercontent.com/sathwikguduguntla-Foss/Frappe-Recorder/main/frontend/public/favicon.svg" height="80" alt="Frappe Recorder Logo">
</a>

<h1>Frappe Recorder</h1>

**Record your screen. Share your ideas. Turn recordings into knowledge.**

[![CI](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/actions/workflows/ci.yml/badge.svg)](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/actions/workflows/ci.yml)
[![Linters](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/actions/workflows/linter.yml/badge.svg)](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/actions/workflows/linter.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/blob/main/license.txt)

[Getting Started](#getting-started) · [Key Features](#key-features) · [Report an Issue](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/issues)

</div>

## Frappe Recorder

Frappe Recorder is an open-source screen and camera recording app built on the Frappe Framework. Capture your screen, your camera, or both directly in your browser, then share your recording with a link.

Organize recordings in a searchable library and turn spoken explanations into timestamped transcripts, summaries, highlights, and step-by-step standard operating procedures (SOPs). Open-source AI models run in the recording owner's browser without an API key or server-side model installation.

### Motivation

A short recording can explain a workflow, demonstrate a feature, or make a bug easier to reproduce. Finding the useful information later should be just as simple.

Frappe Recorder brings recording, sharing, and written notes into one application. Built on Frappe, it helps teams communicate asynchronously and document processes while keeping recordings within their own Frappe deployment.

### Key Features

- **Flexible Recording Modes:** Capture your screen and camera together with a camera bubble, record only your screen, or record only your camera.
- **Audio Controls:** Choose your microphone and capture supported system or tab audio.
- **Recording Controls:** Start with a three-second countdown, pause and resume, mute your microphone, or discard a take.
- **Uploads While Recording:** Video uploads in small chunks as you record, reducing the wait after you stop.
- **Shareable Playback:** Anyone with an enabled share link can watch without signing in.
- **Owner Controls:** Rename, download, delete, or disable link sharing for your recordings. Views are counted.
- **Searchable Library:** Find previous recordings with thumbnails and search.
- **File Manager Integration:** Finished recordings appear as private Files under **Home / Recordings**, attached to their Screen Recording documents.
- **Timestamped Transcripts:** Read transcripts with clickable timestamps that jump to the relevant moment.
- **AI Notes:** Generate summaries, highlights, and SOPs using browser-based open-source models.

### Transcripts and AI Notes

Transcripts and AI notes are enabled by default. A System Manager can configure them at `/recorder/settings`.

- **Speech Recognition:** When the owner opens a finished recording, Whisper runs through Transformers.js in their browser and saves a timestamped transcript.
- **Summaries and SOPs:** Models such as Qwen2.5 or Llama 3.2 run through WebLLM to generate written notes.
- **Browser Caching:** Models download on first use and are cached for later sessions.
- **Saved Results:** Generated text is stored on your Frappe site, allowing viewers to read it without running the models themselves.

Writing models require WebGPU and compatible hardware. Transcription can also use WebAssembly. Model downloads require internet access and sufficient browser storage.

### Under the Hood

- [Frappe Framework](https://github.com/frappe/frappe): Backend, authentication, DocTypes, APIs, and file storage.
- [Vue 3](https://vuejs.org/): Frontend application framework.
- [Frappe UI](https://github.com/frappe/frappe-ui): User interface components.
- [Vite](https://vite.dev/): Frontend development and build tooling.
- [Tailwind CSS](https://tailwindcss.com/): Interface styling.
- [Transformers.js](https://github.com/huggingface/transformers.js): Browser-based Whisper transcription.
- [WebLLM](https://github.com/mlc-ai/web-llm): Browser-based text generation.

### Requirements and Compatibility

| Component | Requirement |
| :--- | :--- |
| Backend | A working Frappe Bench and site |
| Python | Python 3.10 or later, subject to your Frappe version |
| Frontend tooling | Node.js and Yarn compatible with your Frappe setup |
| Recording | A recent desktop browser with screen and media capture support |
| Hosted access | HTTPS; localhost can be used for local development |
| AI writing | A WebGPU-capable browser and compatible hardware |

The repository does not currently declare a supported Frappe or ERPNext version matrix.

System and tab audio availability depends on the browser, operating system, and selected capture source.

## Getting Started

### Install on an Existing Site

First, [set up Frappe Bench](https://docs.frappe.io/framework/user/en/installation).

Run the following commands from your bench directory:

```bash
cd /path/to/frappe-bench

bench get-app frappe_recorder https://github.com/sathwikguduguntla-Foss/Frappe-Recorder.git --branch main

bench --site your-site.localhost install-app frappe_recorder

bench build --app frappe_recorder

bench --site your-site.localhost migrate
```

Replace `your-site.localhost` with your site's name.

For production deployments, restart services using your normal Bench or hosting workflow. Sign in to your site and open `/recorder`.

### Local Development

After fetching the app, create a development site if you do not already have one:

```bash
bench new-site recorder.localhost

bench --site recorder.localhost install-app frappe_recorder

bench build --app frappe_recorder

bench start
```

Open `http://recorder.localhost:8000/recorder` and sign in.

### Frontend Development

Keep `bench start` running. Open another terminal and run:

```bash
cd /path/to/frappe-bench/apps/frappe_recorder/frontend

yarn install

yarn dev
```

The project documents the frontend at `http://your-site.localhost:8080/recorder`. Use the port printed by Vite if it differs.

For local Vite development, enable the project's development CSRF setting from your bench directory:

```bash
bench --site your-site.localhost set-config ignore_csrf 1
```

Use this only on a local development site. Restore CSRF protection when finished:

```bash
bench --site your-site.localhost set-config ignore_csrf 0
```

Frontend source code is available in `apps/frappe_recorder/frontend`.

## Using Frappe Recorder

1. Open `/recorder` and select a recording mode.
2. Choose your camera, microphone, and audio options.
3. Grant the requested browser permissions and start recording.
4. Pause, resume, or mute as needed.
5. Stop recording and copy the share link.
6. Find previous recordings in `/recorder/library`.

| Route | Purpose | Access |
| :--- | :--- | :--- |
| `/recorder` | Record screen, camera, and audio | Signed-in users |
| `/recorder/library` | Browse and search your recordings | Signed-in users |
| `/recorder/settings` | Configure transcripts and AI notes | System Managers |
| `/r/<token>` | Watch a recording and read saved notes | Anyone with the link while sharing is enabled |

### Storage and Sharing

Video files are stored in `private/files` and served through `frappe_recorder.api.stream`, which checks access. Turning off link sharing prevents other viewers from accessing the recording through that link.

Deleting a recording removes its video and File Manager entry. Files belonging to recordings cannot be deleted independently through File Manager; delete the recording instead.

## Contributing

Bug reports, feature suggestions, and pull requests are welcome. Visit [GitHub Issues](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/issues) to report problems or discuss improvements.

The project uses [pre-commit](https://pre-commit.com/#installation) for formatting and linting. After installing it, enable the hooks:

```bash
cd /path/to/frappe-bench/apps/frappe_recorder

pre-commit install

pre-commit run --all-files
```

Configured tools include:

- Ruff
- ESLint
- Prettier
- pyupgrade

GitHub Actions workflows also cover server tests, linting, Semgrep checks, and dependency auditing.

## Learn and Connect

- [Project Repository](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder)
- [Issues and Feature Requests](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/issues)
- [Frappe Framework Documentation](https://docs.frappe.io/framework)
- [Frappe Community Forum](https://discuss.frappe.io/)

## License

Frappe Recorder is licensed under the [GNU Affero General Public License v3.0](https://github.com/sathwikguduguntla-Foss/Frappe-Recorder/blob/main/license.txt).

<br>

<div align="center">
    <p>
        Built on <a href="https://frappe.io/framework">Frappe Framework</a>
        · Maintained by
        <a href="https://github.com/sathwikguduguntla-Foss">Sathwik Guduguntla</a>
        and contributors
    </p>
</div>
