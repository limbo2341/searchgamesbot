from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    # Bot
    bot_token: str = Field(..., env="BOT_TOKEN")

    # Database
    database_url: str = Field(..., env="DATABASE_URL")

    # Redis
    redis_url: str = Field(..., env="REDIS_URL")

    # APIs
    openrouter_api_key: str = Field("", env="OPENROUTER_API_KEY")
    rawg_api_key: str = Field(..., env="RAWG_API_KEY")
    openrouter_model: str = Field("google/gemini-flash-1.5", env="OPENROUTER_MODEL")
    gemini_api_key: str = Field("", env="GEMINI_API_KEY")

    # Payments
    privat_card: str = Field(..., env="PRIVAT_CARD")

    # Admins
    admin_ids_str: str = Field("7245932902,8528807150", env="ADMIN_IDS")

    # App
    default_language: str = Field("en", env="DEFAULT_LANGUAGE")

    # Limits
    free_daily_searches: int = 2

    # Premium prices (UAH)
    premium_7_days_uah: int = 39
    premium_30_days_uah: int = 89
    premium_90_days_uah: int = 199
    premium_forever_uah: int = 399

    # Premium prices (Stars)
    premium_7_days_stars: int = 100
    premium_30_days_stars: int = 250
    premium_90_days_stars: int = 500
    premium_forever_stars: int = 1000

    # Referral
    referral_reward_days: int = 5
    referral_required_count: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.admin_ids_str.split(",") if x.strip()]


settings = Settings()
