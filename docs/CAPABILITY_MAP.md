# Supported capabilities

`agent/deep_agent/routing_policy.json` is the routing source of truth. Only built,
supported integrations appear in the tool catalog. Named provider requests must
remain explicit; an unavailable provider never authorizes a substitute.

| Capability | Default tool alias |
| --- | --- |
| t2v | `wan3_t2v` |
| i2v | `wan3_i2v` |
| reference_video | `wan3_r2v` |
| v2v_edit | `seedance25_edit` |
| extend | `seedance25_extend` |
| still_image | `gpt_image25_t2i` |
| image_edit | `gpt_image25_edit` |
| lipsync | `sync3_lipsync` |
| performance_transfer | `kling_motion_control` |
| tts | `eleven_v4_turbo` |
| voice_clone | `voices_ivc_create` |
| music | `mureka_v95` |
| sfx | `mirelo_v2a` |
| upscale | `topaz_upscale` |
| interpolate | `topaz_interpolate` |
| motion_graphics | `remotion_render` |
| nle_handoff | `Remotion___export_nle_timeline` |
| lyrics_video | `mureka_lyrics_video` |
| nle_import | `nle_import` |
| media_inspection | `ffmpeg_tool` |
| ad_variant_matrix | `ad_variant_matrix` |
| delivery_render | `delivery_render` |
| deliverable_qc | `deliverable_qc` |
| loudness_qc | `ffmpeg_tool` |
| cloned_tts | `eleven_v4_turbo` |
| motion_carry_qc | `motion_carry_probe` |
| local_finishing | `ffmpeg_tool` |
| shot_recipes | `shot_recipe_search` |
| lottie_animation | `lottie_author` |
| logo_animation | `logo_vectorize` |
| reference_analysis | `shot_breakdown` |
| reference_labels | `gemini_shot_labels` |

Existing fal credentials serve Wan, VACE, Vidu, Kling motion control, Mureka,
Mirelo, Topaz, Sync, image specialists and named video tools. Seedance defaults
to fal US; its existing BytePlus alternative retains regional and permission checks.
Seedream uses BytePlus, images use OpenAI, speech uses ElevenLabs or Fish Audio,
and explicit visual review uses Gemini with `GOOGLE_API_KEY`.

Local Remotion, FFmpeg, Lottie, logo, reference and recipe tools use operator compute.
Dry runs remain input previews. Saved outputs and passing checksum-matched QC are
required before delivery. Unknown prices remain unknown and cannot pass spending checks.
All paid video and likeness/voice use retain their approval and consent boundaries.

See [skills](SKILLS.md), [local assembly](LOCAL_ASSEMBLY.md),
[Sync](SYNC.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
