from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.landing_view, name="home"),
    path("audit-log/", views.audit_log_view, name="audit_log"),
    path("bad-request/", views.bad_request_view, name="bad_request"),
    path("permission-denied/", views.permission_denied_view, name="permission_denied"),
    path("page-not-found/", views.page_not_found_view, name="page_not_found"),
    path("server-error/", views.server_error_view, name="server_error"),
    
]

# Root-scope route (not app-namespaced, not under any prefix) — see
# service_worker_view's docstring for why this must live at the root.
urlpatterns += [
    path("service-worker.js", views.service_worker_view, name="service_worker"),
]
