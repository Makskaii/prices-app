#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import time
import math
import argparse
import datetime as dt
from difflib import SequenceMatcher
from collections import defaultdict

import requests
import pandas as pd


# =========================
# Настройки
# =========================
BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip() or "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"
UF_CONTRACT = "UF_CRM_1766138026024"   # поле "Договор" в сделке

DEFAULT_CURRENCY = "RUB"
DEFAULT_CATEGORY_ID = 0

# В твоей воронке по curl статусы: NEW..WON..LOSE, category=0, stage_id="WON"
FINAL_STAGE_ID = "WON"

# Bitrix надёжнее принимает datetime ISO, чем просто YYYY-MM-DD (в некоторых порталах)
UTC_MIDNIGHT_SUFFIX = "T00:00:00+00:00"

# Минимальный порог сходства для поиска компании (уменьшен для лучшего поиска)
SIMILARITY_THRESHOLD = 0.7  # было 0.92


# =========================
# Вспомогательное
# =========================
def die(msg, code=1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def is_nan_like(v):
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    s = str(v).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}


def normalize_company_name(name):
    """Упрощенная нормализация - находит ГАЗПРОМ НЕДРА"""
    if not name:
        return ""
    
    s = str(name).strip()
    
    # Простая нормализация
    s = s.replace("«", "").replace("»", "").replace('"', '').replace("'", "")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.upper()
    
    # Убираем только ООО/АО в начале, но сохраняем если есть пробелы или кавычки
    if s.startswith("ООО "):
        s = s[4:].strip()
    elif s.startswith("АО "):
        s = s[3:].strip()
    elif s.startswith('ООО"') or s.startswith('АО"'):
        s = s[3:].strip()
    
    return s


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _date_to_iso_pair(d: dt.date):
    date_iso = d.isoformat()
    return date_iso, date_iso + UTC_MIDNIGHT_SUFFIX


def parse_close_date(value):
    """
    Дату берём ТОЛЬКО из колонки "Дата" (никаких парсингов из договора).

    Поддерживает:
      - pandas.Timestamp / datetime / date
      - Excel serial number (число)
      - строка 'dd.mm.yyyy' / 'dd.mm.yy'
      - строка 'm/d/yy' / 'm/d/yyyy' (как в твоих логах: 11/11/13, 8/6/15, 10/18/22)
      - ISO 'YYYY-MM-DD' (+ с временем)
    Возвращает:
      (date_iso='YYYY-MM-DD', datetime_iso='YYYY-MM-DDT00:00:00+00:00')
    """
    if is_nan_like(value):
        return None, None

    # pandas Timestamp -> datetime
    try:
        if hasattr(value, "to_pydatetime"):
            vdt = value.to_pydatetime()
            if isinstance(vdt, dt.datetime):
                return _date_to_iso_pair(vdt.date())
    except Exception:
        pass

    # python datetime/date
    if isinstance(value, dt.datetime):
        return _date_to_iso_pair(value.date())
    if isinstance(value, dt.date):
        return _date_to_iso_pair(value)

    # Excel serial number
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v > 20000:  # защита от мусора
            try:
                base = dt.datetime(1899, 12, 30)  # как у pandas
                d = (base + dt.timedelta(days=v)).date()
                return _date_to_iso_pair(d)
            except Exception:
                pass

    s = str(value).strip()

    # иногда встречалось "0.01.2012" -> "01.01.2012"
    if s.startswith("0."):
        s = "01." + s.split(".", 1)[1]

    # 1) dd.mm.yyyy
    try:
        d = dt.datetime.strptime(s, "%d.%m.%Y").date()
        return _date_to_iso_pair(d)
    except Exception:
        pass

    # 2) dd.mm.yy
    try:
        d = dt.datetime.strptime(s, "%d.%m.%y").date()
        return _date_to_iso_pair(d)
    except Exception:
        pass

    # 3) m/d/yyyy or m/d/yy (US формат из твоих логах)
    #    допускаем также mm/dd/yy
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*", s)
    if m:
        mm = int(m.group(1))
        dd = int(m.group(2))
        yy = m.group(3)
        if len(yy) == 2:
            y = int(yy)
            # разумное правило для 2-значного года: 00-69 => 2000-2069, 70-99 => 1970-1999
            year = 2000 + y if y <= 69 else 1900 + y
        else:
            year = int(yy)
        try:
            d = dt.date(year, mm, dd)
            return _date_to_iso_pair(d)
        except Exception:
            return None, None

    # 4) ISO / ISO-like (YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, YYYY-MM-DDTHH:MM:SS)
    try:
        s2 = s.replace("T", " ")
        if " " in s2:
            s2 = s2.split(" ", 1)[0]
        d = dt.date.fromisoformat(s2)
        return _date_to_iso_pair(d)
    except Exception:
        pass

    return None, None


