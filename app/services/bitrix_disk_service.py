# app/services/bitrix_disk_service.py
import os
import re
import urllib.parse
import requests
import base64

BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip() or "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"

# папка в диске для КП
KP_FOLDER_ID = 316

# куда писать ссылку в сделке
UF_KP_LINK_DEAL = "UF_CRM_1768908090840"

# QUOTE поля (ты дал)
UF_KP_FILE_QUOTE = "ufCrm_697C815A39C78"
UF_KP_LINK_QUOTE = "ufCrm_697C815A3D688"

BITRIX_PORTAL_BASE = os.getenv("BITRIX_PORTAL_BASE", "").strip()
if not BITRIX_PORTAL_BASE:
    try:
        u = urllib.parse.urlparse(BITRIX_WEBHOOK_BASE)
        BITRIX_PORTAL_BASE = f"{u.scheme}://{u.netloc}"
    except Exception:
        BITRIX_PORTAL_BASE = ""


def _sanitize_filename(name: str) -> str:
    s = (name or "").strip()
    # запретные символы для Win/Bitrix
    s = re.sub(r"[\\/:\*\?\"<>\|]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or "kp.docx"


def bx_call(method: str, params: dict) -> dict:
    """
    Универсальный POST вызов к webhook REST.
    """
    url = BITRIX_WEBHOOK_BASE.rstrip("/") + f"/{method}.json"
    r = requests.post(url, json=params, timeout=90)

    txt = r.text
    try:
        data = r.json()
    except Exception:
        data = None

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {method}: {txt[:1500]}")

    # ✅ ВАЖНО: Bitrix иногда возвращает error="" но error_description заполнен
    if isinstance(data, dict):
        err = data.get("error", None)
        err_desc = data.get("error_description", None)

        # считаем ошибкой:
        # - error не пустой
        # - или есть error_description (даже если error="")
        if (err is not None and str(err).strip() != "") or (err_desc is not None and str(err_desc).strip() != ""):
            raise RuntimeError(f"Bitrix error {method}: {err} {err_desc}")

    return data



def upload_docx_to_disk(folder_id: int | str, filename: str, content: bytes) -> int:
    """
    1) Получаем uploadUrl через disk.folder.uploadfile
    2) Грузим файл multipart'ом на uploadUrl
    3) Из ответа берём file_id
    """
    filename = _sanitize_filename(filename)

    # ✅ generateUniqueName лучше передавать отдельным параметром
    resp = bx_call("disk.folder.uploadfile", {
        "id": int(folder_id),
        "data": {"NAME": filename},
        "generateUniqueName": 0
    })

    result = resp.get("result") or resp
    upload_url = result.get("uploadUrl") or result.get("upload_url")
    field = result.get("field") or "file"

    if not upload_url:
        raise RuntimeError(f"disk.folder.uploadfile не вернул uploadUrl: {resp}")

    files = {
        field: (filename, content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }
    r2 = requests.post(upload_url, files=files, timeout=180)
    r2.raise_for_status()

    try:
        j2 = r2.json()
    except Exception:
        raise RuntimeError(f"Ответ uploadUrl не JSON: {r2.text[:500]}")

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


def find_files_in_folder_by_name(folder_id: int, filename: str) -> list[int]:
    """
    Ищет все файлы с точным именем filename в папке folder_id.
    """
    filename = (filename or "").strip()
    if not filename:
        return []

    out: list[int] = []
    start = 0

    while True:
        resp = bx_call("disk.folder.getchildren", {"id": int(folder_id), "start": start})
        items = (resp.get("result") if isinstance(resp, dict) else None) or []
        if not items:
            break

        for it in items:
            if str(it.get("TYPE")).lower() != "file":
                continue
            name = it.get("NAME") or it.get("name")
            if name == filename:
                fid = it.get("ID") or it.get("id")
                if fid is not None:
                    try:
                        out.append(int(fid))
                    except Exception:
                        pass

        start += len(items)
        if len(items) < 50:
            # чаще всего порция 50; если меньше — конец
            break

    return out


def delete_disk_file(file_id: int) -> None:
    bx_call("disk.file.delete", {"id": int(file_id)})


def upload_docx_to_disk_replace(folder_id: int | str, filename: str, content: bytes) -> int:
    """
    Если файл с таким названием уже есть в папке — удаляем (все совпадения),
    затем загружаем новый и возвращаем новый file_id.
    """
    folder_id_int = int(folder_id)
    filename = _sanitize_filename(filename)

    old_ids = find_files_in_folder_by_name(folder_id_int, filename)
    for fid in old_ids:
        try:
            delete_disk_file(fid)
        except Exception:
            # не валим процесс из-за одного файла
            pass

    return upload_docx_to_disk(folder_id_int, filename, content)


def get_portal_base() -> str:
    u = urllib.parse.urlparse(BITRIX_WEBHOOK_BASE)
    return f"{u.scheme}://{u.netloc}"


def get_disk_file_detail_url(file_id: int) -> str:
    """
    Пытаемся получить DETAIL_URL (то, что открывается в интерфейсе).
    """
    portal = get_portal_base()
    info = bx_call("disk.file.get", {"id": int(file_id)})
    r = info.get("result") or {}

    detail = r.get("DETAIL_URL") or r.get("detailUrl") or r.get("DETAIL_URL_RAW")
    if detail:
        if not (detail.startswith("http://") or detail.startswith("https://")):
            detail = portal + detail

        # режем query/fragment
        u = urllib.parse.urlsplit(detail)
        detail = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
        return detail

    return f"{portal}/disk/file/{int(file_id)}/"


# =========================
# CRM updates
# =========================

def set_deal_kp_link(deal_id: int, link: str) -> None:
    bx_call("crm.deal.update", {"id": int(deal_id), "fields": {UF_KP_LINK_DEAL: link}})


def upload_docx_to_deal_file_field(deal_id: int, field_code: str, filename: str, content: bytes) -> dict:
    """
    Загружает файл напрямую в поле сделки типа "Файл".
    field_code: например "UF_CRM_1768830570994"
    """
    b64 = base64.b64encode(content).decode("utf-8")
    return bx_call("crm.deal.update", {
        "id": int(deal_id),
        "fields": {
            field_code: {
                "fileData": [filename, b64]
            }
        }
    })


def set_quote_kp_link(quote_id: int, link: str) -> None:
    """
    Пишем ссылку КП в предложение (crm.item.update, entityTypeId=7).
    """
    bx_call("crm.item.update", {
        "entityTypeId": 7,
        "id": int(quote_id),
        "fields": {
            UF_KP_LINK_QUOTE: link
        }
    })


def upload_docx_to_quote_file_field(quote_id: int, filename: str, content: bytes) -> dict:
    """
    Загружает файл в поле предложения типа "Файл" (crm.item.update, entityTypeId=7).

    В Bitrix у UF типа "Файл" есть 2 варианта:
    - одиночное поле: fields[UF] = {"fileData":[name, base64]}
    - множественное поле: fields[UF] = [{"fileData":[name, base64]}]

    Поэтому делаем попытку #1 и fallback #2.
    """
    filename = _sanitize_filename(filename)
    b64 = base64.b64encode(content).decode("utf-8")

    # Попытка 1: одиночное поле
    try:
        return bx_call("crm.item.update", {
            "entityTypeId": 7,
            "id": int(quote_id),
            "fields": {
                UF_KP_FILE_QUOTE: {
                    "fileData": [filename, b64]
                }
            }
        })
    except Exception as e1:
        # Попытка 2: множественное поле
        return bx_call("crm.item.update", {
            "entityTypeId": 7,
            "id": int(quote_id),
            "fields": {
                UF_KP_FILE_QUOTE: [
                    {"fileData": [filename, b64]}
                ]
            }
        })
