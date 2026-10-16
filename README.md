# TakeLab

Direct a short video, compare takes, and keep the recipe.

TakeLab turns a scene brief, camera move, lighting choice, and sound description into a five-second video with audio. It runs LTX-2.5 on your own ComfyUI through the **official Comfy Python SDK** and **Comfy API v2 proxy**. Every take keeps its seed and exact workflow; download a ZIP with the video and settings to share or reproduce it.

Built for the [Open Source Higgsfield competition](https://comfy.org/open-source-higgsfield). TakeLab code is MIT licensed. The model weights have their own licenses and are not included.

## Example takes

[Locked camera](examples/paper-boat-locked/video.mp4) · [Slow push-in](examples/paper-boat-push/video.mp4)

[Watch the 15-second output comparison](examples/comparison.mp4) — both clips loop three times, side by side, without audio.

| Locked camera | Slow push-in |
| --- | --- |
| ![Red paper sailboat, locked camera](examples/paper-boat-locked/preview.png) | ![The camera moves closer to the red paper sailboat](examples/paper-boat-push/preview.png) |

Preview frames from the actual clips, at 1.0 and 4.8 seconds respectively.

These two fresh renders use the same paper-boat scene and seed, with only camera direction changed. Each [example directory](examples) includes its original video, exact workflow, and settings. The model changes some scene details as it interprets the camera prompt.

Both completed locally through the SDK on an RTX 3060 12 GB with 64 GB system RAM: approximately 269 seconds for the first take and 147 seconds for the second. These are individual runs, not a performance guarantee. Both files passed full video/audio decoding and visual frame inspection; their generated ambient audio is quiet.

## What you can do

- Direct locked, push-in, orbit, or tracking shots with four lighting presets.
- Generate 864 × 480 video: 121 frames at 24 fps, approximately 5.04 seconds, with audio.
- Compare two takes, reuse their settings, and download the video, workflow, or complete take bundle.
- Keep a local take history across restarts. An interrupted submission is never silently submitted again.

Camera and lighting are prompt directions, not geometric constraints. The model may interpret them imperfectly. Matching seeds help controlled comparisons but do not guarantee scene identity across changed prompts or runtime versions.

## Requirements

- Python 3.10+ and a running ComfyUI with the native LTX-2.5 nodes (tested with ComfyUI 0.38.0).
- An NVIDIA GPU suitable for LTX-2.5. The included low-memory preset was selected for a 12 GB RTX 3060 with CPU offloading; results depend on the rest of your setup.
- About 36 GiB for the four model files, plus room for ComfyUI and outputs. Large models can also require substantial system RAM.

Install the files in [workflows/models.json](workflows/models.json) into the matching directories under your ComfyUI `models` folder. It records the upstream revision, sizes, and SHA-256 checksums. Obtain weights directly from [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) after reviewing its access terms. TakeLab does not download or redistribute weights.

| Directory | Required file |
| --- | --- |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` |
| `vae` | `ltx-2.5-video-vae-conv-bf16.safetensors` |
| `vae` | `ltx-2.5-audio-vae-bf16.safetensors` |

## Run locally

Start ComfyUI on `http://127.0.0.1:8188`. No custom nodes or partner nodes are required for this graph.

Create an environment from the repository root:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

In one terminal, start the official proxy. Keep its state directory so job IDs survive restarts:

```powershell
./.venv/Scripts/comfy-api-proxy.exe run --comfyui http://127.0.0.1:8188 --port 8189 --state-dir data/proxy
```

In another terminal:

```powershell
./.venv/Scripts/python.exe app.py
```

Open **http://127.0.0.1:41732**. On Linux/macOS, replace `.venv/Scripts/python.exe` with `.venv/bin/python` and `.venv/Scripts/comfy-api-proxy.exe` with `.venv/bin/comfy-api-proxy`.

The app checks for the four models before enabling generation. Choose a starter scene or write your own, select camera and light, and generate a take. Keep the browser open or return later; rendering happens in the server. Wait for the current take before starting another. Use the same seed while comparing camera or lighting changes.

## How it works

```text
Browser → TakeLab → comfy-sdk → comfy-api-proxy → ComfyUI → local LTX-2.5
```

The app loads [the API workflow](workflows/ltx25.json), changes the prompt and seed, submits it through `Comfy.submit`, follows the returned job, and downloads node 20's MP4 through the SDK. The workflow uses eight distilled steps, separate video/audio latents, and tiled video decoding. Video and audio frame counts and frame rates remain aligned.

Takes live in `data/takes.sqlite3`; completed videos live in `data/<take-id>/video.mp4`. The ZIP export contains `video.mp4`, `workflow.json`, and `take.json`. A workflow export is ComfyUI API format. It can be executed through the official SDK; it is not an editor canvas layout.

The server listens only on loopback and rejects cross-origin browser requests. This is a single-user local application. There is no account, analytics, external font/CDN dependency, or provider billing integration. Do not expose these services to the internet. The application supports loopback URLs only, ignores `COMFY_API_KEY`, and disables ambient proxy routing inside its own process.

Configuration: `COMFY_BASE_URL` sets the local proxy (default port 8189); `TAKELAB_COMFY_URL` sets native ComfyUI (8188); `TAKELAB_PORT` sets the app port (41732); `TAKELAB_DATA` sets the local data directory. Use a dedicated proxy/state directory for TakeLab.

## Recovery

An uncertain browser response retains the same request ID; checking that submission cannot create a second take. If TakeLab stops with a known job ID, restart it with the same data and proxy state to recover that job and its output. If submission was interrupted before an ID was saved, the take is marked **unknown** and is not resubmitted. Inspect ComfyUI's queue/history before explicitly starting another take. Native jobs from other applications are not canceled or deleted.

ComfyUI's history and output files must remain available for recovery. An app restart can recover an existing job; it cannot reconstruct a deleted output. Failed/unknown take records remain in history. This release has no cancel or history-delete control.

## Development

```powershell
./.venv/Scripts/python.exe -m pip install pytest
./.venv/Scripts/python.exe -m pytest -q
node --check static/app.js
```

Tests cover workflow alignment, input validation, duplicate requests, busy queues, restart behavior, browser-origin protection, and export boundaries. Actual generation additionally requires ComfyUI and the model files; unit tests do not claim to validate model quality.

## Credits and licenses

- [Comfy Python SDK](https://github.com/Comfy-Org/comfy-python-sdk) and [API proxy](https://github.com/Comfy-Org/comfy-api-proxy), MIT.
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI), GPL-3.0; used as a separate local service.
- [Lightricks LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5), [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x), including its use restrictions and commercial thresholds. Model and encoder terms are separate from TakeLab's MIT license.
- The workflow follows the [official LTX ComfyUI integration](https://docs.ltx.io/open-source-model/integration-tools/comfy-ui) using native ComfyUI nodes.

Public examples are AI-generated synthetic scenery. Keep source and output rights in mind when using your own prompts and sharing results. No claim of affiliation with ComfyUI or Lightricks is made.
