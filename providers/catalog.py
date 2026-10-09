"""Provider catalog: one spec per Gateway Lambda target."""

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


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="heygen", target_name="HeyGen", function_name="renderhaus-heygen-tools",
        module_path="providers.heygen.api",
        env_keys=("HEYGEN_API_KEY", "HEYGEN_DRY_RUN", "HEYGEN_MODEL", "HEYGEN_API_PLAN", "AWS_S3_BUCKET"),
        default_env={"HEYGEN_DRY_RUN": "true", "HEYGEN_MODEL": "avatar_v", "HEYGEN_API_PLAN": "unknown"},
    ),
    ProviderSpec(
        id="sync", target_name="Sync", function_name="renderhaus-sync-tools",
        module_path="providers.sync.api",
        env_keys=("SYNC_API_KEY", "SYNC_DRY_RUN", "SYNC_MODEL", "SYNC_TRANSPORT",
                  "SYNC_DIRECT_AUTHORIZED", "SYNC_MAX_CHUNK_SECONDS", "SYNC_BILLING_PLAN",
                  "FAL_KEY", "FAL_DRY_RUN", "AWS_S3_BUCKET", "REMOTION_LOCAL_MEDIA_HOSTS"),
        default_env={"SYNC_DRY_RUN": "true", "SYNC_MODEL": "sync-3", "SYNC_TRANSPORT": "fal",
                     "SYNC_DIRECT_AUTHORIZED": "false", "SYNC_MAX_CHUNK_SECONDS": "60",
                     "SYNC_BILLING_PLAN": "legacy_base", "FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="openai_images", target_name="OpenAI", function_name="renderhaus-openai-images-tools",
        module_path="providers.openai_images.api",
        env_keys=("OPENAI_API_KEY", "OPENAI_IMAGES_DRY_RUN", "OPENAI_IMAGES_MODEL",
                  "OPENAI_IMAGES_TOOL_COST_CENTS_JSON", "AWS_S3_BUCKET", "REMOTION_APP_BUCKET_NAME"),
        default_env={"OPENAI_IMAGES_DRY_RUN": "true", "OPENAI_IMAGES_MODEL": "gpt-image-2.5-sunburst"},
    ),
    ProviderSpec(
        id="kling",
        target_name="Kling",
        function_name="renderhaus-kling-tools",
        module_path="providers.kling.api",
        env_keys=(
            "KLING_BASE_URL",
            "KLING_MODEL",
            "KLING_API_STYLE",
            "KLING_DRY_RUN",
        ),
        default_env={
            "KLING_DRY_RUN": "true",
            "KLING_MODEL": "kling-3.0",
            "KLING_API_STYLE": "current",
            "KLING_BASE_URL": "https://api-singapore.klingai.com",
        },
    ),
    ProviderSpec(
        id="runway",
        target_name="Runway",
        function_name="renderhaus-runway-tools",
        module_path="providers.runway.api",
        env_keys=("RUNWAYML_API_SECRET", "RUNWAY_DRY_RUN"),
        default_env={"RUNWAY_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="fal",
        target_name="Fal",
        function_name="renderhaus-fal-tools",
        module_path="providers.fal.api",
        env_keys=("FAL_KEY", "FAL_DRY_RUN"),
        default_env={"FAL_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="luma",
        target_name="Luma",
        function_name="renderhaus-luma-tools",
        module_path="providers.luma.api",
        env_keys=("LUMA_API_KEY", "LUMA_DRY_RUN"),
        default_env={"LUMA_DRY_RUN": "true"},
    ),
    ProviderSpec(
        id="alibaba_modelstudio",
        target_name="ModelStudio",
        function_name="renderhaus-modelstudio-tools",
        module_path="providers.alibaba_modelstudio.api",
        env_keys=("DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_WORKSPACE_ID",
                  "DASHSCOPE_REGION", "DASHSCOPE_MODEL", "MODELSTUDIO_DRY_RUN"),
        default_env={"MODELSTUDIO_DRY_RUN": "true"},
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
            "REMOTION_FRAMES_PER_LAMBDA",
            "PROVIDER_INPUT_BUCKET",
            "AWS_S3_BUCKET",
        ),
        default_env={
            "REMOTION_DRY_RUN": "true",
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
