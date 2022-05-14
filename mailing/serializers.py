from rest_framework import serializers
from django.utils import timezone

from .models import Client, Mailing, Message


class ClientSerializer(serializers.Serializer):
    """
    Добавление, обновление клиента в справочник со всеми его атрибутами, а также его удаление из справочника
    """

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(max_length=11)
    code = serializers.IntegerField(max_value=999, min_value=900)
    tag = serializers.CharField(max_length=100)
    zone = serializers.CharField(max_length=30)

    def create(self, validated_data):

        return Client.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.number = validated_data.get('number', instance.number)
        instance.tag = validated_data.get('tag', instance.tag)
        instance.zone = validated_data.get('zone', instance.zone)
        instance.save()

        return instance


class MailingSerializer(serializers.Serializer):
    """
    Добавление, обновление рассылки со всеми её атрибутами, а также ее удаление из базы
    """

    id = serializers.IntegerField(read_only=True)
    starts_at = serializers.DateTimeField(default=timezone.now())
    expired_at = serializers.DateTimeField()
    text = serializers.CharField(max_length=500)
    filter = serializers.CharField(max_length=100)

    def create(self, validated_data):

        return Mailing.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.starts_at = validated_data.get('starts_at', instance.starts_at)
        instance.expired_at = validated_data.get('expired_at', instance.expired_at)
        instance.text = validated_data.get('text', instance.text)
        instance.filter = validated_data.get('filter', instance.filter)
        instance.save()

        return instance


class MessagesSerializer(serializers.ModelSerializer):

    client = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'client', 'status']

    def get_client(self, obj):
        number = obj.client.number

        return number


class StatsMailingSerializer(serializers.ModelSerializer):
    """
    Общая статистика по созданным рассылкам и количеству отправленных сообщений по ним с группировкой по статусам
    """

    text = serializers.SerializerMethodField()

    # Добавление вложенного уровня полей статусов сообщений
    messages_status = serializers.SerializerMethodField()

    # Поля рассылки
    class Meta:
        model = Mailing
        fields = ['id', 'starts_at', 'text', 'messages_status']

    # если в поле text больше 50 символов, вывести первые 50 символов
    def get_text(self, obj):
        if len(obj.text) > 50:
            return obj.text[:50] + '...'
        return obj.text

    # Поля сообщений
    def get_messages_status(self, obj):
        stat = dict()
        total = obj.messages.count()
        stat.update({'total': total}) if total > 0 else None
        new = obj.messages.filter(status='new').count()
        stat.update({'new': new}) if new > 0 else None
        sent = obj.messages.filter(status='sent').count()
        stat.update({'sent': sent}) if sent > 0 else None
        failure = obj.messages.filter(status='failure').count()
        stat.update({'failure': failure}) if failure > 0 else None
        return stat


class StatsMailingPKSerializer(StatsMailingSerializer):
    """
    Получение детальной статистики отправленных сообщений по конкретной рассылке
    """

    text = serializers.CharField()
    tag = serializers.SerializerMethodField()

    messages = MessagesSerializer(many=True, read_only=True)

    class Meta:
        model = Mailing
        fields = ['id', 'text', 'starts_at', 'expired_at', 'tag', 'messages_status', 'messages']

    def get_tag(self, obj):

        if obj.messages.first() is not None:  # ищем клиентов по тегу либо отдаем None, если клиент не найден
            tag = obj.messages.first().client.tag
            return tag
        return None