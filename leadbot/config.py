import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so the app runs without extra tooling."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    ig_access_token: str
    ig_user_id: str
    app_secret: str
    verify_token: str
    graph_host: str
    graph_api_version: str
    admin_username: str
    admin_password: str
    database_path: str
    content_path: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path(".env"))
        env = os.environ.get
        return cls(
            ig_access_token=env("IG_ACCESS_TOKEN", ""),
            ig_user_id=env("IG_USER_ID", ""),
            app_secret=env("APP_SECRET", ""),
            verify_token=env("VERIFY_TOKEN", ""),
            graph_host=env("GRAPH_HOST", "https://graph.instagram.com").rstrip("/"),
            graph_api_version=env("GRAPH_API_VERSION", "v23.0"),
            admin_username=env("ADMIN_USERNAME", "admin"),
            admin_password=env("ADMIN_PASSWORD", ""),
            database_path=env("DATABASE_PATH", "leads.db"),
            content_path=env("CONTENT_PATH", "content.yaml"),
            dry_run=env("DRY_RUN", "0").lower() in ("1", "true", "yes"),
        )
