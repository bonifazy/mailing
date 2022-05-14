from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator, ValidationError


class Mailing(models.Model):
    starts_at = models.DateTimeField(verbose_name='Дата запуска рассылки')
    expired_at = models.DateTimeField(verbose_name='Дата окончания рассылки')
    text = models.TextField(max_length=500, verbose_name='Текст сообщения')
    filter = models.CharField(max_length=100, verbose_name='Фильтр: код оператора, теги')

    def save(self, *args, **kwargs):
        if self.expired_at < self.starts_at:
            raise ValidationError("Дата и время окончания рассылки не может быть меньше времени начала рассылки!")
        super(Mailing, self).save(*args, **kwargs)

    def __str__(self):
        return "id: {}, text: {}".format(self.id, self.text[:100])

    class Meta:
        verbose_name = 'Рассылка'
        verbose_name_plural = 'Рассылки'


class Client(models.Model):
    import pytz  # часовой пояс клиента
    europe_zones = [i for i in pytz.all_timezones if i.startswith('Europe')]
    asia_zones = [i for i in pytz.all_timezones if i.startswith('Asia')]
    etc_zones = [i for i in pytz.all_timezones if i.startswith('Etc')]
    TIMEZONES = [*europe_zones, *asia_zones, *etc_zones]  # список часовых поясов в России
    TIMEZONES = tuple(map(lambda x: (x, x), TIMEZONES))  # представление для параметра 'choices' поля 'zone'

    number = models.BigIntegerField(unique=True, validators=[MinValueValidator(70000000000),
                                                    MaxValueValidator(79999999999)], verbose_name='Номер телефона')
    code = models.PositiveSmallIntegerField(validators=[MinValueValidator(900), MaxValueValidator(999)],
                                            verbose_name='Код оператора')
    tag = models.CharField(max_length=100, verbose_name='Тег, произвольная метка')
    zone = models.CharField(max_length=32, choices=TIMEZONES, default='Europe/Moscow', verbose_name='Часовой пояс')

    def __str__(self):
        return "id: {}, number: {}".format(self.id, self.number)

    def __save__(self, *args, **kwargs):
        self.code = int(self.number) // 10_000_000 - 7_000
        super(Client, self).save(*args, **kwargs)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'


class Message(models.Model):
    STATUS = (('new', 'новый'), ('active', 'в обработке'), ('sent', 'отправлено'), ('failure', 'неудачная отправка'))

    starts_at = models.DateTimeField(verbose_name='Дата отправки')
    status = models.CharField(max_length=20, choices=STATUS, default='new', verbose_name='Статус отправки')
    mailing = models.ForeignKey('Mailing', related_name='messages', on_delete=models.CASCADE, verbose_name='id рассылки')
    client = models.ForeignKey('Client', related_name='clients', on_delete=models.CASCADE, verbose_name='id клиента')

    def __str__(self):
        return "id: {}, client to: {}, from mailing: {}".format(self.id, self.client.number, self.mailing.text[:100])

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
