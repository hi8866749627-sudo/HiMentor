from .module_utils import allowed_modules_for_user, get_current_module, is_superadmin_user
from .utils import resolve_mentor_identity


def module_context(request):
    home_url = "/"
    if request.session.get("mentor"):
        home_url = "/mentor-dashboard/"
    elif request.user.is_authenticated:
        home_url = "/home/" if is_superadmin_user(request.user) else "/reports/"

    if not request.user.is_authenticated and not request.session.get("mentor"):
        return {
            "module_list": [],
            "current_module": None,
            "can_manage_modules": False,
            "home_url": home_url,
            "mentor_display_name": "",
            "login_role_name": "",
        }

    current = get_current_module(request)
    modules = list(allowed_modules_for_user(request))
    current_id = current.id if current else None
    for m in modules:
        m.is_current = (m.id == current_id)

    mentor_display_name = ""
    if request.session.get("mentor"):
        mentor_obj = resolve_mentor_identity(request.session.get("mentor"))
        if mentor_obj:
            mentor_display_name = mentor_obj.full_name or mentor_obj.name
        else:
            mentor_display_name = request.session.get("mentor")
    login_role_name = ""
    if request.user.is_authenticated and not request.session.get("mentor"):
        login_role_name = "Superadmin" if is_superadmin_user(request.user) else "Coordinator"
    return {
        "module_list": modules,
        "current_module": current,
        "can_manage_modules": bool(request.user.is_authenticated and not request.session.get("mentor") and is_superadmin_user(request.user)),
        "home_url": home_url,
        "mentor_display_name": mentor_display_name,
        "login_role_name": login_role_name,
    }
