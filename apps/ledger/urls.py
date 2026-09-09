from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("exports/", views.export_list_view, name="export_list"),
    path("exports/<int:pk>/download/", views.export_download_view, name="export_download"),
    path("my-statement/pdf/", views.my_statement_pdf_view, name="my_statement_pdf"),
    path("my-statement/csv/", views.my_statement_csv_view, name="my_statement_csv"),
    path("reports/", views.reports_index_view, name="reports_index"),
    path("reports/member-statements.csv", views.report_member_statements_csv, name="report_member_statements"),
    path("reports/loan-book.csv", views.report_loan_book_csv, name="report_loan_book"),
    path("reports/savings-summary.csv", views.report_savings_summary_csv, name="report_savings_summary"),
    path("reports/overdue.csv", views.report_overdue_csv, name="report_overdue"),
]
