import os
import sys
import time
import logging
from datetime import datetime
import calendar

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.bitrix_api import bitrix_call, bitrix_call_paginated

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

QUOTE_DATE_FIELD = "ufCrm_QUOTE_1773390831247"

def get_russian_month(month_num):
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря"
    }
    return months.get(month_num, "")

def add_months(source_date, months):
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return source_date.replace(year=year, month=month, day=day)

def format_date_russian(date_obj):
    return f"{date_obj.day} {get_russian_month(date_obj.month)} {date_obj.year}"

def get_all_quote_ids():
    quote_ids = []
    start = 0

    logger.info("Начинаю получение списка предложений")

    while True:
        try:
            logger.info("Запрос crm.item.list: entityTypeId=7, start=%s", start)

            result = bitrix_call("crm.item.list", {
                "entityTypeId": 7,
                "select": ["id"],
                "start": start
            })

            logger.info("Ответ crm.item.list type=%s", type(result).__name__)

            items = []
            if isinstance(result, list):
                items = result
            elif isinstance(result, dict):
                items = result.get("items", [])

            logger.info("Получено элементов на странице: %s", len(items))

            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    quote_ids.append(item["id"])
                elif isinstance(item, (int, str)):
                    quote_ids.append(str(item))

            logger.info("Всего собрано ID на текущий момент: %s", len(quote_ids))

            if len(items) < 50:
                logger.info("Последняя страница списка предложений достигнута")
                break

            start += 50

        except Exception as e:
            logger.exception("Ошибка при получении списка предложений")
            break

    logger.info("Итоговое количество предложений: %s", len(quote_ids))
    return quote_ids

def process_quote(quote_id):
    try:
        today = datetime.now().date()
        future_date = add_months(today, 3)
        formatted_date = format_date_russian(future_date)

        logger.info("Обработка предложения id=%s, дата для записи=%s", quote_id, formatted_date)

        quote = bitrix_call("crm.item.get", {"entityTypeId": 7, "id": quote_id})

        if not quote:
            logger.warning("Предложение id=%s не найдено или вернулся пустой ответ", quote_id)
            return False

        logger.info("Ответ crm.item.get для id=%s type=%s", quote_id, type(quote).__name__)

        item = None
        if isinstance(quote, dict):
            if "item" in quote:
                item = quote["item"]
            else:
                item = quote

        if not item:
            logger.warning("Не удалось извлечь item из ответа для предложения id=%s. Ответ=%s", quote_id, str(quote)[:1000])
            return False

        current_value = item.get(QUOTE_DATE_FIELD)
        logger.info("Текущее значение поля %s у предложения %s: %s", QUOTE_DATE_FIELD, quote_id, current_value)

        if current_value == formatted_date:
            logger.info("Предложение id=%s уже содержит актуальную дату, пропускаю", quote_id)
            return False

        update_payload = {
            "entityTypeId": 7,
            "id": quote_id,
            "fields": {QUOTE_DATE_FIELD: formatted_date}
        }

        logger.info("Отправляю crm.item.update для предложения id=%s: %s", quote_id, update_payload)

        update_result = bitrix_call("crm.item.update", update_payload)

        logger.info("Ответ crm.item.update для предложения id=%s: %s", quote_id, str(update_result)[:1000])

        verify_result = bitrix_call("crm.item.get", {"entityTypeId": 7, "id": quote_id})
        verify_item = None

        if isinstance(verify_result, dict):
            if "item" in verify_result:
                verify_item = verify_result["item"]
            else:
                verify_item = verify_result

        verified_value = verify_item.get(QUOTE_DATE_FIELD) if isinstance(verify_item, dict) else None

        logger.info(
            "Проверка после обновления для предложения id=%s: ожидалось=%s, фактически=%s",
            quote_id,
            formatted_date,
            verified_value
        )

        if verified_value != formatted_date:
            logger.warning(
                "Дата не сохранилась для предложения id=%s. Ожидалось=%s, фактически=%s",
                quote_id,
                formatted_date,
                verified_value
            )
            return False

        logger.info("Дата успешно обновлена для предложения id=%s", quote_id)
        return True

    except Exception as e:
        logger.exception("Ошибка обработки предложения %s", quote_id)
        return False

def run():
    try:
        logger.info("Старт обработчика дат предложений")

        quote_ids = get_all_quote_ids()

        if not quote_ids:
            logger.warning("Список предложений пуст")
            return

        updated_count = 0
        skipped_count = 0
        failed_count = 0

        for index, quote_id in enumerate(quote_ids, start=1):
            logger.info("Прогресс: %s/%s, предложение id=%s", index, len(quote_ids), quote_id)

            result = process_quote(quote_id)

            if result is True:
                updated_count += 1
            elif result is False:
                skipped_count += 1
            else:
                failed_count += 1

            time.sleep(0.2)

        logger.info(
            "Обработчик завершён. Всего=%s, обновлено=%s, пропущено/не обновлено=%s, ошибок=%s",
            len(quote_ids),
            updated_count,
            skipped_count,
            failed_count
        )

    except Exception as e:
        logger.exception("Критическая ошибка в run()")

if __name__ == "__main__":
    run()