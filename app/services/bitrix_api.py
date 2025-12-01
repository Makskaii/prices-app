import os
import requests

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")

SESSION = requests.Session()  # быстрее при множественных запросах


def _request(method: str, url: str, params: dict | None = None, http_method: str = "POST"):
    

    if http_method.upper() == "GET":
        response = SESSION.get(url, params=params, timeout=20)
    else:
        response = SESSION.post(url, json=params or {}, timeout=20)

    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise Exception(f"Bitrix24 error: {data.get('error_description') or data['error']}")

    return data


def bitrix_call_raw(method: str, params: dict | None = None, http_method: str = "POST"):
    

    if not BITRIX_WEBHOOK:
        raise RuntimeError("ENV var BITRIX_WEBHOOK_URL is not set")

    url = f"{BITRIX_WEBHOOK}/{method}"

    
    return _request(method, url, params, http_method)


def bitrix_call(method: str, params: dict | None = None, http_method: str = "POST"):
    

    data = bitrix_call_raw(method, params, http_method)
    return data.get("result")


def bitrix_call_paginated(method: str, params: dict | None = None, http_method: str = "POST"):

    params = params.copy() if params else {}
    start = 0
    all_items = []

    while True:
        params["start"] = start

        response = bitrix_call_raw(method, params, http_method)

        items = response.get("result", []) or []
        all_items.extend(items)

        next_start = response.get("next")
        if next_start is None:
            break

        start = next_start

    return all_items
