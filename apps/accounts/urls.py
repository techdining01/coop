from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.CoopLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("pending-approval/", views.pending_approval_view, name="pending_approval"),
    path("approvals/", views.member_approval_queue_view, name="approve_members"),
    path("approvals/<int:pk>/", views.member_approval_detail_view, name="member_approval_detail"),
]
