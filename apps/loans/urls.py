from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("apply/", views.apply_for_loan_view, name="apply"),
    path("mine/", views.my_loans_view, name="my_loans"),
    path("<int:pk>/", views.loan_detail_view, name="loan_detail"),
    path("<int:pk>/guarantor-response/", views.respond_to_guarantor_request_view, name="guarantor_response"),
    path("admin/queue/", views.loan_queue_view, name="admin_queue"),
    path("admin/<int:pk>/review/", views.loan_review_view, name="admin_review"),
    path("admin/<int:pk>/record-repayment/", views.record_repayment_view, name="record_repayment"),
]
