from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE / 'backend' / '.env'), extra='ignore')
    openai_api_key: str = ''
    openai_model: str = 'gpt-4o-mini'
    embedding_model: str = 'text-embedding-3-small'
    database_url: str = f'sqlite:///{BASE / "data" / "researchmind.db"}'
    storage_dir: str = str(BASE / 'data')
    frontend_origin: str = 'http://localhost:5173'
    max_upload_mb: int = 15

settings = Settings()
