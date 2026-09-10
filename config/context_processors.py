from django.conf import settings


def cooperative_info(request):
    return {
        "COOPERATIVE_SHORT_NAME": getattr(settings, "COOPERATIVE_SHORT_NAME", "AL-HALAL"),
    }
