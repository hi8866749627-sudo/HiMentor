import os
import time

from django.conf import settings
from django.db import connection

from .module_utils import (
    allowed_modules_for_user,
    get_current_module,
    get_mentor_home_url,
    get_staff_home_url,
    get_staff_role_name,
    has_staff_panel_access,
    is_legacy_admin_user,
)
from .access import is_college_head, is_erp_owner, is_university_head
from .exam_access import has_exam_section_access
from .models import MentorAdminAccess
from .utils import resolve_mentor_identity

_SYSTEM_INFO_CACHE = {"ts": 0.0, "value": None}


def _format_bytes(size_bytes):
    if size_bytes is None:
        return None
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _resolve_git_commit():
    for key in [
        "RENDER_GIT_COMMIT",
        "RENDER_GIT_COMMIT_SHA",
        "GIT_COMMIT",
        "COMMIT_SHA",
        "SOURCE_VERSION",
    ]:
        val = os.environ.get(key)
        if val:
            return val.strip()

    head_path = os.path.join(settings.BASE_DIR, ".git", "HEAD")
    if not os.path.exists(head_path):
        return None
    try:
        with open(head_path, "r", encoding="utf-8") as handle:
            ref = handle.read().strip()
        if ref.startswith("ref:"):
            ref_path = ref.split(" ", 1)[1].strip()
            ref_file = os.path.join(settings.BASE_DIR, ".git", ref_path)
            if os.path.exists(ref_file):
                with open(ref_file, "r", encoding="utf-8") as handle:
                    return handle.read().strip()
        return ref
    except Exception:
        return None


def _fetch_db_size():
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "sqlite" in engine:
        db_path = settings.DATABASES.get("default", {}).get("NAME")
        if db_path and os.path.exists(db_path):
            return os.path.getsize(db_path)
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute("select pg_database_size(current_database())")
            row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _system_footer_info():
    now = time.time()
    if _SYSTEM_INFO_CACHE["value"] and (now - _SYSTEM_INFO_CACHE["ts"] < 120):
        return _SYSTEM_INFO_CACHE["value"]

    size_bytes = _fetch_db_size()
    commit_full = _resolve_git_commit()
    info = {
        "db_size_bytes": size_bytes,
        "db_size_pretty": _format_bytes(size_bytes),
        "commit_full": commit_full,
        "commit_short": (commit_full[:7] if commit_full else None),
    }
    _SYSTEM_INFO_CACHE["ts"] = now
    _SYSTEM_INFO_CACHE["value"] = info
    return info


def module_context(request):
    sidebar_role_class = "role-public"
    home_url = "/"
    if request.session.get("mentor"):
        home_url = "/mentor-dashboard/"
        sidebar_role_class = "role-mentor"
    elif request.user.is_authenticated:
        home_url = get_staff_home_url(request.user)
        if is_erp_owner(request.user):
            sidebar_role_class = "role-erp-owner"
        elif is_university_head(request.user):
            sidebar_role_class = "role-university-head"
        elif is_college_head(request.user):
            sidebar_role_class = "role-college-head"
        elif get_staff_role_name(request.user) == "Coordinator":
            sidebar_role_class = "role-coordinator"
        else:
            sidebar_role_class = "role-year-head"

    if not request.user.is_authenticated and not request.session.get("mentor"):
        return {
            "module_list": [],
            "current_module": None,
            "can_manage_modules": False,
            "home_url": home_url,
            "mentor_display_name": "",
            "login_role_name": "",
            "sidebar_role_class": sidebar_role_class,
        }

    current = get_current_module(request)
    modules = list(allowed_modules_for_user(request))
    current_id = current.id if current else None
    for m in modules:
        m.is_current = (m.id == current_id)
    current_scope = None
    if current and getattr(current, "year_scope_id", None) and getattr(current.year_scope, "college_id", None):
        college = current.year_scope.college
        university = getattr(college, "university", None)
        current_scope = {
            "university_name": university.name if university else "",
            "college_name": college.name,
            "year_code": current.year_scope.year_code,
            "module_name": current.name,
        }

    mentor_display_name = ""
    mentor_is_admin = False
    admin_mode = False
    if request.session.get("mentor"):
        mentor_obj = resolve_mentor_identity(request.session.get("mentor"))
        if mentor_obj:
            mentor_display_name = mentor_obj.full_name or mentor_obj.name
            mentor_is_admin = bool(
                mentor_obj.is_admin and MentorAdminAccess.objects.filter(mentor=mentor_obj).exists()
            )
        else:
            mentor_display_name = request.session.get("mentor")
        admin_mode = bool(request.session.get("admin_mode")) if mentor_is_admin else False
        if admin_mode:
            home_url = "/reports/"
        else:
            if current:
                home_url = get_mentor_home_url(current)
    login_role_name = ""
    if request.user.is_authenticated and not request.session.get("mentor"):
        login_role_name = get_staff_role_name(request.user)
    context = {
        "module_list": modules,
        "current_module": current,
        "can_manage_modules": bool(
            request.user.is_authenticated and not request.session.get("mentor") and has_staff_panel_access(request.user)
        ),
        "home_url": home_url,
        "mentor_display_name": mentor_display_name,
        "mentor_is_admin": mentor_is_admin,
        "admin_mode": admin_mode,
        "login_role_name": login_role_name,
        "current_scope": current_scope,
        "sidebar_role_class": sidebar_role_class,
    }
    if request.user.is_authenticated and not request.session.get("mentor"):
        role_name = get_staff_role_name(request.user)
        context["show_org_setup_nav_link"] = bool(has_staff_panel_access(request.user))
        context["show_university_home_link"] = bool(is_erp_owner(request.user) or is_university_head(request.user))
        context["show_college_home_link"] = bool(
            is_erp_owner(request.user) or is_university_head(request.user) or is_college_head(request.user)
        )
        context["show_exam_section_link"] = bool(has_exam_section_access(request.user) or has_staff_panel_access(request.user))
        context["is_owner_role"] = bool(is_erp_owner(request.user))
        context["is_university_head_role"] = bool(is_university_head(request.user))
        context["is_college_head_role"] = bool(is_college_head(request.user))
        context["is_year_head_role"] = bool(sidebar_role_class == "role-year-head")
        context["is_legacy_admin_role"] = bool(is_legacy_admin_user(request.user))
        context["is_coordinator_role"] = bool(role_name == "Coordinator")
        context["is_exam_only_role"] = bool(role_name == "Exam Faculty")
        context["system_footer_info"] = _system_footer_info()
    return context
