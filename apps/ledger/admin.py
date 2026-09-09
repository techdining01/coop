from django.contrib import admin

from .models import CooperativeSettings, LedgerEntry, LedgerExport


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("member", "entry_type", "status", "amount", "balance_after", "source", "created_at")
    list_filter = ("entry_type", "status", "source")
    search_fields = ("member__username", "reference")
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]  # immutable — admin can view, never edit

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CooperativeSettings)
class CooperativeSettingsAdmin(admin.ModelAdmin):
    list_display = ("required_share_capital_amount",)

    def has_add_permission(self, request):
        # singleton — only allow adding if the row doesn't exist yet
        return not CooperativeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerExport)
class LedgerExportAdmin(admin.ModelAdmin):
    list_display = ("period_start", "period_end", "downloaded_by", "downloaded_at", "deleted_at")
