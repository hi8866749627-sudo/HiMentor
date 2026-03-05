from django.contrib import admin
from .models import (
    Attendance,
    CallRecord,
    Mentor,
    OtherCallRecord,
    ResultCallRecord,
    ResultUpload,
    Student,
    StudentResult,
    Subject,
)
from django.utils.html import format_html
from django.contrib import admin
from django.templatetags.static import static
from django.utils.html import format_html

# -------- Mentor --------
@admin.register(Mentor)
class MentorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


# -------- Student --------
@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        'roll_no',
        'name',
        'enrollment',
        'mentor',
        'batch',
        'student_mobile',
        'father_mobile',
        'mother_mobile',
    )

    search_fields = ('name', 'enrollment', 'roll_no', 'student_mobile', 'father_mobile')
    list_filter = ('mentor', 'batch')
    ordering = ('roll_no',)

def print_file(self,obj):
    return format_html(f'<a target="_blank" href="/print-student/{obj.enrollment}/">Print</a>')
print_file.short_description="Register"

list_display = (
    'roll_no','name','enrollment','mentor','batch',
    'student_mobile','father_mobile','mother_mobile','print_file'
)


# -------- Attendance --------
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        'week_no',
        'student',
        'week_percentage',
        'overall_percentage',
        'call_required'
    )

    list_filter = ('week_no', 'call_required', 'student__mentor')
    search_fields = ('student__name', 'student__enrollment')


# -------- Call Record --------
@admin.register(CallRecord)
class CallRecordAdmin(admin.ModelAdmin):
    list_display = (
        'student',
        'week_no',
        'final_status',
        'talked_with',
        'duration',
        'message_sent',
        'created_at'
    )

    list_filter = ('week_no', 'final_status', 'student__mentor')
    search_fields = ('student__name', 'student__enrollment')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "result_format", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(ResultUpload)
class ResultUploadAdmin(admin.ModelAdmin):
    list_display = ("test_name", "subject", "uploaded_by", "uploaded_at", "rows_failed")
    list_filter = ("test_name", "subject")
    search_fields = ("subject__name", "uploaded_by")


@admin.register(StudentResult)
class StudentResultAdmin(admin.ModelAdmin):
    list_display = ("upload", "student", "marks_current", "marks_total", "fail_flag")
    list_filter = ("fail_flag", "upload__test_name", "upload__subject")
    search_fields = ("student__name", "student__enrollment")


@admin.register(ResultCallRecord)
class ResultCallRecordAdmin(admin.ModelAdmin):
    list_display = ("upload", "student", "final_status", "message_sent", "created_at")
    list_filter = ("upload__test_name", "upload__subject", "final_status")
    search_fields = ("student__name", "student__enrollment")


@admin.register(OtherCallRecord)
class OtherCallRecordAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "mentor",
        "last_called_target",
        "final_status",
        "talked_with",
        "updated_at",
    )
    list_filter = ("final_status", "mentor")
    search_fields = ("student__name", "student__enrollment", "mentor__name")

admin.site.site_header = "LJ Attendance Follow-up ERP"
admin.site.site_title = "LJ Admin"
admin.site.index_title = "Coordinator Control Panel"

class AdminMedia:
    class Media:
        css = {"all": (static("admin.css"),)}

admin.site.__class__ = type(
    "CustomAdminSite",
    (admin.site.__class__, AdminMedia),
    {}
)
