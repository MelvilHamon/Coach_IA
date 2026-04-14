"""
analyse/llm_client.py — Factory pour le client LLM (OpenAI / Groq).

Le provider est configurable via config.json :
  "llm": {
    "provider": "groq",          # "openai" (defaut) ou "groq"
    "model": "llama-3.3-70b-versatile",
    "temperature": 0.5
  }

Groq utilise le SDK OpenAI avec un base_url different.
"""

import os

from openai import OpenAI

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


def get_llm_client(llm_cfg: dict) -> tuple[OpenAI, str]:
    """Retourne (client, model) selon la config LLM.

    Parameters
    ----------
    llm_cfg : dict
        Section "llm" du config.json. Clés attendues :
        - provider (str) : "openai" ou "groq" (defaut: "openai")
        - model (str) : override du modèle
        - temperature (float) : utilisé par l'appelant, pas ici

    Returns
    -------
    (OpenAI client, model name)
    """
    provider = llm_cfg.get("provider", "openai").lower()
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
    model = llm_cfg.get("model", spec["default_model"])

    return client, model
