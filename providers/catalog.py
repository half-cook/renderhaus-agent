"""Provider catalog for Gateway schemas and local worker tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    target_name: str
    function_name: str
    module_path: str
    env_keys: tuple[str, ...]
    default_env: dict[str, str] = field(default_factory=dict)
    local_only: bool = False


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="fish_audio", target_name="FishAudio", function_name="renderhaus-fish-audio-tools",
        module_path="providers.fish_audio.api",
        env_keys=("FISH_API_KEY", "FISH_AUDIO_DRY_RUN", "FISH_AUDIO_MODEL"),
        default_env={"FISH_AUDIO_DRY_RUN": "true", "FISH_AUDIO_MODEL": "s2.1-pro-free"},
    ),
    ProviderSpec(
        id='reference_shots', target_name='Reference', function_name='renderhaus-reference-local-tools',
        module_path='providers.reference_shots.api',
        env_keys=('REFERENCE_SHOTS_DRY_RUN', 'RENDERHAUS_MEDIA_DIR'),
        default_env={'REFERENCE_SHOTS_DRY_RUN': 'true'}, local_only=True,
    ),
    ProviderSpec(
        id="lottie", target_name="Lottie", function_name="renderhaus-lottie-tools",
        module_path="providers.lottie.api", env_keys=("RENDERHAUS_MEDIA_DIR",),
    ),
    ProviderSpec(
        id="logo_animation", target_name="Logo", function_name="renderhaus-logo-local-tools",
        module_path="providers.logo_animation.api", env_keys=(), local_only=True,
    ),
    ProviderSpec(
        id="shot_recipes", target_name="ShotRecipes", function_name="renderhaus-shot-recipes-tools",
        module_path="providers.shot_recipes.api", env_keys=(),
    ),
    ProviderSpec(
        id="ffmpeg", target_name="Ffmpeg", function_name="renderhaus-ffmpeg-tools",
        module_path="providers.ffmpeg.api",
        env_keys=("FFMPEG_DRY_RUN", "RENDERHAUS_MEDIA_DIR"),
        default_env={"FFMPEG_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="gemini", target_name="Gemini", function_name="renderhaus-gemini-tools",
        module_path="providers.gemini.tools",
        env_keys=("GOOGLE_API_KEY", "GEMINI_DRY_RUN", "GEMINI_VLM_MODEL",
                  "GEMINI_VLM_TIMEOUT_SECONDS", "GEMINI_VLM_MAX_RETRIES", "GEMINI_TOOL_COST_CENTS_JSON"),
        default_env={"GEMINI_DRY_RUN": "true", "GEMINI_VLM_MODEL": "gemini-3.8-flash"},
    ),
    ProviderSpec(
        id="mureka", target_name="Mureka", function_name="renderhaus-mureka-tools",
        module_path="providers.mureka.api",
        env_keys=("MUREKA_DRY_RUN", "MUREKA_MODEL", "FAL_KEY", "FAL_DRY_RUN"),
        default_env={"MUREKA_DRY_RUN": "true", "MUREKA_MODEL": "mureka-9.5", "FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="topaz", target_name="Topaz", function_name="renderhaus-topaz-tools",
        module_path="providers.topaz.api",
        env_keys=("TOPAZ_DRY_RUN", "FAL_KEY", "FAL_DRY_RUN"),
        default_env={"TOPAZ_DRY_RUN": "true", "FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="sync", target_name="Sync", function_name="renderhaus-sync-tools",
        module_path="providers.sync.api",
        env_keys=("SYNC_DRY_RUN", "SYNC_MODEL", "SYNC_MAX_CHUNK_SECONDS", "FAL_KEY", "FAL_DRY_RUN",
                  "AWS_S3_BUCKET", "REMOTION_LOCAL_MEDIA_HOSTS"),
        default_env={"SYNC_DRY_RUN": "true", "SYNC_MODEL": "sync-3",
                     "SYNC_MAX_CHUNK_SECONDS": "60", "FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="openai_images", target_name="OpenAI", function_name="renderhaus-openai-images-tools",
        module_path="providers.openai_images.api",
        env_keys=("OPENAI_API_KEY", "OPENAI_IMAGES_DRY_RUN", "OPENAI_IMAGES_MODEL",
                  "OPENAI_IMAGES_TOOL_COST_CENTS_JSON", "AWS_S3_BUCKET", "REMOTION_APP_BUCKET_NAME"),
        default_env={"OPENAI_IMAGES_DRY_RUN": "true", "OPENAI_IMAGES_MODEL": "gpt-image-2.5-sunburst"},
    ),
    ProviderSpec(
        id="fal",
        target_name="Fal",
        function_name="renderhaus-fal-tools",
        module_path="providers.fal.api",
        env_keys=("FAL_KEY", "FAL_DRY_RUN", "AWS_S3_BUCKET", "REMOTION_APP_BUCKET_NAME"),
        default_env={"FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="seedance",
        target_name="Seedance",
        function_name="renderhaus-seedance-tools",
        module_path="providers.seedance.api",
        env_keys=(
            "BYTEPLUS_API_KEY",
            "ARK_API_KEY",
            "BYTEPLUS_BASE_URL",
            "SEEDANCE_MODEL",
            "SEEDANCE_DRY_RUN",
            "SEEDANCE_TRANSPORT",
            "SEEDANCE_FAL_REGION",
            "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED",
            "RENDERHAUS_CUSTOMER_REGION",
            "FAL_KEY",
            "FAL_DRY_RUN",
        ),
        default_env={
            "SEEDANCE_DRY_RUN": "true",
            "SEEDANCE_MODEL": "dreamina-seedance-2-5-260628",
            "SEEDANCE_TRANSPORT": "fal",
            "SEEDANCE_FAL_REGION": "us",
            "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED": "false",
            "FAL_DRY_RUN": "true",
            "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
        },
    ),
    ProviderSpec(
        id="seedream",
        target_name="Seedream",
        function_name="renderhaus-seedream-tools",
        module_path="providers.seedream.api",
        env_keys=(
            "BYTEPLUS_API_KEY",
            "ARK_API_KEY",
            "BYTEPLUS_BASE_URL",
            "SEEDREAM_MODEL",
            "SEEDREAM_DRY_RUN",
            "SEEDANCE_DRY_RUN",
        ),
        default_env={
            "SEEDREAM_DRY_RUN": "true",
            "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
        },
    ),
    ProviderSpec(
        id="elevenlabs",
        target_name="ElevenLabs",
        function_name="renderhaus-elevenlabs-tools",
        module_path="providers.elevenlabs.api",
        env_keys=(
            "ELEVENLABS_DRY_RUN",
            "ELEVENLABS_TTS_MODEL",
            "AWS_S3_BUCKET",
            "PROVIDER_INPUT_BUCKET",
            "REMOTION_APP_BUCKET_NAME",
        ),
        default_env={
            "ELEVENLABS_DRY_RUN": "true",
            "ELEVENLABS_TTS_MODEL": "eleven_v4_turbo",
        },
    ),
    ProviderSpec(
        id="remotion",
        target_name="Remotion",
        function_name="renderhaus-remotion-tools",
        module_path="providers.remotion.api",
        env_keys=(
            "REMOTION_APP_REGION",
            "REMOTION_APP_FUNCTION_NAME",
            "REMOTION_APP_SERVE_URL",
            "REMOTION_APP_BUCKET_NAME",
            "REMOTION_DRY_RUN",
            "MOTION_CARRY_QC_DRY_RUN",
            "REMOTION_RENDER_BACKEND",
            "REMOTION_LICENSE_RENDER_USD",
            "REMOTION_MATRIX_LAMBDA_MEMORY_MB",
            "REMOTION_MATRIX_LAMBDA_COMPUTE_SECONDS",
            "REMOTION_MATRIX_LAMBDA_REQUESTS",
            "REMOTION_MATRIX_LAMBDA_RENDER_USD",
            "REMOTION_OVERLAY_CONTRACT_VERSION",
            "REMOTION_FRAMES_PER_LAMBDA",
            "REMOTION_LOCAL_MEDIA_HOSTS",
            "PROVIDER_INPUT_BUCKET",
            "AWS_S3_BUCKET",
        ),
        default_env={
            "REMOTION_DRY_RUN": "true",
            "MOTION_CARRY_QC_DRY_RUN": "true",
        },
    ),
)

PROVIDERS_BY_ID = {spec.id: spec for spec in PROVIDERS}


def get_provider(provider_id: str) -> ProviderSpec:
    spec = PROVIDERS_BY_ID.get(provider_id)
    if spec is None:
        known = ", ".join(PROVIDERS_BY_ID)
        raise ValueError(f"Unknown provider {provider_id!r}. Known: {known}")
    return spec


def parse_provider_ids(raw: str) -> tuple[ProviderSpec, ...]:
    value = (raw or "all").strip().lower()
    if value in {"", "all"}:
        return PROVIDERS
    ids = [part.strip() for part in value.split(",") if part.strip()]
    return tuple(get_provider(provider_id) for provider_id in ids)
