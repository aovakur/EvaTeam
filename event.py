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
    PAUSE_BETWEEN_EMAILS_SEC = 1
    ALERT_FRAGMENT_LEN = 600

    URL_SITE = 'https://eva.local/'
    # ===================

    now = g.now()
    today = now.date()
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
            return None

    def get_responsible_name(task):
        try:
            responsible = getattr(task, 'responsible', None)
            if responsible:
                name = getattr(responsible, 'name', None)
                return name if name else '?'
            return 'не назначен'
        except Exception as e:
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
            return f'{URL_SITE}desk/cards?obj=Task:{task_id}'
        except Exception as e:
            return URL_SITE

    def send_email(to_email, subject, content):
        """
        Обёртка вокруг cmfutil.send_email с нормальной диагностикой.
        Возвращает True только если отправка реально успешна.
        """
        # 1. Валидация адреса ДО вызова
        if not to_email:
            return False

        to_email = str(to_email).strip()
        if '@' not in to_email or '.' not in to_email.split('@')[-1]:
            return False

        # Небольшая пауза, если нужно (оставляем как у тебя)
        time.sleep(PAUSE_BETWEEN_EMAILS_SEC)
        cmfutil.send_email(to=to_email, subject=subject, content=content, cc=[],bcc=[])


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
        tasks = models.CmfTask.list(
            filter=FILTER_COND,
            fields=REQUIRED_FIELDS,
            slice=[0, 100000],
            sort=[('created_at', 'DESC')],
        )
    except Exception as e:
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
            pass

    def send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days):

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
                if send_email(email, subject, content):
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1

    # --- Запуск ---
    send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days)

main()