import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_file() -> None:
    """Загружает .env из корня проекта. Уже заданные переменные окружения не переопределяет."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


load_env_file()
