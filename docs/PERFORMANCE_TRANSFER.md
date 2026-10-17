# Performance transfer

The supported adapter is `Fal___kling_motion_control`, using the existing fal key.
Inputs are a character image and driving video. The driving clip must be 3–30 seconds;
image orientation permits at most 10 seconds. Every face, body and voice needs an
identified subject and `consent_confirmed=true`. Cost approval remains separate.

`Fal___get_video_task` polls the saved handle. Do not retry accepted jobs automatically.
See the exact request schema in `configs/gateway/fal.tools.json` and
[official endpoint](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control/api).
