import time

def main():
    PAUSE_BETWEEN_EMAILS_SEC = 1
    URL_SITE = 'https://eva.local/'

    now = g.now()
    today = now.date()

    def parse_to_date(val):
        if val is None:
            return None
        try:
            parts = str(val)[:10].split('-')
            if len(parts) != 3:
                return None
            return type(today)(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            return None

    def get_task_code(task):
        for field in ('code', 'external_id', 'number', 'key'):
            try:
                val = getattr(task, field, None)
                if val:
                    return str(val)
            except Exception:
                pass
        return '?'

    def get_deadline_date(task):
        dl = getattr(task, 'deadline', None)
        if dl is not None:
            return parse_to_date(dl)
        gantt = getattr(task, 'op_gantt_task', None)
        if gantt:
            return parse_to_date(getattr(gantt, 'sched_finish_date', None))
        return None

    def get_responsible_email(task):
        responsible = getattr(task, 'responsible', None)
        if responsible:
            email = getattr(responsible, 'code', None)
            if email and '@' in str(email):
                return str(email).strip()
        return None

    def get_responsible_name(task):
        responsible = getattr(task, 'responsible', None)
        if responsible:
            name = getattr(responsible, 'name', None)
            return name if name else '?'
        return 'не назначен'

    def format_task_list(tasks):
        if not tasks:
            return '<p>Нет задач.</p>'
        lines = []
        for t in tasks:
            code = get_task_code(t)
            task_url = f'{URL_SITE}desk/cards?obj=Task:{code}'
            status = getattr(t, 'status', None)
            status_code = getattr(status, 'code', '?') if status else '?'
            lines.append(f'<b>- <a href="{task_url}">{t.name}</a> (Код: {code})</b><br>')
            lines.append(f'&nbsp;&nbsp;Статус: {status_code}<br>')
            lines.append(f'&nbsp;&nbsp;Срок не установлен<br><br>')
        return ''.join(lines)

    def send_email(to_email, subject, content):
        if not to_email or '@' not in str(to_email):
            return False
        time.sleep(PAUSE_BETWEEN_EMAILS_SEC)
        cmfutil.send_email(to=to_email, subject=subject, content=content, cc=[], bcc=[])

    # --- Получение задач ---
    try:
        tasks = models.CmfTask.list(
            filter=[['status.code', '==', 'in_progress']],
            slice=[0, 100000],
            sort=[('created_at', 'DESC')],
        )
    except Exception:
        tasks = []

    # --- Фильтр: без срока ---
    no_deadline = []
    for task in tasks:
        finish = get_deadline_date(task)
        if finish is None:
            no_deadline.append(task)

    if not no_deadline:
        cmf_alert('Задач без срока нет')
        return

    # --- Группировка по исполнителям ---
    by_email = {}
    for task in no_deadline:
        email = get_responsible_email(task)
        if not email:
            cmf_alert(
                f'У задачи "{task.name}" (код: {get_task_code(task)}) '
                f'нет email ответственного — уведомление не отправляется'
            )
            continue
        name = get_responsible_name(task)
        if email not in by_email:
            by_email[email] = {'name': name, 'tasks': []}
        by_email[email]['tasks'].append(task)

    # --- Отправка исполнителям ---
    for email, data in by_email.items():
        content = f'<h2>ЗАДАЧИ БЕЗ СРОКА — {data["name"]}</h2><hr>'
        content += format_task_list(data['tasks'])
        subject = f'Задач без срока: {len(data["tasks"])}'
        send_email(email, subject, content)

main()