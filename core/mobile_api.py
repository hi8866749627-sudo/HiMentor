import json
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.core import signing
from django.db.models import Count
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .module_utils import is_superadmin_user
from .attendance_utils import import_attendance
from .result_utils import import_compiled_bulk_all, import_compiled_result_sheet, import_result_sheet
from .models import (
    AcademicModule,
    Attendance,
    CallRecord,
    CoordinatorModuleAccess,
    Mentor,
    MentorAuthToken,
    MentorPassword,
    OtherCallRecord,
    ResultCallRecord,
    ResultUpload,
    Subject,
    StudentResult,
    Student,
)
from .utils import import_students_from_excel
from .utils import resolve_mentor_identity


TOKEN_TTL_HOURS = 24 * 7
STAFF_TOKEN_TTL_SECONDS = 24 * 60 * 60
STAFF_TOKEN_SALT = "easymentor.mobile.staff"


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _token_from_request(request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _auth_mentor(request):
    raw = _token_from_request(request)
    if not raw:
        return None
    token_obj = (
        MentorAuthToken.objects.select_related("mentor")
        .filter(token=raw, is_active=True)
        .first()
    )
    if not token_obj:
        return None
    if token_obj.expires_at <= timezone.now():
        token_obj.is_active = False
        token_obj.save(update_fields=["is_active"])
        return None
    return token_obj.mentor


def _issue_staff_token(user, role):
    payload = {
        "uid": user.id,
        "role": role,
        "exp": int(timezone.now().timestamp()) + STAFF_TOKEN_TTL_SECONDS,
    }
    return signing.dumps(payload, salt=STAFF_TOKEN_SALT)


def _decode_staff_token(raw):
    if not raw:
        return None
    try:
        payload = signing.loads(raw, salt=STAFF_TOKEN_SALT)
    except Exception:
        return None
    exp = int(payload.get("exp") or 0)
    if exp <= int(timezone.now().timestamp()):
        return None
    return payload


def _auth_staff(request):
    payload = _decode_staff_token(_token_from_request(request))
    if not payload:
        return None, None
    from django.contrib.auth.models import User

    user = User.objects.filter(id=payload.get("uid"), is_active=True).first()
    if not user:
        return None, None
    role = payload.get("role")
    if role not in {"superadmin", "coordinator"}:
        return None, None
    return user, role


def _staff_modules(user, role):
    if role == "superadmin":
        return AcademicModule.objects.filter(is_active=True).order_by("-id")
    return (
        AcademicModule.objects.filter(is_active=True, coordinator_accesses__coordinator=user)
        .distinct()
        .order_by("-id")
    )


def _resolve_staff_module(request, user, role):
    modules = _staff_modules(user, role)
    if not modules.exists():
        return None
    module_id = _module_id_from_request(request)
    if module_id:
        selected = modules.filter(id=module_id).first()
        if selected:
            return selected
    return modules.first()


def _mentor_modules(mentor):
    return (
        AcademicModule.objects.filter(is_active=True, students__mentor=mentor)
        .distinct()
        .order_by("-id")
    )


def _module_id_from_request(request):
    qv = request.GET.get("module_id")
    if qv:
        return qv
    body = _json_body(request) if request.method in {"POST", "PUT", "PATCH"} else {}
    bv = body.get("module_id")
    if bv:
        return str(bv)
    hv = request.headers.get("X-Module-Id", "")
    return hv.strip() or None


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_login(request):
    body = _json_body(request)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = authenticate(username=username, password=password)
    if not user or not user.is_active:
        return JsonResponse({"ok": False, "msg": "Invalid credentials"}, status=401)

    if is_superadmin_user(user):
        role = "superadmin"
    elif CoordinatorModuleAccess.objects.filter(coordinator=user).exists():
        role = "coordinator"
    else:
        return JsonResponse({"ok": False, "msg": "Access denied"}, status=403)

    token = _issue_staff_token(user, role)
    return JsonResponse(
        {
            "ok": True,
            "token": token,
            "role": role,
            "username": user.username,
        }
    )


@require_http_methods(["GET"])
def api_mobile_staff_modules(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    modules = list(_staff_modules(user, role))
    selected = _resolve_staff_module(request, user, role)
    return JsonResponse(
        {
            "ok": True,
            "role": role,
            "modules": [
                {
                    "module_id": m.id,
                    "name": m.name,
                    "batch": m.academic_batch,
                    "year_level": m.year_level,
                    "variant": m.variant,
                    "semester": m.semester,
                }
                for m in modules
            ],
            "selected_module_id": selected.id if selected else None,
        }
    )


@require_http_methods(["GET"])
def api_mobile_staff_students(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "students": [], "module_id": None})

    try:
        page = max(int(request.GET.get("page", "1")), 1)
    except Exception:
        page = 1
    try:
        page_size = int(request.GET.get("page_size", "50"))
    except Exception:
        page_size = 50
    page_size = max(10, min(page_size, 200))

    q = (request.GET.get("q") or "").strip()
    qs = Student.objects.select_related("mentor").filter(module=module)
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(enrollment__icontains=q)
            | Q(batch__icontains=q)
            | Q(division__icontains=q)
            | Q(mentor__name__icontains=q)
            | Q(student_mobile__icontains=q)
            | Q(father_mobile__icontains=q)
        )

    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    rows = qs.order_by("roll_no", "name")[start:end]
    has_more = end < total

    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
            "students": [
                {
                    "roll_no": s.roll_no,
                    "branch": s.batch,
                    "division": s.division,
                    "enrollment": s.enrollment,
                    "name": s.name,
                    "mentor": s.mentor.name if s.mentor_id else "",
                    "student_mobile": s.student_mobile,
                    "father_mobile": s.father_mobile,
                }
                for s in rows
            ],
        }
    )


