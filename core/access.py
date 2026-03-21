from django.db.models import Q

from .models import AcademicModule, College, CoordinatorModuleAccess, RoleAssignment, University, YearScope


def _active_assignments(user, role=None):
    if not user or not user.is_authenticated:
        return RoleAssignment.objects.none()
    qs = RoleAssignment.objects.filter(user=user, is_active=True)
    if role:
        qs = qs.filter(role=role)
    return qs


def has_role(user, role):
    return _active_assignments(user, role=role).exists()


def is_erp_owner(user):
    return has_role(user, RoleAssignment.ROLE_ERP_OWNER)


def is_university_head(user):
    return has_role(user, RoleAssignment.ROLE_UNIVERSITY_HEAD)


def is_college_head(user):
    return has_role(user, RoleAssignment.ROLE_COLLEGE_HEAD)


def is_year_head(user):
    return has_role(user, RoleAssignment.ROLE_YEAR_HEAD)


def is_scoped_admin_user(user):
    return any(
        [
            is_erp_owner(user),
            is_university_head(user),
            is_college_head(user),
            is_year_head(user),
        ]
    )


def universities_for_user(user):
    if not user or not user.is_authenticated:
        return University.objects.none()
    if is_erp_owner(user):
        return University.objects.filter(is_active=True)
    return University.objects.filter(
        Q(role_assignments__user=user, role_assignments__role=RoleAssignment.ROLE_UNIVERSITY_HEAD, role_assignments__is_active=True)
        | Q(colleges__role_assignments__user=user, colleges__role_assignments__role=RoleAssignment.ROLE_COLLEGE_HEAD, colleges__role_assignments__is_active=True)
        | Q(colleges__year_scopes__role_assignments__user=user, colleges__year_scopes__role_assignments__role=RoleAssignment.ROLE_YEAR_HEAD, colleges__year_scopes__role_assignments__is_active=True)
        | Q(colleges__year_scopes__modules__role_assignments__user=user, colleges__year_scopes__modules__role_assignments__role=RoleAssignment.ROLE_COORDINATOR, colleges__year_scopes__modules__role_assignments__is_active=True)
        | Q(colleges__year_scopes__modules__coordinator_accesses__coordinator=user),
        is_active=True,
    ).distinct()


def colleges_for_user(user):
    if not user or not user.is_authenticated:
        return College.objects.none()
    if is_erp_owner(user):
        return College.objects.filter(is_active=True)
    return College.objects.filter(
        Q(role_assignments__user=user, role_assignments__role=RoleAssignment.ROLE_COLLEGE_HEAD, role_assignments__is_active=True)
        | Q(university__role_assignments__user=user, university__role_assignments__role=RoleAssignment.ROLE_UNIVERSITY_HEAD, university__role_assignments__is_active=True)
        | Q(year_scopes__role_assignments__user=user, year_scopes__role_assignments__role=RoleAssignment.ROLE_YEAR_HEAD, year_scopes__role_assignments__is_active=True)
        | Q(year_scopes__modules__role_assignments__user=user, year_scopes__modules__role_assignments__role=RoleAssignment.ROLE_COORDINATOR, year_scopes__modules__role_assignments__is_active=True)
        | Q(year_scopes__modules__coordinator_accesses__coordinator=user),
        is_active=True,
        university__is_active=True,
    ).distinct()


def year_scopes_for_user(user):
    if not user or not user.is_authenticated:
        return YearScope.objects.none()
    if is_erp_owner(user):
        return YearScope.objects.filter(is_active=True, college__is_active=True, college__university__is_active=True)
    return YearScope.objects.filter(
        Q(role_assignments__user=user, role_assignments__role=RoleAssignment.ROLE_YEAR_HEAD, role_assignments__is_active=True)
        | Q(college__role_assignments__user=user, college__role_assignments__role=RoleAssignment.ROLE_COLLEGE_HEAD, college__role_assignments__is_active=True)
        | Q(college__university__role_assignments__user=user, college__university__role_assignments__role=RoleAssignment.ROLE_UNIVERSITY_HEAD, college__university__role_assignments__is_active=True)
        | Q(modules__role_assignments__user=user, modules__role_assignments__role=RoleAssignment.ROLE_COORDINATOR, modules__role_assignments__is_active=True)
        | Q(modules__coordinator_accesses__coordinator=user),
        is_active=True,
        college__is_active=True,
        college__university__is_active=True,
    ).distinct()


def modules_for_user(user):
    if not user or not user.is_authenticated:
        return AcademicModule.objects.none()
    if is_erp_owner(user):
        return AcademicModule.objects.filter(is_active=True)
    return AcademicModule.objects.filter(
        Q(role_assignments__user=user, role_assignments__role=RoleAssignment.ROLE_COORDINATOR, role_assignments__is_active=True)
        | Q(year_scope__role_assignments__user=user, year_scope__role_assignments__role=RoleAssignment.ROLE_YEAR_HEAD, year_scope__role_assignments__is_active=True)
        | Q(year_scope__college__role_assignments__user=user, year_scope__college__role_assignments__role=RoleAssignment.ROLE_COLLEGE_HEAD, year_scope__college__role_assignments__is_active=True)
        | Q(year_scope__college__university__role_assignments__user=user, year_scope__college__university__role_assignments__role=RoleAssignment.ROLE_UNIVERSITY_HEAD, year_scope__college__university__role_assignments__is_active=True)
        | Q(coordinator_accesses__coordinator=user),
        is_active=True,
    ).distinct()


def can_manage_university(user, university):
    if not university:
        return False
    if is_erp_owner(user):
        return True
    return _active_assignments(user, RoleAssignment.ROLE_UNIVERSITY_HEAD).filter(university=university).exists()


def can_manage_college(user, college):
    if not college:
        return False
    if is_erp_owner(user) or can_manage_university(user, college.university):
        return True
    return _active_assignments(user, RoleAssignment.ROLE_COLLEGE_HEAD).filter(college=college).exists()


def can_manage_year_scope(user, year_scope):
    if not year_scope:
        return False
    if is_erp_owner(user) or can_manage_college(user, year_scope.college):
        return True
    return _active_assignments(user, RoleAssignment.ROLE_YEAR_HEAD).filter(year_scope=year_scope).exists()


def can_manage_module(user, module):
    if not module:
        return False
    if is_erp_owner(user):
        return True
    if module.year_scope_id and can_manage_year_scope(user, module.year_scope):
        return True
    if _active_assignments(user, RoleAssignment.ROLE_COORDINATOR).filter(module=module).exists():
        return True
    return CoordinatorModuleAccess.objects.filter(coordinator=user, module=module).exists()
