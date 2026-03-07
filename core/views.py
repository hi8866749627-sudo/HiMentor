# ---------- DJANGO ----------
import io
import os
import re
import tempfile
import threading
import uuid
import zipfile
from zoneinfo import ZoneInfo
from django.core.management import call_command

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import authenticate, login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.db import close_old_connections
from django.db.models import Count
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db.models import Max 
from django.db.models import Q
from urllib.parse import quote
from django.core.paginator import Paginator
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
# ---------- LOCAL FORMS ----------
from .forms import UploadFileForm

# ---------- LOCAL MODELS ----------
from .models import (
    AcademicModule,
    Attendance,
    CallRecord,
    CoordinatorModuleAccess,
    Mentor,
    MentorPassword,
    OtherCallRecord,
    PracticalMarkUpload,
    SifMarksLock,
    ResultCallRecord,
    ResultUpload,
    ResultUploadJob,
    Student,
    StudentPracticalMark,
    StudentResult,
    Subject,
    SubjectTemplate,
    WeekLock,
)

# ---------- LOCAL UTILITIES ----------
from .utils import import_students_from_excel, resolve_mentor_identity
from .attendance_utils import import_attendance
from .result_utils import import_compiled_bulk_all, import_compiled_result_sheet, import_result_sheet
from .practical_utils import import_practical_marks, ordered_subjects
from .pdf_report import generate_student_pdf, generate_student_prefilled_pdf
from .module_utils import allowed_modules_for_user, get_current_module, is_superadmin_user

TEST_NAMES = ["T1", "T2", "T3", "T4", "REMEDIAL"]
IST = ZoneInfo("Asia/Kolkata")


def _session_mentor_obj(request):
    mentor_key = request.session.get("mentor")
    mentor = resolve_mentor_identity(mentor_key)
    if mentor and mentor_key != mentor.name:
        request.session["mentor"] = mentor.name
    return mentor


def _active_module(request):
    return get_current_module(request)


def _latest_attendance_calls_map(module, week_no, mentor=None):
    qs = CallRecord.objects.filter(student__module=module, week_no=week_no).select_related("student", "student__mentor")
    if mentor:
        qs = qs.filter(student__mentor=mentor)
    qs = qs.order_by("student_id", "-attempt1_time", "-attempt2_time", "-created_at", "-id")
    latest = {}
    for rec in qs:
        if rec.student_id not in latest:
            latest[rec.student_id] = rec
    return latest


def _latest_result_calls_map(upload, mentor=None, student=None, module=None, student_ids=None):
    qs = ResultCallRecord.objects.filter(upload=upload).select_related("student", "student__mentor", "upload", "upload__subject")
    if module:
        qs = qs.filter(student__module=module)
    if mentor:
        qs = qs.filter(student__mentor=mentor)
    if student:
        qs = qs.filter(student=student)
    if student_ids is not None:
        qs = qs.filter(student_id__in=list(student_ids))
    qs = qs.order_by("student_id", "-attempt1_time", "-attempt2_time", "-created_at", "-id")
    latest = {}
    for rec in qs:
        if rec.student_id not in latest:
            latest[rec.student_id] = rec
    return latest


def _upload_fail_student_ids(upload):
    return set(
        StudentResult.objects.filter(upload=upload, fail_flag=True).values_list("student_id", flat=True)
    )


def _require_superadmin(request):
    if not request.user.is_authenticated or request.session.get("mentor"):
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    if not is_superadmin_user(request.user):
        return JsonResponse({"ok": False, "msg": "SuperAdmin only"}, status=403)
    return None


def _normalize_whatsapp_phone(number):
    digits = re.sub(r"\D", "", str(number or ""))
    if not digits:
        return ""
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def _ensure_subject_display_order(module):
    subjects = list(Subject.objects.filter(module=module, is_active=True).order_by("display_order", "name"))
    changed = False
    next_order = 1
    for s in subjects:
        if not s.display_order or s.display_order <= 0:
            s.display_order = next_order
            s.save(update_fields=["display_order"])
            changed = True
        next_order += 1
    return changed


def _latest_result_map_for_student(student, module):
    rows = {}
    subjects = Subject.objects.filter(module=module, is_active=True)
    for s in subjects:
        upload = (
            ResultUpload.objects.filter(module=module, subject=s)
            .order_by("-uploaded_at")
            .first()
        )
        if not upload:
            rows[s.id] = None
            continue
        rows[s.id] = StudentResult.objects.filter(upload=upload, student=student).first()
    return rows


def _fmt_mark(v):
    if v is None:
        return "-"
    try:
        if float(v).is_integer():
            return str(int(v))
        return str(round(float(v), 2))
    except Exception:
        return str(v)


def _module_display_name(variant, semester, batch):
    return f"{variant}_{semester} - Batch {batch}"


def _sif_marks_rows_for_student(student, module):
    subjects = ordered_subjects(module)
    practical_map = {
        pm.subject_id: pm
        for pm in StudentPracticalMark.objects.filter(module=module, student=student).select_related("subject")
    }
    result_map = _latest_result_map_for_student(student, module)

    rows = []
    for s in subjects:
        practical = practical_map.get(s.id)
        sr = result_map.get(s.id)
        attendance_val = _fmt_mark(practical.attendance_percentage) if practical and practical.attendance_percentage is not None else "-"
        short = (s.short_name or s.name).strip()
        t1 = sr.marks_t1 if sr and sr.marks_t1 is not None else (sr.marks_current if sr and sr.upload.test_name == "T1" else None)
        t2 = sr.marks_t2 if sr and sr.marks_t2 is not None else (sr.marks_current if sr and sr.upload.test_name == "T2" else None)
        t3 = sr.marks_t3 if sr and sr.marks_t3 is not None else (sr.marks_current if sr and sr.upload.test_name == "T3" else None)
        t4 = sr.marks_t4 if sr and sr.marks_t4 is not None else (sr.marks_current if sr and sr.upload.test_name == "T4" else None)
        total = sr.marks_total if sr else None
        rows.append(
            {
                "label": f"{short}-TH",
                "t1": _fmt_mark(t1),
                "t2": _fmt_mark(t2),
                "t3": _fmt_mark(t3),
                "t4": _fmt_mark(t4),
                "total": _fmt_mark(total),
                "attendance": attendance_val,
            }
        )
        rows.append(
            {
                "label": f"{short}-PR",
                "t1": "-",
                "t2": "-",
                "t3": "-",
                "t4": "-",
                "total": _fmt_mark(practical.pr_marks) if practical and practical.pr_marks is not None else "-",
                "attendance": attendance_val,
            }
        )
    return rows


def _result_report_text(test_name, subject_name, mentor_name, total, received, not_received, message_done):
    if test_name == "T1":
        rule = f"Less than 9 marks in {test_name}"
    elif test_name == "T2":
        rule = "Less than 9 marks in T2 & less than 18 in (T1+T2)"
    elif test_name == "T3":
        rule = "Less than 9 marks in T3 & less than 27 in (T1+T2+T3)"
    elif test_name == "T4":
        rule = "Less than 18 marks in SEE & less than 35 in (T1+T2+T3+SEE)"
    else:
        rule = "Less than 35 marks in REMEDIAL"

    return f"""📞Phone call done regarding failed in {subject_name} ({rule})
Name of Faculty- {mentor_name}
Total no of calls- {total:02d}
Received Calls - {received:02d}
Not received- {not_received:02d}
No of Message done as call not Received - {message_done:02d}"""


def _result_filter_config(test_name):
    test_name = (test_name or "").upper()
    if test_name == "T1":
        return {
            "current_key": "current_fail",
            "current_label": "T1<9",
            "total_key": "total_fail",
            "total_label": "till T1<9",
            "either_key": "either_fail",
            "either_label": "Either (T1<9 OR till T1<9)",
            "current_threshold": 9,
            "total_threshold": 9,
            "exam_col_label": "T1 marks /25",
            "total_col_label": "Total till T1 /25",
            "display_columns": [
                {"key": "marks_current", "label": "T1 marks /25"},
                {"key": "marks_total", "label": "Total till T1 /25"},
            ],
        }
    if test_name == "T2":
        return {
            "current_key": "current_fail",
            "current_label": "T2<9",
            "total_key": "total_fail",
            "total_label": "T1+T2<18",
            "either_key": "either_fail",
            "either_label": "Either (T2<9 OR T1+T2<18)",
            "current_threshold": 9,
            "total_threshold": 18,
            "exam_col_label": "T2 marks /25",
            "total_col_label": "T1+T2 /50",
            "display_columns": [
                {"key": "marks_t1", "label": "T1 marks /25"},
                {"key": "marks_current", "label": "T2 marks /25"},
                {"key": "marks_total", "label": "T1+T2 /50"},
            ],
        }
    if test_name == "T3":
        return {
            "current_key": "current_fail",
            "current_label": "T3<9",
            "total_key": "total_fail",
            "total_label": "T1+T2+T3<27",
            "either_key": "either_fail",
            "either_label": "Either (T3<9 OR T1+T2+T3<27)",
            "current_threshold": 9,
            "total_threshold": 27,
            "exam_col_label": "T3 marks /25",
            "total_col_label": "T1+T2+T3 /75",
            "display_columns": [
                {"key": "marks_t1", "label": "T1 marks /25"},
                {"key": "marks_t2", "label": "T2 marks /25"},
                {"key": "marks_current", "label": "T3 marks /25"},
                {"key": "marks_total", "label": "T1+T2+T3 /75"},
            ],
        }
    if test_name == "T4":
        return {
            "current_key": "current_fail",
            "current_label": "T4<18",
            "total_key": "total_fail",
            "total_label": "T1+T2+T3+T4<35",
            "either_key": "either_fail",
            "either_label": "Either (T4<18 OR T1+T2+T3+T4<35)",
            "current_threshold": 18,
            "total_threshold": 35,
            "exam_col_label": "T4 marks /50",
            "total_col_label": "T1+T2+T3+(T4/2) /100",
            "display_columns": [
                {"key": "marks_t1", "label": "T1 marks /25"},
                {"key": "marks_t2", "label": "T2 marks /25"},
                {"key": "marks_t3", "label": "T3 marks /25"},
                {"key": "marks_current", "label": "T4 marks /50"},
                {"key": "marks_t4_half", "label": "T4/2 /25"},
                {"key": "marks_total", "label": "T1+T2+T3+(T4/2) /100"},
            ],
        }
    return {
        "current_key": "current_fail",
        "current_label": "REM<35",
        "total_key": "total_fail",
        "total_label": "REM<35",
        "either_key": "either_fail",
        "either_label": "Either (REM<35)",
        "current_threshold": 35,
        "total_threshold": 35,
        "exam_col_label": "REM marks /100",
        "total_col_label": "Total till REM /100",
        "display_columns": [
            {"key": "marks_current", "label": "REM marks /100"},
            {"key": "marks_total", "label": "Total till REM /100"},
        ],
    }


def _format_parent_faculty_remark(text):
    raw = (text or "").strip()
    if not raw:
        return "-"
    if "PARENT::" in raw and "||FACULTY::" in raw:
        parent_part, faculty_part = raw.split("||FACULTY::", 1)
        parent_val = parent_part.replace("PARENT::", "", 1).strip() or "-"
        faculty_val = faculty_part.strip() or "-"
        return f"PARENT: {parent_val}\nFACULTY: {faculty_val}"
    return raw

# ---------------- LOGIN ----------------
def login_page(request):
    error = ""

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        # coordinator login
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            request.session.pop("mentor", None)
            _active_module(request)
            if is_superadmin_user(user):
                return redirect("/home/")
            return redirect("/reports/")

        # mentor login supports both legacy and new scheme:
        # - legacy: mentor@LJ123
        # - new: <mentor_short_name>@LJ123
        mentor = resolve_mentor_identity(username)
        if mentor:
            entered_username = (username or "").strip().lower()
            expected_short = f"{(mentor.name or '').strip().lower()}@LJ123".lower()
            expected_entered = f"{entered_username}@LJ123"
            entered_password_raw = (password or "").strip()
            entered_password = entered_password_raw.lower()
            cred = MentorPassword.objects.filter(mentor=mentor).first()
            custom_ok = bool(cred and cred.check_password(entered_password_raw))
            if custom_ok or entered_password in {expected_short, expected_entered, "mentor@lj123"}:
                request.session["mentor"] = mentor.name
                _active_module(request)
                return redirect("/mentor-dashboard/")

        error = "Invalid username or password"

    return render(request, "login.html", {"error": error})


@login_required
def manage_mentors(request):
    if request.session.get("mentor"):
        return redirect("/mentor-dashboard/")

    module = _active_module(request)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        mentor_id = request.POST.get("mentor_id")
        mentor = Mentor.objects.filter(id=mentor_id).first() if mentor_id else None
        module_mentor_ids = set(Student.objects.filter(module=module).values_list("mentor_id", flat=True))
        if not mentor or mentor.id not in module_mentor_ids:
            messages.error(request, "Mentor not found for current module.")
            return redirect("/manage-mentors/")

        if action == "update_password":
            new_password = (request.POST.get("new_password") or "").strip()
            if len(new_password) < 6:
                messages.error(request, "Password must be at least 6 characters.")
            else:
                cred, _ = MentorPassword.objects.get_or_create(mentor=mentor, defaults={"password_hash": ""})
                cred.set_password(new_password)
                cred.save(update_fields=["password_hash", "updated_at"])
                messages.success(request, f"Password updated for mentor {mentor.name}.")
        elif action == "reset_default":
            MentorPassword.objects.filter(mentor=mentor).delete()
            messages.success(request, f"Password reset to default rule for mentor {mentor.name}.")
        else:
            messages.error(request, "Invalid action.")
        return redirect("/manage-mentors/")

    mentors = (
        Mentor.objects.filter(student__module=module)
        .distinct()
        .annotate(student_count=Count("student", filter=Q(student__module=module)))
        .order_by("name")
    )
    cred_map = {c.mentor_id: c for c in MentorPassword.objects.filter(mentor__in=mentors)}
    rows = []
    for m in mentors:
        rows.append(
            {
                "mentor": m,
                "student_count": getattr(m, "student_count", 0),
                "has_custom_password": m.id in cred_map,
            }
        )

    return render(
        request,
        "manage_mentors.html",
        {
            "rows": rows,
            "module": module,
        },
    )


