import type { AgentToolEvent, CreativeNodeKind, PortDataType, ToolDefinition } from "./types";

const CREATIVE_TOOLS: ToolDefinition[] = [
  {
    id: "image.ideogram.edit",
    displayName: "Ideogram text edit",
    description: "Correct text in an existing image; review pixel preservation",
    category: "image",
    providerId: "fal",
    toolName: "ideogram_edit",
    inputPorts: [
      { id: "image", label: "Source image", dataType: "image", targetField: "image_url", required: true },
      { id: "prompt", label: "Edit instruction", dataType: "text", targetField: "prompt", required: true },
      { id: "mask", label: "Edit mask", dataType: "image", targetField: "mask_url" },
    ],
    outputPorts: [{ id: "image", label: "Edited image", dataType: "image" }],
    primaryFields: ["prompt", "image_url", "mask_url", "reference_image_urls", "edit_precision", "image_size", "quality", "num_images", "seed"],
    pollTool: "get_video_task",
    pollIntervalMs: 5000,
    defaults: { edit_precision: "high", image_size: "auto", quality: "medium", num_images: 1 },
  },
  {
    id: "image.recraft.vector",
    displayName: "Recraft editable vector",
    description: "Generate an editable SVG with a preferred RGB palette",
    category: "image",
    providerId: "fal",
    toolName: "recraft_text_to_vector",
    inputPorts: [{ id: "prompt", label: "Vector design", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "image", label: "SVG", dataType: "image" }],
    primaryFields: ["prompt", "image_size", "colors", "background_color", "enable_safety_checker"],
    pollTool: "get_video_task",
    pollIntervalMs: 5000,
    defaults: { image_size: "square_hd", enable_safety_checker: true },
  },
  {
    id: "video.mirelo.foley",
    displayName: "Mirelo video foley",
    description: "Use chat to approve synchronized SFX with a cost estimate",
    category: "video",
    providerId: "fal",
    toolName: "mirelo_v2a",
    inputPorts: [{ id: "video", label: "Silent video", dataType: "video", targetField: "video_url", required: true }],
    outputPorts: [{ id: "video", label: "Video with SFX", dataType: "video" }],
    primaryFields: ["video_url", "text_prompt", "duration", "num_samples", "seed"],
    pollTool: "get_video_task",
    pollIntervalMs: 5000,
    defaults: { duration: 10, num_samples: 1 },
  },
  {
    id: "video.topaz.upscale",
    displayName: "Topaz Starlight upscale",
    description: "Use chat to approve finishing with a cost estimate",
    category: "video",
    providerId: "topaz",
    toolName: "upscale_video",
    inputPorts: [{ id: "video", label: "Video", dataType: "video", targetField: "video_url", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["video_url", "source_duration_seconds", "source_fps", "source_width", "source_height",
      "target_resolution", "upscale_factor", "target_fps", "model", "softness"],
    pollTool: "get_video_task",
    pollIntervalMs: 10000,
    defaults: { model: "Starlight Precise 2.6", H264_output: true },
  },
  {
    id: "video.topaz.interpolate",
    displayName: "Topaz frame interpolation",
    description: "Use chat to approve Apollo or Chronos interpolation with a cost estimate",
    category: "video",
    providerId: "topaz",
    toolName: "interpolate_video",
    inputPorts: [{ id: "video", label: "Video", dataType: "video", targetField: "video_url", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["video_url", "source_duration_seconds", "source_fps", "source_width", "source_height",
      "target_fps", "fps_multiplier", "slowdown_factor", "model"],
    pollTool: "get_video_task",
    pollIntervalMs: 10000,
    defaults: { model: "Apollo", H264_output: true },
  },
  {
    id: "video.heygen.presenter",
    displayName: "HeyGen Avatar V presenter",
    description: "Use chat to approve a presenter video with recorded face and voice consent",
    category: "video",
    providerId: "heygen",
    toolName: "create_avatar_video",
    inputPorts: [{ id: "script", label: "Script", dataType: "text", targetField: "script" }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["avatar_id", "voice_id", "script", "audio_url", "language", "duration_seconds",
      "subjects", "consent_confirmed", "consent_record_id", "resolution", "aspect_ratio"],
    pollTool: "get_video_status",
    pollIntervalMs: 10000,
    defaults: { model: "avatar_v", resolution: "1080p", aspect_ratio: "16:9" },
  },
  {
    id: "runway.performance.transfer",
    displayName: "Act-Two performance",
    category: "video",
    providerId: "runway",
    toolName: "act_two",
    inputPorts: [
      { id: "character", label: "Character", dataType: "image", targetField: "character_uri", required: true },
      { id: "performance", label: "Performance", dataType: "video", targetField: "performance_uri", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["character_uri", "character_type", "performance_uri", "performance_duration_seconds",
      "subjects", "consent_confirmed", "body_control", "expression_intensity", "ratio"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: { character_type: "image", ratio: "1280:720", body_control: true, expression_intensity: 3 },
  },
  {
    id: "fal.performance.motion",
    displayName: "Kling motion control",
    category: "video",
    providerId: "fal",
    toolName: "kling_motion_control",
    inputPorts: [
      { id: "character", label: "Character", dataType: "image", targetField: "image_url", required: true },
      { id: "performance", label: "Performance", dataType: "video", targetField: "video_url", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["image_url", "video_url", "performance_duration_seconds", "subjects", "consent_confirmed",
      "character_orientation", "keep_original_sound", "prompt"],
    pollTool: "get_video_task",
    pollIntervalMs: 5000,
    defaults: { character_orientation: "video", keep_original_sound: true },
  },
  {
    id: "runway.video.generate",
    displayName: "Runway video",
    category: "video",
    providerId: "runway",
    toolName: "text_to_video",
    inputPorts: [
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "ratio", "duration_seconds"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4.5", "ratio": "1280:720", "duration_seconds": 5},
  },
  {
    id: "runway.video.fromImage",
    displayName: "Runway image to video",
    category: "video",
    providerId: "runway",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "ratio", "duration_seconds", "image_path_or_url"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4.5", "ratio": "1280:720", "duration_seconds": 5},
  },
  {
    id: "runway.video.edit",
    displayName: "Runway Aleph edit",
    category: "video",
    providerId: "runway",
    toolName: "video_to_video",
    inputPorts: [
      { id: "video", label: "Video", dataType: "video", targetField: "video_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
      { id: "reference", label: "Guidance image", dataType: "image", targetField: "reference_image_path_or_url" },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "video_path_or_url", "video_duration_seconds", "reference_image_path_or_url", "reference_seconds"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "aleph2"},
  },
  {
    id: "runway.image.generate",
    displayName: "Runway image",
    category: "image",
    providerId: "runway",
    toolName: "text_to_image",
    inputPorts: [
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "ratio"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4_image", "ratio": "1280:720"},
  },
  {
    id: "runway.image.edit",
    displayName: "Runway reference image",
    category: "image",
    providerId: "runway",
    toolName: "image_to_image",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "ratio", "image_path_or_url"],
    pollTool: "get_runway_task",
    pollIntervalMs: 5000,
    defaults: {"model": "gen4_image", "ratio": "1280:720"},
  },
  {
    id: "video.falGenerate",
    displayName: "Wan VACE video",
    description: "Generate a Wan VACE clip from a prompt",
    category: "video",
    providerId: "fal",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "num_frames", "frames_per_second", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.wan3.generate",
    displayName: "Wan 3.0 video",
    description: "Generate a video with native audio from a prompt",
    category: "video",
    providerId: "fal",
    toolName: "generate_wan3_t2v",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "aspect_ratio", "duration", "resolution", "audio"],
    pollTool: "get_video_task",
    defaults: { resolution: "1080p", aspect_ratio: "adaptive", duration: 5, audio: true },
  },
  {
    id: "video.wan3.animate",
    displayName: "Wan 3.0 animation",
    description: "Animate a start frame with an optional end frame",
    category: "video",
    providerId: "fal",
    toolName: "generate_wan3_i2v",
    inputPorts: [
      { id: "image", label: "Start frame", dataType: "image", targetField: "start_image_url", required: true },
      { id: "end_image", label: "End frame", dataType: "image", targetField: "end_image_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt" },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "start_image_url", "end_image_url", "duration", "resolution", "audio", "real_face_refs", "likeness_consent"],
    pollTool: "get_video_task",
    defaults: { resolution: "1080p", aspect_ratio: "adaptive", duration: 5, audio: true },
  },
  {
    id: "video.wan3.reference",
    displayName: "Wan 3.0 reference video",
    description: "Generate a shot from image, video, or audio references",
    category: "video",
    providerId: "fal",
    toolName: "generate_wan3_r2v",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt" }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "reference_image_urls", "reference_video_urls", "reference_audio_urls", "duration", "resolution", "audio", "real_face_refs", "likeness_consent"],
    pollTool: "get_video_task",
    defaults: { resolution: "1080p", aspect_ratio: "adaptive", duration: 5, audio: true },
  },
  {
    id: "video.wan3.edit",
    displayName: "Wan 3.0 video edit",
    description: "Edit existing footage with Wan 3.0",
    category: "video",
    providerId: "alibaba_modelstudio",
    toolName: "edit_wan3_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_url", required: true },
      { id: "prompt", label: "Edit instruction", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "video_url", "source_duration_seconds", "source_fps", "duration", "resolution", "audio", "real_face_refs", "likeness_consent"],
    pollTool: "get_task",
    pollIntervalMs: 15000,
    defaults: { resolution: "1080p", aspect_ratio: "adaptive", duration: -1, audio: true },
  },
  {
    id: "video.wan3.extend",
    displayName: "Wan 3.0 video extend",
    description: "Continue existing footage with Wan 3.0",
    category: "video",
    providerId: "alibaba_modelstudio",
    toolName: "extend_wan3_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_url", required: true },
      { id: "prompt", label: "Continuation", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "video_url", "source_duration_seconds", "source_fps", "duration", "direction", "resolution", "audio", "real_face_refs", "likeness_consent"],
    pollTool: "get_task",
    pollIntervalMs: 15000,
    defaults: { resolution: "1080p", aspect_ratio: "adaptive", duration: -1, audio: true, direction: "forward" },
  },
  {
    id: "video.luma.generate",
    displayName: "Luma video",
    description: "Generate a Ray 3.2 clip from a prompt",
    category: "video",
    providerId: "luma",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "duration_seconds", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.fromImage",
    displayName: "Luma image to video",
    category: "video",
    providerId: "luma",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Start image", dataType: "image", targetField: "image_path_or_url" },
      { id: "endImage", label: "End image", dataType: "image", targetField: "last_frame_path_or_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "resolution", "image_path_or_url", "last_frame_path_or_url"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.modify",
    displayName: "Modify Luma video",
    category: "video",
    providerId: "luma",
    toolName: "modify_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_path_or_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "video_path_or_url", "source_generation_id", "source_duration_seconds", "resolution", "strength"],
    pollTool: "get_video_task",
  },
  {
    id: "video.luma.extend",
    displayName: "Extend Luma video",
    category: "video",
    providerId: "luma",
    toolName: "extend_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "generation_id", "direction", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "openai.image.generate",
    displayName: "GPT Image 2.5",
    description: "Generate a still from a prompt",
    category: "image",
    providerId: "openai_images",
    toolName: "generate_image",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size", "quality", "background", "output_format", "n"],
    defaults: { model: "gpt-image-2.5-sunburst", size: "2K", quality: "high", n: 1 },
  },
  {
    id: "openai.image.edit",
    displayName: "GPT Image 2.5 edit",
    description: "Restyle an image from a prompt",
    category: "image",
    providerId: "openai_images",
    toolName: "edit_image",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "mask", label: "Mask", dataType: "image", targetField: "mask_path_or_url" },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size", "quality", "image_path_or_url", "reference_image_urls", "mask_path_or_url", "background", "output_format", "n"],
    defaults: { model: "gpt-image-2.5-sunburst", size: "2K", quality: "high", n: 1 },
  },
  {
    id: "image.generate",
    displayName: "Seedream image",
    description: "Use Seedream when explicitly requested",
    category: "image",
    providerId: "seedream",
    toolName: "text_to_image",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size"],
  },
  {
    id: "image.edit",
    displayName: "Seedream edit",
    description: "Use Seedream editing when explicitly requested",
    category: "image",
    providerId: "seedream",
    toolName: "image_to_image",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "image", label: "Image", dataType: "image" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "size", "image_path_or_url"],
  },
  {
    id: "video.generate",
    displayName: "Seedance 2.5 video",
    description: "Generate synthetic-character dialogue",
    category: "video",
    providerId: "seedance",
    toolName: "text_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "aspect_ratio", "duration_seconds", "resolution"],
    pollTool: "get_video_task",
  },
  {
    id: "video.fromImage",
    displayName: "Seedance 2.5 image to video",
    description: "Animate a synthetic-character frame",
    category: "video",
    providerId: "seedance",
    toolName: "image_to_video",
    inputPorts: [
      { id: "image", label: "Image", dataType: "image", targetField: "image_path_or_url", required: true },
      { id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "model", "duration_seconds", "resolution", "image_path_or_url", "end_image_path_or_url", "source_aspect_ratio", "generate_audio", "real_face_refs"],
    pollTool: "get_video_task",
  },
  {
    id: "video.seedance.reference",
    displayName: "Seedance 2.5 references",
    description: "Generate a shot from synthetic-character references",
    category: "video",
    providerId: "seedance",
    toolName: "reference_to_video",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "reference_image_urls", "reference_video_urls", "reference_video_durations", "reference_video_fps", "reference_audio_urls", "reference_audio_durations", "duration_seconds", "resolution", "generate_audio", "real_face_refs"],
    pollTool: "get_video_task",
    defaults: { resolution: "720p", aspect_ratio: "16:9", duration_seconds: 5, generate_audio: true },
  },
  {
    id: "video.seedance.edit",
    displayName: "Seedance 2.5 edit",
    description: "Edit synthetic-character footage",
    category: "video",
    providerId: "seedance",
    toolName: "edit_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_url", required: true },
      { id: "prompt", label: "Edit instruction", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "video_url", "source_duration_seconds", "source_fps", "source_aspect_ratio", "resolution", "generate_audio", "real_face_refs"],
    pollTool: "get_video_task",
    defaults: { resolution: "720p", aspect_ratio: "adaptive", duration_seconds: -1, generate_audio: true },
  },
  {
    id: "video.seedance.extend",
    displayName: "Seedance 2.5 extend",
    description: "Continue synthetic-character footage",
    category: "video",
    providerId: "seedance",
    toolName: "extend_video",
    inputPorts: [
      { id: "video", label: "Source video", dataType: "video", targetField: "video_url", required: true },
      { id: "prompt", label: "Continuation", dataType: "text", targetField: "prompt", required: true },
    ],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["prompt", "video_url", "source_duration_seconds", "source_fps", "source_aspect_ratio", "duration_seconds", "resolution", "generate_audio", "real_face_refs"],
    pollTool: "get_video_task",
    defaults: { resolution: "720p", aspect_ratio: "adaptive", duration_seconds: 5, generate_audio: true },
  },
  {
    id: "music.generate",
    displayName: "Music",
    description: "Generate a Mureka V9.5 instrumental music bed",
    category: "audio",
    providerId: "mureka",
    toolName: "generate_instrumental",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["prompt", "instrumental_id", "model"],
    pollTool: "get_music_task",
    pollIntervalMs: 10000,
    defaults: { model: "mureka-9.5" },
  },
  {
    id: "music.song",
    displayName: "Mureka song",
    description: "Generate a song from lyrics or a prompt",
    category: "audio",
    providerId: "mureka",
    toolName: "generate_song",
    inputPorts: [{ id: "prompt", label: "Prompt", dataType: "text", targetField: "prompt" }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["lyrics", "prompt", "styles", "gender", "model"],
    pollTool: "get_music_task",
    pollIntervalMs: 10000,
    defaults: { model: "mureka-9.5" },
  },
  {
    id: "video.mureka.lyrics",
    displayName: "Mureka lyrics video",
    description: "Use chat to approve a lyrics video from a Mureka song or uploaded audio ID",
    category: "video",
    providerId: "mureka",
    toolName: "generate_lyrics_video",
    inputPorts: [],
    outputPorts: [{ id: "video", label: "Video", dataType: "video" }],
    primaryFields: ["song_id", "upload_audio_id", "layout", "aspect_ratio", "title", "background_id",
      "cover_url", "lyrics_start_row", "lyrics_end_row", "selection_start", "selection_end"],
    pollTool: "get_video_task",
    pollIntervalMs: 10000,
    defaults: { layout: "layout_1", aspect_ratio: "9:16" },
  },
  {
    id: "voice.generate",
    displayName: "Voiceover",
    description: "Read text as speech",
    category: "audio",
    providerId: "elevenlabs",
    toolName: "text_to_speech_convert",
    inputPorts: [{ id: "text", label: "Script", dataType: "text", targetField: "text", required: true }],
    outputPorts: [{ id: "audio", label: "Audio", dataType: "audio" }],
    primaryFields: ["text", "voice_id", "model_id", "output_format"],
  },
];

export function toolById(id: string | undefined): ToolDefinition | undefined {
  if (!id) {
    return undefined;
  }
  return CREATIVE_TOOLS.find((tool) => tool.id === id);
}

export function defaultToolForRail(
  rail: "image" | "video" | "audio" | "voice",
): ToolDefinition | undefined {
  switch (rail) {
    case "image":
      return toolById("openai.image.generate");
    case "video":
      return toolById("video.wan3.generate");
    case "audio":
      return toolById("music.generate");
    case "voice":
      return toolById("voice.generate");
    default: {
      const exhaustive: never = rail;
      return exhaustive;
    }
  }
}

export function toolForAgentArtifact(
  kind: "image" | "video" | "audio",
  event?: Pick<AgentToolEvent, "name" | "provider" | "providerJobId">,
): ToolDefinition | undefined {
  // Agent artifacts become self-contained text-to-media nodes. Even when the
  // agent used an input asset or a composition tool, placing the result must
  // not create an invisible dependency on another artifact in the run.
  const provider = `${event?.provider || ""} ${event?.name || ""} ${event?.providerJobId || ""}`.toLowerCase();
  const runway = provider.includes("runway");
  if (kind === "image") {
    if (provider.includes("ideogram")) return toolById("image.ideogram.edit");
    if (provider.includes("recraft")) return toolById("image.recraft.vector");
    return toolById(runway ? "runway.image.generate" : provider.includes("seedream") ? "image.generate" : "openai.image.generate");
  }
  if (kind === "video") {
    return toolById(
      provider.includes("heygen") ? "video.heygen.presenter"
        : runway ? "runway.video.generate"
        : provider.includes("luma") ? "video.luma.generate"
        : provider.includes("generate_wan3") ? "video.wan3.generate"
        : provider.includes("fal") ? "video.falGenerate"
        : provider.includes("seedance") ? "video.generate"
        : "video.wan3.generate",
    );
  }
  const source = `${event?.provider || ""} ${event?.name || ""}`.toLowerCase();
  return toolById(
    source.includes("fish_audio") || source.includes("speech") || source.includes("voice")
      ? "voice.generate"
      : "music.generate",
  );
}

export function portsForNode(toolId: string | undefined, kind: CreativeNodeKind): {
  inputs: ToolDefinition["inputPorts"];
  outputs: ToolDefinition["outputPorts"];
} {
  const tool = toolById(toolId);
  if (tool) {
    return { inputs: tool.inputPorts, outputs: tool.outputPorts };
  }
  switch (kind) {
    case "text":
      return { inputs: [], outputs: [{ id: "text", label: "Text", dataType: "text" }] };
    case "image":
      return { inputs: [], outputs: [{ id: "image", label: "Image", dataType: "image" }] };
    case "video":
      return { inputs: [], outputs: [{ id: "video", label: "Video", dataType: "video" }] };
    case "audio":
      return { inputs: [], outputs: [{ id: "audio", label: "Audio", dataType: "audio" }] };
    case "storyboard":
      return {
        inputs: [
          { id: "image", label: "Shot", dataType: "image", targetField: "shot" },
          { id: "video", label: "Clip", dataType: "video", targetField: "clip" },
        ],
        outputs: [],
      };
    case "generator":
      return { inputs: [], outputs: [] };
    case "agentResult":
      return { inputs: [], outputs: [{ id: "text", label: "Result", dataType: "text" }] };
    case "agentRun":
      return { inputs: [], outputs: [] };
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export function portDataTypeLabel(dataType: PortDataType): string {
  switch (dataType) {
    case "text":
      return "text";
    case "image":
      return "image";
    case "video":
      return "video";
    case "audio":
      return "audio";
    default: {
      const exhaustive: never = dataType;
      return exhaustive;
    }
  }
}
