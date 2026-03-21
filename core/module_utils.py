from datetime import time
from django.utils import timezone
from django.db.models import Q
from .models import AcademicModule, Mentor, MentorModuleAccess, MentorAdminAccess, MentorModuleOptOut, MentorHomeSetting
from .access import (
    is_college_head,
    is_erp_owner,
    is_scoped_admin_user,
    is_university_head,
    is_year_head,
    modules_for_user,
)
from .exam_access import has_exam_section_access


LEGACY_ADMIN_USERNAMES = {"superadmin1", "superadmin2"}
SUPERADMIN_USERNAMES = LEGACY_ADMIN_USERNAMES


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


def is_legacy_superadmin_user(user):
    return bool(user and user.is_authenticated and user.username.lower() in LEGACY_ADMIN_USERNAMES)


def is_legacy_admin_user(user):
    return is_legacy_superadmin_user(user)


def is_global_staff_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_legacy_admin_user(user)
            or is_erp_owner(user)
            or is_year_head(user)
        )
    )


def is_superadmin_user(user):
    # Backward-compatible alias for older call sites.
    return is_global_staff_admin(user)


def has_staff_panel_access(user):
    return bool(user and user.is_authenticated and (is_global_staff_admin(user) or is_scoped_admin_user(user)))


def has_superadmin_panel_access(user):
    # Backward-compatible alias for older call sites.
    return has_staff_panel_access(user)


def get_staff_home_url(user):
    if not user or not user.is_authenticated:
        return "/"
    if is_erp_owner(user) or is_year_head(user) or is_legacy_admin_user(user):
        return "/home/"
    if is_university_head(user):
        return "/university-home/"
    if is_college_head(user):
        return "/college-home/"
    if has_exam_section_access(user):
        return "/exam-section/"
    return "/reports/" if not has_staff_panel_access(user) else "/home/"


def get_staff_role_name(user):
    if not user or not user.is_authenticated:
        return ""
    if is_erp_owner(user):
        return "ERP Owner"
    if is_university_head(user):
        return "University Head"
    if is_college_head(user):
        return "College Head"
    if is_year_head(user):
        return "Year Head"
    if is_legacy_admin_user(user):
        return "Admin"
    if is_scoped_admin_user(user):
        return "Admin"
    if has_exam_section_access(user):
        return "Exam Faculty"
    return "Coordinator"


def allowed_modules_for_user(request):
    if request.session.get("mentor"):
        mentor_key = (request.session.get("mentor") or "").strip()
        if not mentor_key:
            return AcademicModule.objects.none()
        mentor_obj = None
        try:
            from .utils import resolve_mentor_identity

            mentor_obj = resolve_mentor_identity(mentor_key)
        except Exception:
            mentor_obj = None

        admin_mode = bool(request.session.get("admin_mode"))
        if mentor_obj and mentor_obj.is_admin and admin_mode:
            return (
                AcademicModule.objects.filter(
                    is_active=True,
                    mentor_admins__mentor=mentor_obj,
                )
                .distinct()
                .order_by("-id")
            )

        mentor_names = {mentor_key}
        if mentor_obj:
            if (mentor_obj.name or "").strip():
                mentor_names.add(mentor_obj.name.strip())
            if (mentor_obj.full_name or "").strip():
                mentor_names.add(mentor_obj.full_name.strip())
        else:
            # Try to map login name to any mentor record even if no mentees
            direct = Mentor.objects.filter(name__iexact=mentor_key).first()
            full = Mentor.objects.filter(full_name__iexact=mentor_key).first()
            for m in [direct, full]:
                if not m:
                    continue
                if (m.name or "").strip():
                    mentor_names.add(m.name.strip())
                if (m.full_name or "").strip():
                    mentor_names.add(m.full_name.strip())
            # Compact match (ignores symbols/spaces)
            compact_key = "".join(ch for ch in mentor_key.upper() if ch.isalnum())
            if compact_key:
                for m in Mentor.objects.all():
                    name_compact = "".join(ch for ch in (m.name or "").upper() if ch.isalnum())
                    full_compact = "".join(ch for ch in (m.full_name or "").upper() if ch.isalnum())
                    if compact_key and (compact_key == name_compact or compact_key == full_compact):
                        if (m.name or "").strip():
                            mentor_names.add(m.name.strip())
                        if (m.full_name or "").strip():
                            mentor_names.add(m.full_name.strip())

        faculty_q = Q()
        for name in mentor_names:
            faculty_q |= Q(timetable_entries__faculty__iexact=name)
            faculty_q |= Q(lecture_adjustments__original_faculty__iexact=name)
        if mentor_obj:
            faculty_q |= Q(students__mentor=mentor_obj)
            faculty_q |= Q(lecture_adjustments__proxy_faculty=mentor_obj)

        modules = (
            AcademicModule.objects.filter(is_active=True)
            .filter(faculty_q)
            .distinct()
            .order_by("-id")
        )
        if mentor_obj:
            modules = modules.exclude(mentor_optouts__mentor=mentor_obj)
        return modules

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return AcademicModule.objects.none()

    if is_legacy_admin_user(user):
        return AcademicModule.objects.filter(is_active=True).order_by("-id")

    if has_staff_panel_access(user):
        return modules_for_user(user).filter(is_active=True).order_by("-id")

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

    if not module and getattr(request, "user", None) and has_staff_panel_access(request.user):
        module = get_or_create_default_module()

    if module:
        request.session["current_module_id"] = module.id
    return module


def get_mentor_home_url(module):
    default_before = MentorHomeSetting.PAGE_SCHEDULE
    default_after = MentorHomeSetting.PAGE_DAILY_CALLS
    default_manual = MentorHomeSetting.PAGE_SCHEDULE
    default_cutoff = time(12, 35)

    setting = MentorHomeSetting.objects.filter(module=module).first()
    if not setting:
        now_t = timezone.localtime().time()
        return default_before if now_t < default_cutoff else default_after

    if setting.mode == MentorHomeSetting.MODE_MANUAL:
        return setting.manual_page or default_manual

    cutoff = setting.cutoff_time or default_cutoff
    now_t = timezone.localtime().time()
    before_page = setting.before_page or default_before
    after_page = setting.after_page or default_after
    return before_page if now_t < cutoff else after_page
