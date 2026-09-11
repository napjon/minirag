from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.domain.enums import AuthMode, DeploymentProfile, ModelProvider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Marketdesk"
    app_env: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8130
    web_origin: str = "http://127.0.0.1:3130"
    database_url: str = "postgresql+asyncpg://marketdesk:marketdesk@127.0.0.1:5432/marketdesk"
    database_admin_url: str | None = (
        "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/marketdesk"
    )
    redis_url: str = "redis://:devredispass@127.0.0.1:6379/0"
    object_store_endpoint: str = "http://127.0.0.1:59000"
    object_store_access_key: str = "marketdesk"
    object_store_secret_key: SecretStr = SecretStr("marketdesk-secret")
    object_store_bucket: str = "marketdesk"
    object_store_region: str = "us-east-1"
    auth_mode: AuthMode = AuthMode.DEMO
    jwt_secret: SecretStr = SecretStr("change-me-local-only-32bytes-min")
    jwt_issuer: str = "marketdesk-local"
    jwt_audience: str = "marketdesk"
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_cache_seconds: int = 300
    deployment_profile: DeploymentProfile = DeploymentProfile.HOSTED
    model_provider: ModelProvider = ModelProvider.FIXTURE
    hosted_model_base_url: str = "https://hosted-model.example.invalid/v1"
    hosted_model_api_key: SecretStr | None = None
    hosted_generation_model: str = "hosted-generation-v1"
    hosted_intent_model: str = "hosted-intent-v1"
    hosted_input_cost_per_million: float = 2.0
    hosted_output_cost_per_million: float = 6.0
    private_model_base_url: str = "http://127.0.0.1:18000/v1"
    private_generation_model: str = "private-generation-32b"
    private_vision_model: str = "private-vision-8b"
    embedding_provider: Literal["fixture", "multilingual"] = "fixture"
    embedding_dim: int = 1024
    private_egress_blocked: bool = False
    log_level: str = "INFO"
    interactive_queue_limit: int = 200
    interactive_start_timeout_seconds: int = 15
    job_execution_mode: Literal["inline", "worker"] = "inline"
    job_max_attempts: int = 3
    job_lease_seconds: int = 300
    job_poll_seconds: float = 1.0
    evidence_token_budget: int = 6000
    max_upload_bytes: int = 25_000_000
    lexical_k: int = 60
    vector_k: int = 60
    rrf_k: int = 60
    rerank_k: int = 40
    evidence_k: int = 10
    demo_workspace_slug: str = "harbor"

    @property
    def admin_database_url(self) -> str:
        return self.database_admin_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
