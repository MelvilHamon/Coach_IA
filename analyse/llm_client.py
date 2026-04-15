"""
analyse/llm_client.py — Factory pour le client LLM (OpenAI / Groq).

Le provider est configurable via config.json :
  "llm": {
    "provider": "groq",          # "openai" (defaut) ou "groq"
    "model": "llama-3.3-70b-versatile",
    "temperature": 0.5
  }

Groq utilise le SDK OpenAI avec un base_url different.

La section "llm" de la config racine fait toujours autorite :
si la config utilisateur ne contient pas "provider", on le lit
depuis la config racine du projet.
"""

import json
import os

from openai import OpenAI

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_CONFIG = os.path.join(_ROOT, "config.json")

# Defaults par provider
_PROVIDERS = {
    "openai": {
        "base_url": None,  # SDK default
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "API_KEY_GROQ",
        "default_model": "llama-3.3-70b-versatile",
    },
}


def _root_llm_cfg() -> dict:
    """Charge la section "llm" de la config racine du projet."""
    if os.path.exists(_ROOT_CONFIG):
        with open(_ROOT_CONFIG, encoding="utf-8") as f:
            return json.load(f).get("llm", {})
    return {}


def get_llm_client(llm_cfg: dict) -> tuple[OpenAI, str]:
    """Retourne (client, model) selon la config LLM.

    La config racine fait autorité pour "provider" et "model" :
    si la config utilisateur ne les définit pas, on hérite de la racine.

    Parameters
    ----------
    llm_cfg : dict
        Section "llm" du config.json (utilisateur ou racine).

    Returns
    -------
    (OpenAI client, model name)
    """
    # Fusionner : config racine en base, config utilisateur par-dessus
    root = _root_llm_cfg()
    merged = {**root, **{k: v for k, v in llm_cfg.items() if v is not None}}
    provider = merged.get("provider", "openai").lower()
    if provider not in _PROVIDERS:
        raise ValueError(f"Provider LLM inconnu : {provider}. Choix : {list(_PROVIDERS)}")

    spec = _PROVIDERS[provider]
    api_key = os.getenv(spec["env_key"])
    if not api_key:
        raise ValueError(
            f"{spec['env_key']} non configurée. "
            f"Ajoute-la dans ton .env pour utiliser le provider '{provider}'."
        )

    kwargs = {"api_key": api_key}
    if spec["base_url"]:
        kwargs["base_url"] = spec["base_url"]

    client = OpenAI(**kwargs)
    model = merged.get("model", spec["default_model"])

    return client, model