def to_float_money(v):
    """
    Поддержка форматов:
      - 378480 / 378480.0
      - '378 480' / '378 480,50'
      - '340,000.00'
      - '90,000.00  '
      - NaN/пусто -> 0.0
    """
    if is_nan_like(v):
        return 0.0

    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)

    s = str(v).strip()
    if not s:
        return 0.0

    s = s.replace("\u00A0", " ")
    s = s.replace("руб.", "").replace("руб", "").replace("RUB", "").replace("₽", "").strip()
    s = s.replace(" ", "")

    filtered = []
    for ch in s:
        if ch.isdigit() or ch in {",", ".", "-"}:
            filtered.append(ch)
    s = "".join(filtered)

    if not s or s in {"-", ".", ",", "-.", "-,"}:
        return 0.0

    if "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_dot > last_comma:
            s = s.replace(",", "")
        else:
            s = s.replace(".", "")
            s = s.replace(",", ".")
    else:
        if "," in s:
            parts = s.split(",")
            if len(parts) == 2 and len(parts[1]) in (1, 2, 3):
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")

    try:
        return float(s)
    except Exception:
        return 0.0


# =========================
# Bitrix REST
# =========================
def bx_call(method, params):
    if not BITRIX_WEBHOOK_BASE:
        die("Нет BITRIX_WEBHOOK_BASE в env. Пример: https://.../rest/ID/WEBHOOK/")

    url = BITRIX_WEBHOOK_BASE.rstrip("/") + f"/{method}.json"
    r = requests.post(url, json=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} при вызове {method}: {r.text[:300]}")
    data = r.json()
    if "error" in data and data["error"]:
        raise RuntimeError(f"Bitrix error {method}: {data.get('error')} {data.get('error_description')}")
    return data


def bx_list_all(method, params, result_key="result"):
    out = []
    start = 0
    while True:
        p = dict(params or {})
        p["start"] = start
        data = bx_call(method, p)
        chunk = data.get(result_key, [])
        if isinstance(chunk, dict) and "items" in chunk:
            chunk = chunk["items"]
        if chunk:
            out.extend(chunk)
        nxt = data.get("next")
        if nxt is None:
            break
        start = nxt
        time.sleep(0.2)
    return out


def load_companies_index():
    """Загружает все компании из Bitrix с нормализованными названиями"""
    companies = bx_list_all(
        "crm.company.list",
        {"select": ["ID", "TITLE"], "order": {"ID": "ASC"}, "filter": {}}
    )
    
    idx = {}
    original_names = {}  # Сохраняем оригинальные названия для отладки
    
    for c in companies:
        title = c.get("TITLE", "") or ""
        cid = c.get("ID")
        if not cid:
            continue
        
        # Сохраняем оригинальное название
        original_names[str(cid)] = title
        
        # Нормализуем название
        n = normalize_company_name(title)
        if n:
            if n not in idx:
                idx[n] = str(cid)
            else:
                # Если уже есть такая нормализация, объединяем ID
                # (на случай дубликатов в CRM)
                pass
    
    return idx, original_names


