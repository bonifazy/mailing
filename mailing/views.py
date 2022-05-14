import json
from django.utils import timezone
from django.http import JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import get_object_or_404

from .models import Mailing, Client, Message
from .serializers import ClientSerializer, MailingSerializer, StatsMailingSerializer, StatsMailingPKSerializer
from .tasks import send


class ClientView(APIView):
    """
    Create, update, delete Client with attributes to database.
    """

    def post(self, request):
        """
        Adding new client to database with its attributes.
        """

        client = request.data
        client['code'] = int(client['number']) // 10_000_000 - 7_000
        serializer = ClientSerializer(data=client)
        if serializer.is_valid(raise_exception=True):
            client = serializer.save()
            return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK)

    def put(self, request, pk):
        """
        Update client attributes.
        """

        client = get_object_or_404(Client, pk=pk)
        data = request.data
        serializer = ClientSerializer(instance=client, data=data, partial=True)
        if serializer.is_valid(raise_exception=True):
            client = serializer.save()
            return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """
        Delete client from database.
        """

        client = get_object_or_404(Client, pk=pk)
        client.delete()
        data = {
            'id': pk,
            'number': client.number,
            'code': client.code,
            'tag': client.tag,
            'zone': client.zone,
        }
        return JsonResponse(data, content_type='application/json', status=status.HTTP_200_OK)


class MailingView(APIView):
    """
    View, create, update and delete Mailing with attributes to database.
    http://127.0.0.1:8000/docs/
    """

    def get(self, *args, **kwargs):
        """
        List short statistics for all created mailing (without PK parameter) and its sending messages grouped by status.
        List detail statistics for each mailing and its sending messages (with PK parameter).
        """
        if 'pk' in self.kwargs:
            pk = self.kwargs['pk']
            query = get_object_or_404(Mailing, pk=pk)
            serializer = StatsMailingPKSerializer(query)
            return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK)
        else:
            query = Mailing.objects.order_by('-id')
            serializer = StatsMailingSerializer(query, many=True)
            return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK, safe=False)

    def post(self, request):
        """
        Adding new mailing to database with its attributes.
        """

        mailing = request.data
        serializer = MailingSerializer(data=mailing)
        if serializer.is_valid(raise_exception=True):
            # validators in ./models.py
            mailing = serializer.save()
        # find client by mailing filter
        if mailing.filter.isnumeric():
            # find by code number
            filter = int(mailing.filter)
            if 0 < filter <= 999:
                filter_min_value = filter * 10000000 + 70000000000
                filter_max_value = (filter + 1) * 10000000 + 70000000000
                clients = Client.objects.filter(number__gte=filter_min_value, number__lt=filter_max_value)
        else:
            # find by tag
            clients = Client.objects.filter(tag=mailing.filter)

        # Create message by each client.
        # Next, its messages need to send to clients (Celery tasks)
        for client in clients:
            message = Message()
            message.starts_at = mailing.starts_at
            message.client = client
            message.mailing = mailing
            message.save()
        # send mailing by id, if 'starts_at' time has come and 'expired_at' time is not over
        # send now
        now = timezone.now()
        if mailing.starts_at <= now < mailing.expired_at:
            # run celery.task.group
            send.delay(mailing.pk)

        # info to REST API client of successfull create mailing.
        return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK)

    def put(self, request, pk):
        """
        Update mailing attributes.
        If starts_at field has been updated, than update 'starts_at' field of each 'new' message of this mailing
        """
        mailing = get_object_or_404(Mailing, pk=pk)
        data = request.data

        serializer = MailingSerializer(instance=mailing, data=data, partial=True)
        if serializer.is_valid(raise_exception=True):
            start = serializer.validated_data.get('starts_at')

            # update starts_at time field of 'new' messages if this field from mailing has been changed
            if start != mailing.starts_at:
                messages = Message.objects.filter(mailing=pk).exclude(status='sent')
                for message in messages:
                    message.starts_at = start
                    message.status = 'new'
                    message.save()
            # all changed data is valid. Save mailing
            mailing = serializer.save()
        # send mailing by id, if 'starts_at' time has come and 'expired_at' time is not over
        # send now
        now = timezone.now()
        if mailing.starts_at <= now < mailing.expired_at:
            # run celery.task.group
            send.delay(mailing.pk)

        # info to REST API client of successfull update mailing
        return JsonResponse(serializer.data, content_type='application/json', status=status.HTTP_200_OK)

    def delete(self, request, pk):
        """
        Delete mailing from database.
        """

        mailing = get_object_or_404(Mailing, pk=pk)
        mailing.delete()
        data = {
            "id": pk,
            "starts_at": mailing.starts_at,
            "expired_at": mailing.expired_at,
            "filter": mailing.filter,
            "text": mailing.text[:50],
        }
        return JsonResponse(data, content_type='application/json', status=status.HTTP_200_OK)
