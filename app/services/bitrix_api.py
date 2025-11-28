import os
import requests

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")

def bitrix_call(method, params=None):
    url = f"{BITRIX_WEBHOOK}/{method}"
    response = requests.post(url, json=params or {})
    data = response.json()

    if "error" in data:
        raise Exception(f"Bitrix error: {data['error_description']}")

    return data.get("result")


def bitrix_call_paginated(method, params=None):
    
    params = params or {}
    params["start"] = 0

    all_items = []

    while True:
        chunk = bitrix_call(method, params)
        items = chunk.get("items", chunk)  # Bitrix иногда возвращает {items: []}
        all_items.extend(items)

        next_start = chunk.get("next")
        if next_start is None:
            break

        params["start"] = next_start

    return all_items
