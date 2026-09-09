from django.contrib import admin

from .models import PaymentProof, ReconciliationDiscrepancy, ReconciliationRun, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("transaction_reference", "provider", "status", "received_at", "processed_at")
    list_filter = ("provider", "status")
    search_fields = ("transaction_reference",)
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]  # a delivery log, never hand-edited

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PaymentProof)
class PaymentProofAdmin(admin.ModelAdmin):
    list_display = ("member", "claimed_type", "claimed_amount", "status", "uploaded_at", "reviewed_by")
    list_filter = ("status", "claimed_type")
    search_fields = ("member__username",)
    readonly_fields = ("file_hash", "uploaded_at", "reviewed_by", "reviewed_at", "resulting_ledger_entry")


class ReconciliationDiscrepancyInline(admin.TabularInline):
    model = ReconciliationDiscrepancy
    extra = 0
    readonly_fields = [f.name for f in ReconciliationDiscrepancy._meta.fields]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "uploaded_by", "total_rows_in_file", "matched_count", "discrepancy_count", "created_at")
    readonly_fields = ("uploaded_by", "source_file", "total_rows_in_file", "matched_count", "discrepancy_count", "created_at")
    inlines = [ReconciliationDiscrepancyInline]

    def has_add_permission(self, request):
        return False  # created only via the upload view/service, never hand-added
