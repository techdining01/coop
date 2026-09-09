from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.landing_view, name="home"),
    path("audit-log/", views.audit_log_view, name="audit_log"),
]

# Root-scope route (not app-namespaced, not under any prefix) — see
# service_worker_view's docstring for why this must live at the root.
urlpatterns += [
    path("service-worker.js", views.service_worker_view, name="service_worker"),
]
