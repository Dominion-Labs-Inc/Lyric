#!/usr/bin/env python3
"""Environment loader (portable).

This project supports env-based configuration via `.env.production` and/or `.env`.
Historically, this module hardcoded a Dominion Labs workstation path and carried
MySQL-era defaults. Those assumptions have been removed.

Resolution order:
- If `LYRIC_ENV_FILE` (or `DOMINION_ENV_FILE`) is set, load that path.
- Else, look for `.env.production` then `.env` in common repo locations.
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILES: tuple[str, ...] = (".env.production", ".env")


def resolve_env_files() -> list[Path]:
    """The env files to load: the substrate's OWN, and nothing else.

    This used to layer the Dominion Labs workspace `.env` (every company
    credential: payments, email, cloud storage, other products) under Lyric's
    own file, so the substrate's process held 158 keys it never reads. Measured
    2026-10-01: Lyric's code reads no key that exists only in the workspace file
    (the threat-intelligence and DB readers that named some were dead). The
    substrate holds its own keys, in its own file, which it may add to through
    `core.security.secrets`.
    """
    explicit = os.getenv("LYRIC_ENV_FILE") or os.getenv("DOMINION_ENV_FILE")
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return [p] if p.exists() else []

    lyric_root = Path(__file__).resolve().parents[2]
    files: list[Path] = []
    # .env.production before .env so .env still wins locally; `.env` is
    # normally a link to `.env.production`, and one file is loaded once.
    for name in (".env.production", ".env"):
        candidate = lyric_root / name
        if candidate.exists() and candidate.resolve() not in {f.resolve() for f in files}:
            files.append(candidate)
    return files


def resolve_env_file() -> Optional[Path]:
    """The single winning env file (the last override), for messaging.

    Kept for callers that want one representative path. The real loading uses
    `resolve_env_files()`.
    """
    files = resolve_env_files()
    return files[-1] if files else None


def load_global_env(force_reload: bool = False):
    """
    Load environment variables from the Dominion Labs global .env file

    This ensures all services (Lyric, security systems, Cloud Storage, etc.)
    use the same environment configuration.

    Args:
        force_reload: If True, reload even if already loaded

    Returns:
        True if loaded successfully, False otherwise
    """
    # Check if already loaded (unless force reload)
    if not force_reload and os.getenv('DOMINION_ENV_LOADED'):
        logger.debug("Global environment already loaded")
        return True

    env_files = resolve_env_files()
    if not env_files:
        logger.debug("No .env file found; using existing process environment")
        return False

    try:
        # Load each layer in base→override order (workspace master first, local
        # overrides last). override=True so a later layer wins, which is the
        # whole point of the ordering.
        try:
            from dotenv import load_dotenv
            for env_file in env_files:
                load_dotenv(env_file, override=True)
            logger.info("✅ Loaded environment from: %s",
                        ", ".join(str(f) for f in env_files))
        except ImportError:
            # Fallback: Manual parsing if dotenv not available
            logger.warning("python-dotenv not available, using manual parsing")
            for env_file in env_files:
                _manual_load_env(env_file)

        # Mark as loaded
        os.environ['DOMINION_ENV_LOADED'] = 'true'
        return True

    except Exception as e:
        logger.error(f"Failed to load global environment: {e}")
        return False


def _manual_load_env(env_file: Path):
    """
    Manually parse .env file if python-dotenv not available

    Args:
        env_file: Path to .env file
    """
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                # Set environment variable
                os.environ[key] = value


def get_env(
    key: str,
    default: Optional[str] = None,
    required: bool = False
) -> Optional[str]:
    """
    Get environment variable from global .env

    Args:
        key: Environment variable key
        default: Default value if not found
        required: If True, raise error if not found

    Returns:
        Environment variable value or default

    Raises:
        ValueError: If required=True and key not found
    """
    # Ensure global env is loaded
    load_global_env()

    value = os.getenv(key, default)

    if required and value is None:
        source = resolve_env_file()
        raise ValueError(
            f"Required environment variable '{key}' not found" + (f" in {source}" if source else "")
        )

    return value


def get_cloudflare_credentials() -> dict:
    """
    Get Cloudflare credentials from global .env

    Returns:
        Dictionary with api_token and zone_id (may be None if not set)
    """
    return {
        'api_token': get_env('CLOUDFLARE_API_TOKEN'),
        'zone_id': get_env('CLOUDFLARE_ZONE_ID')
    }


def get_github_token() -> Optional[str]:
    """The substrate's GitHub token: `GITHUB_TOKEN` (or `GH_TOKEN`) from its own
    key file, or None.

    This used to fall through to the gh CLI, the macOS Keychain and
    `git credential fill`, so with no token of its own the substrate took the
    owner's personal GitHub login. A credential it was not given is not one it
    may use; the substrate has its own token.
    """
    load_global_env()
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.getenv(var, "").strip()
        if val and not val.startswith("#"):
            return val
    logger.warning("get_github_token(): the substrate holds no GitHub token "
                   "(GITHUB_TOKEN in its key file)")
    return None


# Auto-load on module import
load_global_env()

logger.info(f"📁 Environment loader initialized (source: {resolve_env_file()})")
