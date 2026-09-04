import time
def main():
        # === НАСТРОЙКИ ===
    REPORT_EMAILS = [
        # 'manager@company.ru',
        # 'product@company.ru',
    ]

    MAX_TASKS_PER_EMAIL = 50
    TOP_N_RISK = 10
    PAUSE_BETWEEN_EMAILS_SEC = 1
    PAGE_SIZE = 500
    MAX_PAGES = 30
    # ===================
    now = g.now()
    today = now.date()
    cmf_alert(f'[START] Мониторинг запущен. Время: {now.strftime("%Y-%m-%d %H:%M:%S")}')

    def parse_to_date(val):
        if val is None:
            return None
        s = str(val)
        date_part = s[:10]
        parts = date_part.split('-')
        if len(parts) != 3:
            return None
        try:
            return type(today)(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            return None

    def get_task_type(task):
        activity = getattr(task, 'activity', None)
        if activity:
            name = getattr(activity, 'name', None)
            if name:
                return name
            code = getattr(activity, 'code', None)
            if code:
                return code
            return str(activity)
        return 'Не указан'

    def get_task_code(task):
        candidates = ['code', 'external_id', 'number', 'key']
        for field in candidates:
            val = getattr(task, field, None)
            if val:
                return str(val)
        return '?'

    def get_effective_deadline_date(task):
        deadline_raw = getattr(task, 'deadline', None)
        if deadline_raw is not None:
            return parse_to_date(deadline_raw)

        gantt = getattr(task, 'op_gantt_task', None)
        if gantt:
            sched_raw = getattr(gantt, 'sched_finish_date', None)
            if sched_raw is not None:
                return parse_to_date(sched_raw)
        return None

    def get_deadline_source(task):
        dl = getattr(task, 'deadline', None)
        if dl is not None:
            return f'deadline = {dl}'
        gantt = getattr(task, 'op_gantt_task', None)
        if gantt:
            sched = getattr(gantt, 'sched_finish_date', None)
            if sched is not None:
                return f'sched_finish_date = {sched}'
        return 'не определён'

    def get_responsible_email(task):
        responsible = getattr(task, 'responsible', None)
        if responsible:
            email = getattr(responsible, 'email', None)
            if email:
                return email
        return None

    def get_responsible_name(task):
        responsible = getattr(task, 'responsible', None)
        if responsible:
            return getattr(responsible, 'name', '?')
        return 'не назначен'

    REQUIRED_FIELDS = [
        'name', 'code', 'external_id', 'number', 'key',
        'status.code', 'deadline', 'op_gantt_task.sched_finish_date',
        'responsible.name', 'responsible.email',
        'activity.name', 'activity.code',
        'created_at',
        'id'
    ]

    FILTER_COND = [
        ['status.code', '==', 'in_progress']
    ]

    def get_total_count():
        """Получает общее количество задач по фильтру."""
        try:
            # Пытаемся получить count — название метода зависит от платформы
            # Вариант 1: models.CmfTask.count(filter=...)
            if hasattr(models.CmfTask, 'count'):
                return models.CmfTask.count(filter=FILTER_COND)

            # Вариант 2: models.CmfTask.list() и берём len
            all_tasks = models.CmfTask.list(filter=FILTER_COND)
            return len(all_tasks)
        except Exception as e:
            cmf_alert(f'Не удалось получить count: {e}. Используем запасной вариант.')
            try:
                all_tasks = models.CmfTask.list(filter=FILTER_COND)
                return len(all_tasks)
            except Exception as e2:
                cmf_alert(f'Запасной вариант тоже не сработал: {e2}')
                return 0

    def fetch_all_tasks(total_count):
        """
        Сначала получает count, потом решает: один запрос или пагинация.
        """
        all_tasks = []

        if total_count == 0:
            cmf_alert('Задач по фильтру не найдено.')
            return []

        cmf_alert(f'Всего задач по фильтру: {total_count}')

        # Если задач немного — берём всё за один запрос
        if total_count <= PAGE_SIZE * MAX_PAGES:
            cmf_alert(f'Задач {total_count} <= {PAGE_SIZE * MAX_PAGES} — берём одним запросом.')
            try:
                all_tasks = models.CmfTask.list(
                    filter=FILTER_COND,
                    fields=REQUIRED_FIELDS,
                    limit=PAGE_SIZE * MAX_PAGES,
                    sort=[('created_at', 'DESC')]
                )
                cmf_alert(f'Получено задач: {len(all_tasks)}')
                return all_tasks
            except Exception as e:
                cmf_alert(f'Ошибка при запросе: {e}')
                return []

        # Если задач много — пагинация по курсору (через created_at)
        cmf_alert(f'Задач {total_count} > {PAGE_SIZE * MAX_PAGES} — включаем пагинацию.')

        last_date = None
        page_num = 0
        seen_ids = set()

        while page_num < MAX_PAGES:
            page_num += 1

            cursor_filter = list(FILTER_COND)  # копируем фильтр

            if last_date is not None:
                cursor_filter.append(['created_at', '<', last_date])

            try:
                tasks = models.CmfTask.list(
                    filter=cursor_filter,
                    fields=REQUIRED_FIELDS,
                    limit=PAGE_SIZE,
                    sort=[('created_at', 'DESC')]
                )
            except Exception as e:
                cmf_alert(f'Ошибка на странице {page_num}: {e}')
                break

            cmf_alert(f'[DEBUG] Страница {page_num}: получено задач: {len(tasks)}')

            if not tasks:
                cmf_alert('[DEBUG] Пустая страница — конец данных.')
                break

            new_tasks = []
            for t in tasks:
                if t.id not in seen_ids:
                    seen_ids.add(t.id)
                    new_tasks.append(t)

            if not new_tasks:
                cmf_alert('[DEBUG] Все задачи на странице — дубли. Стоп.')
                break

            all_tasks.extend(new_tasks)
            last_date = getattr(tasks[-1], 'created_at', None)

            if last_date is None:
                cmf_alert('[DEBUG] Нет created_at у последней задачи — курсор недоступен. Стоп.')
                break

            cmf_alert(f'[DEBUG] Набрано: {len(all_tasks)}, курсор: {last_date}')

        cmf_alert(f'Пагинация завершена. Всего собрано: {len(all_tasks)}')
        return all_tasks

    def analyze_tasks_sync(threshold_days=1):
        overdue = []
        near_deadline = []
        no_deadline = []

        total_count = get_total_count()
        tasks = fetch_all_tasks(total_count)

        cmf_alert(f'Начинаем анализ {len(tasks)} задач...')

        for i, task in enumerate(tasks, start=1):
            task_code = get_task_code(task)
            cmf_alert(f'--- [{i}/{len(tasks)}] Задача: {task.name} (Код: {task_code}, ID: {task.id}) ---')

            finish_date = get_effective_deadline_date(task)

            if finish_date is None:
                cmf_alert('  Нет срока — «без срока»')
                no_deadline.append(task)
                continue

            try:
                f_ord = finish_date.toordinal()
                t_ord = today.toordinal()

                if f_ord < t_ord:
                    cmf_alert(f'  ПРОСРОЧЕНА. Дедлайн: {finish_date}')
                    overdue.append(task)
                else:
                    days_left = f_ord - t_ord
                    if days_left <= threshold_days:
                        cmf_alert(f'  Близка к дедлайну. Осталось: {days_left} дн.')
                        near_deadline.append(task)
                    else:
                        cmf_alert(f'  В норме. Осталось: {days_left} дн.')
            except Exception as e:
                cmf_alert(f'  Ошибка сравнения дат: {e}')
                no_deadline.append(task)
                continue

        cmf_alert(
            f'Анализ завершён. Просрочено: {len(overdue)}, '
            f'Скоро дедлайн: {len(near_deadline)}, Без срока: {len(no_deadline)}'
        )
        return overdue, near_deadline, no_deadline

    def group_by_email(tasks):
        groups = {}
        for task in tasks:
            email = get_responsible_email(task)
            if not email:
                email = 'неизвестен'
            if email not in groups:
                groups[email] = []
            groups[email].append(task)
        return groups

    def format_task_list_brief(tasks, max_count=MAX_TASKS_PER_EMAIL):
        if not tasks:
            return 'Нет задач.'
        lines = []
        for t in tasks[:max_count]:
            task_code = get_task_code(t)
            line = f'{t.name} (Код: {task_code}, ID: {t.id})'

            status = getattr(t, 'status', None)
            status_code = getattr(status, 'code', '?') if status else '?'
            line += f' — статус: {status_code}'

            source = get_deadline_source(t)
            line += f', источник: {source}'

            finish_date = get_effective_deadline_date(t)
            if finish_date:
                days_overdue = (today - finish_date).days if finish_date < today else 0
                if days_overdue > 0:
                    line += f', просрочка: {days_overdue} дн.'
                else:
                    days_left = (finish_date - today).days
                    line += f', до дедлайна: {days_left} дн.'
            lines.append(line)

        total = len(tasks)
        if total > max_count:
            lines.append(f'\n... и ещё {total - max_count} задач. Полный список: [ссылка на фильтр в системе]')
        return '\n'.join(lines)

    def send_email(to_email, subject, content):
        if not to_email or '@' not in to_email:
            cmf_alert(f'ПРЕДУПРЕЖДЕНИЕ: некорректный адрес: {to_email}')
            return False

        try:
            time.sleep(PAUSE_BETWEEN_EMAILS_SEC)
            # result = cmfutil.send_email(to=to_email, subject=subject, content=content)
            result = True  # Эмуляция

            if result:
                cmf_alert(f'ОТПРАВЛЕНО: {subject} → {to_email}')
                return True
            else:
                cmf_alert(f'НЕ ОТПРАВЛЕНО: {subject} → {to_email}')
                return False
        except Exception as e:
            cmf_alert(f'Ошибка отправки: {e}')
            return False

    def make_risk_score(task):
        finish_date = get_effective_deadline_date(task)
        if finish_date is None:
            return 9999
        try:
            days_overdue = (today - finish_date).days
            return days_overdue
        except Exception:
            return 0

    def get_top_risk_tasks(tasks, n=TOP_N_RISK):
        return sorted(tasks, key=make_risk_score, reverse=True)[:n]

    def send_report_to_management(overdue, near_deadline, no_deadline, threshold_days):
        cmf_alert('=== Отправка отчёта руководству ===')
        report_lines = [
            'ОТЧЁТ ПО ПОРТФЕЛЮ ЗАДАЧ (активные: in_progress / open)',
            '',
            f'Дата формирования: {g.now().strftime("%Y-%m-%d %H:%M")}',
            f'Порог для «скоро дедлайн»: <= {threshold_days} дн.',
            f'Логика дедлайна: сначала deadline, если нет — sched_finish_date',
            '',
            'СТАТИСТИКА:',
            f'Просрочено: {len(overdue)}',
            f'Скоро дедлайн (≤ {threshold_days} дн.): {len(near_deadline)}',
            f'Без срока: {len(no_deadline)}',
            '',
        ]

        if overdue:
            report_lines.append('ТОП РИСКОВ (самые просроченные):')
            report_lines.append(format_task_list_brief(get_top_risk_tasks(overdue)))
            report_lines.append('')
        else:
            report_lines.append('Просроченных задач нет.')
            report_lines.append('')

        if near_deadline:
            report_lines.append('СКОРО ДЕДЛАЙН (топ по сроку):')
            near_sorted = sorted(
                near_deadline,
                key=lambda t: (get_effective_deadline_date(t) or type(today)(1970, 1, 1)),
                reverse=False
            )[:TOP_N_RISK]
            report_lines.append(format_task_list_brief(near_sorted))
            report_lines.append('')
        else:
            report_lines.append('Задач с приближающимся дедлайном нет.')
            report_lines.append('')

        if no_deadline:
            report_lines.append('ЗАДАЧИ БЕЗ СРОКА (топ):')
            report_lines.append(format_task_list_brief(no_deadline[:TOP_N_RISK]))
            report_lines.append('')
        else:
            report_lines.append('У всех задач есть срок.')
            report_lines.append('')

        report_content = '\n'.join(report_lines)
        subject = f'Отчёт по портфелю: просрочено={len(overdue)}, скоро={len(near_deadline)}, без срока={len(no_deadline)}'

        sent_count = 0
        for email in REPORT_EMAILS:
            if send_email(email, subject, report_content):
                sent_count += 1
        cmf_alert(f'Отчёт руководству: отправлено на {sent_count}/{len(REPORT_EMAILS)} адресов.')

    def send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days):
        cmf_alert('=== Отправка уведомлений исполнителям ===')
        stats = {'sent': 0, 'failed': 0}

        if overdue:
            groups = group_by_email(overdue)
            for email, tasks in groups.items():
                content = 'СРОЧНО: Просроченные задачи:\n\n' + format_task_list_brief(tasks)
                if send_email(email, 'СРОЧНО: Просроченные задачи', content):
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1

        if near_deadline:
            groups = group_by_email(near_deadline)
            for email, tasks in groups.items():
                content = f'Срок завершения приближается (осталось ≤ {threshold_days} дн.):\n\n' + format_task_list_brief(tasks)
                if send_email(email, f'Дедлайн скоро: {len(tasks)} задач', content):
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1

        if no_deadline:
            groups = group_by_email(no_deadline)
            for email, tasks in groups.items():
                content = 'Задачи без установленного срока:\n\n' + format_task_list_brief(tasks)
                if send_email(email, f'Задачи без срока: {len(tasks)} шт.', content):
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1

        cmf_alert(f'Уведомления исполнителям: отправлено={stats["sent"]}, ошибок={stats["failed"]}')

    def process_all_sync(threshold_days=1):
        overdue, near_deadline, no_deadline = analyze_tasks_sync(threshold_days)
        send_report_to_management(overdue, near_deadline, no_deadline, threshold_days)
        send_notifications_to_responsible(overdue, near_deadline, no_deadline, threshold_days)
    process_all_sync()

    cmf_alert(f'[END] Мониторинг завершён. Время: {g.now().strftime("%Y-%m-%d %H:%M:%S")}')


main()