# app/services/bitrix_disk_service.py
import os
import re
import urllib.parse
import requests
import base64

BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip() or "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"

# куда писать ссылку в сделке
UF_KP_LINK = "UF_CRM_1768908090840"  # UF_CRM_1768817716375

# папка в диске для КП
KP_FOLDER_ID = "316"

BITRIX_PORTAL_BASE = os.getenv("BITRIX_PORTAL_BASE", "").strip()
if not BITRIX_PORTAL_BASE:
    try:
        u = urllib.parse.urlparse(BITRIX_WEBHOOK_BASE)
        BITRIX_PORTAL_BASE = f"{u.scheme}://{u.netloc}"
    except Exception:
        BITRIX_PORTAL_BASE = ""


def _sanitize_filename(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"[\\/:\*\?\"<>\|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or "kp.docx"


def _bx_url(method: str) -> str:
    return BITRIX_WEBHOOK_BASE.rstrip("/") + f"/{method}.json"


def bx_call(method: str, params: dict) -> dict:
    url = BITRIX_WEBHOOK_BASE.rstrip("/") + f"/{method}.json"
    r = requests.post(url, json=params, timeout=90)

    txt = r.text
    try:
        data = r.json()
    except Exception:
        data = None

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {method}: {txt[:1500]}")

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Bitrix error {method}: {data.get('error')} {data.get('error_description')}")

    return data


def upload_docx_to_disk(folder_id: int | str, filename: str, content: bytes) -> int:
    """
    1) Получаем uploadUrl через disk.folder.uploadfile
    2) Грузим файл multipart'ом на uploadUrl
    3) Из ответа берём file_id
    """
    # 1) запрос uploadUrl
    resp = bx_call("disk.folder.uploadfile", {
        "id": int(folder_id),
        "data": {
            "NAME": filename,
            "generateUniqueName": 0
        }
    })

    result = resp.get("result") or resp  # на всякий случай
    upload_url = result.get("uploadUrl") or result.get("upload_url")
    field = result.get("field") or "file"

    if not upload_url:
        raise RuntimeError(f"disk.folder.uploadfile не вернул uploadUrl: {resp}")

    # 2) загрузка файла на uploadUrl (multipart/form-data)
    files = {
        field: (filename, content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }
    r2 = requests.post(upload_url, files=files, timeout=180)
    r2.raise_for_status()

    # Bitrix обычно возвращает JSON
    try:
        j2 = r2.json()
    except Exception:
        raise RuntimeError(f"Ответ uploadUrl не JSON: {r2.text[:500]}")

    # 3) вынимаем file_id из второго ответа
    # варианты структур, которые встречаются:
    # {"result":{"ID":"123"}} или {"result":{"id":123}} или {"result":[{"ID":"123"}]}
    res2 = j2.get("result", j2)

    file_id = None
    if isinstance(res2, dict):
        file_id = res2.get("ID") or res2.get("Id") or res2.get("id")
    elif isinstance(res2, list) and res2:
        first = res2[0]
        if isinstance(first, dict):
            file_id = first.get("ID") or first.get("Id") or first.get("id")

    if not file_id:
        raise RuntimeError(f"Не удалось получить file_id из ответа uploadUrl: {j2}")

    return int(file_id)


def disk_file_link(file_id: str) -> str:
    """
    Ссылка, которая открывает файл в диске (и для docx даёт редактировать).
    """
    return f"{BITRIX_PORTAL_BASE}/disk/file/{file_id}/"


def set_deal_kp_link(deal_id: int, link: str) -> None:
    bx_call("crm.deal.update", {"id": int(deal_id), "fields": {UF_KP_LINK: link}})


def save_kp_and_write_link(deal_id: int, filename: str, content: bytes) -> dict:
    KP_FOLDER_ID = 316
    UF_KP_LINK = "UF_CRM_1768908090840"  # UF_CRM_1768817716375

    file_id = upload_docx_to_disk(KP_FOLDER_ID, filename, content)

    # строим ссылку на файл (обычно так открывается в Bitrix Disk)
    # https://bitrix....../disk/file/123/
    u = urllib.parse.urlparse(BITRIX_WEBHOOK_BASE)
    portal_base = f"{u.scheme}://{u.netloc}"
    file_url = get_disk_file_detail_url(file_id)

    # пишем ссылку в сделку
    bx_call("crm.deal.update", {
        "id": int(deal_id),
        "fields": {
            UF_KP_LINK: file_url
        }
    })

    return {"file_id": file_id, "file_url": file_url}

def get_portal_base() -> str:
    u = urllib.parse.urlparse(BITRIX_WEBHOOK_BASE)
    return f"{u.scheme}://{u.netloc}"

def get_disk_file_detail_url(file_id: int) -> str:
    """
    Пытаемся получить DETAIL_URL вида /docs/shared/... или /company/personal/user/.../disk/...
    и склеиваем с доменом.
    """
    portal = get_portal_base()

    info = bx_call("disk.file.get", {"id": int(file_id)})
    r = info.get("result") or {}

    # Bitrix часто отдаёт DETAIL_URL (это то, что открывается в интерфейсе)
    detail = r.get("DETAIL_URL") or r.get("detailUrl") or r.get("DETAIL_URL_RAW")

    if detail:
        # приводим к абсолютному
        if not (detail.startswith("http://") or detail.startswith("https://")):
            detail = portal + detail

        # режем query/fragment чтобы ссылка не превышала лимит поля
        u = urllib.parse.urlsplit(detail)
        detail = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))

        return detail


    # fallback (если вдруг DETAIL_URL нет)
    return f"{portal}/disk/file/{int(file_id)}/"

def upload_docx_to_deal_file_field(deal_id: int, field_code: str, filename: str, content: bytes) -> dict:
    """
    Загружает файл напрямую в поле сделки типа "Файл".
    field_code: например "UF_CRM_1768830570994"
    """
    b64 = base64.b64encode(content).decode("utf-8")

    # ВАЖНО: используем тот же bx_call, который уже есть в этом файле
    return bx_call("crm.deal.update", {
        "id": int(deal_id),
        "fields": {
            field_code: {
                "fileData": [filename, b64]
            }
        }
    })