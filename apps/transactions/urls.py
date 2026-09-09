from django.urls import path

from . import views

app_name = "transactions"

urlpatterns = [
    path("manual-entry/", views.manual_entry_view, name="manual_entry"),
]
