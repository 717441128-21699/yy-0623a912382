from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "材料进场验收服务"
    APP_VERSION: str = "1.0.0"

    DATABASE_URL: str = "sqlite:///./material_acceptance.db"

    REINSPECTION_DAYS: int = 3

    API_V1_PREFIX: str = "/api/v1"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
