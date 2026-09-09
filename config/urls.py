from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "AL-HALAL ISLAMIC COOPERATIVE"
admin.site.site_title = "AL-HALAL ISLAMIC COOPERATIVE"
admin.site.index_title = "AL-HALAL ISLAMIC COOPERATIVE"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("transactions/", include("apps.transactions.urls")),
    path("payments/", include("apps.payments.urls")),
    path("loans/", include("apps.loans.urls")),
    path("ledger/", include("apps.ledger.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    # In production, nginx serves /media/ directly (see nginx.conf) —
    # this is dev-only so uploaded receipts render locally without nginx.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