@login_required
def superadmin_home(request):
    if request.session.get("mentor"):
        return redirect("/mentor-dashboard/")
    if not is_superadmin_user(request.user):
        return redirect("/reports/")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            coordinator_name = (request.POST.get("coordinator_name") or "").strip()
            username = (request.POST.get("username") or "").strip()
            password = (request.POST.get("password") or "").strip()
            module_ids = request.POST.getlist("module_ids")
            if not coordinator_name or not username or not password:
                messages.error(request, "Coordinator name, username and password are required.")
            elif User.objects.filter(username__iexact=username).exists():
                messages.error(request, "Coordinator username already exists.")
            else:
                coordinator = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=coordinator_name,
                    is_active=True,
                    is_staff=False,
                    is_superuser=False,
                )
                modules = list(AcademicModule.objects.filter(id__in=module_ids))
                if not modules:
                    coordinator.delete()
                    messages.error(request, "Select at least one module.")
                else:
                    CoordinatorModuleAccess.objects.bulk_create(
                        [CoordinatorModuleAccess(coordinator=coordinator, module=m) for m in modules],
                        ignore_conflicts=True,
                    )
                    messages.success(request, f"Coordinator created: {coordinator.username}")

        elif action == "update":
            coord_id = request.POST.get("coordinator_id")
            username = (request.POST.get("username") or "").strip()
            coordinator_name = (request.POST.get("coordinator_name") or "").strip()
            new_password = (request.POST.get("new_password") or "").strip()
            module_ids = request.POST.getlist("module_ids")
            active_val = (request.POST.get("is_active") or "").strip() == "1"
            coordinator = User.objects.filter(id=coord_id, is_superuser=False).first()
            if not coordinator:
                messages.error(request, "Coordinator not found.")
            else:
                if not username:
                    messages.error(request, "Username is required.")
                    return redirect("/home/")
                username_exists = User.objects.filter(username__iexact=username).exclude(id=coordinator.id).exists()
                if username_exists:
                    messages.error(request, "Username already exists.")
                    return redirect("/home/")
                modules = list(AcademicModule.objects.filter(id__in=module_ids))
                if not modules:
                    messages.error(request, "Select at least one module.")
                    return redirect("/home/")
                coordinator.username = username
                coordinator.first_name = coordinator_name
                coordinator.is_active = active_val
                if new_password:
                    coordinator.set_password(new_password)
                coordinator.save()
                CoordinatorModuleAccess.objects.filter(coordinator=coordinator).delete()
                CoordinatorModuleAccess.objects.bulk_create(
                    [CoordinatorModuleAccess(coordinator=coordinator, module=m) for m in modules],
                    ignore_conflicts=True,
                )
                messages.success(request, f"Coordinator updated: {coordinator.username}")

        elif action == "delete":
            coord_id = request.POST.get("coordinator_id")
            coordinator = User.objects.filter(id=coord_id, is_superuser=False).first()
            if not coordinator:
                messages.error(request, "Coordinator not found.")
            else:
                CoordinatorModuleAccess.objects.filter(coordinator=coordinator).delete()
                coordinator.delete()
                messages.success(request, "Coordinator deleted.")
        elif action == "change_super_password":
            current_password = (request.POST.get("current_password") or "").strip()
            new_password = (request.POST.get("new_password") or "").strip()
            if not request.user.check_password(current_password):
                messages.error(request, "Current password is incorrect.")
            elif len(new_password) < 8:
                messages.error(request, "New password must be at least 8 characters.")
            else:
                request.user.set_password(new_password)
                request.user.save(update_fields=["password"])
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password updated.")

        return redirect("/home/")

    modules = list(AcademicModule.objects.all().order_by("-id"))
    active_modules = [m for m in modules if m.is_active]
    active_module_ids = [m.id for m in active_modules]
    coordinators = User.objects.filter(is_superuser=False).order_by("username")
    coordinator_rows = []
    for c in coordinators:
        mapped = list(
            AcademicModule.objects.filter(coordinator_accesses__coordinator=c)
            .distinct()
            .order_by("-id")
        )
        coordinator_rows.append({"user": c, "modules": mapped})

    stats = {
        "total_coordinators": User.objects.filter(
            is_superuser=False,
            is_active=True,
            module_accesses__module__in=active_modules,
        ).distinct().count(),
        "total_modules": len(active_modules),
        "total_mentors": Mentor.objects.filter(student__module_id__in=active_module_ids).distinct().count(),
        "total_students": Student.objects.filter(module_id__in=active_module_ids).count(),
    }

    module_summary = []
    for m in modules:
        student_qs = Student.objects.filter(module=m)
        module_summary.append(
            {
                "module": m,
                "students": student_qs.count(),
                "mentors": Mentor.objects.filter(student__module=m).distinct().count(),
                "coordinators": User.objects.filter(is_superuser=False, module_accesses__module=m).distinct().count(),
            }
        )

    mentor_summary = (
        Mentor.objects.annotate(
            total_students=Count("student", filter=Q(student__module_id__in=active_module_ids), distinct=True),
            total_modules=Count("student__module", filter=Q(student__module_id__in=active_module_ids), distinct=True),
        )
        .filter(total_students__gt=0)
        .order_by("name")
    )

    student_report_rows = []
    for m in modules:
        student_qs = Student.objects.filter(module=m)
        student_report_rows.append(
            {
                "module_name": m.name,
                "students": student_qs.count(),
                "mentors": Mentor.objects.filter(student__module=m).distinct().count(),
                "attendance_rows": Attendance.objects.filter(student__module=m).count(),
                "result_uploads": ResultUpload.objects.filter(module=m).count(),
                "practical_uploads": PracticalMarkUpload.objects.filter(module=m).count(),
            }
        )

    return render(
        request,
        "home.html",
        {
            "modules": modules,
            "coordinator_rows": coordinator_rows,
            "stats": stats,
            "module_summary": module_summary,
            "mentor_summary": mentor_summary,
            "student_report_rows": student_report_rows,
        },
    )


# ---------------- STUDENT MASTER ----------------
@login_required
def upload_students(request):
    module = _active_module(request)

    message = ""
    skipped_rows = []
    form = UploadFileForm()

    if request.method == 'POST':
        if request.POST.get("action") == "clear_module_students":
            deleted_count, _ = Student.objects.filter(module=module).delete()
            message = f"Deleted student master data for module '{module.name}'. Records removed: {deleted_count}"
        else:
            form = UploadFileForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES['file']
                try:
                    added, updated, skipped, skipped_rows = import_students_from_excel(file, module)
                    message = f"Added: {added} | Updated: {updated} | Skipped: {skipped}"
                except Exception as e:
                    message = f"Upload failed: {str(e)}"
            else:
                message = "Please select a file to upload."
    else:
        form = UploadFileForm()

    students = Student.objects.select_related("mentor").filter(module=module).order_by("roll_no")

    return render(request, 'upload.html', {
        'form': form,
        'message': message,
        'students': students,
        'module': module,
        'skipped_rows': skipped_rows[:200],
    })

# ---------------- ATTENDANCE VIEW & UPLOAD ----------------
@require_http_methods(["GET","POST"])
def upload_attendance(request):
    module = _active_module(request)

    # -------- OPEN PAGE --------
    if request.method == "GET":
        return render(request, "upload_attendance.html")

    # -------- AJAX UPLOAD --------
    try:
        week_no = int(request.POST.get('week'))
        rule = request.POST.get('rule')
        weekly_file = request.FILES.get('weekly_file')
        overall_file = request.FILES.get('overall_file')

        # Week-1 has no overall
        if week_no == 1:
            overall_file = None

        # lock check
        if WeekLock.objects.filter(module=module, week_no=week_no, locked=True).exists():
            return JsonResponse({
                "ok": False,
                "msg": f"Week {week_no} is LOCKED. Upload not allowed."
            })

        # import
        count = import_attendance(weekly_file, overall_file, week_no, module, rule)

        # mentor-wise counts
        mentor_stats = list(
            CallRecord.objects.filter(week_no=week_no, student__module=module)
            .values("student__mentor__name")
            .annotate(total=Count("student", distinct=True))
            .order_by("student__mentor__name")
        )

        total_calls = sum(m["total"] for m in mentor_stats)

        return JsonResponse({
            "ok": True,
            "msg": f"{count} students require follow-up calls for Week {week_no}",
            "week": week_no,
            "mentor_stats": mentor_stats,
            "total_calls": total_calls
        })

    except Exception as e:
        return JsonResponse({
            "ok": False,
            "msg": str(e)
        })


def _process_result_upload(module, username, test_name, subject_id, upload_mode, bulk_confirm, file_obj, progress_cb=None, cancel_cb=None):
    is_all_tests = test_name == "ALL_EXAMS"
    is_all_subjects = str(subject_id).upper() == "ALL"

    if is_all_tests and is_all_subjects:
        summary = import_compiled_bulk_all(
            file_obj,
            username,
            module=module,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
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
        summary = import_compiled_result_sheet(file_obj, upload, progress_cb=progress_cb, cancel_cb=cancel_cb)
    else:
        summary = import_result_sheet(file_obj, upload, progress_cb=progress_cb, cancel_cb=cancel_cb)

    mentor_stats = list(
        ResultCallRecord.objects.filter(upload=upload)
        .values("student__mentor__name")
        .annotate(total=Count("student", distinct=True))
        .order_by("student__mentor__name")
    )
    total_calls = sum(m["total"] for m in mentor_stats)
    return {
        "ok": True,
        "msg": (
            f"Processed {summary['rows_total']} rows. "
            f"Matched: {summary['rows_matched']}. "
            f"Fail calls generated: {summary['rows_failed']}."
        ),
        "test_name": test_name,
        "subject_name": subject.name,
        "upload_id": upload.id,
        "mentor_stats": mentor_stats,
        "total_calls": total_calls,
        "upload_mode": upload_mode,
        "found_subjects": summary.get("found_subjects", []),
        "used_subject": summary.get("used_subject", ""),
    }


def _run_result_upload_job(job_id, module_id, username, test_name, subject_id, upload_mode, bulk_confirm, temp_path):
    close_old_connections()
    try:
        job = ResultUploadJob.objects.filter(job_id=job_id).first()
        if not job:
            return
        job.status = ResultUploadJob.STATUS_RUNNING
        job.message = "Reading marks and preparing result call list..."
        job.save(update_fields=["status", "message", "updated_at"])

        def cancel_cb():
            return ResultUploadJob.objects.filter(job_id=job_id, cancel_requested=True).exists()

        def progress_cb(current, total, enrollment, student_name, message):
            ResultUploadJob.objects.filter(job_id=job_id).update(
                progress_current=current or 0,
                progress_total=total or 0,
                current_enrollment=(enrollment or ""),
                current_student_name=(student_name or ""),
                message=(message or "Processing result upload..."),
                updated_at=timezone.now(),
            )

        module = AcademicModule.objects.filter(id=module_id).first()
        if not module:
            raise Exception("Module not found")

        with open(temp_path, "rb") as f:
            payload = _process_result_upload(
                module=module,
                username=username,
                test_name=test_name,
                subject_id=subject_id,
                upload_mode=upload_mode,
                bulk_confirm=bulk_confirm,
                file_obj=f,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
            )

        if cancel_cb():
            ResultUploadJob.objects.filter(job_id=job_id).update(
                status=ResultUploadJob.STATUS_CANCELLED,
                message="Upload cancelled.",
                updated_at=timezone.now(),
            )
            return

        ResultUploadJob.objects.filter(job_id=job_id).update(
            status=ResultUploadJob.STATUS_COMPLETED,
            message="Upload completed.",
            result_payload=payload,
            progress_current=1,
            progress_total=1,
            updated_at=timezone.now(),
        )
    except Exception as exc:
        cancelled = ResultUploadJob.objects.filter(job_id=job_id, cancel_requested=True).exists()
        ResultUploadJob.objects.filter(job_id=job_id).update(
            status=(ResultUploadJob.STATUS_CANCELLED if cancelled else ResultUploadJob.STATUS_FAILED),
            message=("Upload cancelled." if cancelled else str(exc)),
            updated_at=timezone.now(),
        )
    finally:
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        close_old_connections()


@login_required
@require_http_methods(["GET"])
def upload_results_progress(request, job_id):
    if "mentor" in request.session:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=403)
    module = _active_module(request)
    job = ResultUploadJob.objects.filter(job_id=job_id, module=module).first()
    if not job:
        return JsonResponse({"ok": False, "msg": "Job not found"}, status=404)
    return JsonResponse(
        {
            "ok": True,
            "job_id": job.job_id,
            "status": job.status,
            "message": job.message or "",
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
            "current_enrollment": job.current_enrollment or "",
            "current_student_name": job.current_student_name or "",
            "result": job.result_payload or {},
        }
    )


def _to_ist_datetime_text(dt):
    if not dt:
        return "-", "-"
    local_dt = dt.astimezone(IST)
    return local_dt.strftime("%d-%m-%Y"), local_dt.strftime("%I:%M %p")


def _call_status_text(status):
    if status == "received":
        return "Received"
    if status == "not_received":
        return "Not Received"
    return "Pending"


def _exam_name_for_sif(test_name):
    test = (test_name or "").upper()
    if test == "T1":
        return "T1"
    if test == "T2":
        return "T2 / (T1+T2)"
    if test == "T3":
        return "T3 / (T1+T2+T3)"
    if test == "T4":
        return "T4 / (T1+T2+T3+T4)"
    if test == "REMEDIAL":
        return "REM"
    return test_name or "-"


def _result_thresholds(test_name):
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


def _test_sort_key(test_name):
    order = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "REMEDIAL": 5}
    return order.get((test_name or "").upper(), 99)


def _subject_sort_key(subject_name):
    name = (subject_name or "").strip().lower()
    priority = ["mathematics", "java", "physics", "software engineering"]
    for idx, token in enumerate(priority, start=1):
        if token in name:
            return idx
    return 99


@login_required
@require_http_methods(["POST"])
def upload_results_cancel(request, job_id):
    if "mentor" in request.session:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=403)
    module = _active_module(request)
    updated = ResultUploadJob.objects.filter(
        job_id=job_id,
        module=module,
        status__in=[ResultUploadJob.STATUS_QUEUED, ResultUploadJob.STATUS_RUNNING],
    ).update(cancel_requested=True, message="Cancelling upload...", updated_at=timezone.now())
    if not updated:
        return JsonResponse({"ok": False, "msg": "Upload is already finished."})
    return JsonResponse({"ok": True, "msg": "Cancel requested."})


