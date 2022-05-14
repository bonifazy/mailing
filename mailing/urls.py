from django.urls import path

from .views import ClientView, MailingView


app_name = 'mailing'

urlpatterns = [
    path('client/', ClientView.as_view()),
    path('client/<int:pk>/', ClientView.as_view()),
    path('mailing/', MailingView.as_view()),
    path('mailing/<int:pk>/', MailingView.as_view())
]
