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
        ),
        default_env={
            "SEEDANCE_DRY_RUN": "true",
            "SEEDANCE_MODEL": "seedance-1-5-pro-251215",
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
        id="mureka",
        target_name="Mureka",
        function_name="renderhaus-mureka-tools",
        module_path="providers.mureka.api",
        env_keys=(
            "MUREKA_API_KEY",
            "MUREKA_API_URL",
            "MUREKA_MODEL",
            "MUREKA_DRY_RUN",
        ),
        default_env={
            "MUREKA_DRY_RUN": "true",
            "MUREKA_API_URL": "https://api.mureka.ai",
            "MUREKA_MODEL": "auto",
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
