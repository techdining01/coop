from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.CoopLoginView.as_view(), name="login"),
    path("logout/", views.CoopLogoutView.as_view(), name="logout"),
    path("register/", views.register_view, name="register"),
    path("pending-approval/", views.pending_approval_view, name="pending_approval"),
    path("admin/approve-members/", views.approve_members_view, name="approve_members"),
]
