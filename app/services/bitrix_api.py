import os
import requests

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")


def bitrix_call(method: str, params: dict | None = None):
    
    if not BITRIX_WEBHOOK:
        raise RuntimeError("BITRIX_WEBHOOK_URL is not set in environment")

    url = f"{BITRIX_WEBHOOK}/{method}"
    response = requests.post(url, json=params or {})
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        
        raise Exception(f"Bitrix error: {data.get('error_description') or data['error']}")

    return data.get("result")


def bitrix_call_paginated(method: str, params: dict | None = None):
    
    params = params.copy() if params else {}
    params["start"] = 0

    all_items: list[dict] = []

    while True:
        chunk = bitrix_call(method, params)

        if isinstance(chunk, dict):
            items = chunk.get("items", [])
            next_start = chunk.get("next")
        else:
            items = chunk
            next_start = None

        all_items.extend(items)

        if next_start is None:
            break

        params["start"] = next_start

    return all_items
