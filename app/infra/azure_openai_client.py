"""
app/infra/azure_openai_client.py
─────────────────────────────────
Singleton Azure-hosted OpenAI client (OpenAI-compatible v1 API).
Uses the standard `openai` package pointed at the Azure Foundry endpoint.
Import `get_openai` anywhere to get the shared instance.
"""
from functools import lru_cache
from openai import AzureOpenAI
from app.config import settings


@lru_cache(maxsize=1)
def get_openai() -> AzureOpenAI:
    """Returns the singleton OpenAI-compatible client for Azure, initialised once on first call."""
    # We must use AzureOpenAI instead of OpenAI so the client automatically handles
    # formatting the deployment name into the path (e.g. /openai/deployments/...).
    # Using base_url with the standard OpenAI client causes 404 DeploymentNotFound.
    return AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint="https://viswalpha-foundry-50bd.openai.azure.com/",
        api_version="2024-02-15-preview",
        timeout=30.0,
        max_retries=2,
    )
