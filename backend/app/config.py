from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MerchantOS API"
    environment: str = "development"

    database_url: str

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        """Normalize provider URLs to SQLAlchemy's Psycopg 3 dialect."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgresql+psycopg2://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql+psycopg2://")
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    payment_provider: str = "razorpay"
    payment_mode: str = "mock"

    llm_provider: str = "fallback"
    llm_api_key: str = ""

    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
