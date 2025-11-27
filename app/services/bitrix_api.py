import requests
import os

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")

def bitrix_call(method: str, params: dict = None):
    url = f"{BITRIX_WEBHOOK}{method}"
    response = requests.post(url, json=params or {})
    response.raise_for_status()
    return response.json()