def find_company_id(company_name, companies_index, original_names, debug=False):
    """Поиск компании с улучшенной логикой - ИСПРАВЛЕН для ГАЗПРОМ НЕДРА"""
    n = normalize_company_name(company_name)
    if not n:
        return None

    # 1. Прямое совпадение по нормализованному имени
    if n in companies_index:
        if debug:
            print(f"  [FOUND DIRECT] {company_name} -> {companies_index[n]}")
        return companies_index[n]

    # 2. ДЛЯ ГАЗПРОМ НЕДРА: дополнительный поиск по части названия
    if "ГАЗПРОМ" in n:
        # Ищем компании, содержащие "ГАЗПРОМ"
        for norm_name, cid in companies_index.items():
            if "ГАЗПРОМ" in norm_name:
                if debug:
                    print(f"  [FOUND GAZPROM] {company_name} -> {cid} ({norm_name})")
                return cid
    
    # 3. Поиск по частичному совпадению в Bitrix API
    needle = (company_name or "").strip()
    if len(needle) > 100:
        needle = needle[:100]

    try:
        data = bx_call(
            "crm.company.list",
            {"select": ["ID", "TITLE"], "filter": {"%TITLE": needle}, "order": {"ID": "ASC"}}
        ).get("result", []) or []
    except Exception as e:
        if debug:
            print(f"  [SEARCH ERROR] {company_name}: {e}")
        data = []

    best_id = None
    best_score = 0.0
    best_match = ""

    # 4. Ищем лучшее совпадение среди результатов
    for c in data:
        title = c.get("TITLE", "") or ""
        cid = c.get("ID")
        if not cid:
            continue
        
        norm_title = normalize_company_name(title)
        score = similarity(n, norm_title)
        
        if score > best_score and score >= SIMILARITY_THRESHOLD:
            best_score = score
            best_id = str(cid)
            best_match = title

    # 5. Если нашли хорошее совпадение - сохраняем в индекс
    if best_id and best_score >= SIMILARITY_THRESHOLD:
        companies_index[n] = best_id
        if debug:
            print(f"  [FOUND SIMILAR] {company_name} -> {best_id} ({best_match}) score: {best_score:.2f}")
        return best_id

    # 6. Попробуем поиск по ключевым словам для сложных случаев
    keywords = [word for word in n.split() if len(word) > 3]
    
    for norm_name, cid in companies_index.items():
        matches = sum(1 for kw in keywords if kw in norm_name)
        if matches >= 2:
            score = similarity(n, norm_name)
            if score > best_score:
                best_score = score
                best_id = cid
    
    if best_id and best_score >= 0.5:
        if debug:
            orig_name = original_names.get(best_id, "unknown")
            print(f"  [FOUND BY KEYWORDS] {company_name} -> {best_id} ({orig_name}) score: {best_score:.2f}")
        return best_id

    if debug:
        print(f"  [NOT FOUND] {company_name} (normalized: {n})")
    
    return None


def create_company(company_name):
    """Создать компанию в Bitrix24"""
    fields = {
        "TITLE": company_name,
        "COMPANY_TYPE": "CUSTOMER",
        "IS_MY_COMPANY": "N"
    }
    
    data = bx_call("crm.company.add", {"fields": fields})
    company_id = str(data.get("result"))
    
    if company_id:
        print(f"[COMPANY CREATED] Создана компания: {company_name} (ID: {company_id})")
    
    return company_id


def deal_exists(company_id, contract, close_date_iso):
    flt = {"COMPANY_ID": company_id}
    if contract:
        flt[f"={UF_CONTRACT}"] = contract
    if close_date_iso:
        flt["=CLOSEDATE"] = close_date_iso

    data = bx_call(
        "crm.deal.list",
        {"select": ["ID"], "filter": flt, "order": {"ID": "ASC"}, "start": 0}
    ).get("result", []) or []
    return len(data) > 0


def create_deal(fields):
    data = bx_call("crm.deal.add", {"fields": fields})
    return str(data.get("result"))


def update_deal(deal_id, fields):
    bx_call("crm.deal.update", {"id": deal_id, "fields": fields})


