import pandas as pd
from .models import Student, Attendance, CallRecord


# ---------------- BASIC CLEANERS ----------------

def clean(val):
    """Convert excel value to clean string"""
    if pd.isna(val):
        return ""
    val = str(val).strip()
    if val.endswith(".0"):
        val = val[:-2]
    return val

def percent_to_float(val):

    if val is None:
        return None

    # if numeric (Excel percent stored as decimal)
    if isinstance(val, (int, float)):
        return round(val * 100, 2)

    val = str(val).strip()

    if not val or "ATTENDANCE" in val.upper():
        return None

    val = val.replace('%', '')

    try:
        return float(val)
    except:
        return None



# ---------------- FIND REAL TABLE ----------------

def find_header_row(df):
    """
    Detect the row where actual table header starts
    (contains Roll and Name)
    """
    for i in range(len(df)):
        row_text = " ".join(str(x).lower() for x in df.iloc[i].values)
        if "roll" in row_text and "name" in row_text:
            return i
    return 0


# ---------------- READ ATTENDANCE SHEET ----------------

def read_sheet(file):

    xls = pd.ExcelFile(file)

    # choose sheet containing OVERALL if exists
    sheet_name = xls.sheet_names[0]
    for s in xls.sheet_names:
        if "OVERALL" in s.upper():
            sheet_name = s
            break

    # read raw to detect header row
    raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    header_row = find_header_row(raw)

    # read with two header rows
    df = pd.read_excel(xls, sheet_name=sheet_name, header=[header_row, header_row+1])

    # ---------------- FIND ATTENDANCE COLUMN ----------------
    percent_col_index = None

    for i, col in enumerate(df.columns):
        top = str(col[0]).lower()
        bottom = str(col[1]).lower()

        if "attendance" in top and "overall" in bottom:
            percent_col_index = i
            break

    if percent_col_index is None:
        raise Exception("Attendance column not found in Excel")

    percent_series = df.iloc[:, percent_col_index]

    # ---------------- FIND ENROLLMENT COLUMN ----------------
    enroll_col_index = None

    for i, col in enumerate(df.columns):
        if "enrol" in str(col[0]).lower():
            enroll_col_index = i
            break

    if enroll_col_index is None:
        raise Exception("Enrollment column not found")

    enroll_series = df.iloc[:, enroll_col_index]

    # ---------------- BUILD RESULT ----------------
    result = {}

    for enrollment, percent in zip(enroll_series, percent_series):

        enrollment = clean(enrollment)
        percent = percent_to_float(percent)

        if enrollment and percent is not None:
            result[enrollment] = percent

    return result

# ---------------- IMPORT LOGIC ----------------

def import_attendance(weekly_file, overall_file, week_no, module, rule="both"):

    weekly = read_sheet(weekly_file)

    # Week 1 overall = weekly
    if week_no == 1 or overall_file is None:
        overall = weekly
    else:
        overall = read_sheet(overall_file)

    created_calls = 0

    for enrollment, week_per in weekly.items():

        try:
            student = Student.objects.get(module=module, enrollment=enrollment)
        except Student.DoesNotExist:
            continue

        overall_per = overall.get(enrollment, week_per)

        # decide call condition
        if rule == "week":
            call_required = week_per < 80
        elif rule == "overall":
            call_required = overall_per < 80
        else:
            call_required = week_per < 80 or overall_per < 80

        # save attendance
        Attendance.objects.update_or_create(
            week_no=week_no,
            student=student,
            defaults={
                'week_percentage': week_per,
                'overall_percentage': overall_per,
                'call_required': call_required
            }
        )

        # create call record
        if call_required:
            CallRecord.objects.get_or_create(student=student, week_no=week_no)
            created_calls += 1

    return created_calls
