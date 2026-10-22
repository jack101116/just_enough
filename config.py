"""Environment-based configuration for Just Enough.

Nothing secret is hard-coded. SECRET_KEY comes from the environment (or a .env
file). If it is not provided, a random key is generated once and stored in
instance/secret_key so sessions survive restarts on a local machine.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def load_dotenv(path=None):
    """Tiny .env reader (KEY=VALUE lines). Existing environment values win."""
    path = Path(path or BASE_DIR / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_secret_key():
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    INSTANCE_DIR.mkdir(exist_ok=True)
    key_file = INSTANCE_DIR / "secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


def build_config():
    load_dotenv()
    INSTANCE_DIR.mkdir(exist_ok=True)
    return {
        "SECRET_KEY": get_secret_key(),
        "DATABASE": os.environ.get("JUST_ENOUGH_DB", str(INSTANCE_DIR / "just_enough.db")),
        "DEBUG_MODE": os.environ.get("FLASK_DEBUG", "0") == "1",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        "CURRENCY_SYMBOL": os.environ.get("CURRENCY_SYMBOL", "₹"),
        "MAX_CONTENT_LENGTH": 1024 * 1024,
    }