# =========================
# XLSX
# =========================
def detect_header_row(xlsx_path, sheet_name="Клиенты", scan_rows=80):
    tmp = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None, nrows=scan_rows)
    keys = ["договор", "дата", "сумма"]
    for i in range(len(tmp)):
        row = tmp.iloc[i].astype(str).str.strip().str.lower()
        hits = 0
        for k in keys:
            if any(k in cell for cell in row.values):
                hits += 1
        if hits >= 2:
            return i
    return 0


def read_xlsx(xlsx_path):
    sheet = "Клиенты"
    header_row = detect_header_row(xlsx_path, sheet_name=sheet)
    df = pd.read_excel(xlsx_path, sheet_name=sheet, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def find_col(df, contains):
    contains = contains.lower()
    for c in df.columns:
        if contains in str(c).strip().lower():
            return c
    return None


def build_deals_from_xlsx(df):
    deals = []
    current_company = None
    per_company_counter = {}

    col_company = df.columns[0] if len(df.columns) else None
    if not col_company:
        die("Не удалось определить колонку компании (первая колонка пустая?)")

    col_contract = find_col(df, "договор")
    col_date = find_col(df, "дата")
    col_sum = find_col(df, "сумма")

    print("DEBUG columns:")
    print("  company =", col_company)
    print("  contract =", col_contract)
    print("  date =", col_date)
    print("  sum =", col_sum)

    if not col_contract or not col_date or not col_sum:
        die("Не нашёл одну из колонок: Договор/Дата/Сумма. Проверь заголовки.")

    debug_first = []
    skipped_bad_date = 0

    for _, row in df.iterrows():
        company_raw = row.get(col_company)

        if not is_nan_like(company_raw):
            current_company = str(company_raw).strip()
            if current_company not in per_company_counter:
                per_company_counter[current_company] = 0

        contract_raw = row.get(col_contract)
        date_raw = row.get(col_date)
        sum_raw = row.get(col_sum)

        has_any_deal_data = (
            not is_nan_like(contract_raw)
            or not is_nan_like(date_raw)
            or not is_nan_like(sum_raw)
        )
        if not has_any_deal_data:
            continue

        if is_nan_like(current_company):
            continue

        contract = None if is_nan_like(contract_raw) else str(contract_raw).strip()
        close_iso, close_dt = parse_close_date(date_raw)
        amount = to_float_money(sum_raw)

        if not close_iso:
            skipped_bad_date += 1
            continue

        per_company_counter[current_company] += 1
        seq = per_company_counter[current_company]

        deals.append({
            "company_name": current_company,
            "seq": seq,
            "contract": contract,
            "close_date_iso": close_iso,   # YYYY-MM-DD
            "close_date_dt": close_dt,     # YYYY-MM-DDT00:00:00+00:00
            "amount": amount,
            "currency": DEFAULT_CURRENCY,
            "raw_date": str(date_raw) if not is_nan_like(date_raw) else "",
            "raw_sum": str(sum_raw) if not is_nan_like(sum_raw) else ""
        })

        if len(debug_first) < 5:
            debug_first.append((current_company, date_raw, close_iso, sum_raw, amount))

    if debug_first:
        print("\nDEBUG первые 5 сделок (дата и сумма):")
        for cname, raw_date, iso, raw_sum, parsed_sum in debug_first:
            print(f"  {cname} | raw_date={raw_date!r} -> {iso} | raw_sum={raw_sum!r} -> {parsed_sum}")
        print()

    if skipped_bad_date:
        print(f"DEBUG: пропущено из-за нераспознанной даты: {skipped_bad_date}")

    return deals


# =========================
# Улучшенный вывод результатов
# =========================
def print_results_summary(deals_to_create, companies_not_found, dry_run=True):
    """Выводит понятную сводку результатов"""
    
    print("\n" + "="*80)
    print("ИТОГОВАЯ СВОДКА ИМПОРТА")
    print("="*80)
    
    # 1. Сделки, которые будут созданы (компании найдены)
    if deals_to_create:
        print(f"\n✅ БУДУТ СОЗДАНЫ СДЕЛКИ ДЛЯ {len(deals_to_create)} КОМПАНИЙ:")
        print("-" * 80)
        
        # Группируем сделки по компаниям
        companies_with_deals = defaultdict(list)
        for deal in deals_to_create:
            companies_with_deals[deal["company_name"]].append(deal)
        
        # Выводим статистику по компаниям
        for idx, (company_name, company_deals) in enumerate(sorted(companies_with_deals.items()), 1):
            total_amount = sum(d["amount"] for d in company_deals)
            deal_count = len(company_deals)
            print(f"{idx:3}. {company_name[:70]:70} | Сделок: {deal_count:3} | Сумма: {total_amount:12.2f} руб.")
        
        print(f"\nВсего сделок к созданию: {len(deals_to_create)}")
    
    # 2. Компании, которые не найдены
    if companies_not_found:
        print(f"\n⚠️  НЕ НАЙДЕНЫ В CRM ({len(companies_not_found)} компаний):")
        print("-" * 80)
        
        for idx, (company_name, company_deals) in enumerate(sorted(companies_not_found.items()), 1):
            total_amount = sum(d["amount"] for d in company_deals)
            deal_count = len(company_deals)
            print(f"{idx:3}. {company_name[:70]:70} | Сделок: {deal_count:3} | Сумма: {total_amount:12.2f} руб.")
        
        print(f"\nВсего сделок для отсутствующих компаний: {sum(len(d) for d in companies_not_found.values())}")
        
        # Инструкция
        print("\n" + "="*80)
        print("ЧТО ДЕЛАТЬ ДАЛЬШЕ:")
        print("1. Создайте указанные выше компании в Bitrix24")
        print("2. Запустите этот скрипт снова с флагом --commit")
        print("="*80)
    else:
        print("\n✅ ВСЕ КОМПАНИИ НАЙДЕНЫ В CRM!")
        
        if dry_run:
            print("\nДля создания сделок запустите скрипт с флагом --commit")
        else:
            print("\n✅ Все сделки успешно созданы!")


# =========================
# Main
# =========================
def main():
    parser = argparse.ArgumentParser(description="Импорт закрытых сделок (WON) в Bitrix24 из XLSX")
    parser.add_argument("--xlsx", required=True, help="Путь к XLSX файлу")

    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--dry-run", action="store_true", help="Только показать (по умолчанию)")
    mode.add_argument("--commit", action="store_true", help="Создавать сделки в Bitrix")

    parser.add_argument("--sleep", type=float, default=0.2, help="Пауза между запросами (сек)")
    parser.add_argument("--category-id", type=int, default=DEFAULT_CATEGORY_ID)
    parser.add_argument("--debug-search", action="store_true",
                       help="Включить отладку поиска компаний")

    args = parser.parse_args()
    dry_run = not args.commit

    if not os.path.exists(args.xlsx):
        die(f"Файл не найден: {args.xlsx}")

    df = read_xlsx(args.xlsx)
    deals = build_deals_from_xlsx(df)
    
    from collections import defaultdict

    print("\n=== НАЙДЕННЫЕ ДУБЛИ В ФАЙЛЕ ===")

    groups = defaultdict(list)

    for d in deals:
        key = (
            d["company_name"],
            (d.get("contract") or "").strip().lower(),
            d.get("close_date_iso"),
        )
        groups[key].append(d)

    dupes = {k: v for k, v in groups.items() if len(v) > 1}

    print(f"Количество групп-дублей: {len(dupes)}\n")

    for (company, contract, close_date), items in dupes.items():
        print(f"Компания: {company}")
        print(f"Договор: {contract}")
        print(f"Дата закрытия: {close_date}")
        print(f"Количество строк в файле: {len(items)}")
        print("Сделки:")
        for it in items:
            print(
                f"  №{it['seq']} | сумма={it['amount']} | дата={it['close_date_iso']}"
            )
        print("-" * 80)


    # Загружаем компании с оригинальными названиями
    companies_index, original_names = load_companies_index()
    
    if args.debug_search:
        print(f"\nЗагружено компаний из CRM: {len(companies_index)}")
        print("Примеры компаний в CRM:")
        for norm_name, cid in list(companies_index.items())[:10]:
            print(f"  {original_names.get(cid, 'unknown')} -> {norm_name}")

    created = 0
    skipped_dupe = 0
    errors = 0
    
    # Словари для хранения результатов
    deals_to_create = []           # Сделки, которые будут созданы (компании найдены)
    companies_not_found = defaultdict(list)  # Компании не найдены совсем
    companies_found_with_deals = set()       # Компании, которые найдены и есть сделки
    
    print(f"\nРаспознано сделок из файла: {len(deals)}")
    print("Режим:", "DRY_RUN" if dry_run else "COMMIT")
    print("-" * 80)

    for d in deals:
        company_name = d["company_name"]
        
        if args.debug_search:
            print(f"\nПоиск компании: {company_name}")
        
        company_id = find_company_id(company_name, companies_index, original_names, args.debug_search)

        # Если компания не найдена
        if not company_id:
            companies_not_found[company_name].append(d)
            continue
        
        # Компания найдена
        companies_found_with_deals.add(company_name)
        
        seq = d["seq"]  # номер строго по файлу внутри компании
        title = f"{company_name} №{seq}"

        contract_key = d.get("contract") or ""
        close_iso = d.get("close_date_iso") or ""
        close_dt = d.get("close_date_dt") or ""

        if deal_exists(company_id, contract_key, close_iso):
            skipped_dupe += 1
            continue

        # Добавляем сделку в список для создания
        deal_info = {
            "company_name": company_name,
            "company_id": company_id,
            "title": title,
            "contract": contract_key,
            "close_iso": close_iso,
            "close_dt": close_dt,
            "amount": d["amount"],
            "currency": d["currency"],
            "seq": seq
        }
        
        deals_to_create.append(deal_info)

    # Создаем сделки (если не dry-run)
    if not dry_run and deals_to_create:
        print(f"\nСоздание {len(deals_to_create)} сделок...")
        print("-" * 80)
        
        for deal_info in deals_to_create:
            try:
                fields_add = {
                    "TITLE": deal_info["title"],
                    "COMPANY_ID": deal_info["company_id"],
                    "CATEGORY_ID": int(args.category_id),
                    "STAGE_ID": FINAL_STAGE_ID,
                    "CLOSED": "Y",
                    "CURRENCY_ID": deal_info["currency"],
                    "OPPORTUNITY": float(deal_info["amount"]),
                    "CLOSEDATE": deal_info["close_dt"],
                }

                if deal_info["contract"]:
                    fields_add[UF_CONTRACT] = deal_info["contract"]

                deal_id = create_deal(fields_add)

                # Фиксируем дату закрытия update'ом
                update_deal(deal_id, {
                    "STAGE_ID": FINAL_STAGE_ID,
                    "CLOSED": "Y",
                    "CLOSEDATE": deal_info["close_dt"],
                })

                print(f"[OK] Создана сделка ID={deal_id}: {deal_info['title']}")
                created += 1

                time.sleep(args.sleep)

            except Exception as e:
                errors += 1
                print(f"[ERROR] {deal_info['company_name']}: {e}")
    
    # Выводим итоговую статистику
    print("\n" + "="*80)
    print("СТАТИСТИКА ПРОЦЕССА:")
    print("="*80)
    print(f"Всего сделок в файле: {len(deals)}")
    print(f"Найдено компаний в CRM: {len(companies_found_with_deals)}")
    print(f"Сделок к созданию: {len(deals_to_create)}")
    print(f"Пропущено (дубликаты): {skipped_dupe}")
    print(f"Компаний не найдено: {len(companies_not_found)}")
    print(f"Ошибок: {errors}")
    
    if not dry_run:
        print(f"\nСоздано сделок в этом запуске: {created}")
    
    # Выводим подробную сводку
    print_results_summary(deals_to_create, companies_not_found, dry_run)


if __name__ == "__main__":
    main()