@login_required
@require_http_methods(["GET", "POST"])
def upload_results(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)

    if request.method == "GET":
        return render(
            request,
            "upload_results.html",
            {
                "tests": TEST_NAMES,
                "subjects": Subject.objects.filter(module=module, is_active=True).order_by("name"),
            },
        )

    try:
        test_name = (request.POST.get("test_name") or "").strip().upper()
        subject_id = request.POST.get("subject_id")
        upload_mode = (request.POST.get("upload_mode") or "subject").strip().lower()
        bulk_confirm = (request.POST.get("bulk_confirm") or "").strip().lower()
        file_obj = request.FILES.get("result_file")

        allowed_tests = set(TEST_NAMES) | {"ALL_EXAMS"}
        if test_name not in allowed_tests:
            return JsonResponse({"ok": False, "msg": "Invalid test name"})
        if not subject_id:
            return JsonResponse({"ok": False, "msg": "Subject is required"})
        if not file_obj:
            return JsonResponse({"ok": False, "msg": "Result file is required"})
        if upload_mode not in {"subject", "compiled"}:
            return JsonResponse({"ok": False, "msg": "Invalid upload mode"})

        is_all_tests = test_name == "ALL_EXAMS"
        is_all_subjects = str(subject_id).upper() == "ALL"
        if is_all_tests != is_all_subjects:
            return JsonResponse({"ok": False, "msg": "Please select BOTH ALL EXAMS and ALL subjects for bulk upload."})
        if is_all_tests and is_all_subjects and upload_mode != "compiled":
            return JsonResponse({"ok": False, "msg": "ALL_EXAMS + ALL subjects is supported only for Compiled sheet mode."})
        if is_all_tests and is_all_subjects and bulk_confirm != "yes":
            return JsonResponse({"ok": False, "msg": "Bulk upload cancelled. Please select YES to replace old uploads."})

        suffix = os.path.splitext(getattr(file_obj, "name", ""))[1] or ".xlsx"
        fd, temp_path = tempfile.mkstemp(prefix="result_upload_", suffix=suffix, dir=tempfile.gettempdir())
        with os.fdopen(fd, "wb") as tmp:
            for chunk in file_obj.chunks():
                tmp.write(chunk)

        job_key = str(uuid.uuid4())
        job = ResultUploadJob.objects.create(
            job_id=job_key,
            module=module,
            created_by=request.user.username,
            status=ResultUploadJob.STATUS_QUEUED,
            message="Upload queued...",
        )

        t = threading.Thread(
            target=_run_result_upload_job,
            kwargs={
                "job_id": job.job_id,
                "module_id": module.id,
                "username": request.user.username,
                "test_name": test_name,
                "subject_id": str(subject_id),
                "upload_mode": upload_mode,
                "bulk_confirm": bulk_confirm,
                "temp_path": temp_path,
            },
            daemon=True,
        )
        t.start()
        return JsonResponse({"ok": True, "job_id": job.job_id})
    except Exception as e:
        return JsonResponse({"ok": False, "msg": str(e)})


