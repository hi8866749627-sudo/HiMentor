from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from core.models import AcademicCalendar, AcademicModule, College, CoordinatorModuleAccess, Mentor, RoleAssignment, University, YearScope


def create_module(
    name="FY2-CE_Sem-2 - Batch 2026-2030",
    academic_batch="2026-2030",
    year_level="FY",
    variant="FY2-CE",
    semester="Sem-2",
    is_active=True,
):
    return AcademicModule.objects.create(
        name=name,
        academic_batch=academic_batch,
        year_level=year_level,
        variant=variant,
        semester=semester,
        is_active=is_active,
    )


def create_superadmin(username="superadmin1", password="pass12345"):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"is_active": True},
    )
    if created or not user.check_password(password):
        user.set_password(password)
        user.is_active = True
        user.save()
    return user


def create_erp_owner(username="erpowner1", password="pass12345"):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_active=True,
    )
    RoleAssignment.objects.create(
        user=user,
        role=RoleAssignment.ROLE_ERP_OWNER,
    )
    return user


def create_college_head(username="collegehead1", password="pass12345"):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_active=True,
    )
    university, _ = University.objects.get_or_create(name="LJU", defaults={"code": "LJU"})
    college, _ = College.objects.get_or_create(
        university=university,
        name="LJIET",
        defaults={"code": "LJIET"},
    )
    RoleAssignment.objects.create(
        user=user,
        role=RoleAssignment.ROLE_COLLEGE_HEAD,
        college=college,
    )
    return user, college


def create_university_head(username="universityhead1", password="pass12345"):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_active=True,
    )
    university, _ = University.objects.get_or_create(name="LJU", defaults={"code": "LJU"})
    RoleAssignment.objects.create(
        user=user,
        role=RoleAssignment.ROLE_UNIVERSITY_HEAD,
        university=university,
    )
    return user, university


def create_year_head(username="yearhead1", password="pass12345", year_code="FY"):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_active=True,
    )
    university, _ = University.objects.get_or_create(name="LJU", defaults={"code": "LJU"})
    college, _ = College.objects.get_or_create(
        university=university,
        name="LJIET",
        defaults={"code": "LJIET"},
    )
    year_scope, _ = YearScope.objects.get_or_create(
        college=college,
        year_code=year_code,
        defaults={"title": year_code},
    )
    RoleAssignment.objects.create(
        user=user,
        role=RoleAssignment.ROLE_YEAR_HEAD,
        year_scope=year_scope,
    )
    return user, year_scope


def create_coordinator(module, username="coordinator1", password="pass12345"):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_active=True,
    )
    CoordinatorModuleAccess.objects.create(coordinator=user, module=module)
    return user


def login_mentor_session(client: Client, mentor: Mentor, module: AcademicModule, admin_mode=False):
    session = client.session
    session["mentor"] = mentor.name
    session["current_module_id"] = module.id
    session["admin_mode"] = bool(admin_mode)
    session.save()


def create_active_calendar(module, start=None, end=None):
    today = timezone.localdate()
    start = start or (today - timedelta(days=14))
    end = end or (today + timedelta(days=14))
    return AcademicCalendar.objects.create(
        module=module,
        is_active=True,
        t1_start=start,
        t1_end=end,
        t2_start=end + timedelta(days=1),
        t2_end=end + timedelta(days=7),
        t3_start=end + timedelta(days=8),
        t3_end=end + timedelta(days=14),
        t4_start=end + timedelta(days=15),
        t4_end=end + timedelta(days=21),
    )
