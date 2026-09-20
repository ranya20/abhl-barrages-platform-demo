from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    APP_NAME: str = "ABHL Barrages Platform"
    APP_ENV: str = "development"
    DEBUG: bool = True
    DATABASE_URL: str

    EXCEL_TEMPLATES_DIR: str = "../excel_templates"
    DATA_IMPORTS_DIR: str = "../data/imports"
    DATA_EXPORTS_DIR: str = "../data/exports"

    JWT_SECRET_KEY: str = "CHANGE_ME_WITH_A_LONG_RANDOM_SECRET"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_MINUTES: int = 480
    JWT_ISSUER: str = "abhl-barrages-api"
    JWT_AUDIENCE: str = "abhl-barrages-frontend"

    AUTH_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_LOCK_MINUTES: int = 15

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        extra="ignore",
    )


settings = Settings()

if (
    settings.APP_ENV.lower() in {"production", "prod"}
    and settings.JWT_SECRET_KEY == "CHANGE_ME_WITH_A_LONG_RANDOM_SECRET"
):
    raise RuntimeError(
        "JWT_SECRET_KEY doit être défini avec une valeur aléatoire en production."
    )
