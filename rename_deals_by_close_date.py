#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import argparse
import datetime as dt

import requests


BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip() or "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"
DEFAULT_SLEEP = 0.2


def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def bx_call(method: str, params: dict) -> dict:
    if not BITRIX_WEBHOOK_BASE:
        die("Нет BITRIX_WEBHOOK_BASE (env).")

    url = BITRIX_WEBHOOK_BASE.rstrip("/") + f"/{method}.json"
    r = requests.post(url, json=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} при вызове {method}: {r.text[:300]}")
    data = r.json()
    if "error" in data and data["error"]:
        raise RuntimeError(f"Bitrix error {method}: {data.get('error')} {data.get('error_description')}")
    return data


def bx_list_all(method: str, params: dict, result_key: str = "result"):
    out = []
    start = 0
    while True:
        p = dict(params or {})
        p["start"] = start
        data = bx_call(method, p)
        chunk = data.get(result_key, [])
        if chunk:
            out.extend(chunk)
        nxt = data.get("next")
        if nxt is None:
            break
        start = nxt
        time.sleep(0.1)
    return out


def load_companies_map() -> dict:
    companies = bx_list_all(
        "crm.company.list",
        {
            "select": ["ID", "TITLE"],
            "order": {"ID": "ASC"},
            "filter": {}
        }
    )
    mp = {}
    for c in companies:
        cid = str(c.get("ID") or "").strip()
        title = (c.get("TITLE") or "").strip()
        if cid and title:
            mp[cid] = title
    return mp


def parse_bx_datetime(s: str):
    if not s:
        return None
    s = str(s).strip()
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        try:
            d = dt.date.fromisoformat(s[:10])
            return dt.datetime(d.year, d.month, d.day)
        except Exception:
            return None


def list_deals_for_company(company_id: str, only_won: bool):
    flt = {"=COMPANY_ID": company_id}
    if only_won:
        flt["=STAGE_ID"] = "WON"

    return bx_list_all(
        "crm.deal.list",
        {
            "select": ["ID", "TITLE", "CLOSEDATE", "COMPANY_ID", "STAGE_ID"],
            "order": {"ID": "ASC"},
            "filter": flt
        }
    )


def update_deal_title(deal_id: str, new_title: str):
    bx_call("crm.deal.update", {"id": deal_id, "fields": {"TITLE": new_title}})


def compute_plan(company_title: str, deals: list):
    """
    Возвращает список кортежей:
      (deal_id, close_dt, old_title, final_title)
    Отсортировано по close_dt asc, затем ID asc.
    """
    def sort_key(d):
        close_dt = parse_bx_datetime(d.get("CLOSEDATE"))
        return (
            close_dt is None,                         # None -> в конец
            close_dt or dt.datetime.max,
            int(d["ID"]) if str(d.get("ID", "")).isdigit() else 10**18
        )

    deals_sorted = sorted(deals, key=sort_key)
    plan = []
    for i, d in enumerate(deals_sorted, start=1):
        deal_id = str(d.get("ID"))
        old_title = (d.get("TITLE") or "").strip()
        final_title = f"{company_title} №{i}"
        plan.append((deal_id, d.get("CLOSEDATE"), old_title, final_title))
    return plan


def main():
    parser = argparse.ArgumentParser(
        description="Переименование сделок: 'Название компании №N', где N — по возрастанию CLOSEDATE внутри компании. Делает rename в 2 прохода (через TMP), чтобы не было конфликтов."
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--dry-run", action="store_true", help="Только показать изменения (по умолчанию)")
    mode.add_argument("--commit", action="store_true", help="Применить изменения в Bitrix")

    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="Пауза между запросами (сек)")
    parser.add_argument("--only-won", action="store_true", help="Обрабатывать только сделки со стадией WON")
    parser.add_argument("--company-id", help="Только одна компания (ID), для теста/частичного прогона")
    parser.add_argument("--limit-companies", type=int, default=0, help="Ограничить число компаний (0 = без ограничений)")

    args = parser.parse_args()
    dry_run = not args.commit

    companies_map = load_companies_map()
    if not companies_map:
        die("Не удалось загрузить компании из CRM.")

    company_ids = [args.company_id] if args.company_id else list(companies_map.keys())
    company_ids.sort(key=lambda x: int(x) if x.isdigit() else x)
    if args.limit_companies and args.limit_companies > 0:
        company_ids = company_ids[: args.limit_companies]

    total_deals_seen = 0
    total_to_change = 0
    total_changed = 0
    total_skipped = 0
    total_errors = 0

    print("Режим:", "DRY_RUN" if dry_run else "COMMIT")
    print("Фильтр:", "только WON" if args.only_won else "все стадии")
    if args.company_id:
        print("Компания:", args.company_id, "-", companies_map.get(args.company_id, "<не найдена>"))
    print("----")

    for cid in company_ids:
        company_title = companies_map.get(cid)
        if not company_title:
            continue

        deals = list_deals_for_company(cid, only_won=args.only_won)
        if not deals:
            continue

        total_deals_seen += len(deals)

        plan = compute_plan(company_title, deals)

        # что реально меняем
        changes = [(deal_id, close_raw, old, new) for (deal_id, close_raw, old, new) in plan if old != new]
        if not changes:
            total_skipped += len(deals)
            continue

        total_to_change += len(changes)

        # Вывод плана (как у тебя сейчас)
        for deal_id, close_raw, old, new in changes:
            print(json.dumps({
                "COMPANY_ID": cid,
                "COMPANY_TITLE": company_title,
                "DEAL_ID": deal_id,
                "CLOSEDATE": close_raw,
                "OLD_TITLE": old,
                "NEW_TITLE": new
            }, ensure_ascii=False))

        if dry_run:
            continue

        # ---------- COMMIT: 2-pass rename ----------
        # PASS 1: temporary titles
        try:
            for deal_id, _, old, _ in changes:
                tmp_title = f"TMP#{deal_id}"
                update_deal_title(deal_id, tmp_title)
                time.sleep(args.sleep)
        except Exception as e:
            total_errors += 1
            print(f"[ERROR] company={cid} PASS1: {e}")
            continue

        # PASS 2: final titles
        try:
            for deal_id, _, _, new in changes:
                update_deal_title(deal_id, new)
                total_changed += 1
                print(f"[OK] deal={deal_id} -> '{new}'")
                time.sleep(args.sleep)
        except Exception as e:
            total_errors += 1
            print(f"[ERROR] company={cid} PASS2: {e}")
            # не прерываем весь скрипт, идём дальше
            continue

    print("\n=== Итоги ===")
    print("Компаний обработано:", len(company_ids))
    print("Сделок просмотрено:", total_deals_seen)
    print("Нужно переименовать:", total_to_change)
    print("Переименовано:", total_changed)
    print("Пропущено (без изменений):", total_skipped)
    print("Ошибок:", total_errors)


if __name__ == "__main__":
    main()
