# Skills and routing

The Codex harness is the default. Deep Agents is an explicit opt-in. Both enforce
provider/model policy, consent, spending caps and native approval at the Gateway boundary.
Read the relevant skill before dispatch. Discover the actual schema; never invent tools.

The executable routing contract is `agent/deep_agent/routing_policy.json`.
Only supported tools have aliases. Routes are proposals, never proof of generated media.
See [capabilities](CAPABILITY_MAP.md), [Codex](CODEX_HARNESS.md) and [Deep Agents](DEEP_AGENT.md).

| Skill | Routing aliases |
| --- | --- |
| [art-style-motion](../agent/deep_agent/skills/art-style-motion/SKILL.md) | remotion_render gpt_image25_t2i eleven_v4_turbo elevenlabs_sfx_v2 |
| [audio](../agent/deep_agent/skills/audio/SKILL.md) | eleven_v4_turbo voices_ivc_create mureka_v95 mirelo_v2a elevenlabs_sfx_v2 |
| [audio-bed](../agent/deep_agent/skills/audio-bed/SKILL.md) | eleven_v4_turbo voices_ivc_create mureka_v95 mirelo_v2a elevenlabs_sfx_v2 |
| [chat-story-video](../agent/deep_agent/skills/chat-story-video/SKILL.md) | remotion_render ffmpeg_tool ad_variant_matrix delivery_render deliverable_qc |
| [cinematic-product-promo](../agent/deep_agent/skills/cinematic-product-promo/SKILL.md) | shot_recipe_search remotion_render eleven_v4_turbo mureka_v95 ffmpeg_tool delivery_render deliverable_qc motion_carry_probe |
| [codebase-video](../agent/deep_agent/skills/codebase-video/SKILL.md) | remotion_render eleven_v4_turbo ffmpeg_tool deliverable_qc |
| [conversational-edit](../agent/deep_agent/skills/conversational-edit/SKILL.md) | remotion_render |
| [edit-v2v](../agent/deep_agent/skills/edit-v2v/SKILL.md) | seedance25_edit seedance25_extend |
| [final-assembly](../agent/deep_agent/skills/final-assembly/SKILL.md) | remotion_render ad_variant_matrix ffmpeg_tool delivery_render deliverable_qc |
| [i2v](../agent/deep_agent/skills/i2v/SKILL.md) | wan3_i2v wan3_r2v seedance25_i2v seedance25_r2v |
| [image-gen](../agent/deep_agent/skills/image-gen/SKILL.md) | gpt_image25_t2i gpt_image25_edit recraft_v41_vector ideogram45_edit |
| [knowledge-explainer](../agent/deep_agent/skills/knowledge-explainer/SKILL.md) | remotion_render mirelo_v2a elevenlabs_sfx_v2 motion_carry_probe |
| [lipsync](../agent/deep_agent/skills/lipsync/SKILL.md) | sync3_lipsync eleven_v4_turbo |
| [logo-animation](../agent/deep_agent/skills/logo-animation/SKILL.md) | logo_vectorize remotion_render deliverable_qc ffmpeg_tool |
| [lottie-animation](../agent/deep_agent/skills/lottie-animation/SKILL.md) | lottie_author lottie_validate lottie_preview_render |
| [lyrics-video](../agent/deep_agent/skills/lyrics-video/SKILL.md) | mureka_lyrics_video mureka_v95 |
| [motion-carry-qc](../agent/deep_agent/skills/motion-carry-qc/SKILL.md) | motion_carry_probe remotion_render |
| [motion-graphics](../agent/deep_agent/skills/motion-graphics/SKILL.md) | remotion_render ffmpeg_tool motion_carry_probe |
| [named-provider](../agent/deep_agent/skills/named-provider/SKILL.md) | gemini_vlm_judge kling_motion_control pixverse_vibemv pixelcut_looping_video voices_ivc_create eleven_v4_turbo vidu_q4_i2v vidu_q4_r2v seedream_t2i fish_audio_tts wan_vace_edit |
| [plan-to-video](../agent/deep_agent/skills/plan-to-video/SKILL.md) | remotion_render eleven_v4_turbo fish_audio_tts ffmpeg_tool deliverable_qc |
| [podcast-audiogram](../agent/deep_agent/skills/podcast-audiogram/SKILL.md) | remotion_render elevenlabs_stt ffmpeg_tool deliverable_qc delivery_render motion_carry_probe |
| [product-demo-video](../agent/deep_agent/skills/product-demo-video/SKILL.md) | remotion_render motion_carry_probe |
| [product-images](../agent/deep_agent/skills/product-images/SKILL.md) | gpt_image25_t2i gpt_image25_edit recraft_v41_vector ideogram45_edit |
| [reference-shot-breakdown](../agent/deep_agent/skills/reference-shot-breakdown/SKILL.md) | shot_breakdown gemini_shot_labels |
| [refinement](../agent/deep_agent/skills/refinement/SKILL.md) | ideogram45_edit recraft_v41_vector gpt_image25_edit seedance25_edit seedance25_extend remotion_render |
| [remotion-ad-variant-matrix](../agent/deep_agent/skills/remotion-ad-variant-matrix/SKILL.md) | ad_variant_matrix remotion_render ffmpeg_tool delivery_render deliverable_qc |
| [remotion-aspect-ratio-variants](../agent/deep_agent/skills/remotion-aspect-ratio-variants/SKILL.md) | ad_variant_matrix remotion_render ffmpeg_tool delivery_render deliverable_qc |
| [remotion-deliverable-qc](../agent/deep_agent/skills/remotion-deliverable-qc/SKILL.md) | deliverable_qc ffmpeg_tool |
| [remotion-delivery-render](../agent/deep_agent/skills/remotion-delivery-render/SKILL.md) | delivery_render deliverable_qc ffmpeg_tool remotion_render |
| [remotion-loudness-qc](../agent/deep_agent/skills/remotion-loudness-qc/SKILL.md) | ffmpeg_tool |
| [resolve-handoff](../agent/deep_agent/skills/resolve-handoff/SKILL.md) | Remotion___export_nle_timeline nle_import |
| [series-video-planner](../agent/deep_agent/skills/series-video-planner/SKILL.md) | None |
| [short-drama-series](../agent/deep_agent/skills/short-drama-series/SKILL.md) | gpt_image25_t2i gpt_image25_edit wan3_t2v wan3_i2v wan3_r2v seedance25_t2v seedance25_i2v seedance25_r2v seedance25_edit seedance25_extend eleven_v4_turbo mureka_v95 remotion_render ffmpeg_tool deliverable_qc delivery_render |
| [still-then-video](../agent/deep_agent/skills/still-then-video/SKILL.md) | gpt_image25_t2i gpt_image25_edit wan3_i2v seedance25_i2v |
| [storyboard-shots](../agent/deep_agent/skills/storyboard-shots/SKILL.md) | gpt_image25_t2i gpt_image25_edit wan3_i2v wan3_r2v seedance25_i2v seedance25_r2v |
| [t2v](../agent/deep_agent/skills/t2v/SKILL.md) | wan3_t2v seedance25_t2v |
| [upscale](../agent/deep_agent/skills/upscale/SKILL.md) | topaz_upscale topaz_interpolate |
| [video-short](../agent/deep_agent/skills/video-short/SKILL.md) | gpt_image25_t2i wan3_t2v wan3_i2v seedance25_t2v seedance25_i2v remotion_render |
| [whiteboard-explainer](../agent/deep_agent/skills/whiteboard-explainer/SKILL.md) | remotion_render eleven_v4_turbo |