@require_http_methods(["GET"])
def api_mobile_staff_weeks(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "weeks": [], "latest_week": None, "module_id": None})

    weeks = sorted(
        Attendance.objects.filter(student__module=module)
        .values_list("week_no", flat=True)
        .distinct()
    )
    latest = weeks[-1] if weeks else None
    return JsonResponse({"ok": True, "weeks": weeks, "latest_week": latest, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_staff_attendance(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "rows": [], "week": None, "module_id": None})

    week = request.GET.get("week")
    if not week:
        return JsonResponse({"ok": False, "msg": "week is required"}, status=400)
    try:
        week_no = int(week)
    except Exception:
        return JsonResponse({"ok": False, "msg": "Invalid week"}, status=400)

    att_map = {
        a.student_id: a
        for a in Attendance.objects.filter(student__module=module, week_no=week_no).select_related("student")
    }
    call_map = {
        c.student_id: c
        for c in CallRecord.objects.filter(student__module=module, week_no=week_no).select_related("student")
    }

    rows = []
    students = Student.objects.select_related("mentor").filter(module=module).order_by("roll_no", "name")
    for s in students:
        a = att_map.get(s.id)
        c = call_map.get(s.id)
        rows.append(
            {
                "roll_no": s.roll_no,
                "enrollment": s.enrollment,
                "name": s.name,
                "mentor": s.mentor.name if s.mentor_id else "",
                "week_percentage": a.week_percentage if a else None,
                "overall_percentage": a.overall_percentage if a else None,
                "call_required": bool(a.call_required) if a else False,
                "call_status": (c.final_status if c else None),
            }
        )
    return JsonResponse({"ok": True, "module_id": module.id, "week": week_no, "rows": rows})


def _staff_result_thresholds(test_name):
    test = (test_name or "").upper()
    if test == "T1":
        return 9, 9
    if test == "T2":
        return 9, 18
    if test == "T3":
        return 9, 27
    if test == "T4":
        return 18, 35
    return 35, 35


def _staff_process_result_upload(module, username, test_name, subject_id, upload_mode, bulk_confirm, file_obj):
    is_all_tests = test_name == "ALL_EXAMS"
    is_all_subjects = str(subject_id).upper() == "ALL"

    if is_all_tests and is_all_subjects:
        summary = import_compiled_bulk_all(
            file_obj,
            username,
            module=module,
            progress_cb=None,
            cancel_cb=None,
        )
        return {
            "ok": True,
            "msg": (
                f"Bulk replace completed. Created uploads: {summary['uploads_created']}. "
                f"Rows matched: {summary['rows_matched']}. Failed calls: {summary['rows_failed']}."
            ),
            "test_name": "ALL_EXAMS",
            "subject_name": "ALL",
            "upload_id": "",
            "mentor_stats": [],
            "total_calls": summary["rows_failed"],
            "upload_mode": upload_mode,
            "found_subjects": summary.get("found_subjects", []),
            "used_subject": "ALL",
        }

    subject = Subject.objects.filter(id=subject_id, module=module, is_active=True).first()
    if not subject:
        raise Exception("Invalid subject")
    if subject.result_format == Subject.FORMAT_T4_ONLY and test_name != "T4":
        raise Exception("This subject is configured as Only T4. Please upload in T4.")

    upload, _ = ResultUpload.objects.update_or_create(
        module=module,
        test_name=test_name,
        subject=subject,
        defaults={"uploaded_by": username},
    )

    if upload_mode == "compiled":
        summary = import_compiled_result_sheet(file_obj, upload, progress_cb=None, cancel_cb=None)
    else:
        summary = import_result_sheet(file_obj, upload, progress_cb=None, cancel_cb=None)

    mentor_stats = list(
        ResultCallRecord.objects.filter(upload=upload)
        .values("student__mentor__name")
        .annotate(total=Count("id"))
        .order_by("student__mentor__name")
    )
    total_calls = sum(m["total"] for m in mentor_stats)
    return {
        "ok": True,
        "msg": (
            f"Result uploaded: {upload.test_name} - {upload.subject.name}. "
            f"Rows total: {summary['rows_total']}, matched: {summary['rows_matched']}, failed: {summary['rows_failed']}."
        ),
        "test_name": upload.test_name,
        "subject_name": upload.subject.name,
        "upload_id": upload.id,
        "mentor_stats": mentor_stats,
        "total_calls": total_calls,
        "upload_mode": upload_mode,
        "found_subjects": summary.get("found_subjects", []),
        "used_subject": summary.get("used_subject", upload.subject.name),
    }


@require_http_methods(["GET"])
def api_mobile_staff_result_cycles(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "cycles": [], "latest_upload_id": None, "module_id": None})

    uploads = (
        ResultUpload.objects.filter(module=module)
        .select_related("subject")
        .order_by("-uploaded_at")
    )
    data = [
        {
            "upload_id": u.id,
            "test_name": u.test_name,
            "subject_name": u.subject.name,
            "uploaded_at": u.uploaded_at.isoformat(),
            "rows_total": u.rows_total,
            "rows_matched": u.rows_matched,
            "rows_failed": u.rows_failed,
        }
        for u in uploads
    ]
    latest = data[0]["upload_id"] if data else None
    return JsonResponse({"ok": True, "cycles": data, "latest_upload_id": latest, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_staff_result_rows(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "rows": [], "upload": None, "module_id": None})

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        upload = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at").first()
    if not upload:
        return JsonResponse({"ok": True, "rows": [], "upload": None, "module_id": module.id})

    cur_thr, total_thr = _staff_result_thresholds(upload.test_name)
    try:
        page = max(int(request.GET.get("page", "1")), 1)
    except Exception:
        page = 1
    try:
        page_size = int(request.GET.get("page_size", "50"))
    except Exception:
        page_size = 50
    page_size = max(10, min(page_size, 200))
    q = (request.GET.get("q") or "").strip()
    fail_filter = (request.GET.get("fail_filter") or "all").strip().lower()

    rows_qs = StudentResult.objects.filter(upload=upload, student__module=module).select_related("student", "student__mentor")
    if q:
        rows_qs = rows_qs.filter(
            Q(student__name__icontains=q)
            | Q(student__enrollment__icontains=q)
            | Q(student__mentor__name__icontains=q)
        )
    if fail_filter == "current":
        rows_qs = rows_qs.filter(marks_current__lt=cur_thr)
    elif fail_filter == "total":
        rows_qs = rows_qs.filter(marks_total__lt=total_thr)
    elif fail_filter == "either":
        rows_qs = rows_qs.filter(Q(marks_current__lt=cur_thr) | Q(marks_total__lt=total_thr))
    rows_qs = rows_qs.order_by("student__roll_no", "student__name")

    total = rows_qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    rows_qs = rows_qs[start:end]
    has_more = end < total
    rows = []
    for r in rows_qs:
        current_fail = r.marks_current is not None and r.marks_current < cur_thr
        total_fail = r.marks_total is not None and r.marks_total < total_thr
        either_fail = current_fail or total_fail
        rows.append(
            {
                "roll_no": r.student.roll_no,
                "enrollment": r.student.enrollment,
                "name": r.student.name,
                "mentor": (r.student.mentor.name if r.student.mentor_id else ""),
                "marks_current": r.marks_current,
                "marks_t1": r.marks_t1,
                "marks_t2": r.marks_t2,
                "marks_t3": r.marks_t3,
                "marks_t4": r.marks_t4,
                "marks_total": r.marks_total,
                "fail_flag": bool(r.fail_flag),
                "fail_reason": r.fail_reason or "",
                "current_fail": current_fail,
                "total_fail": total_fail,
                "either_fail": either_fail,
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
            "upload": {
                "upload_id": upload.id,
                "test_name": upload.test_name,
                "subject_name": upload.subject.name,
                "uploaded_at": upload.uploaded_at.isoformat(),
                "rows_total": upload.rows_total,
                "rows_matched": upload.rows_matched,
                "rows_failed": upload.rows_failed,
            },
            "rows": rows,
        }
    )


@require_http_methods(["GET"])
def api_mobile_staff_control_summary(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "module_id": None, "attendance": [], "result": []})

    week_raw = request.GET.get("week")
    if week_raw:
        try:
            week_no = int(week_raw)
        except Exception:
            return JsonResponse({"ok": False, "msg": "Invalid week"}, status=400)
    else:
        weeks = sorted(
            Attendance.objects.filter(student__module=module)
            .values_list("week_no", flat=True)
            .distinct()
        )
        week_no = weeks[-1] if weeks else None

    mentors = Mentor.objects.filter(student__module=module).distinct().order_by("name")
    attendance_rows = []
    for m in mentors:
        total_students = Student.objects.filter(module=module, mentor=m).count()
        need_call = (
            Attendance.objects.filter(
                week_no=week_no,
                student__module=module,
                student__mentor=m,
                call_required=True,
            ).count()
            if week_no
            else 0
        )
        received = (
            CallRecord.objects.filter(
                week_no=week_no,
                student__module=module,
                student__mentor=m,
                final_status="received",
            ).count()
            if week_no
            else 0
        )
        not_received = (
            CallRecord.objects.filter(
                week_no=week_no,
                student__module=module,
                student__mentor=m,
                final_status="not_received",
            ).count()
            if week_no
            else 0
        )
        done = received + not_received
        not_done = max(need_call - done, 0)
        percent = round((done / need_call) * 100, 1) if need_call else 0
        attendance_rows.append(
            {
                "mentor": m.name,
                "students": total_students,
                "need_call": need_call,
                "done": done,
                "received": received,
                "not_received": not_received,
                "not_done": not_done,
                "completion_percent": percent,
            }
        )

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        upload = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at").first()

    result_rows = []
    upload_meta = None
    if upload:
        upload_meta = {
            "upload_id": upload.id,
            "test_name": upload.test_name,
            "subject_name": upload.subject.name,
            "uploaded_at": upload.uploaded_at.isoformat(),
        }
        for m in mentors:
            qs = ResultCallRecord.objects.filter(upload=upload, student__module=module, student__mentor=m)
            need_call = qs.count()
            received = qs.filter(final_status="received").count()
            not_received = qs.filter(final_status="not_received").count()
            done = received + not_received
            not_done = max(need_call - done, 0)
            percent = round((done / need_call) * 100, 1) if need_call else 0
            result_rows.append(
                {
                    "mentor": m.name,
                    "need_call": need_call,
                    "done": done,
                    "received": received,
                    "not_received": not_received,
                    "not_done": not_done,
                    "completion_percent": percent,
                }
            )

    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "week": week_no,
            "attendance": attendance_rows,
            "result_upload": upload_meta,
            "result": result_rows,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_upload_students(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": False, "msg": "No module selected"}, status=400)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "msg": "File is required"}, status=400)

    try:
        added, updated, skipped, skipped_rows = import_students_from_excel(f, module)
        return JsonResponse(
            {
                "ok": True,
                "module_id": module.id,
                "added": added,
                "updated": updated,
                "skipped": skipped,
                "skipped_rows": skipped_rows[:50],
                "msg": f"Added: {added} | Updated: {updated} | Skipped: {skipped}",
            }
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "msg": str(exc)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_clear_students(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": False, "msg": "No module selected"}, status=400)

    deleted_count, _ = Student.objects.filter(module=module).delete()
    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "deleted": deleted_count,
            "msg": f"Deleted student master data for module '{module.name}'. Records removed: {deleted_count}",
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_upload_attendance(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": False, "msg": "No module selected"}, status=400)

    try:
        week_no = int(request.POST.get("week") or "0")
    except Exception:
        return JsonResponse({"ok": False, "msg": "Invalid week"}, status=400)
    if week_no <= 0:
        return JsonResponse({"ok": False, "msg": "Week is required"}, status=400)

    rule = (request.POST.get("rule") or "both").strip().lower()
    if rule not in {"both", "week", "overall"}:
        rule = "both"

    weekly_file = request.FILES.get("weekly_file")
    overall_file = request.FILES.get("overall_file")
    if not weekly_file:
        return JsonResponse({"ok": False, "msg": "Weekly file is required"}, status=400)
    if week_no == 1:
        overall_file = None

    try:
        count = import_attendance(weekly_file, overall_file, week_no, module, rule)
        mentor_stats = list(
            CallRecord.objects.filter(week_no=week_no, student__module=module)
            .values("student__mentor__name")
            .annotate(total=Count("id"))
            .order_by("student__mentor__name")
        )
        total_calls = sum(m["total"] for m in mentor_stats)
        return JsonResponse(
            {
                "ok": True,
                "module_id": module.id,
                "week": week_no,
                "created_calls": count,
                "mentor_stats": mentor_stats,
                "total_calls": total_calls,
                "msg": f"{count} students require follow-up calls for Week {week_no}",
            }
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "msg": str(exc)}, status=400)


@require_http_methods(["GET"])
def api_mobile_staff_attendance_report(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "module_id": None, "rows": [], "week": None})

    week_raw = request.GET.get("week")
    if week_raw:
        try:
            week_no = int(week_raw)
        except Exception:
            return JsonResponse({"ok": False, "msg": "Invalid week"}, status=400)
    else:
        weeks = sorted(
            Attendance.objects.filter(student__module=module)
            .values_list("week_no", flat=True)
            .distinct()
        )
        week_no = weeks[-1] if weeks else None
    if not week_no:
        return JsonResponse({"ok": True, "module_id": module.id, "rows": [], "week": None})

    mentors = Mentor.objects.filter(student__module=module).distinct().order_by("name")
    rows = []
    for m in mentors:
        total_students = Student.objects.filter(module=module, mentor=m).count()
        need_call = Attendance.objects.filter(
            week_no=week_no,
            student__module=module,
            student__mentor=m,
            call_required=True,
        ).count()
        received = CallRecord.objects.filter(
            week_no=week_no,
            student__module=module,
            student__mentor=m,
            final_status="received",
        ).count()
        not_received = CallRecord.objects.filter(
            week_no=week_no,
            student__module=module,
            student__mentor=m,
            final_status="not_received",
        ).count()
        done = received + not_received
        not_done = max(need_call - done, 0)
        msg_sent = CallRecord.objects.filter(
            week_no=week_no,
            student__module=module,
            student__mentor=m,
            message_sent=True,
        ).count()
        percent = round((done / need_call) * 100, 1) if need_call else 0
        rows.append(
            {
                "mentor": m.name,
                "students": total_students,
                "need_call": need_call,
                "done": done,
                "received": received,
                "not_received": not_received,
                "not_done": not_done,
                "msg_sent": msg_sent,
                "completion_percent": percent,
            }
        )
    return JsonResponse({"ok": True, "module_id": module.id, "week": week_no, "rows": rows})


@require_http_methods(["GET"])
def api_mobile_staff_result_report(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "module_id": None, "rows": [], "upload": None})

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        upload = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at").first()
    if not upload:
        return JsonResponse({"ok": True, "module_id": module.id, "rows": [], "upload": None})

    mentors = Mentor.objects.filter(student__module=module).distinct().order_by("name")
    rows = []
    for m in mentors:
        qs = ResultCallRecord.objects.filter(upload=upload, student__module=module, student__mentor=m)
        need_call = qs.count()
        received = qs.filter(final_status="received").count()
        not_received = qs.filter(final_status="not_received").count()
        done = received + not_received
        not_done = max(need_call - done, 0)
        msg_sent = qs.filter(message_sent=True).count()
        percent = round((done / need_call) * 100, 1) if need_call else 0
        rows.append(
            {
                "mentor": m.name,
                "need_call": need_call,
                "done": done,
                "received": received,
                "not_received": not_received,
                "not_done": not_done,
                "msg_sent": msg_sent,
                "completion_percent": percent,
            }
        )
    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "upload": {
                "upload_id": upload.id,
                "test_name": upload.test_name,
                "subject_name": upload.subject.name,
            },
            "rows": rows,
        }
    )


