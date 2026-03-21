from django.db import migrations


SUPERADMIN_USERNAMES = {"superadmin1", "superadmin2"}


def seed_local_hierarchy(apps, schema_editor):
    AcademicModule = apps.get_model("core", "AcademicModule")
    College = apps.get_model("core", "College")
    CoordinatorModuleAccess = apps.get_model("core", "CoordinatorModuleAccess")
    RoleAssignment = apps.get_model("core", "RoleAssignment")
    University = apps.get_model("core", "University")
    YearScope = apps.get_model("core", "YearScope")
    User = apps.get_model("auth", "User")

    university, _ = University.objects.get_or_create(
        name="LJU",
        defaults={"code": "LJU", "is_active": True},
    )
    college, _ = College.objects.get_or_create(
        university=university,
        name="LJIET",
        defaults={"code": "LJIET", "is_active": True},
    )
    year_scope, _ = YearScope.objects.get_or_create(
        college=college,
        year_code="FY",
        defaults={"title": "First Year", "is_active": True},
    )

    AcademicModule.objects.filter(year_scope__isnull=True).update(year_scope=year_scope)

    for coordinator_access in CoordinatorModuleAccess.objects.select_related("coordinator", "module"):
        RoleAssignment.objects.get_or_create(
            user_id=coordinator_access.coordinator_id,
            role="coordinator",
            module_id=coordinator_access.module_id,
            defaults={"is_active": True},
        )

    for user in User.objects.filter(username__in=SUPERADMIN_USERNAMES):
        RoleAssignment.objects.get_or_create(
            user_id=user.id,
            role="year_head",
            year_scope_id=year_scope.id,
            defaults={"is_active": True},
        )


def unseed_local_hierarchy(apps, schema_editor):
    College = apps.get_model("core", "College")
    RoleAssignment = apps.get_model("core", "RoleAssignment")
    University = apps.get_model("core", "University")
    YearScope = apps.get_model("core", "YearScope")

    year_scope = YearScope.objects.filter(college__name="LJIET", year_code="FY").first()
    if year_scope:
        RoleAssignment.objects.filter(role="year_head", year_scope=year_scope).delete()

    lju = University.objects.filter(name="LJU").first()
    if not lju:
        return

    lji_et = College.objects.filter(university=lju, name="LJIET").first()
    if not lji_et:
        return

    fy = YearScope.objects.filter(college=lji_et, year_code="FY").first()
    if fy and not fy.modules.exists():
        fy.delete()
    if lji_et and not lji_et.year_scopes.exists():
        lji_et.delete()
    if lju and not lju.colleges.exists():
        lju.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_university_college_yearscope_roleassignment_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_local_hierarchy, unseed_local_hierarchy),
    ]
