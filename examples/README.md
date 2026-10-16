# Example takes

Two original, AI-generated paper-boat scenes made with TakeLab and LTX-2.5. No reference footage or real person's likeness was supplied.

[comparison.mp4](comparison.mp4) is a 15.125-second, silent side-by-side edit, looping each original clip three times. It is an output preview; it does not represent an app screen recording or real-time generation.

| Take | Camera direction | Seed | Render time |
| --- | --- | --- | --- |
| [Paper boat, locked camera](paper-boat-locked/video.mp4) | Locked tripod | 3061016 | 268.67 seconds |
| [Paper boat, slow push-in](paper-boat-push/video.mp4) | Slow dolly forward | 3061016 | 146.52 seconds |

Each directory contains `video.mp4`, `workflow.json`, and `settings.json`. The workflow is the exact submitted ComfyUI API graph. Settings omit machine-specific storage paths and job identifiers. Rendering depends on the model/runtime versions and hardware; matching a seed does not guarantee identical output on every machine.

Video: H.264, 864 × 480, 121 frames at 24 fps. Audio: AAC, stereo, 48 kHz. Duration: approximately 5.04 seconds. The audio in these examples is quiet; its presence is not a claim of sound-design quality.

These example files are provided under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) to the extent the creator can grant rights. Model terms remain separate; see the main README. No model weights are included.
