from pathlib import Path

from dotenv import load_dotenv


def load_environment(root: Path | None = None) -> None:
    """Load project-local config without overriding deployment environment values."""
    root = root if root is not None else Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env.local", override=False)
    load_dotenv(root / ".env", override=False)
