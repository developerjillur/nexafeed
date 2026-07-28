#!/usr/bin/env python3
"""Shared environment and provider configuration helpers for NexaFeed.

Secrets stay in environment files or platform secrets, never in generated public
JSON or frontend JavaScript. These helpers intentionally expose only redacted
provider readiness metadata.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}

LLM_PROVIDER_ALIASES = {
    "": "none",
    "off": "none",
    "disabled": "none",
    "openai-compatible": "custom",
    "openai_compatible": "custom",
    "gemini": "google",
    "google-ai": "google",
    "google_ai": "google",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "x": "xai",
    "x-ai": "xai",
    "z-ai": "zai",
    "glm": "zai",
}

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "none": {
        "displayName": "No LLM provider",
        "keyEnv": [],
        "baseUrl": "",
        "defaultModel": "",
        "requiresApiKey": False,
    },
    "openai": {
        "displayName": "OpenAI",
        "keyEnv": ["OPENAI_API_KEY"],
        "baseUrl": "https://api.openai.com/v1",
        "defaultModel": "gpt-4o-mini",
    },
    "anthropic": {
        "displayName": "Anthropic Claude",
        "keyEnv": ["ANTHROPIC_API_KEY"],
        "baseUrl": "https://api.anthropic.com",
        "defaultModel": "claude-3-5-haiku-latest",
    },
    "openrouter": {
        "displayName": "OpenRouter",
        "keyEnv": ["OPENROUTER_API_KEY"],
        "baseUrl": "https://openrouter.ai/api/v1",
        "defaultModel": "openai/gpt-4o-mini",
    },
    "google": {
        "displayName": "Google Gemini",
        "keyEnv": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "defaultModel": "gemini-1.5-flash",
    },
    "groq": {
        "displayName": "Groq",
        "keyEnv": ["GROQ_API_KEY"],
        "baseUrl": "https://api.groq.com/openai/v1",
        "defaultModel": "llama-3.1-8b-instant",
    },
    "mistral": {
        "displayName": "Mistral",
        "keyEnv": ["MISTRAL_API_KEY"],
        "baseUrl": "https://api.mistral.ai/v1",
        "defaultModel": "mistral-small-latest",
    },
    "deepseek": {
        "displayName": "DeepSeek",
        "keyEnv": ["DEEPSEEK_API_KEY"],
        "baseUrl": "https://api.deepseek.com/v1",
        "defaultModel": "deepseek-chat",
    },
    "xai": {
        "displayName": "xAI",
        "keyEnv": ["XAI_API_KEY"],
        "baseUrl": "https://api.x.ai/v1",
        "defaultModel": "grok-2-latest",
    },
    "zai": {
        "displayName": "Z.ai / GLM",
        "keyEnv": ["ZAI_API_KEY"],
        "baseUrl": "https://api.z.ai/api/paas/v4",
        "defaultModel": "glm-4.5",
    },
    "ollama": {
        "displayName": "Ollama",
        "keyEnv": [],
        "baseUrl": "http://127.0.0.1:11434/v1",
        "defaultModel": "llama3.1",
        "requiresApiKey": False,
    },
    "custom": {
        "displayName": "Custom OpenAI-compatible",
        "keyEnv": ["NEXAFEED_LLM_API_KEY"],
        "baseUrl": "",
        "defaultModel": "",
    },
}


def clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def parse_env_file(path: Path) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        output[key] = clean_env_value(value)
    return output


def split_env_paths(raw: str | None) -> list[Path]:
    if not raw:
        return []
    separator = os.pathsep if os.pathsep in raw else ","
    return [Path(part).expanduser() for part in raw.split(separator) if part.strip()]


def hermes_env_path() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / ".env"


def candidate_env_files(
    explicit_env_file: str | os.PathLike[str] | None = None,
    *,
    include_project: bool = True,
    include_hermes: bool = True,
) -> list[Path]:
    paths: list[Path] = []
    if explicit_env_file:
        paths.append(Path(explicit_env_file).expanduser())
    paths.extend(split_env_paths(os.getenv("NEXAFEED_ENV_FILE")))
    if include_project:
        paths.extend([ROOT / ".env.local", ROOT / ".env"])
    if include_hermes and env_flag("NEXAFEED_DISABLE_HERMES_ENV", default=False) is False:
        paths.append(hermes_env_path())

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def load_env_files(
    explicit_env_file: str | os.PathLike[str] | None = None,
    *,
    include_project: bool = True,
    include_hermes: bool = True,
) -> list[str]:
    """Load supported .env files without overriding already-set env vars.

    Precedence is: process environment, explicit env file / NEXAFEED_ENV_FILE,
    project .env.local, project .env, then Hermes ~/.hermes/.env when present.
    """
    loaded: list[str] = []
    for path in candidate_env_files(
        explicit_env_file,
        include_project=include_project,
        include_hermes=include_hermes,
    ):
        if not path.is_file():
            continue
        values = parse_env_file(path)
        for key, value in values.items():
            os.environ.setdefault(key, value)
        loaded.append(str(path))
    return loaded


def env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(str(os.getenv(name, "")).strip())
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def normalize_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    provider = LLM_PROVIDER_ALIASES.get(provider, provider)
    return provider if provider in LLM_PROVIDERS else "custom"


def detect_provider_from_env() -> str:
    if os.getenv("NEXAFEED_LLM_API_KEY") and os.getenv("NEXAFEED_LLM_BASE_URL"):
        return "custom"
    for provider, meta in LLM_PROVIDERS.items():
        if provider in {"none", "custom"}:
            continue
        if any(os.getenv(name) for name in meta.get("keyEnv", [])):
            return provider
    if os.getenv("OLLAMA_HOST"):
        return "ollama"
    return "none"


def first_configured_key(provider: str) -> tuple[str, bool]:
    names = ["NEXAFEED_LLM_API_KEY"]
    names.extend(LLM_PROVIDERS.get(provider, {}).get("keyEnv", []))
    for name in names:
        if os.getenv(name):
            return name, True
    return (LLM_PROVIDERS.get(provider, {}).get("keyEnv") or ["NEXAFEED_LLM_API_KEY"])[0], False


def resolve_llm_config(*, required: bool = False) -> dict[str, Any]:
    requested = os.getenv("NEXAFEED_LLM_PROVIDER")
    provider = normalize_provider(requested) if requested is not None else detect_provider_from_env()
    meta = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["custom"])
    key_name, key_configured = first_configured_key(provider)
    base_url = (
        os.getenv("NEXAFEED_LLM_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or meta.get("baseUrl")
        or ""
    ).strip()
    model = (
        os.getenv("NEXAFEED_LLM_MODEL")
        or os.getenv(f"{provider.upper()}_MODEL")
        or meta.get("defaultModel")
        or ""
    ).strip()
    requires_key = bool(meta.get("requiresApiKey", True)) and provider != "none"
    missing: list[str] = []
    if required and provider == "none":
        missing.append("NEXAFEED_LLM_PROVIDER")
    if required and requires_key and not key_configured:
        missing.append(key_name)
    if required and provider == "custom" and not base_url:
        missing.append("NEXAFEED_LLM_BASE_URL")
    return {
        "enabled": provider != "none",
        "provider": provider,
        "displayName": str(meta.get("displayName") or provider),
        "model": model,
        "baseUrl": base_url,
        "apiKeyName": key_name,
        "apiKeyConfigured": bool(key_configured),
        "requiresApiKey": requires_key,
        "missing": missing,
        "ready": not missing and (provider == "none" or not requires_key or key_configured),
    }


def redacted_env(keys: list[str]) -> dict[str, Any]:
    return {key: {"configured": bool(os.getenv(key))} for key in keys}
