import os
import requests

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")


def bitrix_call_raw(method: str, params: dict | None = None) -> dict:
    
    if not BITRIX_WEBHOOK:
        raise RuntimeError("BITRIX_WEBHOOK_URL is not set in environment")

    url = f"{BITRIX_WEBHOOK}/{method}"
    resp = requests.post(url, json=params or {})
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise Exception(f"Bitrix error: {data.get('error_description') or data['error']}")

    return data


def bitrix_call(method: str, params: dict | None = None):
    
    data = bitrix_call_raw(method, params)
    return data.get("result")


def bitrix_call_paginated(method: str, params: dict | None = None):
    
    params = params.copy() if params else {}
    start = 0

    all_items: list[dict] = []

    while True:
        params["start"] = start
        data = bitrix_call_raw(method, params)

        
        items = data.get("result", []) or []
        all_items.extend(items)

        next_start = data.get("next")
        if next_start is None:
            break

        start = next_start

    return all_items
