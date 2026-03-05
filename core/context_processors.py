from .module_utils import allowed_modules_for_user, get_current_module, is_superadmin_user


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
        }

    current = get_current_module(request)
    modules = list(allowed_modules_for_user(request))
    current_id = current.id if current else None
    for m in modules:
        m.is_current = (m.id == current_id)
    return {
        "module_list": modules,
        "current_module": current,
        "can_manage_modules": bool(request.user.is_authenticated and not request.session.get("mentor") and is_superadmin_user(request.user)),
        "home_url": home_url,
    }

