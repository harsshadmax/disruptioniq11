from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-env"
_DEFAULT_WEBHOOK_SECRET = "dev-webhook-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # anything else (for example "production") refuses default secrets
    database_url: str = "postgresql+psycopg://disruptioniq:disruptioniq@localhost:5433/disruptioniq"
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    approval_sla_hours: float = 2.0  # plans waiting longer than this are flagged overdue and re-notified
    webhook_secret: str = _DEFAULT_WEBHOOK_SECRET  # shared with the (simulated) carrier; signs request bodies
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    # Optional second opinion on contract terms from any OpenAI-compatible chat API, such as a free-tier provider.
    check_llm_base_url: str | None = None  # for example https://api.groq.com/openai/v1
    check_llm_api_key: str | None = None
    check_llm_model: str | None = None
    cors_origins: str = "http://localhost:3000"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in ("development", "dev", "test")

    @model_validator(mode="after")
    def _use_the_psycopg3_driver(self) -> "Settings":
        """Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy would pick psycopg2 for those."""
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix):]
        return self

    @model_validator(mode="after")
    def _no_default_secrets_outside_development(self) -> "Settings":
        if not self.is_development:
            weak = [name for name, value, default in (("JWT_SECRET", self.jwt_secret, _DEFAULT_JWT_SECRET),
                                                      ("WEBHOOK_SECRET", self.webhook_secret, _DEFAULT_WEBHOOK_SECRET))
                    if value == default or len(value) < 16]
            if weak:
                raise ValueError(f"{', '.join(weak)} must be set to a strong value (16+ characters) when ENVIRONMENT="
                                 f"{self.environment}")
        return self


settings = Settings()