@require_http_methods(["GET"])
def api_mobile_staff_subjects(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": True, "subjects": [], "module_id": None})

    rows = Subject.objects.filter(module=module, is_active=True).order_by("display_order", "name")
    return JsonResponse(
        {
            "ok": True,
            "module_id": module.id,
            "subjects": [
                {
                    "id": s.id,
                    "name": s.name,
                    "short_name": s.short_name,
                    "result_format": s.result_format,
                }
                for s in rows
            ],
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_upload_results(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_staff_module(request, user, role)
    if not module:
        return JsonResponse({"ok": False, "msg": "No module selected"}, status=400)

    test_name = (request.POST.get("test_name") or "").strip().upper()
    subject_id = (request.POST.get("subject_id") or "").strip()
    upload_mode = (request.POST.get("upload_mode") or "subject").strip().lower()
    bulk_confirm = (request.POST.get("bulk_confirm") or "").strip().lower()
    result_file = request.FILES.get("result_file")

    allowed_tests = {"T1", "T2", "T3", "T4", "REMEDIAL", "ALL_EXAMS"}
    if test_name not in allowed_tests:
        return JsonResponse({"ok": False, "msg": "Invalid test name"}, status=400)
    if not subject_id:
        return JsonResponse({"ok": False, "msg": "Subject is required"}, status=400)
    if upload_mode not in {"subject", "compiled"}:
        return JsonResponse({"ok": False, "msg": "Invalid upload mode"}, status=400)
    if not result_file:
        return JsonResponse({"ok": False, "msg": "Result file is required"}, status=400)
    if test_name == "ALL_EXAMS" and str(subject_id).upper() != "ALL":
        return JsonResponse({"ok": False, "msg": "For ALL_EXAMS, subject must be ALL"}, status=400)
    if test_name == "ALL_EXAMS" and upload_mode != "compiled":
        return JsonResponse({"ok": False, "msg": "For ALL_EXAMS, upload mode must be compiled"}, status=400)
    if test_name == "ALL_EXAMS" and bulk_confirm != "yes":
        return JsonResponse({"ok": False, "msg": "Bulk upload requires confirmation (bulk_confirm=yes)"}, status=400)

    try:
        payload = _staff_process_result_upload(
            module=module,
            username=user.username,
            test_name=test_name,
            subject_id=subject_id,
            upload_mode=upload_mode,
            bulk_confirm=bulk_confirm,
            file_obj=result_file,
        )
        payload["module_id"] = module.id
        return JsonResponse(payload)
    except Exception as exc:
        return JsonResponse({"ok": False, "msg": str(exc)}, status=400)


@require_http_methods(["GET"])
def api_mobile_staff_home_summary(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    if role != "superadmin":
        return JsonResponse({"ok": False, "msg": "SuperAdmin only"}, status=403)

    modules = AcademicModule.objects.filter(is_active=True).order_by("-id")
    total_coordinators = CoordinatorModuleAccess.objects.values("coordinator_id").distinct().count()
    total_modules = modules.count()
    total_mentors = Mentor.objects.filter(student__module__in=modules).distinct().count()
    total_students = Student.objects.filter(module__in=modules).count()

    module_rows = []
    for m in modules:
        module_rows.append(
            {
                "id": m.id,
                "name": m.name,
                "batch": m.academic_batch,
                "year_level": m.year_level,
                "variant": m.variant,
                "semester": m.semester,
                "is_active": m.is_active,
                "students": Student.objects.filter(module=m).count(),
                "mentors": Mentor.objects.filter(student__module=m).distinct().count(),
                "coordinators": CoordinatorModuleAccess.objects.filter(module=m).values("coordinator_id").distinct().count(),
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "stats": {
                "total_coordinators": total_coordinators,
                "total_modules": total_modules,
                "total_mentors": total_mentors,
                "total_students": total_students,
            },
            "modules": module_rows,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_mobile_staff_modules_manage(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)

    if request.method == "GET":
        rows = _staff_modules(user, role)
        return JsonResponse(
            {
                "ok": True,
                "role": role,
                "modules": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "batch": m.academic_batch,
                        "year_level": m.year_level,
                        "variant": m.variant,
                        "semester": m.semester,
                        "is_active": m.is_active,
                    }
                    for m in rows
                ],
            }
        )

    if role != "superadmin":
        return JsonResponse({"ok": False, "msg": "SuperAdmin only"}, status=403)

    body = _json_body(request)
    name = (body.get("name") or "").strip()
    batch = (body.get("academic_batch") or "").strip()
    year_level = (body.get("year_level") or "FY").strip()
    variant = (body.get("variant") or "FY2-CE").strip()
    semester = (body.get("semester") or "Sem-1").strip()
    if not name or not batch:
        return JsonResponse({"ok": False, "msg": "Name and batch are required"}, status=400)
    if AcademicModule.objects.filter(name__iexact=name).exists():
        return JsonResponse({"ok": False, "msg": "Module name already exists"}, status=400)

    m = AcademicModule.objects.create(
        name=name,
        academic_batch=batch,
        year_level=year_level,
        variant=variant,
        semester=semester,
        is_active=True,
    )
    return JsonResponse({"ok": True, "msg": f"Module created: {m.name}", "module_id": m.id})


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_staff_module_toggle(request):
    user, role = _auth_staff(request)
    if not user:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    if role != "superadmin":
        return JsonResponse({"ok": False, "msg": "SuperAdmin only"}, status=403)

    body = _json_body(request)
    module_id = body.get("module_id")
    action = (body.get("action") or "").strip().lower()  # activate/archive
    m = AcademicModule.objects.filter(id=module_id).first()
    if not m:
        return JsonResponse({"ok": False, "msg": "Module not found"}, status=404)
    if action not in {"activate", "archive"}:
        return JsonResponse({"ok": False, "msg": "Invalid action"}, status=400)
    m.is_active = action == "activate"
    m.save(update_fields=["is_active"])
    return JsonResponse({"ok": True, "msg": f"Module {action}d: {m.name}"})


def _resolve_module(request, mentor, required=False):
    modules = _mentor_modules(mentor)
    if not modules.exists():
        return None
    module_id = _module_id_from_request(request)
    if module_id:
        picked = modules.filter(id=module_id).first()
        if picked:
            return picked
        if required:
            return "__INVALID__"
    return modules.first()


def _attendance_map(mentor, week_no, module):
    rows = Attendance.objects.filter(
        week_no=week_no,
        student__mentor=mentor,
        student__module=module,
    ).select_related("student")
    out = {}
    for row in rows:
        out[row.student_id] = row
    return out


def _result_report_text(upload, mentor_name, total, received, not_received, message_done):
    test_name = upload.test_name
    subject_name = upload.subject.name
    if test_name == "T1":
        rule = "Less than 9 marks in T1"
    elif test_name == "T2":
        rule = "Less than 9 marks in T2 & less than 18 in (T1+T2)"
    elif test_name == "T3":
        rule = "Less than 9 marks in T3 & less than 27 in (T1+T2+T3)"
    elif test_name == "T4":
        rule = "Less than 18 marks in SEE & less than 35 in (T1+T2+T3+SEE)"
    else:
        rule = "Less than 35 marks in REMEDIAL"

    return (
        f"📞Phone call done regarding failed in {subject_name} ({rule})\n"
        f"Name of Faculty- {mentor_name}\n"
        f"Total no of calls- {total:02d}\n"
        f"Received Calls - {received:02d}\n"
        f"Not received- {not_received:02d}\n"
        f"No of Message done as call not Received - {message_done:02d}"
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_login(request):
    body = _json_body(request)
    mentor_name = (body.get("mentor") or "").strip()
    password_raw = (body.get("password") or "").strip()
    password = password_raw.lower()

    mentor = resolve_mentor_identity(mentor_name)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Invalid credentials"}, status=401)

    entered_username = mentor_name.lower()
    expected_short = f"{(mentor.name or '').strip().lower()}@lj123"
    expected_entered = f"{entered_username}@lj123"
    cred = MentorPassword.objects.filter(mentor=mentor).first()
    custom_ok = bool(cred and cred.check_password(password_raw))
    if not (custom_ok or password in {expected_short, expected_entered, "mentor@lj123"}):
        return JsonResponse({"ok": False, "msg": "Invalid credentials"}, status=401)

    MentorAuthToken.objects.filter(mentor=mentor, is_active=True).update(is_active=False)

    token = secrets.token_hex(32)
    expires_at = timezone.now() + timedelta(hours=TOKEN_TTL_HOURS)
    MentorAuthToken.objects.create(
        mentor=mentor,
        token=token,
        expires_at=expires_at,
        is_active=True,
    )

    return JsonResponse(
        {
            "ok": True,
            "token": token,
            "mentor": mentor.name,
            "expires_at": expires_at.isoformat(),
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_logout(request):
    token = _token_from_request(request)
    if token:
        MentorAuthToken.objects.filter(token=token, is_active=True).update(is_active=False)
    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def api_mobile_modules(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    modules = list(_mentor_modules(mentor))
    selected = _resolve_module(request, mentor)
    return JsonResponse(
        {
            "ok": True,
            "modules": [
                {
                    "module_id": m.id,
                    "name": m.name,
                    "batch": m.academic_batch,
                    "year_level": m.year_level,
                    "variant": m.variant,
                    "semester": m.semester,
                }
                for m in modules
            ],
            "selected_module_id": selected.id if selected else None,
        }
    )


@require_http_methods(["GET"])
def api_mobile_weeks(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor)
    if not module:
        return JsonResponse({"ok": True, "weeks": [], "latest_week": None, "module_id": None})

    weeks = sorted(
        Attendance.objects.filter(student__mentor=mentor, student__module=module)
        .values_list("week_no", flat=True)
        .distinct()
    )
    latest = weeks[-1] if weeks else None
    return JsonResponse({"ok": True, "weeks": weeks, "latest_week": latest, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_calls(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "records": [], "all_done": False, "module_id": None})

    week = request.GET.get("week")
    if not week:
        return JsonResponse({"ok": False, "msg": "week is required"}, status=400)

    week_no = int(week)
    attendance_map = _attendance_map(mentor, week_no, module)

    calls = (
        CallRecord.objects.filter(student__mentor=mentor, student__module=module, week_no=week_no)
        .select_related("student")
        .order_by("student__roll_no", "student__name")
    )

    data = []
    for c in calls:
        a = attendance_map.get(c.student_id)
        data.append(
            {
                "call_id": c.id,
                "week_no": c.week_no,
                "student": {
                    "roll_no": c.student.roll_no,
                    "enrollment": c.student.enrollment,
                    "name": c.student.name,
                    "student_mobile": c.student.student_mobile,
                    "father_mobile": c.student.father_mobile,
                    "mother_mobile": c.student.mother_mobile,
                },
                "week_percentage": a.week_percentage if a else None,
                "overall_percentage": a.overall_percentage if a else None,
                "final_status": c.final_status,
                "talked_with": c.talked_with,
                "duration": c.duration,
                "parent_reason": c.parent_reason,
                "message_sent": c.message_sent,
            }
        )

    total = len(data)
    done = len([x for x in data if x["final_status"] is not None])

    return JsonResponse(
        {
            "ok": True,
            "week": week_no,
            "mentor": mentor.name,
            "module_id": module.id,
            "total": total,
            "done": done,
            "all_done": total > 0 and done == total,
            "records": data,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_save_call(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)

    body = _json_body(request)
    call_id = body.get("id")
    status = body.get("status")
    talked = body.get("talked")
    duration = (body.get("duration") or "").strip()
    reason = (body.get("reason") or "").strip()

    call = (
        CallRecord.objects.select_related("student", "student__mentor")
        .filter(id=call_id, student__mentor=mentor, student__module=module)
        .first()
    )
    if not call:
        return JsonResponse({"ok": False, "msg": "Call not found"}, status=404)

    if not call.attempt1_time:
        call.attempt1_time = timezone.now()
    elif not call.attempt2_time:
        call.attempt2_time = timezone.now()

    if status == "received":
        if not reason:
            return JsonResponse(
                {"ok": False, "msg": "Parent remark is required for received calls"},
                status=400,
            )
        if talked not in {"father", "mother", "guardian"}:
            talked = "guardian"
        call.final_status = "received"
        call.talked_with = talked
        call.duration = duration
        call.parent_reason = reason
    elif status == "not_received":
        call.final_status = "not_received"

    call.save()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_mark_message(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)

    body = _json_body(request)
    call_id = body.get("id")
    call = (
        CallRecord.objects.select_related("student", "student__mentor")
        .filter(id=call_id, student__mentor=mentor, student__module=module)
        .first()
    )
    if not call:
        return JsonResponse({"ok": False, "msg": "Call not found"}, status=404)
    call.message_sent = True
    call.save(update_fields=["message_sent"])
    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def api_mobile_retry_list(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "week": None, "records": [], "module_id": None})

    week = request.GET.get("week")
    if not week:
        return JsonResponse({"ok": False, "msg": "week is required"}, status=400)
    week_no = int(week)
    attendance_map = _attendance_map(mentor, week_no, module)

    calls = (
        CallRecord.objects.filter(
            student__mentor=mentor,
            student__module=module,
            week_no=week_no,
            final_status="not_received",
        )
        .select_related("student")
        .order_by("student__roll_no", "student__name")
    )

    data = []
    for c in calls:
        a = attendance_map.get(c.student_id)
        data.append(
            {
                "call_id": c.id,
                "student_name": c.student.name,
                "roll_no": c.student.roll_no,
                "father_mobile": c.student.father_mobile,
                "mother_mobile": c.student.mother_mobile,
                "student_mobile": c.student.student_mobile,
                "week_percentage": a.week_percentage if a else None,
                "overall_percentage": a.overall_percentage if a else None,
                "message_sent": c.message_sent,
            }
        )

    return JsonResponse({"ok": True, "week": week_no, "records": data, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_result_cycles(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "cycles": [], "latest_upload_id": None, "module_id": None})

    uploads = (
        ResultUpload.objects.filter(module=module, calls__student__mentor=mentor, calls__student__module=module)
        .select_related("subject")
        .distinct()
        .order_by("-uploaded_at")
    )
    data = [
        {
            "upload_id": u.id,
            "test_name": u.test_name,
            "subject_name": u.subject.name,
            "uploaded_at": u.uploaded_at.isoformat(),
        }
        for u in uploads
    ]
    latest = data[0]["upload_id"] if data else None
    return JsonResponse({"ok": True, "cycles": data, "latest_upload_id": latest, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_result_calls(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "records": [], "all_done": False, "upload": None, "module_id": None})

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        upload = (
            ResultUpload.objects.filter(module=module, calls__student__mentor=mentor, calls__student__module=module)
            .select_related("subject")
            .distinct()
            .order_by("-uploaded_at")
            .first()
        )
    if not upload:
        return JsonResponse({"ok": True, "records": [], "all_done": False, "upload": None})

    calls = (
        ResultCallRecord.objects.filter(upload=upload, student__mentor=mentor, student__module=module)
        .select_related("student", "upload", "upload__subject")
        .order_by("student__roll_no", "student__name")
    )
    data = []
    for c in calls:
        data.append(
            {
                "call_id": c.id,
                "upload_id": upload.id,
                "test_name": upload.test_name,
                "subject_name": upload.subject.name,
                "student": {
                    "roll_no": c.student.roll_no,
                    "enrollment": c.student.enrollment,
                    "name": c.student.name,
                    "student_mobile": c.student.student_mobile,
                    "father_mobile": c.student.father_mobile,
                    "mother_mobile": c.student.mother_mobile,
                },
                "final_status": c.final_status,
                "talked_with": c.talked_with,
                "duration": c.duration,
                "parent_reason": c.parent_reason,
                "message_sent": c.message_sent,
                "fail_reason": c.fail_reason,
                "marks_current": c.marks_current,
                "marks_total": c.marks_total,
            }
        )

    total = len(data)
    done = len([x for x in data if x["final_status"] is not None])
    return JsonResponse(
        {
            "ok": True,
            "upload": {
                "upload_id": upload.id,
                "test_name": upload.test_name,
                "subject_name": upload.subject.name,
            },
            "module_id": module.id,
            "records": data,
            "total": total,
            "done": done,
            "all_done": total > 0 and done == total,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_save_result_call(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)

    body = _json_body(request)
    call_id = body.get("id")
    status = body.get("status")
    talked = body.get("talked")
    duration = (body.get("duration") or "").strip()
    reason = (body.get("reason") or "").strip()

    call = (
        ResultCallRecord.objects.select_related("student", "student__mentor")
        .filter(id=call_id, student__mentor=mentor, student__module=module)
        .first()
    )
    if not call:
        return JsonResponse({"ok": False, "msg": "Call not found"}, status=404)

    if not call.attempt1_time:
        call.attempt1_time = timezone.now()
    elif not call.attempt2_time:
        call.attempt2_time = timezone.now()

    if status == "received":
        if not reason:
            return JsonResponse(
                {"ok": False, "msg": "Parent remark is required for received calls"},
                status=400,
            )
        if talked not in {"father", "mother", "guardian"}:
            talked = "guardian"
        call.final_status = "received"
        call.talked_with = talked
        call.duration = duration
        call.parent_reason = reason
    elif status == "not_received":
        call.final_status = "not_received"

    call.save()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_mark_result_message(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)

    body = _json_body(request)
    call_id = body.get("id")
    call = (
        ResultCallRecord.objects.select_related("student", "student__mentor")
        .filter(id=call_id, student__mentor=mentor, student__module=module)
        .first()
    )
    if not call:
        return JsonResponse({"ok": False, "msg": "Call not found"}, status=404)
    call.message_sent = True
    call.save(update_fields=["message_sent"])
    return JsonResponse({"ok": True})


@require_http_methods(["GET"])
def api_mobile_result_retry_list(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "records": [], "module_id": None})

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        return JsonResponse({"ok": True, "records": [], "module_id": module.id})

    calls = (
        ResultCallRecord.objects.filter(
            student__mentor=mentor,
            student__module=module,
            upload=upload,
            final_status="not_received",
        )
        .select_related("student")
        .order_by("student__roll_no", "student__name")
    )
    data = []
    for c in calls:
        data.append(
            {
                "call_id": c.id,
                "student_name": c.student.name,
                "roll_no": c.student.roll_no,
                "father_mobile": c.student.father_mobile,
                "mother_mobile": c.student.mother_mobile,
                "student_mobile": c.student.student_mobile,
                "message_sent": c.message_sent,
                "fail_reason": c.fail_reason,
            }
        )
    return JsonResponse({"ok": True, "records": data, "module_id": module.id})


@require_http_methods(["GET"])
def api_mobile_result_report(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "report": "", "stats": {}, "module_id": None})

    upload_id = request.GET.get("upload_id")
    upload = None
    if upload_id:
        upload = ResultUpload.objects.select_related("subject").filter(id=upload_id, module=module).first()
    if not upload:
        upload = (
            ResultUpload.objects.filter(module=module, calls__student__mentor=mentor, calls__student__module=module)
            .select_related("subject")
            .distinct()
            .order_by("-uploaded_at")
            .first()
        )
    if not upload:
        return JsonResponse({"ok": True, "report": "", "stats": {}})

    calls = ResultCallRecord.objects.filter(upload=upload, student__mentor=mentor, student__module=module)
    total = calls.count()
    received = calls.filter(final_status="received").count()
    not_received = calls.filter(final_status="not_received").count()
    message_done = calls.filter(message_sent=True).count()
    report = _result_report_text(upload, mentor.name, total, received, not_received, message_done)
    return JsonResponse(
        {
            "ok": True,
            "report": report,
            "upload": {
                "upload_id": upload.id,
                "test_name": upload.test_name,
                "subject_name": upload.subject.name,
            },
            "module_id": module.id,
            "stats": {
                "total": total,
                "received": received,
                "not_received": not_received,
                "message_done": message_done,
                "pending": max(total - received - not_received, 0),
            },
        }
    )


@require_http_methods(["GET"])
def api_mobile_other_calls(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)
    if not module:
        return JsonResponse({"ok": True, "records": [], "module_id": None})

    students = Student.objects.filter(module=module, mentor=mentor).order_by("roll_no", "name")
    existing = {
        c.student_id: c
        for c in OtherCallRecord.objects.filter(mentor=mentor, student__module=module, student__in=students).select_related("student")
    }
    to_create = []
    for s in students:
        if s.id not in existing:
            to_create.append(OtherCallRecord(student=s, mentor=mentor))
    if to_create:
        OtherCallRecord.objects.bulk_create(to_create)

    rows = (
        OtherCallRecord.objects.filter(mentor=mentor, student__module=module)
        .select_related("student")
        .order_by("student__roll_no", "student__name")
    )
    data = []
    for c in rows:
        data.append(
            {
                "call_id": c.id,
                "student": {
                    "roll_no": c.student.roll_no,
                    "enrollment": c.student.enrollment,
                    "name": c.student.name,
                    "student_mobile": c.student.student_mobile,
                    "father_mobile": c.student.father_mobile,
                    "mother_mobile": c.student.mother_mobile,
                },
                "final_status": c.final_status,
                "talked_with": c.talked_with,
                "duration": c.duration,
                "parent_remark": c.parent_remark,
                "call_done_reason": c.call_done_reason,
                "last_called_target": c.last_called_target,
            }
        )

    return JsonResponse({"ok": True, "records": data, "module_id": module.id})


@csrf_exempt
@require_http_methods(["POST"])
def api_mobile_save_other_call(request):
    mentor = _auth_mentor(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _resolve_module(request, mentor, required=True)
    if module == "__INVALID__":
        return JsonResponse({"ok": False, "msg": "Invalid module"}, status=400)

    body = _json_body(request)
    call_id = body.get("id")
    status = body.get("status")
    talked = body.get("talked")
    duration = (body.get("duration") or "").strip()
    remark = (body.get("remark") or "").strip()
    call_reason = (body.get("call_reason") or "").strip()
    target = (body.get("target") or "").strip()

    call = (
        OtherCallRecord.objects.select_related("student", "mentor")
        .filter(id=call_id, mentor=mentor, student__module=module)
        .first()
    )
    if not call:
        return JsonResponse({"ok": False, "msg": "Call not found"}, status=404)

    if not call.attempt1_time:
        call.attempt1_time = timezone.now()
    elif not call.attempt2_time:
        call.attempt2_time = timezone.now()

    if target in {"student", "father"}:
        call.last_called_target = target

    if status == "received":
        call.final_status = "received"
        if talked not in {"father", "mother", "guardian", "student"}:
            talked = "guardian"
        call.talked_with = talked
        call.duration = duration
        call.parent_remark = remark
        call.call_done_reason = call_reason
    elif status == "not_received":
        call.final_status = "not_received"
        call.call_done_reason = call_reason or call.call_done_reason

    call.save()
    return JsonResponse({"ok": True})
