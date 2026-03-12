from django.db.models import Q
from .models import AcademicModule


SUPERADMIN_USERNAMES = {"superadmin1", "superadmin2"}


DEFAULT_MODULE_NAME = "FY2-CE_Sem-1 - Batch 2026-29"


def get_or_create_default_module():
    module, _ = AcademicModule.objects.get_or_create(
        name=DEFAULT_MODULE_NAME,
        defaults={
            "academic_batch": "2026-29",
            "year_level": "FY",
            "variant": "FY2-CE",
            "semester": "Sem-1",
            "is_active": True,
        },
    )
    return module


def is_superadmin_user(user):
    return bool(user and user.is_authenticated and user.username.lower() in SUPERADMIN_USERNAMES)


def allowed_modules_for_user(request):
    if request.session.get("mentor"):
        mentor_code = (request.session.get("mentor") or "").strip()
        if not mentor_code:
            return AcademicModule.objects.none()
        return (
            AcademicModule.objects.filter(
                Q(students__mentor__name__iexact=mentor_code)
                | Q(timetable_entries__faculty__iexact=mentor_code)
            )
            .distinct()
            .order_by("-id")
        )

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return AcademicModule.objects.none()

    if is_superadmin_user(user):
        return AcademicModule.objects.filter(is_active=True).order_by("-id")

    return (
        AcademicModule.objects.filter(is_active=True, coordinator_accesses__coordinator=user)
        .distinct()
        .order_by("-id")
    )


def get_current_module(request):
    allowed_qs = allowed_modules_for_user(request)
    module_id = request.session.get("current_module_id")
    module = None

    if module_id:
        module = allowed_qs.filter(id=module_id).first()

    if not module:
        module = allowed_qs.first()

    if not module and getattr(request, "user", None) and is_superadmin_user(request.user):
        module = get_or_create_default_module()

    if module:
        request.session["current_module_id"] = module.id
    return module
