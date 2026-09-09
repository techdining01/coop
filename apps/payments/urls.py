from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhook/payvessel/", views.payvessel_webhook_view, name="payvessel_webhook"),
    path("receipts/upload/", views.receipt_upload_view, name="receipt_upload"),
    path("receipts/review/", views.receipt_review_queue_view, name="receipt_review_queue"),
    path("receipts/review/<int:pk>/", views.receipt_review_detail_view, name="receipt_review_detail"),
    path("reconciliation/", views.reconciliation_upload_view, name="reconciliation_upload"),
    path("reconciliation/<int:pk>/", views.reconciliation_result_view, name="reconciliation_result"),
]
