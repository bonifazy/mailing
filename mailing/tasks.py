import requests
import json
from celery import Celery, shared_task, group, current_task
from django.utils import timezone
from time import sleep

from project.settings import CELERY_SETTINGS_FBRQ
from .models import Message

# Количество тасков в одном асинхронном запросе (celery.task.group)
CHUNK = 30
# время ожидания после старта очередной группы тасков для запуска следующей группы
SLEEP = 0.1
# время, в течение которого ожидается прием с сервера
CONNECT_TIMEOUT = 2
# время, в течение которого ожидается чтение данных в буфер дескриптора сокета
READ_TIMEOUT = 2


def message_update_state(obj, status):
    """
    Актуализируем статусы у модели "Сообщение".
    Если сообщение имеет статус 'new' и таск взял в работу это сообщение, меняем статус на 'active'-- в работе.
    Если таск отработал отлично, то меняем статус на "отправлено" (sent)
    Если Сообщение было взято в работу "active" и таск не смог передать сообщение на сервер, меняем статус
    на "новое" (new), позволяя снова пробовать отправить сообщение либо этим же таском (Task.retry(),
    либо новым таском, который найдет его по этому статусу "new", как еще не отправленное сообщение)
    Ecли Сообщение взято в работу 'active' и его не успели отправить по времени, меняем статус на 'failure'
    """
    # смотри .models.Message status field: new, active, sent, failure

    if obj.status != status:
        obj.status = status
        obj.save()
    else:
        return None


app = Celery('tasks')

# подгружаем настройки запроса, чтобы сервер https://probe.fbrq.cloud точно принял данные
URL = CELERY_SETTINGS_FBRQ['url']
HEADERS = CELERY_SETTINGS_FBRQ['headers']


# экземпляр таска self.retry() некорректно работает в celery==5.2.0- 5.2.3
# Поэтому views.django_rest_framework_func() --> tasks.task.retry(eta=start_time, expires=expire_time) не работает!
# Пришлось делать через celery beat: views.django_rest_framework_func() --> tasks.task(run_every=timedelta(seconds=60))
# см project.settings.py
# загружаем из mailing.tasks, а не из корневого каталога celery.py, поэтому @app.on_after_configure.connect не работает!
@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(10.0, send.s(), name='send')


@shared_task(name='send_message')
def send_message(message_id):
    """
    Основной таск для отправки данных на сервер https://probe.fbrq.cloud
    """

    message = Message.objects.get(pk=message_id)

    # дополнительная информация, лог выполнения Celery
    meta = {
        'mailing id': message.mailing.pk,
        'message id': message_id,
        'number': message.client.number,
    }

    # Проверка статуса. Если не active, значит это сообщение либо пришло не из основного таска (неизвестная валидация),
    # либо происходит дублирование этого сообщения в другом таске. Исключаем эти ситуации.
    if message.status != 'active':
        return 'Failed send message with not active status.', meta

    current_task.update_state(state='PROGRESS', meta=json.dumps(meta))  # меняем статус у таска на "в работе"

    # спецификация url принимающего сервера:
    url = URL + str(message_id)

    # спецификация json принимающего сервера
    data = {
        'id': message_id,
        'phone': message.client.number,
        'text': message.mailing.text,
    }

    # настройка, если принимающий сервер подтупливает, либо трафик идет через vpn
    connect_timeout, read_timeout = CONNECT_TIMEOUT, READ_TIMEOUT

    # проверяем актуальное время, чтобы успеть отработать до окончания рассылки
    now = timezone.now()
    if message.starts_at <= now < message.mailing.expired_at:
        response = requests.post(url=url,
                                 data=json.dumps(data),
                                 headers=HEADERS,
                                 verify=True,
                                 timeout=(connect_timeout, read_timeout),
                                 )
        status = response.status_code

        if status == 200:
            # сервер вернул "хорошие" данные
            message_update_state(message, status='sent')  # меняем статус у модели "Сообщение" на "исполнено"
            current_task.update_state(state='SUCCESS', meta=json.dumps(meta))  # меняем статус у таска на "исполнено"
            return 'Success. Message has been sent. ', meta  # возвращаем ответ от сервера: статус, отправленное сообщение
        else:
            # сервер не смог принять данные
            message_update_state(message, status='new')  # меняем статус у сообщения, снова возвращаем в работу
            current_task.update_state(state='FAILURE', meta=json.dumps(meta))  # меняем статус на "неудачное исполнение"
            # возвращаем общую информацию о неудачной попытке передачи сообщения
            return 'Failure. Server not asked in time. ', meta
    else:
        # не успели отправить сообщение вовремя
        message_update_state(message, status='failure')  # неудачное исполнение по времени
        current_task.update_state(state='FAILURE', meta=json.dumps(meta))  # неудачное исполнение по времени
        return 'Failure. Expired time is more than now. ', meta


@shared_task(name='send')
def send(mailing_id=None):
    """
    Обработка активных рассылок и отправка сообщений клиентам.
    Запускать с флагом --beat: (env) user:path$ celery -A project worker -l info --beat
    """

    # отправить все новые сообщения с подходящим временным диапазоном

    # приходит id рассылки mailing_id из .views.py
    # отправить сейчас, время уже проверено в .views.py
    if mailing_id is not None:
        messages = Message.objects.filter(mailing=mailing_id)
    # Получаем управление из celery_beat.
    # Находим все сообщения (не отправленные, но которые нужно отправить), собираем их на отправку в tasks
    else:
        messages = Message.objects.filter(status='new',
                                          starts_at__lte=timezone.now(),
                                          mailing__expired_at__gte=timezone.now(),
                                          )
    # Сообщения, которые нужно отправить, нет. Отдыхаем..
    if len(messages) == 0:
        return 'Im not busy =)'

    # Сообщения для отправки найдены. Отправляем!

    # Забираем сообщения в работу, чтобы другие какие- либо таски не забрали эти сообщения, помеченные как 'new'
    # Меняем на статус в работе: 'active'
    for m in messages:
        message_update_state(m, status='active')

    # Все сообщения разбиваем на группы по кусочкам, равным CHUNK для того, чтобы принимающий сервер не принимал за DDOS

    # id объектов Message() легче, чем сами объекты, поэтому дальше работаем только с id
    # ids-- временное хранилище id сообщение
    ids = list()
    # group_ids-- полный список групп id
    group_ids = list()
    all_messages = len(messages)
    for message in messages:
        if len(ids) == CHUNK - 1:
            ids.append(message.pk)
            group_ids.append(tuple(ids))
            ids.clear()
        else:
            ids.append(message.pk)
    group_ids.append(tuple(ids))

    # Каждую группу отправляем с небольшой задержкой SLEEP
    results = list()
    for ids in group_ids:
        group_tasks = group(send_message.s(message_id) for message_id in ids)
        result = group_tasks.delay()
        results.append(result.save())
        sleep(SLEEP)

    # Результаты групповой отправки
    str_mailing_id = ''
    if mailing_id is not None:
        str_mailing_id = 'Mailing id: {} \n'.format(str(mailing_id))
    total = '\nTotal: \n{} sent messages, \n{} group tasks. \n'.format(all_messages, len(results))
    total += str_mailing_id
    result = total + ' group task id.\n'.join(map(lambda x: x.id, results))
    return result


@shared_task
def dummy():
    """
    Проверочный таск
    """
    return 'Its dummy task =)'
