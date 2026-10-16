# TakeLab implementation contract

A local short-video studio for independent creators. Describe a scene, direct camera and light, generate a five-second LTX take with audio, compare takes, and export the video and exact workflow. Use the official Comfy Python SDK and local API v2 proxy. No cloud billing, input uploads, account system or public inference hosting.

Interface direction: warm ivory editing desk, near-black screening area, restrained burnt-orange accent, editorial serif display headings paired with readable sans-serif controls. Keep primary work visible, avoid decorative cards, support narrow screens, keyboard focus and reduced motion. Brand: practical, cinematic, approachable.

## HTTP contract

All endpoints are same-origin. JSON errors: `{error: string}` with a non-2xx status. No authentication required on loopback; reject other Host headers and cross-origin writes.

- GET `/api/status`: `{ready: boolean, busy: boolean, message: string, model: "LTX-2.5", width:864,height:480,frames:121,fps:24}`. Ready means proxy and Comfy reachable and required models present. Busy includes native Comfy queue.
- GET `/api/takes`: `{takes: Take[]}` newest first.
- POST `/api/takes`: `{request_id: UUID, title: string (1..80), scene: string (1..1600), camera: "locked"|"push"|"orbit"|"track", lighting: "golden"|"studio"|"night"|"overcast", sound: string (0..400), seed: integer (0..4294967295)}`. Returns `{take: Take}` with 202; same UUID/body replays existing take; UUID/body mismatch returns 409. Do not auto-retry with a new UUID after an uncertain POST. One active TakeLab job at a time, reject 409 while busy.
- GET `/api/takes/<id>/workflow`: download exact JSON graph.
- GET `/api/takes/<id>/video`: video/mp4 with range support when succeeded; 404 otherwise.
- GET `/api/takes/<id>/bundle`: ZIP containing video, workflow.json and take.json (public settings/provenance).

Take: `{id,title,scene,camera,lighting,sound,seed,prompt,status,created_at,updated_at,job_id,error,elapsed_seconds,video_url,workflow_url,bundle_url}`. Status: `submitting|queued|running|succeeded|failed|unknown`. Nullable fields: job_id,error,elapsed_seconds,video_url,bundle_url. Workflow always available. `unknown` means submission/status could not be confirmed; never automatically resubmit. Poll GET status/takes every 3 seconds while visible; preserve focused inputs and video playback while refreshing. Compare selection is frontend state. Reuse a take loads its form fields, generating again requires explicit submit.

## Verification

Backend tests: valid workflow preserves aligned video/audio lengths; user text never becomes paths; invalid inputs rejected; request idempotency; busy queue; isolated download routes; cross-origin requests rejected; persistence/restart does not resubmit an uncertain job. Real SDK render, full media decode and visual review are required. Browser verify form, generation/results, comparison/downloads and mobile layout. Public artifacts must exclude email, paths, logs, credentials, personal media and databases.
