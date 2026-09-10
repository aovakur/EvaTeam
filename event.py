import time
import os
from datetime import datetime


def main():
    # === НАСТРОЙКИ ===
    REPORT_EMAILS = [
        'vakurinalarisa@yandex.ru'
        # 'manager@company.ru',
        # 'product@company.ru',
    ]

    MAX_TASKS_PER_EMAIL = 50
    TOP_N_RISK = 10
    PAUSE_BETWEEN_EMAILS_SEC = 1

    WRITE_TO_FILE = True
    EMAIL_LOGS_DIR = 'email_logs'
    ALERT_FRAGMENT_LEN = 600

    URL_SITE = 'https://eva.local/'
    # ===================

    now = g.now()
    today = now.date()
    cmf_alert('[START] Мониторинг запущен')

    # --- Вспомогательные функции ---

    def parse_to_date(val):
        if val is None:
            return None
        try:
            parts = str(val)[:10].split('-')
            if len(parts) != 3:
                return None
            return type(today)(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка парсинга даты: {e}')
            return None

    def get_task_code(task):
        for field in ('code', 'external_id', 'number', 'key'):
            try:
                val = getattr(task, field, None)
                if val:
                    return str(val)
            except Exception as e:
                cmf_alert(f'[ERROR] Ошибка получения поля {field}: {e}')
        return '?'

    def get_deadline_date(task):
        try:
            dl = getattr(task, 'deadline', None)
            if dl is not None:
                return parse_to_date(dl)
            gantt = getattr(task, 'op_gantt_task', None)
            if gantt:
                return parse_to_date(getattr(gantt, 'sched_finish_date', None))
            return None
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка получения дедлайна: {e}')
            return None

    def get_deadline_source(task):
        try:
            if getattr(task, 'deadline', None) is not None:
                return f'deadline = {task.deadline}'
            gantt = getattr(task, 'op_gantt_task', None)
            if gantt and getattr(gantt, 'sched_finish_date', None) is not None:
                return f'sched_finish_date = {gantt.sched_finish_date}'
            return 'не определён'
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка определения источника дедлайна: {e}')
            return 'ошибка определения'

    def get_responsible_email(task):
        try:
            responsible = getattr(task, 'responsible', None)
            if responsible:
                email = getattr(responsible, 'code', None)
                if email and '@' in str(email):
                    return str(email).strip()
            return None
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка получения email ответственного: {e}')
            return None

    def get_responsible_name(task):
        try:
            responsible = getattr(task, 'responsible', None)
            if responsible:
                name = getattr(responsible, 'name', None)
                return name if name else '?'
            return 'не назначен'
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка получения имени ответственного: {e}')
            return '?'

    def format_task_list(tasks, max_count=MAX_TASKS_PER_EMAIL):
        """HTML-список задач. Каждая строка — отдельный append с <br>."""
        if not tasks:
            return f'<p>Нет задач.</p>'

        lines = []
        for t in tasks[:max_count]:
            try:
                code = get_task_code(t)
                task_id = t.id
                status = getattr(t, 'status', None)
                status_code = getattr(status, 'code', '?') if status else '?'
                name = t.name
                source = get_deadline_source(t)
                task_url = get_task_url(t)
                lines.append(f'<b>- <a href="{task_url}">{name}</a> (Код: {code}, ID: {task_id})</b><br>')
                lines.append(f'&nbsp;&nbsp;Статус: {status_code}<br>')
                lines.append(f'&nbsp;&nbsp;Источник дедлайна: {source}<br>')

                finish = get_deadline_date(t)
                if finish:
                    days = (finish - today).days
                    if days < 0:
                        lines.append(f'&nbsp;&nbsp;<b>Просрочка: {-days} дн.</b><br>')
                    else:
                        lines.append(f'&nbsp;&nbsp;До дедлайна: {days} дн.<br>')
                else:
                    lines.append(f'&nbsp;&nbsp;Срок не установлен<br>')

                lines.append(f'<br>')
            except Exception as e:
                cmf_alert(f'[ERROR] Ошибка форматирования задачи: {e}')
                lines.append(f'<p><b>Ошибка отображения задачи</b></p><br>')

        total = len(tasks)
        if total > max_count:
            lines.append(
                f'<i>... и ещё {total - max_count} задач. '
                f'Полный список: <a href="[ссылка на фильтр в системе]">открыть фильтр</a></i><br>'
            )

        return ''.join(lines)

    def safe_filename_part(s):
        s = str(s or '')
        for ch in ['/', '\\', ':', '?', '*', '"', '<', '>', '|']:
            s = s.replace(ch, '_')
        return s[:60]

    def get_task_url(task):
        try:
            task_id = task.code
            return f'{URL_SITE}desk/cards?obj==Task:{task_id}'
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка формирования URL задачи: {e}')
            return URL_SITE


    def write_email_log(prefix, email, subject, content):
        """Записывает контент письма в файл, если WRITE_TO_FILE=True"""
        if not WRITE_TO_FILE:
            return

        try:
            if email is None:
                cmf_alert('ПРЕДУПРЕЖДЕНИЕ: email=None, пропускаем запись лога')
                return

            email_str = str(email).strip()
            if '@' not in email_str:
                cmf_alert(f'ПРЕДУПРЕЖДЕНИЕ: некорректный email для лога: {email_str}')
                email_str = 'unknown'

            if not os.path.exists(EMAIL_LOGS_DIR):
                os.makedirs(EMAIL_LOGS_DIR, exist_ok=True)

            safe_email = safe_filename_part(email_str)
            timestamp = now.strftime('%Y%m%d_%H%M%S')
            filename = f'{EMAIL_LOGS_DIR}/{prefix}_{timestamp}_{safe_email}.html'

            header = (
                f'Дата: {now}\n'
                f'Получатель: {email_str}\n'
                f'Тема: {subject}\n'
                f'---\n\n'
            )

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(header)
                f.write(content)
            cmf_alert(f'Контент письма сохранён: {filename}')
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка записи файла лога: {e}')

    def send_email(to_email, subject, content):
        """
        Обёртка вокруг cmfutil.send_email с нормальной диагностикой.
        Возвращает True только если отправка реально успешна.
        """
        # 1. Валидация адреса ДО вызова
        if not to_email:
            cmf_alert(f'[ERROR] send_email: to_email пуст')
            return False

        to_email = str(to_email).strip()
        if '@' not in to_email or '.' not in to_email.split('@')[-1]:
            cmf_alert(f'[ERROR] send_email: некорректный email: {to_email!r}')
            return False

        # Небольшая пауза, если нужно (оставляем как у тебя)
        time.sleep(PAUSE_BETWEEN_EMAILS_SEC)

        try:
            # 2. Вызов корпоративной функции
            result = cmfutil.send_email(to=to_email, subject=subject, content=content)
            cmf_alert(f'[DEBUG] cmfutil.send_email вернул: {result!r} (тип: {type(result).__name__})')

            # 3. Чёткая логика успеха/неудачи
            # Если cmfutil возвращает None при успехе — ок. Если True — ок.
            # Но если это строка, dict, объект — лучше считать это подозрительным,
            # если у тебя нет точной спецификации.
            if result is False:
                cmf_alert(f'[WARN] cmfutil явно сообщил об ошибке отправки на {to_email}')
                return False
            if result is None or result is True:
                # Это те случаи, которые мы считаем успехом
                cmf_alert(f'ОТПРАВЛЕНО: {subject} → {to_email} (результат: {result!r})')
                return True

            # Любой другой тип результата — логируем как «неожиданный ответ»
            cmf_alert(
                f'[WARN] Неожиданный результат от cmfutil.send_email для {to_email}: {result!r} '
                f'(тип: {type(result).__name__}). Считаем отправкой НЕуспешной.'
            )
            return False

        except Exception as e:
            # 4. Полный стек ошибки — это самое важное для диагностики
            import traceback
            cmf_alert('[ERROR] Исключение при вызове cmfutil.send_email:')
            cmf_alert(traceback.format_exc())
            return False

    # --- Получение задач ---

    REQUIRED_FIELDS = [
        'name', 'code', 'external_id', 'number', 'key',
        'status.code', 'deadline', 'op_gantt_task.sched_finish_date',
        'responsible.name', 'responsible.code',
        'activity.name', 'activity.code',
        'created_at', 'id',
    ]

    FILTER_COND = [['status.code', '==', 'in_progress']]

    try:
        cmf_alert('Выполняется запрос задач...')
        tasks = models.CmfTask.list(
            filter=FILTER_COND,
            fields=REQUIRED_FIELDS,
            slice=[0, 100000],
            sort=[('created_at', 'DESC')],
        )
        cmf_alert(f'Получено задач: {len(tasks)}')
    except Exception as e:
        cmf_alert(f'[ERROR] Ошибка при запросе задач: {e}')
        tasks = []

    # --- Анализ ---

    threshold_days = 1
    overdue, near_deadline, no_deadline = [], [], []

    for i, task in enumerate(tasks, start=1):
        try:
            finish = get_deadline_date(task)
            task_code = get_task_code(task)

            if finish is None:
                no_deadline.append(task)
                continue

            days_left = (finish - today).days
            if days_left < 0:
                overdue.append(task)
            elif days_left <= threshold_days:
                near_deadline.append(task)
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка анализа задачи №{i}: {e}')

    cmf_alert(
        f'Анализ завершён. Просрочено: {len(overdue)}, '
        f'Скоро дедлайн: {len(near_deadline)}, Без срока: {len(no_deadline)}'
    )

    # --- Отправка отчёта руководству ---

    def send_report_to_management(overdue, near_deadline, no_deadline, threshold_days):
        cmf_alert('=== Отправка отчёта руководству ===')

        def risk_score(task):
            try:
                finish = get_deadline_date(task)
                return (today - finish).days if finish else 9999
            except Exception:
                return 9999

        lines = []

        try:
            lines.append(f'<h2>ОТЧЁТ ПО ПОРТФЕЛЮ ЗАДАЧ (активные: in_progress)</h2>')
            lines.append(f'<hr>')
            lines.append(f'Дата формирования: {now.strftime("%Y-%m-%d %H:%M")}<br>')
            lines.append(f'Порог «скоро дедлайн»: &le; {threshold_days} дн.<br>')
            lines.append(f'Логика дедлайна: сначала deadline, если нет — sched_finish_date<br>')
            lines.append(f'<br>')
            lines.append(f'<b>Просрочено:</b> {len(overdue)}<br>')
            lines.append(f'<b>Скоро дедлайн</b> (&le; {threshold_days} дн.): {len(near_deadline)}<br>')
            lines.append(f'<b>Без срока:</b> {len(no_deadline)}<br>')
            lines.append(f'<hr>')

            if overdue:
                lines.append(f'<h3>ТОП РИСКОВ (самые просроченные):</h3>')
                lines.append(format_task_list(sorted(overdue, key=risk_score, reverse=True)[:TOP_N_RISK]))
                lines.append(f'<br>')
            else:
                lines.append(f'<p>Просроченных задач нет.</p>')
                lines.append(f'<br>')

            if near_deadline:
                lines.append(f'<h3>СКОРО ДЕДЛАЙН:</h3>')
                near_sorted = sorted(near_deadline, key=lambda t: get_deadline_date(t) or type(today)(1970, 1, 1))
                lines.append(format_task_list(near_sorted[:TOP_N_RISK]))
                lines.append(f'<br>')
            else:
                lines.append(f'<p>Задач с приближающимся дедлайном нет.</p>')
                lines.append(f'<br>')

            if no_deadline:
                lines.append(f'<h3>ЗАДАЧИ БЕЗ СРОКА (топ):</h3>')
                lines.append(format_task_list(no_deadline[:TOP_N_RISK]))
                lines.append(f'<br>')
            else:
                lines.append(f'<p>У всех задач есть срок.</p>')
                lines.append(f'<br>')

            content = ''.join(lines)
            subject = (f'Отчёт по портфелю: просрочено={len(overdue)}, '
                       f'скоро={len(near_deadline)}, без срока={len(no_deadline)}')

            sent = 0
            for email in REPORT_EMAILS:
                write_email_log('mgmt_report', email, subject, content)

                fragment = content[:ALERT_FRAGMENT_LEN] + ('...' if len(content) > ALERT_FRAGMENT_LEN else '')
                cmf_alert(f'--- Фрагмент контента (руководство) для {email} ---\n{fragment}\n--- Конец фрагмента ---')

                if send_email(email, subject, content):
                    sent += 1

            cmf_alert(f'Отчёт руководству: отправлено на {sent}/{len(REPORT_EMAILS)} адресов.')
        except Exception as e:
            cmf_alert(f'[ERROR] Критическая ошибка при формировании отчёта для руководства: {e}')

    # --- Отправка уведомлений исполнителям ---

    def send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days):
        cmf_alert('=== Отправка уведомлений исполнителям ===')

        by_email = {}

        try:
            for task in overdue + near_deadline + no_deadline:
                email = get_responsible_email(task)
                if not email:
                    cmf_alert(
                        f'У задачи "{task.name}" (код: {get_task_code(task)}) '
                        f'нет email ответственного — уведомление не отправляется'
                    )
                    continue
                name = get_responsible_name(task)
                if email not in by_email:
                    by_email[email] = {
                        'name': name,
                        'overdue': [],
                        'near_deadline': [],
                        'no_deadline': [],
                    }

                if task in overdue:
                    by_email[email]['overdue'].append(task)
                elif task in near_deadline:
                    by_email[email]['near_deadline'].append(task)
                else:
                    by_email[email]['no_deadline'].append(task)
        except Exception as e:
            cmf_alert(f'[ERROR] Ошибка группировки задач по ответственным: {e}')
            return

        sent, failed = 0, 0

        for email, data in by_email.items():
            try:
                lines = []

                lines.append(f'<h2>Сводка по задачам — {data["name"]}</h2>')
                lines.append(f'<hr>')

                if data['overdue']:
                    lines.append(f'<h3>ПРОСРОЧЕННЫЕ ЗАДАЧИ:</h3>')
                    lines.append(format_task_list(data['overdue']))
                    lines.append(f'<br>')

                if data['near_deadline']:
                    lines.append(f'<h3>СКОРО ДЕДЛАЙН (&le; {threshold_days} дн.):</h3>')
                    lines.append(format_task_list(data['near_deadline']))
                    lines.append(f'<br>')

                if data['no_deadline']:
                    lines.append(f'<h3>ЗАДАЧИ БЕЗ СРОКА:</h3>')
                    lines.append(format_task_list(data['no_deadline']))
                    lines.append(f'<br>')

                if len(lines) <= 2:
                    continue

                content = ''.join(lines)
                subject = (
                    f'Сводка по вашим задачам: просрочено={len(data["overdue"])}, '
                    f'скоро={len(data["near_deadline"])}, без срока={len(data["no_deadline"])}'
                )

                cmf_alert(
                    f'Отправка исполнителю: {data["name"]} <{email}> — '
                    f'просрочено: {len(data["overdue"])}, '
                    f'скоро: {len(data["near_deadline"])}, '
                    f'без срока: {len(data["no_deadline"])}'
                )

                write_email_log('resp_notify', email, subject, content)

                fragment = content[:ALERT_FRAGMENT_LEN] + ('...' if len(content) > ALERT_FRAGMENT_LEN else '')
                cmf_alert(f'--- Фрагмент контента (исполнитель) для {email} ---\n{fragment}\n--- Конец фрагмента ---')

                if send_email(email, subject, content):
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                cmf_alert(f'[ERROR] Ошибка при отправке уведомления исполнителю {email}: {e}')
                failed += 1

        cmf_alert(f'Уведомления исполнителям: отправлено={sent}, ошибок={failed}')

    # --- Запуск ---

    send_report_to_management(overdue, near_deadline, no_deadline, threshold_days)
    send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days)

    cmf_alert('[END] Мониторинг завершён')


main()