@login_required
def view_results(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)

    subjects = list(Subject.objects.filter(module=module, is_active=True).order_by("name"))
    selected_test = (request.GET.get("test") or "").upper()
    selected_subject = request.GET.get("subject")
    selected_filter = request.GET.get("filter", "either_fail")
    mentor_filter = request.GET.get("mentor", "")
    sort = request.GET.get("sort", "roll")
    direction = request.GET.get("dir", "asc")

    latest_upload = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at").first()
    if not selected_test and not selected_subject and latest_upload:
        selected_test = latest_upload.test_name
        selected_subject = str(latest_upload.subject_id)

    if selected_test not in TEST_NAMES:
        selected_test = latest_upload.test_name if latest_upload else "T1"

    if not selected_subject and subjects:
        selected_subject = str(subjects[0].id)

    uploads = ResultUpload.objects.filter(module=module).select_related("subject").order_by("test_name", "subject__name")
    upload_map = {(u.test_name, str(u.subject_id)): u for u in uploads}
    selected_upload = upload_map.get((selected_test, str(selected_subject))) if selected_subject else None
    if not selected_upload and latest_upload and not request.GET.get("test") and not request.GET.get("subject"):
        selected_upload = latest_upload
        selected_test = latest_upload.test_name
        selected_subject = str(latest_upload.subject_id)

    matrix_rows = []
    for test in TEST_NAMES:
        cells = []
        for s in subjects:
            up = upload_map.get((test, str(s.id)))
            applicable = True
            if s.result_format == Subject.FORMAT_T4_ONLY and test != "T4":
                applicable = False
            cells.append({"subject": s, "upload": up, "applicable": applicable})
        matrix_rows.append({"test": test, "cells": cells})

    config = _result_filter_config(selected_test)
    records = []
    rows = []
    total_count = 0
    mentor_counts = []
    upload_waiting = False

    if selected_subject and not selected_upload:
        upload_waiting = True

    if selected_upload:
        base_qs = (
            StudentResult.objects.filter(upload=selected_upload)
            .select_related("student", "student__mentor", "upload", "upload__subject")
        )
        if selected_filter == config["current_key"]:
            base_qs = base_qs.filter(marks_current__lt=config["current_threshold"])
        elif selected_filter == config["total_key"]:
            base_qs = base_qs.filter(marks_total__lt=config["total_threshold"])
        elif selected_filter == config["either_key"]:
            base_qs = base_qs.filter(
                Q(marks_current__lt=config["current_threshold"]) |
                Q(marks_total__lt=config["total_threshold"])
            )

        mentor_counts = (
            base_qs.values("student__mentor__name")
            .annotate(c=Count("id"))
            .order_by("student__mentor__name")
        )
        total_count_all = base_qs.count()

        qs = base_qs
        if mentor_filter:
            qs = qs.filter(student__mentor__name=mentor_filter)

        sort_map = {
            "roll": "student__roll_no",
            "enroll": "student__enrollment",
            "name": "student__name",
            "mentor": "student__mentor__name",
            "exam": "marks_current",
            "total": "marks_total",
        }
        order = sort_map.get(sort, "student__roll_no")
        if direction == "desc":
            order = "-" + order
        records = qs.order_by(order)
        total_count = records.count()

        # Build previous-upload comparison maps for changed historical marks (same subject only).
        prev_mark_map = {}
        for prev_test in ["T1", "T2", "T3"]:
            prev_upload = (
                ResultUpload.objects.filter(module=module, test_name=prev_test, subject_id=selected_upload.subject_id)
                .order_by("-uploaded_at")
                .first()
            )
            if not prev_upload:
                continue
            prev_rows = StudentResult.objects.filter(upload=prev_upload).values("student_id", "marks_current")
            prev_mark_map[prev_test] = {r["student_id"]: r["marks_current"] for r in prev_rows}

        display_columns = config["display_columns"]
        for r in records:
            row_cells = []
            for col in display_columns:
                key = col["key"]
                value = None
                if key == "marks_t4_half":
                    value = (r.marks_current / 2.0) if r.marks_current is not None else None
                else:
                    value = getattr(r, key, None)

                changed = False
                hover = ""
                if selected_test in {"T2", "T3", "T4"} and key in {"marks_t1", "marks_t2", "marks_t3"}:
                    ref_test = "T1" if key == "marks_t1" else ("T2" if key == "marks_t2" else "T3")
                    prev_value = prev_mark_map.get(ref_test, {}).get(r.student_id)
                    if prev_value is not None and value is not None and float(prev_value) != float(value):
                        changed = True
                        hover = f"Previous {ref_test}: {prev_value}"

                row_cells.append(
                    {
                        "key": key,
                        "label": col["label"],
                        "value": value,
                        "is_changed": changed,
                        "hover": hover,
                    }
                )

            rows.append(
                {
                    "roll_no": r.student.roll_no,
                    "enrollment": r.enrollment,
                    "name": r.student.name,
                    "mentor": r.student.mentor.name,
                    "cells": row_cells,
                }
            )
    else:
        total_count_all = 0

    return render(
        request,
        "view_results.html",
        {
            "tests": TEST_NAMES,
            "subjects": subjects,
            "matrix_rows": matrix_rows,
            "selected_test": selected_test,
            "selected_subject": str(selected_subject or ""),
            "selected_upload": selected_upload,
            "upload_waiting": upload_waiting,
            "records": records,
            "rows": rows,
            "mentor_counts": mentor_counts,
            "total_count": total_count,
            "filter": selected_filter,
            "filter_current_key": config["current_key"],
            "filter_current_label": config["current_label"],
            "filter_total_key": config["total_key"],
            "filter_total_label": config["total_label"],
            "filter_either_key": config["either_key"],
            "filter_either_label": config["either_label"],
            "exam_col_label": config["exam_col_label"],
            "total_col_label": config["total_col_label"],
            "display_columns": config["display_columns"],
            "table_colspan": 4 + len(config["display_columns"]),
            "current_threshold": config["current_threshold"],
            "total_threshold": config["total_threshold"],
            "mentor_filter": mentor_filter,
            "total_count_all": total_count_all,
            "sort": sort,
            "dir": direction,
            "dir_roll": next_dir(sort, direction, "roll"),
            "dir_enroll": next_dir(sort, direction, "enroll"),
            "dir_name": next_dir(sort, direction, "name"),
            "dir_mentor": next_dir(sort, direction, "mentor"),
            "dir_exam": next_dir(sort, direction, "exam"),
            "dir_total": next_dir(sort, direction, "total"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def view_practical_marks(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    msg = ""
    if request.method == "POST":
        try:
            f = request.FILES.get("practical_file")
            if not f:
                raise Exception("Please select practical marks file.")
            summary = import_practical_marks(f, module=module, uploaded_by=request.user.username)
            msg = (
                f"Uploaded practical marks ({summary.get('mode','-')} mode). "
                f"Rows: {summary['rows_total']}, matched: {summary['rows_matched']}."
            )
        except Exception as exc:
            msg = f"Upload failed: {exc}"

    subjects = ordered_subjects(module)
    students = list(Student.objects.filter(module=module).select_related("mentor").order_by("roll_no", "name"))
    marks_qs = StudentPracticalMark.objects.filter(module=module).select_related("subject", "student")
    mark_map = {(m.student_id, m.subject_id): m for m in marks_qs}
    rows = []
    for s in students:
        row = {"student": s, "cells": []}
        for subj in subjects:
            pm = mark_map.get((s.id, subj.id))
            pr = _fmt_mark(pm.pr_marks) if pm and pm.pr_marks is not None else "-"
            att = _fmt_mark(pm.attendance_percentage) if pm and pm.attendance_percentage is not None else "-"
            row["cells"].append({"subject": subj, "pr": pr, "att": att})
        rows.append(row)

    latest_upload = PracticalMarkUpload.objects.filter(module=module).order_by("-uploaded_at").first()
    return render(
        request,
        "view_practical_marks.html",
        {
            "message": msg,
            "subjects": subjects,
            "rows": rows,
            "latest_upload": latest_upload,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def sif_marks_template(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    _ensure_subject_display_order(module)
    students = list(Student.objects.filter(module=module).select_related("mentor").order_by("roll_no", "name"))
    selected_enrollment = request.GET.get("enrollment") or (students[0].enrollment if students else "")
    selected_student = Student.objects.filter(module=module, enrollment=selected_enrollment).first() if selected_enrollment else None

    lock_obj, _ = SifMarksLock.objects.get_or_create(module=module)
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "lock":
            lock_obj.locked = True
            lock_obj.locked_by = request.user.username
            lock_obj.locked_at = timezone.now()
            lock_obj.save(update_fields=["locked", "locked_by", "locked_at"])
            messages.success(request, "SIF marks view locked.")
        elif action == "unlock":
            lock_obj.locked = False
            lock_obj.save(update_fields=["locked"])
            messages.success(request, "SIF marks view unlocked.")
        elif action in {"move_up", "move_down"}:
            if lock_obj.locked:
                messages.error(request, "Unlock first to change sequence.")
            else:
                sid = request.POST.get("subject_id")
                subj = Subject.objects.filter(module=module, id=sid, is_active=True).first()
                if subj:
                    subjects = ordered_subjects(module)
                    ids = [s.id for s in subjects]
                    try:
                        idx = ids.index(subj.id)
                    except ValueError:
                        idx = -1
                    if idx >= 0:
                        swap_idx = idx - 1 if action == "move_up" else idx + 1
                        if 0 <= swap_idx < len(subjects):
                            a = subjects[idx]
                            b = subjects[swap_idx]
                            a.display_order, b.display_order = b.display_order, a.display_order
                            a.save(update_fields=["display_order"])
                            b.save(update_fields=["display_order"])
        return redirect(f"/sif-marks-template/?enrollment={selected_enrollment}")

    marks_rows = _sif_marks_rows_for_student(selected_student, module) if selected_student else []
    return render(
        request,
        "sif_marks_template.html",
        {
            "students": students,
            "selected_student": selected_student,
            "selected_enrollment": selected_enrollment,
            "marks_rows": marks_rows,
            "lock_obj": lock_obj,
            "subjects_ordered": ordered_subjects(module),
        },
    )


@login_required
def subjects_page(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    subjects = list(Subject.objects.filter(module=module).order_by("name"))
    is_superadmin = is_superadmin_user(getattr(request, "user", None))
    if is_superadmin:
        for s in subjects:
            template, _ = SubjectTemplate.objects.update_or_create(
                name=s.name,
                defaults={
                    "short_name": s.short_name or s.name,
                    "has_theory": s.has_theory,
                    "has_practical": s.has_practical,
                    "result_format": s.result_format,
                    "is_active": True,
                },
            )
            if s.source_template_id != template.id:
                s.source_template = template
                s.save(update_fields=["source_template"])
    templates = list(SubjectTemplate.objects.filter(is_active=True).order_by("name"))
    selected_template_ids = {s.source_template_id for s in subjects if s.source_template_id}
    if not selected_template_ids:
        template_name_map = {t.name.lower(): t.id for t in templates}
        for s in subjects:
            t_id = template_name_map.get((s.name or "").strip().lower())
            if t_id:
                selected_template_ids.add(t_id)
    return render(
        request,
        "subjects.html",
        {
            "subjects": subjects,
            "available_templates": templates,
            "selected_template_ids": selected_template_ids,
            "is_superadmin": is_superadmin,
            "format_full": Subject.FORMAT_FULL,
            "format_t4_only": Subject.FORMAT_T4_ONLY,
        },
    )


@login_required
@require_http_methods(["POST"])
def add_subject(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    name = (request.POST.get("name") or "").strip()
    short_name = (request.POST.get("short_name") or "").strip()
    result_format = (request.POST.get("result_format") or Subject.FORMAT_FULL).strip()
    has_theory = bool(request.POST.get("has_theory"))
    has_practical = bool(request.POST.get("has_practical"))
    if not name:
        messages.error(request, "Subject name is required.")
        return redirect("/subjects/")
    if not short_name:
        short_name = name
    if not has_theory:
        # PR-only subject does not use theory cycle format selection.
        result_format = Subject.FORMAT_FULL
    if result_format not in {Subject.FORMAT_FULL, Subject.FORMAT_T4_ONLY}:
        result_format = Subject.FORMAT_FULL
    subject, created = Subject.objects.get_or_create(
        module=module,
        name=name,
        defaults={
            "is_active": True,
            "result_format": result_format,
            "short_name": short_name,
            "display_order": (Subject.objects.filter(module=module).aggregate(mx=Max("display_order")).get("mx") or 0) + 1,
            "has_theory": has_theory,
            "has_practical": has_practical,
        },
    )
    if not created:
        subject.short_name = short_name
        subject.result_format = result_format
        subject.has_theory = has_theory
        subject.has_practical = has_practical
        subject.is_active = True
        subject.save(update_fields=["short_name", "result_format", "has_theory", "has_practical", "is_active"])
    if is_superadmin_user(getattr(request, "user", None)):
        template, _ = SubjectTemplate.objects.update_or_create(
            name=name,
            defaults={
                "short_name": short_name,
                "has_theory": has_theory,
                "has_practical": has_practical,
                "result_format": result_format,
                "is_active": True,
            },
        )
        if subject.source_template_id != template.id:
            subject.source_template = template
            subject.save(update_fields=["source_template"])
    messages.success(request, "Subject saved.")
    return redirect("/subjects/")


@login_required
@require_http_methods(["POST"])
def edit_subject(request, subject_id):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    name = (request.POST.get("name") or "").strip()
    short_name = (request.POST.get("short_name") or "").strip()
    result_format = (request.POST.get("result_format") or Subject.FORMAT_FULL).strip()
    has_theory = bool(request.POST.get("has_theory"))
    has_practical = bool(request.POST.get("has_practical"))
    if not name:
        messages.error(request, "Subject name is required.")
        return redirect("/subjects/")
    subject = Subject.objects.filter(id=subject_id, module=module).first()
    if subject:
        subject.name = name
        subject.short_name = short_name or name
        if not has_theory:
            result_format = Subject.FORMAT_FULL
        if result_format not in {Subject.FORMAT_FULL, Subject.FORMAT_T4_ONLY}:
            result_format = Subject.FORMAT_FULL
        subject.result_format = result_format
        subject.has_theory = has_theory
        subject.has_practical = has_practical
        subject.save(update_fields=["name", "short_name", "result_format", "has_theory", "has_practical"])
        if is_superadmin_user(getattr(request, "user", None)):
            template = subject.source_template
            if not template:
                template, _ = SubjectTemplate.objects.get_or_create(name=name)
            template.name = name
            template.short_name = subject.short_name
            template.has_theory = has_theory
            template.has_practical = has_practical
            template.result_format = result_format
            template.is_active = True
            template.save()
            if subject.source_template_id != template.id:
                subject.source_template = template
                subject.save(update_fields=["source_template"])
        messages.success(request, "Subject updated.")
    return redirect("/subjects/")


@login_required
@require_http_methods(["POST"])
def apply_subject_templates(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    selected_ids = {
        int(x)
        for x in request.POST.getlist("template_ids")
        if str(x).isdigit()
    }
    templates = list(SubjectTemplate.objects.filter(is_active=True).order_by("name"))
    template_map = {t.id: t for t in templates}

    for template in templates:
        existing = Subject.objects.filter(module=module, source_template=template).first()
        if template.id in selected_ids:
            if existing:
                changed_fields = []
                if existing.is_active is False:
                    existing.is_active = True
                    changed_fields.append("is_active")
                if changed_fields:
                    existing.save(update_fields=changed_fields)
            else:
                Subject.objects.create(
                    module=module,
                    source_template=template,
                    name=template.name,
                    short_name=template.short_name or template.name,
                    has_theory=template.has_theory,
                    has_practical=template.has_practical,
                    result_format=template.result_format,
                    is_active=True,
                    display_order=(Subject.objects.filter(module=module).aggregate(mx=Max("display_order")).get("mx") or 0) + 1,
                )
        else:
            if existing and existing.is_active:
                existing.is_active = False
                existing.save(update_fields=["is_active"])

    for template_id in selected_ids:
        template = template_map.get(template_id)
        if not template:
            continue
        existing_by_name = Subject.objects.filter(module=module, name=template.name).first()
        if existing_by_name and not existing_by_name.source_template_id:
            existing_by_name.source_template = template
            existing_by_name.save(update_fields=["source_template"])

    messages.success(request, "Subject selection updated for this module.")
    return redirect("/subjects/")


@login_required
@require_http_methods(["POST"])
def delete_subject(request, subject_id):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)
    subject = Subject.objects.filter(id=subject_id, module=module).first()
    if subject:
        subject.is_active = False
        subject.save(update_fields=["is_active"])
        messages.success(request, "Subject archived.")
    return redirect("/subjects/")

def next_dir(current_sort, current_dir, column):
    if current_sort == column and current_dir == "asc":
        return "desc"
    return "asc"


def view_attendance(request):

    # mentors should not access coordinator view
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)

    # get available weeks
    weeks = Attendance.objects.filter(student__module=module).values_list("week_no", flat=True)\
                              .distinct().order_by("week_no")

    selected_week = request.GET.get("week")
    # If no week selected → auto open latest week
    if not selected_week:
        latest = Attendance.objects.filter(student__module=module).order_by("-week_no").first()
        if latest:
            selected_week = latest.week_no
    filter_type = request.GET.get("filter", "all")
    mentor_filter = request.GET.get("mentor")
    sort = request.GET.get("sort", "roll")
    direction = request.GET.get("dir", "asc")

    records = None
    mentor_counts = []
    total_count = 0

    # load data only when week selected
    if selected_week:
        selected_week = int(selected_week)

        qs = Attendance.objects.filter(week_no=selected_week, student__module=module)\
            .select_related("student", "student__mentor")

        # ---------- FILTERS ----------
        if filter_type == "weekly":
            qs = qs.filter(week_percentage__lt=80)

        elif filter_type == "overall":
            qs = qs.filter(overall_percentage__lt=80)

        elif filter_type == "either":
            qs = qs.filter(call_required=True)
        
        if mentor_filter:
            qs = qs.filter(student__mentor__name=mentor_filter)

        # ---------- SORTING ----------
        sort_map = {
            "roll": "student__roll_no",
            "enroll": "student__enrollment",
            "name": "student__name",
            "mentor": "student__mentor__name",
            "week": "week_percentage",
            "overall": "overall_percentage",
        }

        order = sort_map.get(sort, "student__roll_no")
        if direction == "desc":
            order = "-" + order

        records = qs.order_by(order)

        # ---------- COUNTS ----------
        mentor_counts = (
            records.values("student__mentor__name")
            .annotate(c=Count("id"))
            .order_by("student__mentor__name")
        )

        total_count = records.count()

    # ---------- ALWAYS RETURN ----------
    return render(request, "view_attendance.html", {
        "weeks": weeks,
        "records": records,
        "selected_week": selected_week,
        "filter": filter_type,
        "sort": sort,
        "dir": direction,
        "mentor_filter": mentor_filter,
        
        # sorting toggle directions
        "dir_roll": next_dir(sort, direction, "roll"),
        "dir_enroll": next_dir(sort, direction, "enroll"),
        "dir_name": next_dir(sort, direction, "name"),
        "dir_mentor": next_dir(sort, direction, "mentor"),
        "dir_week": next_dir(sort, direction, "week"),
        "dir_overall": next_dir(sort, direction, "overall"),

        # counts
        "mentor_counts": mentor_counts,
        "total_count": total_count,
    })



# ---------------- DELETE WEEK ----------------
def delete_week(request):
    module = _active_module(request)

    weeks = Attendance.objects.filter(student__module=module).values_list("week_no", flat=True)\
                              .distinct().order_by("week_no")

    message = ""

    # DELETE SINGLE WEEK
    if request.method == "POST" and "delete_week" in request.POST:
        week_no = int(request.POST.get("week"))

        Attendance.objects.filter(week_no=week_no, student__module=module).delete()
        CallRecord.objects.filter(week_no=week_no, student__module=module).delete()

        message = f"Week-{week_no} deleted successfully"

    # DELETE ALL (password protected)
    if request.method == "POST" and "delete_all" in request.POST:

        password = request.POST.get("password")
        user = authenticate(username=request.user.username, password=password)

        if user:
            Attendance.objects.filter(student__module=module).delete()
            CallRecord.objects.filter(student__module=module).delete()
            message = "ALL WEEKS DELETED"
        else:
            message = "Wrong password"

    return render(request, "delete_week.html", {
        "weeks": weeks,
        "message": message
    })


@login_required
def delete_results(request):
    if "mentor" in request.session:
        return redirect("/")
    module = _active_module(request)

    uploads = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at")
    message = ""

    if request.method == "POST" and "delete_upload" in request.POST:
        upload_id = request.POST.get("upload_id")
        upload = ResultUpload.objects.filter(id=upload_id, module=module).select_related("subject").first()
        if upload:
            label = f"{upload.test_name} - {upload.subject.name}"
            upload.delete()
            message = f"Deleted result upload: {label}"
        else:
            message = "Upload not found."

    if request.method == "POST" and "delete_all" in request.POST:
        password = request.POST.get("password")
        user = authenticate(username=request.user.username, password=password)
        if user:
            ResultUpload.objects.filter(module=module).delete()
            message = "ALL RESULT UPLOADS DELETED"
        else:
            message = "Wrong password"

    uploads = ResultUpload.objects.filter(module=module).select_related("subject").order_by("-uploaded_at")
    return render(
        request,
        "delete_results.html",
        {
            "uploads": uploads,
            "message": message,
        },
    )


# ---------------- LOCK WEEK ----------------
def lock_week(request):
    module = _active_module(request)
    if request.method == "POST":
        week = int(request.POST.get("week"))
        WeekLock.objects.update_or_create(
            module=module,
            week_no=week,
            defaults={"locked": True}
        )
        return redirect(f"/reports/?week={week}")
    return redirect("/reports/")


# ---------------- MENTOR DASHBOARD ----------------
def mentor_dashboard(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)

    # all uploaded weeks
    weeks = sorted(
        Attendance.objects.filter(student__module=module).values_list("week_no", flat=True).distinct()
    )

    # selected week
    selected_week = request.GET.get("week")

    if not selected_week and weeks:
        selected_week = weeks[-1]
    else:
        selected_week = int(selected_week) if selected_week else None

    records = []

    # build attendance map
    attendance_map = {}
    if selected_week:
        atts = Attendance.objects.filter(week_no=selected_week, student__mentor=mentor, student__module=module)
        for a in atts:
            attendance_map[a.student_id] = a
    
    all_done = False
    not_connected = []

    if selected_week:
        latest_by_student = _latest_attendance_calls_map(module, selected_week, mentor=mentor)
        status_weight = {None: 0, "": 0, "not_received": 1, "received": 2}
        records = sorted(
            list(latest_by_student.values()),
            key=lambda c: (status_weight.get(c.final_status, 0), c.student.roll_no or 999999),
        )
        total = len(records)
        finished = len([c for c in records if c.final_status in {"received", "not_received"}])

        if total > 0 and total == finished:
            all_done = True
            not_connected = [c for c in records if c.final_status == "not_received"]

    
    return render(request,"mentor_dashboard.html",{
        "mentor": mentor,
        "weeks": weeks,
        "selected_week": selected_week,
        "records": records,
        "attendance_map": attendance_map,
        "all_done": all_done,
        "not_connected": not_connected
    })
def mentor_other_calls(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    students = Student.objects.filter(module=module, mentor=mentor).order_by("roll_no", "name")

    qs = (
        OtherCallRecord.objects.filter(mentor=mentor, student__module=module, student__in=students)
        .select_related("student")
        .order_by("student_id", "-attempt1_time", "-created_at", "-id")
    )
    latest_by_student = {}
    for rec in qs:
        if rec.student_id not in latest_by_student:
            latest_by_student[rec.student_id] = rec

    status_weight = {None: 0, "": 0, "not_received": 1, "received": 2}
    records = []
    for s in students:
        latest = latest_by_student.get(s.id)
        records.append(
            {
                "id": s.id,  # button uses student id; each save creates a new immutable call record
                "student": s,
                "final_status": (latest.final_status if latest else None),
            }
        )

    records = sorted(records, key=lambda x: (status_weight.get(x.get("final_status"), 0), x["student"].roll_no or 999999))
    return render(
        request,
        "mentor_other_calls.html",
        {
            "mentor": mentor,
            "records": records,
        },
    )


def save_other_call(request):
    if request.method != "POST":
        return JsonResponse({"ok": False})

    mentor = _session_mentor_obj(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _active_module(request)

    raw_id = request.POST.get("id")
    student = Student.objects.select_related("mentor").filter(
        id=raw_id,
        module=module,
        mentor=mentor,
    ).first()
    if not student:
        # Backward compatibility: old UI may still send call record id.
        previous = (
            OtherCallRecord.objects.select_related("student", "mentor")
            .filter(id=raw_id, mentor=mentor, student__module=module)
            .first()
        )
        student = previous.student if previous else None
    if not student:
        return JsonResponse({"ok": False, "msg": "Student not found"}, status=404)

    status = request.POST.get("status")
    talked = request.POST.get("talked")
    duration = request.POST.get("duration")
    remark = request.POST.get("remark")
    call_reason = request.POST.get("call_reason")
    target = request.POST.get("target")
    call_category = (request.POST.get("call_category") or "other").strip().lower()
    week_no_raw = (request.POST.get("week_no") or "").strip()
    day_no_raw = (request.POST.get("day_no") or "").strip()
    exam_name = (request.POST.get("exam_name") or "").strip()
    subject_name = (request.POST.get("subject_name") or "").strip()
    marks_obtained_raw = (request.POST.get("marks_obtained") or "").strip()
    marks_out_of_raw = (request.POST.get("marks_out_of") or "").strip()

    now_ts = timezone.now()
    call = OtherCallRecord(
        student=student,
        mentor=mentor,
        attempt1_time=now_ts,
    )

    if target in {"student", "father"}:
        call.last_called_target = target
    if call_category not in {"less_attendance", "poor_result", "other", "mentor_intro"}:
        call_category = "other"
    call.call_category = call_category

    if call_category == "less_attendance":
        try:
            week_no = int(week_no_raw)
            day_no = int(day_no_raw)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "msg": "Week number and day number are required."}, status=400)

        # Store as a new attendance call record (append-only; never overwrite old call history).
        attendance_call = CallRecord(
            student=student,
            week_no=week_no,
            attempt1_time=timezone.now(),
        )

        parent_text = (remark or "Sick").strip()
        faculty_text = (call_reason or f"Absent on WK-{week_no} DAY-{day_no}").strip()
        attendance_call.talked_with = talked or "father"
        attendance_call.duration = duration or ""
        attendance_call.parent_reason = f"PARENT::{parent_text}||FACULTY::{faculty_text}"
        if status in {"received", "not_received"}:
            attendance_call.final_status = status
        attendance_call.save()
        call.exam_name = ""
        call.subject_name = ""
        call.marks_obtained = None
        call.marks_out_of = None

    if call_category == "poor_result":
        if not exam_name or not subject_name:
            return JsonResponse({"ok": False, "msg": "Exam name and subject name are required."}, status=400)
        call.exam_name = exam_name
        call.subject_name = subject_name
        try:
            call.marks_obtained = float(marks_obtained_raw) if marks_obtained_raw else None
            call.marks_out_of = float(marks_out_of_raw) if marks_out_of_raw else None
        except ValueError:
            return JsonResponse({"ok": False, "msg": "Marks must be numeric."}, status=400)
    elif call_category == "other":
        call.exam_name = ""
        call.subject_name = ""
        call.marks_obtained = None
        call.marks_out_of = None

    if status == "received":
        call.final_status = "received"
        call.talked_with = talked
        call.duration = duration
        if call_category == "poor_result":
            call.parent_remark = (remark or "Student will Study more").strip()
        else:
            call.parent_remark = remark or ""
        call.call_done_reason = call_reason or ""
    elif status == "not_received":
        call.final_status = "not_received"
        call.call_done_reason = call_reason or call.call_done_reason

    call.save()
    return JsonResponse({"ok": True})


# ---------------- SAVE CALL ----------------
def save_call(request):

    if request.method == "POST":
        module = _active_module(request)
        raw_id = request.POST.get("id")
        week_no = request.GET.get("week") or request.POST.get("week") or request.session.get("selected_week")
        try:
            week_no = int(week_no)
        except Exception:
            week_no = None

        student = Student.objects.filter(id=raw_id, module=module).first()
        if not student:
            # Backward compatibility: old payload may still send call record id.
            prev_call = CallRecord.objects.select_related("student").filter(id=raw_id, student__module=module).first()
            student = prev_call.student if prev_call else None
            if not week_no and prev_call:
                week_no = prev_call.week_no
        if not student or not week_no:
            return JsonResponse({"ok": False, "msg": "Invalid student/week"}, status=400)

        status = request.POST.get("status")
        talked = request.POST.get("talked")
        duration = request.POST.get("duration")
        reason = request.POST.get("reason")

        call = CallRecord(
            student=student,
            week_no=week_no,
            attempt1_time=timezone.now(),
        )

        if status == "received":
            call.final_status = "received"
            call.talked_with = talked
            call.duration = duration
            call.parent_reason = reason
        elif status == "not_received":
            call.final_status = "not_received"

        call.save()
        return JsonResponse({"ok": True})


# ---------------- MESSAGE SENT ----------------
def mark_message(request):
    if request.method=="POST":
        module = _active_module(request)
        raw_id = request.POST.get("id")
        week_no = request.GET.get("week") or request.POST.get("week") or request.session.get("selected_week")
        try:
            week_no = int(week_no)
        except Exception:
            week_no = None

        student = Student.objects.filter(id=raw_id, module=module).first()
        source_call = None
        if not student:
            source_call = CallRecord.objects.select_related("student").filter(id=raw_id, student__module=module).first()
            student = source_call.student if source_call else None
            if not week_no and source_call:
                week_no = source_call.week_no
        if not student or not week_no:
            return JsonResponse({"ok": False, "msg": "Invalid student/week"}, status=400)

        if not source_call:
            source_call = (
                CallRecord.objects.filter(student=student, week_no=week_no)
                .order_by("-attempt1_time", "-attempt2_time", "-created_at", "-id")
                .first()
            )
        call = CallRecord(
            student=student,
            week_no=week_no,
            attempt1_time=timezone.now(),
            final_status=(source_call.final_status if source_call else None),
            talked_with=(source_call.talked_with if source_call else None),
            duration=(source_call.duration if source_call else ""),
            parent_reason=(source_call.parent_reason if source_call else ""),
            message_sent=True,
        )
        call.save()
        return JsonResponse({"ok":True})


# ---------------- MENTOR REPORT ----------------
def mentor_report(request):
    mentor_obj = _session_mentor_obj(request)
    if not mentor_obj:
        return redirect("/")
    module = _active_module(request)

    week = request.GET.get("week")
    if not week:
        return render(request,"mentor_report.html")

    week = int(week)

    students = Student.objects.filter(module=module, mentor=mentor_obj).count()

    below80 = Attendance.objects.filter(
        week_no=week, student__mentor=mentor_obj, student__module=module, call_required=True
    ).count()

    latest_calls = _latest_attendance_calls_map(module, week, mentor=mentor_obj)
    calls_done = len([c for c in latest_calls.values() if c.final_status in {"received", "not_received"}])
    received = len([c for c in latest_calls.values() if c.final_status == "received"])
    not_received = len([c for c in latest_calls.values() if c.final_status == "not_received"])
    message_done = len([c for c in latest_calls.values() if c.message_sent])

    not_done = below80 - calls_done

    report = f"""
Follow up Attendance < 80% (Week-{week} only & Overall Week-01 to {week}):

Mentor Name: {mentor_obj.name}
Total no. Of students under mentorship: {students}
No. Of students under mentorship whose attendance < 80%: {below80}
No. Of call done: {calls_done}
No. Of call received: {received}
No. Of call not received: {not_received}
No. Of message done when call not received: {message_done}
Call not done: {not_done}
"""

    return render(request,"mentor_report.html",{"report":report,"week":week})


def mentor_result_calls(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    uploads = list(
        ResultUpload.objects.filter(module=module, calls__student__mentor=mentor, calls__student__module=module)
        .distinct()
        .order_by("-uploaded_at")
    )

    selected_upload = None
    upload_id = request.GET.get("upload")
    if upload_id:
        selected_upload = ResultUpload.objects.filter(id=upload_id, module=module).first()
    if not selected_upload and uploads:
        selected_upload = uploads[0]

    records = []
    all_done = False
    not_connected = []
    if selected_upload:
        fail_student_ids = _upload_fail_student_ids(selected_upload)
        latest_map = _latest_result_calls_map(
            selected_upload,
            mentor=mentor,
            module=module,
            student_ids=fail_student_ids,
        )
        records = sorted(
            list(latest_map.values()),
            key=lambda x: (x.student.roll_no or 999999, x.student.name or ""),
        )
        total = len(records)
        finished = len([c for c in records if c.final_status in {"received", "not_received"}])
        if total > 0 and total == finished:
            all_done = True
            not_connected = [c for c in records if c.final_status == "not_received"]

    return render(
        request,
        "mentor_result_calls.html",
        {
            "mentor": mentor,
            "uploads": uploads,
            "selected_upload": selected_upload,
            "records": records,
            "all_done": all_done,
            "not_connected": not_connected,
        },
    )


def save_result_call(request):
    if request.method != "POST":
        return JsonResponse({"ok": False})

    mentor = _session_mentor_obj(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _active_module(request)

    raw_id = request.POST.get("id")
    upload_id = request.POST.get("upload_id")
    upload = ResultUpload.objects.filter(id=upload_id, module=module).first() if upload_id else None

    student = Student.objects.select_related("mentor").filter(
        id=raw_id,
        mentor=mentor,
        module=module,
    ).first()
    source_call = None
    if not student:
        source_call = ResultCallRecord.objects.select_related("student", "upload").filter(
            id=raw_id,
            student__mentor=mentor,
            student__module=module,
        ).first()
        student = source_call.student if source_call else None
        if not upload and source_call:
            upload = source_call.upload
    if not student or not upload:
        return JsonResponse({"ok": False, "msg": "Student/upload not found"}, status=404)

    if not source_call:
        source_call = (
            ResultCallRecord.objects.filter(upload=upload, student=student)
            .order_by("-attempt1_time", "-attempt2_time", "-created_at", "-id")
            .first()
        )
    if not source_call:
        return JsonResponse({"ok": False, "msg": "No result call context found"}, status=404)

    status = request.POST.get("status")
    talked = request.POST.get("talked")
    duration = request.POST.get("duration")
    reason = request.POST.get("reason")

    call = ResultCallRecord(
        upload=upload,
        student=student,
        attempt1_time=timezone.now(),
        fail_reason=(source_call.fail_reason if source_call else ""),
        marks_current=(source_call.marks_current if source_call else 0),
        marks_total=(source_call.marks_total if source_call else None),
        message_sent=(source_call.message_sent if source_call else False),
    )

    if status == "received":
        call.final_status = "received"
        call.talked_with = talked
        call.duration = duration
        call.parent_reason = reason
    elif status == "not_received":
        call.final_status = "not_received"

    call.save()
    return JsonResponse({"ok": True})


def mark_result_message(request):
    if request.method != "POST":
        return JsonResponse({"ok": False})

    mentor = _session_mentor_obj(request)
    if not mentor:
        return JsonResponse({"ok": False, "msg": "Unauthorized"}, status=401)
    module = _active_module(request)

    raw_id = request.POST.get("id")
    upload_id = request.POST.get("upload_id")
    upload = ResultUpload.objects.filter(id=upload_id, module=module).first() if upload_id else None

    student = Student.objects.select_related("mentor").filter(
        id=raw_id,
        mentor=mentor,
        module=module,
    ).first()
    source_call = None
    if not student:
        source_call = ResultCallRecord.objects.select_related("student", "upload").filter(
            id=raw_id,
            student__mentor=mentor,
            student__module=module,
        ).first()
        student = source_call.student if source_call else None
        if not upload and source_call:
            upload = source_call.upload
    if not student or not upload:
        return JsonResponse({"ok": False, "msg": "Student/upload not found"}, status=404)

    if not source_call:
        source_call = (
            ResultCallRecord.objects.filter(upload=upload, student=student)
            .order_by("-attempt1_time", "-attempt2_time", "-created_at", "-id")
            .first()
        )
    if not source_call:
        return JsonResponse({"ok": False, "msg": "No result call context found"}, status=404)
    call = ResultCallRecord(
        upload=upload,
        student=student,
        attempt1_time=timezone.now(),
        final_status=(source_call.final_status if source_call else None),
        talked_with=(source_call.talked_with if source_call else None),
        duration=(source_call.duration if source_call else ""),
        parent_reason=(source_call.parent_reason if source_call else ""),
        message_sent=True,
        fail_reason=(source_call.fail_reason if source_call else ""),
        marks_current=(source_call.marks_current if source_call else 0),
        marks_total=(source_call.marks_total if source_call else None),
    )
    call.save()
    return JsonResponse({"ok": True})


def mentor_result_report(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)

    uploads = list(
        ResultUpload.objects.filter(module=module, calls__student__mentor=mentor, calls__student__module=module)
        .distinct()
        .order_by("-uploaded_at")
    )

    selected_upload = None
    upload_id = request.GET.get("upload")
    if upload_id:
        selected_upload = ResultUpload.objects.filter(id=upload_id, module=module).first()
    if not selected_upload and uploads:
        selected_upload = uploads[0]

    report = ""
    if selected_upload:
        fail_student_ids = _upload_fail_student_ids(selected_upload)
        latest_calls = _latest_result_calls_map(
            selected_upload,
            mentor=mentor,
            module=module,
            student_ids=fail_student_ids,
        )
        total = len(latest_calls)
        received = len([c for c in latest_calls.values() if c.final_status == "received"])
        not_received = len([c for c in latest_calls.values() if c.final_status == "not_received"])
        message_done = len([c for c in latest_calls.values() if c.message_sent])
        report = _result_report_text(
            selected_upload.test_name,
            selected_upload.subject.name,
            mentor.name,
            total,
            received,
            not_received,
            message_done,
        )

    return render(
        request,
        "mentor_result_report.html",
        {
            "uploads": uploads,
            "selected_upload": selected_upload,
            "report": report,
        },
    )


# ---------------- PDF PRINT ----------------
def print_student(request, enrollment):
    if not request.user.is_authenticated and "mentor" not in request.session:
        return redirect("/")

    module = _active_module(request)
    student = Student.objects.select_related("mentor").get(module=module, enrollment=enrollment)
    mentor = _session_mentor_obj(request)
    if mentor and student.mentor_id != mentor.id:
        return HttpResponse("Unauthorized", status=403)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{student.name}.pdf"'

    generate_student_pdf(response, student)
    return response


def _safe_pdf_name(text):
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", str(text or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "Student"


def mentor_prefilled_sif_pdf(request, enrollment):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    student = Student.objects.select_related("mentor").filter(module=module, enrollment=enrollment, mentor=mentor).first()
    if not student:
        return HttpResponse("Unauthorized", status=403)

    roll = student.roll_no if student.roll_no is not None else "NA"
    filename = f"{roll}_{_safe_pdf_name(student.name)}_SIF.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    generate_student_prefilled_pdf(response, student)
    return response


def mentor_prefilled_sif_zip(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)

    students = list(
        Student.objects.select_related("mentor")
        .filter(module=module, mentor=mentor)
        .order_by("roll_no", "name")
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s in students:
            pdf_bytes = io.BytesIO()
            generate_student_prefilled_pdf(pdf_bytes, s)
            roll = s.roll_no if s.roll_no is not None else "NA"
            pdf_name = f"{roll}_{_safe_pdf_name(s.name)}_SIF.pdf"
            zf.writestr(pdf_name, pdf_bytes.getvalue())

    zip_name = f"{_safe_pdf_name(mentor.name)}_Prefilled_SIF.zip"
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{zip_name}"'
    return response


# ---------------- COORDINATOR DASHBOARD ----------------
def coordinator_dashboard(request):

    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)

    week = request.GET.get("week")
    if not week:
        return render(request,"coordinator_dashboard.html")

    week = int(week)
    mentors = Mentor.objects.filter(student__module=module).distinct()
    data = []

    for m in mentors:

        total_students = Student.objects.filter(module=module, mentor=m).count()

        need_call = Attendance.objects.filter(
            week_no=week, student__mentor=m, student__module=module, call_required=True
        ).count()

        latest_calls = _latest_attendance_calls_map(module, week, mentor=m)
        received = len([c for c in latest_calls.values() if c.final_status == "received"])
        not_received = len([c for c in latest_calls.values() if c.final_status == "not_received"])

        done = received + not_received
        not_done = max(need_call - done, 0)

        message_sent = len([c for c in latest_calls.values() if c.message_sent])

        percent = round((done/need_call)*100,1) if need_call else 0

        data.append({
            "mentor":m.name,
            "students":total_students,
            "need_call":need_call,
            "done":done,
            "received":received,
            "not_received":not_received,
            "not_done":not_done,
            "msg_sent":message_sent,
            "percent":percent
        })

    return render(request,"coordinator_dashboard.html",{"data":data,"week":week})


def _build_live_followup_rows(module, selected_mentor="", selected_type="all", selected_week=None, selected_exam="all"):
    mentor_names = list(
        Mentor.objects.filter(student__module=module)
        .distinct()
        .order_by("name")
        .values_list("name", flat=True)
    )

    rows = []

    def _fmt_num(v):
        if v is None:
            return "-"
        try:
            f = float(v)
            return f"{f:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return str(v)

    def _status_text(status):
        if status == "received":
            return "Received"
        if status == "not_received":
            return "Not Received"
        return "Pending"

    def _result_denom(test_name):
        test = (test_name or "").upper()
        if test == "T1":
            return ("T1/T1", 25, 25)
        if test == "T2":
            return ("T2/T1+T2", 25, 50)
        if test == "T3":
            return ("T3/T1+T2+T3", 25, 75)
        if test == "T4":
            return ("T4/T1+T2+T3+T4", 50, 100)
        return ("REMEDIAL/REMEDIAL", 100, 100)

    attendance_weeks = list(
        Attendance.objects.filter(student__module=module)
        .order_by("week_no")
        .values_list("week_no", flat=True)
        .distinct()
    )

    attendance_calls = (
        CallRecord.objects.select_related("student", "student__mentor")
        .filter(student__module=module)
    )
    if selected_week:
        attendance_calls = attendance_calls.filter(week_no=selected_week)
    attendance_calls = attendance_calls.order_by("student_id", "week_no", "-attempt1_time", "-attempt2_time", "-created_at", "-id")
    latest_attendance_calls = {}
    for c in attendance_calls:
        key = (c.student_id, c.week_no)
        if key not in latest_attendance_calls:
            latest_attendance_calls[key] = c
    attendance_pairs = set(latest_attendance_calls.keys())
    attendance_call_weeks = set(attendance_pairs)
    attendance_map = {
        (a.student_id, a.week_no): a
        for a in Attendance.objects.filter(
            student__module=module,
            student_id__in=[p[0] for p in attendance_pairs] if attendance_pairs else [],
            week_no__in=[p[1] for p in attendance_pairs] if attendance_pairs else [],
        )
    }
    for c in latest_attendance_calls.values():
        status = _status_text(c.final_status)
        dt = c.attempt2_time or c.attempt1_time or c.created_at
        if c.final_status:
            date_text, time_text = _to_ist_datetime_text(dt)
            duration = c.duration or "-"
        else:
            date_text, time_text, duration = "-", "-", "-"
        a = attendance_map.get((c.student_id, c.week_no))
        wk = _fmt_num(getattr(a, "week_percentage", None))
        ov = _fmt_num(getattr(a, "overall_percentage", None))
        rows.append(
            {
                "mentor": c.student.mentor.name if c.student.mentor_id else "",
                "roll_no": c.student.roll_no,
                "enrollment": c.student.enrollment,
                "student_name": c.student.name,
                "followup_type": "less_attendance",
                "followup_label": "Less Attendance",
                "exam_key": "",
                "status": status,
                "date_text": date_text,
                "time_text": time_text,
                "duration": duration,
                "reason": f"Week-{c.week_no} W: {wk}%, O: {ov}",
                "remarks": _format_parent_faculty_remark(c.parent_reason),
                "sort_dt": dt or timezone.now(),
            }
        )

    result_calls = (
        ResultCallRecord.objects.select_related("student", "student__mentor", "upload", "upload__subject")
        .filter(student__module=module)
    )
    active_fail_pairs = set(
        StudentResult.objects.filter(upload__module=module, fail_flag=True).values_list("upload_id", "student_id")
    )
    result_calls = result_calls.order_by("upload_id", "student_id", "-attempt1_time", "-attempt2_time", "-created_at", "-id")
    latest_result_calls = {}
    for c in result_calls:
        key = (c.upload_id, c.student_id)
        if key not in active_fail_pairs:
            continue
        if key not in latest_result_calls:
            latest_result_calls[key] = c
    for c in latest_result_calls.values():
        status = _status_text(c.final_status)
        dt = c.attempt2_time or c.attempt1_time or c.created_at
        if c.final_status:
            date_text, time_text = _to_ist_datetime_text(dt)
            duration = c.duration or "-"
        else:
            date_text, time_text, duration = "-", "-", "-"
        test_name = c.upload.test_name if c.upload_id else "-"
        test_key = (test_name or "").upper()
        subject_name = c.upload.subject.name if c.upload_id and c.upload.subject_id else "-"
        exam_label, cur_total, overall_total = _result_denom(test_name)
        current_marks = _fmt_num(c.marks_current)
        overall_marks = _fmt_num(c.marks_total)
        rows.append(
            {
                "mentor": c.student.mentor.name if c.student.mentor_id else "",
                "roll_no": c.student.roll_no,
                "enrollment": c.student.enrollment,
                "student_name": c.student.name,
                "followup_type": "poor_result",
                "followup_label": "Poor Result",
                "exam_key": test_key,
                "status": status,
                "date_text": date_text,
                "time_text": time_text,
                "duration": duration,
                "reason": f"{exam_label} : {subject_name} : ({current_marks}/{cur_total}, {overall_marks}/{overall_total})",
                "remarks": _format_parent_faculty_remark(c.parent_reason),
                "sort_dt": dt or timezone.now(),
            }
        )

    other_calls = (
        OtherCallRecord.objects.select_related("student", "student__mentor")
        .filter(student__module=module)
    )
    for c in other_calls:
        status = _status_text(c.final_status)
        dt = c.attempt2_time or c.attempt1_time or c.updated_at or c.created_at
        if c.final_status:
            date_text, time_text = _to_ist_datetime_text(dt)
            duration = c.duration or "-"
        else:
            date_text, time_text, duration = "-", "-", "-"
        reason_text = (c.call_done_reason or "").strip()
        remarks_text = (c.parent_remark or "").strip()
        lower_blob = f"{reason_text} {remarks_text}".lower()

        if c.call_category == "less_attendance":
            f_type = "less_attendance"
            f_label = "Less Attendance"
            reason = reason_text or "Less attendance follow-up"
            exam_key = ""
            # De-duplicate with primary attendance call rows:
            # if same student + week already exists in CallRecord, skip OtherCall row.
            wk_match = re.search(r"wk[-\s:]*([0-9]+)", f"{reason_text} {remarks_text}", flags=re.IGNORECASE)
            if wk_match:
                try:
                    wk_no = int(wk_match.group(1))
                except Exception:
                    wk_no = None
                if wk_no is not None and (c.student_id, wk_no) in attendance_call_weeks:
                    continue
        elif c.call_category == "poor_result":
            f_type = "poor_result"
            f_label = "Poor Result"
            if c.exam_name or c.subject_name:
                reason = f"Poor result ({c.exam_name or '-'} - {c.subject_name or '-'})"
            else:
                reason = reason_text or "Poor result follow-up"
            exam_raw = (c.exam_name or "").upper()
            if "T1" in exam_raw and "T2" not in exam_raw and "T3" not in exam_raw and "T4" not in exam_raw:
                exam_key = "T1"
            elif "T2" in exam_raw:
                exam_key = "T2"
            elif "T3" in exam_raw:
                exam_key = "T3"
            elif "T4" in exam_raw or "SEE" in exam_raw or "TOTAL" in exam_raw:
                exam_key = "T4"
            else:
                exam_key = ""
        elif c.call_category == "mentor_intro":
            f_type = "mentor_intro"
            f_label = "Mentor Intro Call"
            reason = reason_text or "Mentor introduction call"
            exam_key = ""
        else:
            if "intro" in lower_blob:
                f_type = "mentor_intro"
                f_label = "Mentor Intro Call"
            else:
                f_type = "other_direct"
                f_label = "Other (Direct)"
            reason = reason_text or "Direct call"
            exam_key = ""

        rows.append(
            {
                "mentor": c.student.mentor.name if c.student.mentor_id else "",
                "roll_no": c.student.roll_no,
                "enrollment": c.student.enrollment,
                "student_name": c.student.name,
                "followup_type": f_type,
                "followup_label": f_label,
                "exam_key": exam_key,
                "status": status,
                "date_text": date_text,
                "time_text": time_text,
                "duration": duration,
                "reason": reason,
                "remarks": _format_parent_faculty_remark(remarks_text),
                "sort_dt": dt or timezone.now(),
            }
        )

    if selected_mentor:
        rows = [r for r in rows if r["mentor"] == selected_mentor]

    if selected_type != "all":
        rows = [r for r in rows if r["followup_type"] == selected_type]

    if selected_exam in {"T1", "T2", "T3", "T4"}:
        rows = [r for r in rows if r.get("exam_key") == selected_exam]

    rows.sort(key=lambda r: (r["sort_dt"], r["mentor"] or "", r["roll_no"] or 999999), reverse=True)
    return mentor_names, attendance_weeks, rows


def live_followup_sheet(request):
    mentor_mode = bool(request.session.get("mentor"))
    if not mentor_mode and not request.user.is_authenticated:
        return redirect("/")

    module = _active_module(request)
    selected_mentor = (request.GET.get("mentor") or "").strip()
    if mentor_mode:
        selected_mentor = (request.session.get("mentor") or "").strip()
    selected_type = (request.GET.get("type") or "all").strip().lower()
    selected_week_raw = (request.GET.get("week") or "").strip()
    selected_exam = (request.GET.get("exam") or "ALL").strip().upper()
    selected_sort = (request.GET.get("sort") or "date").strip().lower()
    selected_dir = (request.GET.get("dir") or "desc").strip().lower()
    page_number = request.GET.get("page", "1")

    selected_week = None
    week_param_present = "week" in request.GET
    if selected_week_raw.isdigit():
        selected_week = int(selected_week_raw)

    if selected_exam not in {"ALL", "T1", "T2", "T3", "T4"}:
        selected_exam = "ALL"
    mentor_names, attendance_weeks, rows = _build_live_followup_rows(
        module,
        selected_mentor,
        selected_type,
        selected_week,
        selected_exam if selected_exam != "ALL" else "all",
    )
    if (not week_param_present) and selected_week is None and attendance_weeks:
        selected_week = max(attendance_weeks)
        mentor_names, attendance_weeks, rows = _build_live_followup_rows(
            module,
            selected_mentor,
            selected_type,
            selected_week,
            selected_exam if selected_exam != "ALL" else "all",
        )
    selected_week_q = str(selected_week) if selected_week is not None else "ALL"

    key_map = {
        "mentor": "mentor",
        "roll": "roll_no",
        "enrollment": "enrollment",
        "name": "student_name",
        "type": "followup_label",
        "status": "status",
        "date": "sort_dt",
        "duration": "duration",
        "reason": "reason",
        "remarks": "remarks",
    }
    if selected_sort not in key_map:
        selected_sort = "date"
    if selected_dir not in {"asc", "desc"}:
        selected_dir = "desc"

    sort_key = key_map[selected_sort]
    reverse = selected_dir == "desc"

    if sort_key == "roll_no":
        rows.sort(key=lambda r: (r.get("roll_no") is None, r.get("roll_no") or 0), reverse=reverse)
    elif sort_key == "sort_dt":
        rows.sort(key=lambda r: r.get("sort_dt") or timezone.now(), reverse=reverse)
    else:
        rows.sort(key=lambda r: str(r.get(sort_key) or "").lower(), reverse=reverse)

    paginator = Paginator(rows, 120)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "live_followup_sheet.html",
        {
            "rows": page_obj.object_list,
            "page_obj": page_obj,
            "mentor_names": mentor_names,
            "attendance_weeks": attendance_weeks,
            "selected_mentor": selected_mentor,
            "selected_type": selected_type,
            "selected_week": selected_week,
            "selected_week_q": selected_week_q,
            "selected_exam": selected_exam,
            "selected_sort": selected_sort,
            "selected_dir": selected_dir,
            "module": module,
            "mentor_mode": mentor_mode,
            "is_superadmin_view": (not mentor_mode and bool(request.user.is_authenticated and is_superadmin_user(request.user))),
        },
    )


def live_followup_sheet_excel(request):
    mentor_mode = bool(request.session.get("mentor"))
    if not mentor_mode and not request.user.is_authenticated:
        return redirect("/")

    module = _active_module(request)
    selected_mentor = (request.GET.get("mentor") or "").strip()
    if mentor_mode:
        selected_mentor = (request.session.get("mentor") or "").strip()
    selected_type = (request.GET.get("type") or "all").strip().lower()
    selected_week_raw = (request.GET.get("week") or "").strip()
    selected_exam = (request.GET.get("exam") or "ALL").strip().upper()
    selected_week = int(selected_week_raw) if selected_week_raw.isdigit() else None
    if selected_exam not in {"ALL", "T1", "T2", "T3", "T4"}:
        selected_exam = "ALL"
    _, _, rows = _build_live_followup_rows(
        module, selected_mentor, selected_type, selected_week, selected_exam if selected_exam != "ALL" else "all"
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Live Followup"

    headers = [
        "Mentor",
        "Roll No.",
        "Enrollment No.",
        "Name of Students",
        "Followup Type",
        "Status",
        "Date of Phone Call",
        "Call Duration (Mins)",
        "Reason of Phone Call",
        "Remarks by Parents",
    ]
    ws.append(headers)

    for r in rows:
        ws.append(
            [
                r["mentor"],
                r["roll_no"],
                r["enrollment"],
                r["student_name"],
                r["followup_label"],
                r["status"],
                f'{r["date_text"]} {r["time_text"]}',
                r["duration"],
                r["reason"],
                r["remarks"],
            ]
        )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="live_followup_sheet.xlsx"'
    wb.save(response)
    return response


def live_followup_sheet_pdf(request):
    mentor_mode = bool(request.session.get("mentor"))
    if not mentor_mode and not request.user.is_authenticated:
        return redirect("/")

    module = _active_module(request)
    selected_mentor = (request.GET.get("mentor") or "").strip()
    if mentor_mode:
        selected_mentor = (request.session.get("mentor") or "").strip()
    selected_type = (request.GET.get("type") or "all").strip().lower()
    selected_week_raw = (request.GET.get("week") or "").strip()
    selected_exam = (request.GET.get("exam") or "ALL").strip().upper()
    selected_week = int(selected_week_raw) if selected_week_raw.isdigit() else None
    if selected_exam not in {"ALL", "T1", "T2", "T3", "T4"}:
        selected_exam = "ALL"
    _, _, rows = _build_live_followup_rows(
        module, selected_mentor, selected_type, selected_week, selected_exam if selected_exam != "ALL" else "all"
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="live_followup_sheet.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        leftMargin=12,
        rightMargin=12,
        topMargin=14,
        bottomMargin=12,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Live Followup Sheet - {module.name}", styles["Heading3"]),
        Spacer(1, 6),
    ]

    table_data = [
        [
            "Mentor",
            "Roll No.",
            "Enrollment No.",
            "Name of Students",
            "Followup Type",
            "Status",
            "Date of Phone Call",
            "Call Duration (Mins)",
            "Reason of Phone Call",
            "Remarks by Parents",
        ]
    ]

    for r in rows:
        table_data.append(
            [
                r["mentor"],
                str(r["roll_no"] or "-"),
                r["enrollment"] or "-",
                r["student_name"] or "-",
                r["followup_label"] or "-",
                r["status"] or "-",
                f'{r["date_text"]} {r["time_text"]}',
                str(r["duration"] or "-"),
                r["reason"] or "-",
                r["remarks"] or "-",
            ]
        )

    tbl = Table(
        table_data,
        repeatRows=1,
        colWidths=[66, 38, 85, 110, 70, 62, 88, 56, 110, 80],
    )
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    story.append(tbl)
    doc.build(story)
    return response


@login_required
def live_followup_sheet_db_backup_json(request):
    if request.session.get("mentor"):
        return HttpResponse("Forbidden", status=403)
    if not is_superadmin_user(request.user):
        return HttpResponse("Forbidden", status=403)

    buffer = io.StringIO()
    call_command(
        "dumpdata",
        "auth.user",
        "core",
        indent=2,
        stdout=buffer,
    )
    payload = buffer.getvalue()
    ts = timezone.now().astimezone(IST).strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(payload, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="easymentor_db_backup_{ts}.json"'
    return response


@login_required
def coordinator_result_report(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    module = _active_module(request)

    uploads = ResultUpload.objects.filter(module=module).order_by("-uploaded_at")
    selected_upload = None
    upload_id = request.GET.get("upload")
    if upload_id:
        selected_upload = ResultUpload.objects.filter(id=upload_id, module=module).first()
    if not selected_upload:
        selected_upload = uploads.first()

    data = []
    if selected_upload:
        fail_student_ids = _upload_fail_student_ids(selected_upload)
        mentors = (
            Mentor.objects.filter(student__module=module, student__resultcallrecord__upload=selected_upload)
            .distinct()
            .order_by("name")
        )
        for m in mentors:
            latest_calls = _latest_result_calls_map(
                selected_upload,
                mentor=m,
                module=module,
                student_ids=fail_student_ids,
            )
            need_call = len(latest_calls)
            received = len([c for c in latest_calls.values() if c.final_status == "received"])
            not_received = len([c for c in latest_calls.values() if c.final_status == "not_received"])
            done = received + not_received
            not_done = max(need_call - done, 0)
            msg_sent = len([c for c in latest_calls.values() if c.message_sent])
            percent = round((done / need_call) * 100, 1) if need_call else 0
            data.append(
                {
                    "mentor": m.name,
                    "need_call": need_call,
                    "done": done,
                    "received": received,
                    "not_received": not_received,
                    "not_done": not_done,
                    "msg_sent": msg_sent,
                    "percent": percent,
                }
            )

    return render(
        request,
        "coordinator_result_report.html",
        {
            "uploads": uploads,
            "selected_upload": selected_upload,
            "data": data,
        },
    )

def update_mobile(request):

    if request.method == "POST":
        if not request.user.is_authenticated and "mentor" not in request.session:
            return JsonResponse({"ok": False, "error": "Unauthorized"}, status=401)

        module = _active_module(request)
        enrollment = request.POST.get("enrollment")
        field = request.POST.get("field")
        value = request.POST.get("value")

        student = Student.objects.get(module=module, enrollment=enrollment)
        mentor = _session_mentor_obj(request)
        is_mentor_update = bool(mentor)
        if is_mentor_update and student.mentor_id != mentor.id:
            return JsonResponse({"ok": False, "error": "Unauthorized"}, status=403)

        if field == "father":
            student.father_mobile = value
            student.father_mobile_updated_by_mentor = is_mentor_update
        elif field == "mother":
            student.mother_mobile = value
        elif field == "student":
            student.student_mobile = value
            student.student_mobile_updated_by_mentor = is_mentor_update

        student.save()

        return JsonResponse({"ok": True})

    
# ---------------- CONTROL PANEL ----------------
def control_panel(request):

    if "mentor" in request.session:
        return redirect("/")

    module = _active_module(request)
    students = Student.objects.select_related("mentor").filter(module=module).order_by("roll_no")

    return render(request,"control_panel.html",{"students":students})


def mentor_print_sif(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)

    students = Student.objects.select_related("mentor").filter(module=module, mentor=mentor).order_by("roll_no", "name")
    return render(
        request,
        "mentor_print_sif.html",
        {
            "mentor": mentor,
            "students": students,
        },
    )


def mentor_view_sif(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")

    module = _active_module(request)
    students = list(
        Student.objects.select_related("mentor")
        .filter(module=module, mentor=mentor)
        .order_by("roll_no", "name")
    )

    selected_enrollment = (request.GET.get("enrollment") or "").strip()
    selected_student = None
    if students:
        if selected_enrollment:
            selected_student = next((s for s in students if s.enrollment == selected_enrollment), None)
        if not selected_student:
            selected_student = students[0]

    sem_value = "1"
    if module and module.semester:
        sem_value = (module.semester.split("-")[-1] or "1").strip()

    attendance_rows = []
    result_rows = []
    other_rows = []

    if selected_student:
        calls_by_week = {}
        for c in CallRecord.objects.filter(student=selected_student).order_by("week_no", "-attempt1_time", "-attempt2_time", "-created_at", "-id"):
            if c.week_no not in calls_by_week:
                calls_by_week[c.week_no] = c
        attendance_qs = Attendance.objects.filter(student=selected_student).order_by("week_no")
        sr = 1
        for att in attendance_qs:
            if (att.week_percentage or 0) >= 80 and (att.overall_percentage or 0) >= 80:
                continue
            call = calls_by_week.get(att.week_no)
            call_done = bool(call and call.final_status in ("received", "not_received"))
            if call_done:
                call_dt = (call.attempt2_time or call.attempt1_time or call.created_at)
                date, time = _to_ist_datetime_text(call_dt)
                duration = (call.duration or "").strip() or "-"
                time_duration = f"{time} ({duration})" if time != "-" else "-"
            else:
                date, time, duration, time_duration = "-", "-", "-", "-"
            discussed = ((call.talked_with or "-").title() if call else "-")
            parent_remark = "-"
            faculty_remark = "-"
            if call and call.parent_reason:
                reason_text = (call.parent_reason or "").strip()
                if "PARENT::" in reason_text and "||FACULTY::" in reason_text:
                    p, f = reason_text.split("||FACULTY::", 1)
                    parent_remark = p.replace("PARENT::", "", 1).strip() or "-"
                    faculty_remark = f.strip() or "-"
                else:
                    parent_remark = reason_text

            attendance_rows.append(
                {
                    "sr": sr,
                    "sem": sem_value,
                    "week_no": att.week_no,
                    "attend_text": f"W:{round(att.week_percentage, 2)} / O:{round(att.overall_percentage, 2)}",
                    "status": _call_status_text(call.final_status if call else None),
                    "date": date,
                    "time_duration": time_duration,
                    "discussed": discussed,
                    "parent_remark": parent_remark,
                    "faculty_remark": faculty_remark,
                }
            )
            sr += 1

        result_rows_qs = StudentResult.objects.filter(student=selected_student).select_related("upload", "upload__subject")
        result_rows_sorted = sorted(
            result_rows_qs,
            key=lambda r: (
                _test_sort_key(r.upload.test_name if r.upload else ""),
                _subject_sort_key(r.upload.subject.name if r.upload and r.upload.subject else ""),
                r.upload.uploaded_at if r.upload else timezone.now(),
                r.id,
            ),
        )
        result_call_map = {}
        for c in ResultCallRecord.objects.filter(student=selected_student).select_related("upload").order_by("upload_id", "-attempt1_time", "-attempt2_time", "-created_at", "-id"):
            if c.upload_id not in result_call_map:
                result_call_map[c.upload_id] = c
        sr = 1
        for row in result_rows_sorted:
            if not row.upload:
                continue
            cur_thr, total_thr = _result_thresholds(row.upload.test_name)
            current_fail = row.marks_current is not None and row.marks_current < cur_thr
            total_fail = row.marks_total is not None and row.marks_total < total_thr
            if not (current_fail or total_fail):
                continue

            call = result_call_map.get(row.upload_id)
            call_done = bool(call and call.final_status in ("received", "not_received"))
            if call_done:
                call_dt = (call.attempt2_time or call.attempt1_time or call.created_at)
                date, time = _to_ist_datetime_text(call_dt)
                duration = (call.duration or "").strip() or "-"
                time_duration = f"{time} ({duration})" if time != "-" else "-"
            else:
                date, time, duration, time_duration = "-", "-", "-", "-"
            discussed = ((call.talked_with or "-").title() if call else "-")
            subject_name = row.upload.subject.name if row.upload.subject else "-"
            obtained = "-" if row.marks_current is None else row.marks_current
            total = "-" if row.marks_total is None else row.marks_total
            result_rows.append(
                {
                    "sr": sr,
                    "sem": sem_value,
                    "status": _call_status_text(call.final_status if call else None),
                    "date": date,
                    "time_duration": time_duration,
                    "discussed": discussed,
                    "exam": _exam_name_for_sif(row.upload.test_name),
                    "subject": f"{subject_name} ({obtained}/{total})",
                    "remark": (call.parent_reason if call and call.parent_reason else "-"),
                }
            )
            sr += 1

        direct_call = (
            OtherCallRecord.objects.filter(student=selected_student)
            .order_by("-attempt1_time", "-created_at", "-id")
            .first()
        )
        if direct_call and direct_call.call_category != "poor_result":
            call_done = direct_call.final_status in ("received", "not_received")
            if call_done:
                call_dt = direct_call.attempt2_time or direct_call.attempt1_time or direct_call.updated_at or direct_call.created_at
                date, time = _to_ist_datetime_text(call_dt)
                duration = (direct_call.duration or "").strip() or "-"
                time_duration = f"{time} ({duration})" if time != "-" else "-"
            else:
                time_duration, date = "-", "-"
            discussed = (direct_call.talked_with or "-").title()
            other_rows.append(
                {
                    "sr": 1,
                    "sem": sem_value,
                    "status": _call_status_text(direct_call.final_status),
                    "date": date,
                    "time_duration": time_duration,
                    "discussed": discussed,
                    "reason": direct_call.call_done_reason or "-",
                    "remark": direct_call.parent_remark or "-",
                }
            )
        else:
            other_rows.append(
                {
                    "sr": 1,
                    "sem": sem_value,
                    "status": "Pending",
                    "date": "-",
                    "time_duration": "-",
                    "discussed": "-",
                    "reason": "-",
                    "remark": "-",
                }
            )

    return render(
        request,
        "mentor_view_sif.html",
        {
            "mentor": mentor,
            "students": students,
            "selected_student": selected_student,
            "attendance_rows": attendance_rows,
            "result_rows": result_rows,
            "other_rows": other_rows,
        },
    )


def mentor_student_data(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")

    module = _active_module(request)
    qs = Student.objects.select_related("mentor").filter(module=module)

    filters = {
        "roll": (request.GET.get("f_roll") or "").strip(),
        "batch": (request.GET.get("f_batch") or "").strip(),
        "division": (request.GET.get("f_division") or "").strip(),
        "enrollment": (request.GET.get("f_enrollment") or "").strip(),
        "name": (request.GET.get("f_name") or "").strip(),
        "mentor": (request.GET.get("f_mentor") or "").strip(),
        "student_mobile": (request.GET.get("f_student_mobile") or "").strip(),
        "father_mobile": (request.GET.get("f_father_mobile") or "").strip(),
    }

    if filters["roll"]:
        qs = qs.filter(roll_no__icontains=filters["roll"])
    if filters["batch"]:
        qs = qs.filter(batch__icontains=filters["batch"])
    if filters["division"]:
        qs = qs.filter(division__icontains=filters["division"])
    if filters["enrollment"]:
        qs = qs.filter(enrollment__icontains=filters["enrollment"])
    if filters["name"]:
        qs = qs.filter(name__icontains=filters["name"])
    if filters["mentor"]:
        qs = qs.filter(mentor__name__icontains=filters["mentor"])
    if filters["student_mobile"]:
        qs = qs.filter(student_mobile__icontains=filters["student_mobile"])
    if filters["father_mobile"]:
        qs = qs.filter(father_mobile__icontains=filters["father_mobile"])

    sort = (request.GET.get("sort") or "roll").strip()
    direction = (request.GET.get("dir") or "asc").strip().lower()
    sort_map = {
        "roll": "roll_no",
        "batch": "batch",
        "division": "division",
        "enrollment": "enrollment",
        "name": "name",
        "mentor": "mentor__name",
        "student_mobile": "student_mobile",
        "father_mobile": "father_mobile",
    }
    sort_field = sort_map.get(sort, "roll_no")
    if direction == "desc":
        sort_field = f"-{sort_field}"
    students = qs.order_by(sort_field, "name")

    def next_dir(key):
        if sort == key and direction == "asc":
            return "desc"
        return "asc"

    return render(
        request,
        "mentor_student_data.html",
        {
            "students": students,
            "filters": filters,
            "sort": sort,
            "direction": direction,
            "dir_roll": next_dir("roll"),
            "dir_batch": next_dir("batch"),
            "dir_division": next_dir("division"),
            "dir_enrollment": next_dir("enrollment"),
            "dir_name": next_dir("name"),
            "dir_mentor": next_dir("mentor"),
            "dir_student_mobile": next_dir("student_mobile"),
            "dir_father_mobile": next_dir("father_mobile"),
        },
    )


def mentor_whatsapp_panel(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")

    module = _active_module(request)
    students = list(
        Student.objects.filter(module=module, mentor=mentor).order_by("roll_no", "name")
    )

    message_text = ""
    target = ""
    recipients = []

    if request.method == "POST":
        message_text = (request.POST.get("message") or "").strip()
        target = (request.POST.get("target") or "").strip()
        if not message_text:
            messages.error(request, "Message is required.")
        elif target not in {"student", "father"}:
            messages.error(request, "Choose a valid target.")
        else:
            for s in students:
                raw_number = s.student_mobile if target == "student" else s.father_mobile
                phone = _normalize_whatsapp_phone(raw_number)
                if not phone:
                    continue
                recipients.append(
                    {
                        "name": s.name,
                        "enrollment": s.enrollment,
                        "phone": phone,
                    }
                )
            if not recipients:
                messages.warning(request, f"No valid {target} numbers found for your mentees.")

    return render(
        request,
        "mentor_whatsapp_panel.html",
        {
            "message_text": message_text,
            "target": target,
            "recipients": recipients,
            "recipient_count": len(recipients),
            "message_encoded": quote(message_text),
        },
    )


def download_whatsapp_extension(request):
    mentor = _session_mentor_obj(request)
    if not mentor and not request.user.is_authenticated:
        return redirect("/")

    ext_dir = os.path.join(settings.BASE_DIR, "whatsapp_automation_extension")
    if not os.path.isdir(ext_dir):
        return HttpResponse("Extension files not found.", status=404)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ["manifest.json", "whatsapp_content.js", "README.md"]:
            path = os.path.join(ext_dir, name)
            if os.path.exists(path):
                zf.write(path, arcname=name)
        zf.writestr(
            "INSTALL_AND_SUPPORT.txt",
            (
                "EasyMentor WhatsApp Extension\n\n"
                "How to use:\n"
                "1. Go to chrome://extensions\n"
                "2. Enable Developer mode\n"
                "3. Load unpacked -> select folder whatsapp_automation_extension\n"
                "4. Login once to WhatsApp Web\n"
                "5. In portal mentor page, enter message and click Start Auto (Extension)\n\n"
                "Buy me a chai with UPI link:\n"
                "upi://pay?pa=8866749627@upi&pn=Hardik%20Shah&am=15&cu=INR&tn=Cutting%20Chai\n"
            ),
        )

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="easymentor_whatsapp_extension.zip"'
    return response


def mentor_sif_marks(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    lock_obj = SifMarksLock.objects.filter(module=module).first()
    if not lock_obj or not lock_obj.locked:
        return render(request, "mentor_sif_marks.html", {"locked": False})

    students = list(
        Student.objects.select_related("mentor")
        .filter(module=module, mentor=mentor)
        .order_by("roll_no", "name")
    )
    selected_enrollment = request.GET.get("enrollment") or (students[0].enrollment if students else "")
    selected_student = Student.objects.filter(module=module, mentor=mentor, enrollment=selected_enrollment).first() if selected_enrollment else None
    marks_rows = _sif_marks_rows_for_student(selected_student, module) if selected_student else []
    return render(
        request,
        "mentor_sif_marks.html",
        {
            "locked": True,
            "students": students,
            "selected_student": selected_student,
            "selected_enrollment": selected_enrollment,
            "marks_rows": marks_rows,
        },
    )


def mentor_sif_marks_pdf(request, enrollment):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    lock_obj = SifMarksLock.objects.filter(module=module).first()
    if not lock_obj or not lock_obj.locked:
        return HttpResponse("Marks not yet locked.", status=403)
    student = Student.objects.filter(module=module, mentor=mentor, enrollment=enrollment).first()
    if not student:
        return HttpResponse("Unauthorized", status=403)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_safe_pdf_name(student.name)}_SIF.pdf"'
    generate_student_pdf(response, student)
    return response


def mentor_sif_marks_pdf_all(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")
    module = _active_module(request)
    lock_obj = SifMarksLock.objects.filter(module=module).first()
    if not lock_obj or not lock_obj.locked:
        return HttpResponse("Marks not yet locked.", status=403)

    students = list(
        Student.objects.select_related("mentor")
        .filter(module=module, mentor=mentor)
        .order_by("roll_no", "name")
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s in students:
            pdf_bytes = io.BytesIO()
            generate_student_pdf(pdf_bytes, s)
            roll = s.roll_no if s.roll_no is not None else "NA"
            zf.writestr(f"{roll}_{_safe_pdf_name(s.name)}_SIF.pdf", pdf_bytes.getvalue())

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{_safe_pdf_name(mentor.name)}_SIF_Marks.zip"'
    return response


def healthz(request):
    return JsonResponse({"ok": True, "service": "easymentor", "ts": timezone.now().isoformat()})


@login_required
@require_http_methods(["POST"])
def rbac_create_coordinator(request):
    guard = _require_superadmin(request)
    if guard:
        return guard

    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    module_ids_raw = (request.POST.get("module_ids") or "").strip()

    if not username or not password:
        return JsonResponse({"ok": False, "msg": "username and password required"}, status=400)
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({"ok": False, "msg": "username already exists"}, status=400)

    module_ids = [x.strip() for x in module_ids_raw.split(",") if x.strip().isdigit()]
    modules = list(AcademicModule.objects.filter(id__in=module_ids, is_active=True)) if module_ids else []
    if not modules:
        return JsonResponse({"ok": False, "msg": "at least one valid module is required"}, status=400)

    user = User.objects.create_user(username=username, password=password, is_active=True, is_staff=False, is_superuser=False)
    CoordinatorModuleAccess.objects.bulk_create(
        [CoordinatorModuleAccess(coordinator=user, module=m) for m in modules],
        ignore_conflicts=True,
    )
    return JsonResponse({"ok": True, "coordinator_id": user.id, "modules": [m.id for m in modules]})


@login_required
@require_http_methods(["POST"])
def rbac_update_coordinator_modules(request):
    guard = _require_superadmin(request)
    if guard:
        return guard

    coordinator_id = request.POST.get("coordinator_id")
    module_ids_raw = (request.POST.get("module_ids") or "").strip()
    if not str(coordinator_id or "").isdigit():
        return JsonResponse({"ok": False, "msg": "valid coordinator_id required"}, status=400)

    coordinator = User.objects.filter(id=int(coordinator_id)).first()
    if not coordinator:
        return JsonResponse({"ok": False, "msg": "coordinator not found"}, status=404)
    if is_superadmin_user(coordinator):
        return JsonResponse({"ok": False, "msg": "cannot remap superadmin"}, status=400)

    module_ids = [x.strip() for x in module_ids_raw.split(",") if x.strip().isdigit()]
    modules = list(AcademicModule.objects.filter(id__in=module_ids, is_active=True)) if module_ids else []
    if not modules:
        return JsonResponse({"ok": False, "msg": "at least one valid module is required"}, status=400)

    CoordinatorModuleAccess.objects.filter(coordinator=coordinator).delete()
    CoordinatorModuleAccess.objects.bulk_create(
        [CoordinatorModuleAccess(coordinator=coordinator, module=m) for m in modules],
        ignore_conflicts=True,
    )
    return JsonResponse({"ok": True, "coordinator_id": coordinator.id, "modules": [m.id for m in modules]})


@login_required
@require_http_methods(["POST"])
def superadmin_change_password(request):
    guard = _require_superadmin(request)
    if guard:
        return guard

    current_password = request.POST.get("current_password") or ""
    new_password = request.POST.get("new_password") or ""
    if not request.user.check_password(current_password):
        return JsonResponse({"ok": False, "msg": "current password is incorrect"}, status=400)
    if len(new_password) < 8:
        return JsonResponse({"ok": False, "msg": "new password must be at least 8 chars"}, status=400)

    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    update_session_auth_hash(request, request.user)
    return JsonResponse({"ok": True})


# ---------------- MODULE SWITCH ----------------
@require_http_methods(["POST"])
def switch_module(request):
    if not request.user.is_authenticated and "mentor" not in request.session:
        return redirect("/")
    module_id = request.POST.get("module_id")
    allowed_qs = allowed_modules_for_user(request)
    module = allowed_qs.filter(id=module_id).first()
    if module:
        request.session["current_module_id"] = module.id
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/reports/"
    return redirect(next_url)


@login_required
def manage_modules(request):
    if "mentor" in request.session:
        return redirect("/mentor-dashboard/")
    if not is_superadmin_user(request.user):
        return HttpResponse("Forbidden", status=403)

    if request.method == "POST":
        action = (request.POST.get("action") or "create").strip()
        if action == "delete":
            module_id = request.POST.get("module_id")
            module = AcademicModule.objects.filter(id=module_id).first()
            if not module:
                messages.error(request, "Module not found.")
            else:
                module.delete()
                messages.success(request, "Module deleted.")
            return redirect("/modules/")

        module_id = request.POST.get("module_id")
        batch = (request.POST.get("academic_batch") or "").strip()
        year_level = (request.POST.get("year_level") or "FY").strip()
        variant = (request.POST.get("variant") or "FY2-CE").strip()
        semester = (request.POST.get("semester") or "Sem-1").strip()
        is_active = (request.POST.get("is_active") or "1").strip() == "1"

        if not batch:
            messages.error(request, "Batch is required.")
            return redirect("/modules/")
        if year_level not in {x[0] for x in AcademicModule.YEAR_CHOICES}:
            year_level = "FY"
        if variant not in {x[0] for x in AcademicModule.VARIANT_CHOICES}:
            variant = "FY2-CE"
        if semester not in {x[0] for x in AcademicModule.SEM_CHOICES}:
            semester = "Sem-1"

        name = _module_display_name(variant, semester, batch)

        if action == "update":
            module = AcademicModule.objects.filter(id=module_id).first()
            if not module:
                messages.error(request, "Module not found.")
                return redirect("/modules/")
            conflict = AcademicModule.objects.filter(name=name).exclude(id=module.id).exists()
            if conflict:
                messages.error(request, "Another module already exists with same name.")
                return redirect("/modules/")
            module.name = name
            module.academic_batch = batch
            module.year_level = year_level
            module.variant = variant
            module.semester = semester
            module.is_active = is_active
            module.save(
                update_fields=[
                    "name",
                    "academic_batch",
                    "year_level",
                    "variant",
                    "semester",
                    "is_active",
                ]
            )
            request.session["current_module_id"] = module.id
            messages.success(request, f"Module updated: {module.name}")
            return redirect("/modules/")

        module, created = AcademicModule.objects.get_or_create(
            name=name,
            defaults={
                "academic_batch": batch,
                "year_level": year_level,
                "variant": variant,
                "semester": semester,
                "is_active": is_active,
            },
        )
        if not created and action == "create":
            module.academic_batch = batch
            module.year_level = year_level
            module.variant = variant
            module.semester = semester
            module.is_active = is_active
            module.save(update_fields=["academic_batch", "year_level", "variant", "semester", "is_active"])
        request.session["current_module_id"] = module.id
        if created:
            messages.success(request, f"Module created: {module.name}")
        else:
            messages.info(request, f"Module already exists and updated: {module.name}")
        return redirect("/modules/")

    return render(
        request,
        "modules.html",
        {
            "modules": AcademicModule.objects.all().order_by("-id"),
            "year_choices": AcademicModule.YEAR_CHOICES,
            "variant_choices": AcademicModule.VARIANT_CHOICES,
            "sem_choices": AcademicModule.SEM_CHOICES,
        },
    )


# ---------------- SEM REGISTER ----------------

def semester_register(request):
    if "mentor" in request.session:
        return redirect("/mentor-semester-register/")

    module = _active_module(request)

    # all uploaded weeks
    weeks = sorted(
        Attendance.objects.filter(student__module=module).values_list("week_no", flat=True).distinct()
    )

    students = Student.objects.select_related("mentor").filter(module=module).order_by("roll_no")

    table = []

    for s in students:

        row = {
            "roll": s.roll_no,
            "enrollment": s.enrollment,
            "name": s.name,
            "mentor": s.mentor.name
        }

        overall = None

        for w in weeks:
            rec = Attendance.objects.filter(student=s, week_no=w).first()
            if rec:
                row[f"week_{w}"] = rec.week_percentage
                overall = rec.overall_percentage
            else:
                row[f"week_{w}"] = None

        row["overall"] = overall
        table.append(row)

    return render(request, "semester_register.html", {
        "title": "Overall Attendance Register",
        "weeks": weeks,
        "rows": table
    })


def mentor_semester_register(request):
    mentor = _session_mentor_obj(request)
    if not mentor:
        return redirect("/")

    module = _active_module(request)
    weeks = sorted(
        Attendance.objects.filter(student__module=module, student__mentor=mentor)
        .values_list("week_no", flat=True)
        .distinct()
    )

    students = (
        Student.objects.select_related("mentor")
        .filter(module=module, mentor=mentor)
        .order_by("roll_no")
    )

    table = []
    for s in students:
        row = {
            "roll": s.roll_no,
            "enrollment": s.enrollment,
            "name": s.name,
            "mentor": s.mentor.name,
        }
        overall = None
        for w in weeks:
            rec = Attendance.objects.filter(student=s, week_no=w).first()
            if rec:
                row[f"week_{w}"] = rec.week_percentage
                overall = rec.overall_percentage
            else:
                row[f"week_{w}"] = None
        row["overall"] = overall
        table.append(row)

    return render(
        request,
        "semester_register.html",
        {
            "title": "My Mentees Attendance Register",
            "weeks": weeks,
            "rows": table,
        },
    )
