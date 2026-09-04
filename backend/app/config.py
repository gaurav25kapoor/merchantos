from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MerchantOS API"
    environment: str = "development"

    database_url: str

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
