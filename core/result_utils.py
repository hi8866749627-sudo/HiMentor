import pandas as pd
from django.db import transaction

from .models import ResultCallRecord, ResultUpload, Student, StudentResult, Subject


TESTS = {"T1", "T2", "T3", "T4", "REMEDIAL"}


def _clean_text(val):
    if pd.isna(val):
        return ""
    text = str(val).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _clean_enrollment(val):
    if pd.isna(val):
        return ""
    text = str(val).strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    if "e+" in text.lower():
        try:
            text = "{:.0f}".format(float(text))
        except Exception:
            pass
    return text


def _norm_key(text):
    t = str(text or "").lower()
    return "".join(ch for ch in t if ch.isalnum())


def _subject_base_name(text):
    raw = str(text or "").strip()
    if "(" in raw:
        raw = raw.split("(", 1)[0].strip()
    return raw


def _to_mark(val):
    if pd.isna(val):
        return None, False
    text = str(val).strip().upper()
    if not text:
        return None, False
    if text == "AB":
        return 0.0, True
    try:
        return float(text), False
    except Exception:
        return None, False


def _resolve_col(columns, keywords, fallback=None):
    lower_cols = [str(c).strip().lower() for c in columns]
    for i, name in enumerate(lower_cols):
        if all(k in name for k in keywords):
            return i
    if fallback is not None:
        return fallback
    return None


def _find_col_any(columns, keyword_sets):
    lower_cols = [str(c).strip().lower() for c in columns]
    for keys in keyword_sets:
        for i, name in enumerate(lower_cols):
            if all(k in name for k in keys):
                return i
    return None


def _looks_subheader_row(values):
    txt = " ".join(str(x).strip().lower() for x in values if str(x).strip())
    if not txt:
        return False
    keys = ["test", "t1", "t2", "t3", "t4", "see", "rem", "remedial", "total", "25", "50", "100"]
    return any(k in txt for k in keys)


def _build_df(file_obj):
    raw = pd.read_excel(file_obj, header=None)
    header_row = 0
    for i in range(len(raw)):
        row_text = " ".join(str(x).lower() for x in raw.iloc[i].tolist())
        if ("sr" in row_text or "roll" in row_text) and ("enroll" in row_text or "enrol" in row_text):
            header_row = i
            break
        if "enrollment" in row_text or "enrol" in row_text:
            header_row = i
            break

    row1 = raw.iloc[header_row].tolist() if header_row < len(raw) else []
    row2 = raw.iloc[header_row + 1].tolist() if header_row + 1 < len(raw) else []

    col_count = max(len(row1), len(row2))
    cols = []
    for idx in range(col_count):
        h1 = str(row1[idx]).strip() if idx < len(row1) else ""
        h2 = str(row2[idx]).strip() if idx < len(row2) else ""
        if h1.lower() == "nan":
            h1 = ""
        if h2.lower() == "nan":
            h2 = ""
        if h2 and "unnamed" not in h2.lower():
            col = f"{h1} {h2}".strip()
        else:
            col = h1.strip()
        if not col:
            col = f"col_{idx}"
        cols.append(col)

    data_start = header_row + 1
    if _looks_subheader_row(row2):
        data_start = header_row + 2

    df = raw.iloc[data_start:].copy()
    df.columns = cols[: len(df.columns)]
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _current_mark_col(test_name, subject_name, columns):
    lower_cols = [str(c).strip().lower() for c in columns]
    preferred = []
    if test_name == "T1":
        preferred = [["test-1", "25"], ["test 1", "25"], ["t1"], ["test-1"], ["test 1"]]
    elif test_name == "T2":
        preferred = [["test-2", "25"], ["test 2", "25"], ["t2"], ["test-2"], ["test 2"]]
    elif test_name == "T3":
        preferred = [["test-3", "25"], ["test 3", "25"], ["t3"], ["test-3"], ["test 3"]]
    elif test_name == "T4":
        preferred = [["test-4", "50"], ["test 4", "50"], ["see", "50"], ["t4", "50"], ["t4"], ["see"], ["test-4"], ["test 4"]]
    elif test_name == "REMEDIAL":
        preferred = [["remedial"], ["marks"]]

    for keys in preferred:
        for idx, name in enumerate(lower_cols):
            if all(k in name for k in keys):
                return idx

    subj = str(subject_name or "").strip().lower()
    if subj:
        for idx, name in enumerate(lower_cols):
            if subj in name and ("test" in name or "t1" in name or "t2" in name or "t3" in name or "t4" in name or "see" in name or "rem" in name):
                return idx

    marks_idx = _resolve_col(columns, ["marks"])
    if marks_idx is not None:
        return marks_idx
    return None


def _fail_rule(test_name, marks_current, marks_total):
    if marks_current is None:
        return False, ""

    if test_name == "T1":
        fail = marks_current < 9
        return fail, "Less than 9 marks in T1"
    if test_name == "T2":
        fail = marks_current < 9 and (marks_total is not None and marks_total < 18)
        return fail, "Less than 9 marks in T2 & less than 18 in (T1+T2)"
    if test_name == "T3":
        fail = marks_current < 9 and (marks_total is not None and marks_total < 27)
        return fail, "Less than 9 marks in T3 & less than 27 in (T1+T2+T3)"
    if test_name == "T4":
        fail = marks_current < 18 and (marks_total is not None and marks_total < 35)
        return fail, "Less than 18 marks in SEE & less than 35 in (T1+T2+T3+SEE)"
    if test_name == "REMEDIAL":
        fail = marks_current < 35
        return fail, "Less than 35 marks in REMEDIAL"
    return False, ""


def _save_import_rows(upload, rows, progress_cb=None, cancel_cb=None):
    StudentResult.objects.filter(upload=upload).delete()
    ResultCallRecord.objects.filter(upload=upload).delete()

    rows_total = 0
    rows_matched = 0
    rows_failed = 0

    total_rows = len(rows)
    for idx, row in enumerate(rows, start=1):
        if cancel_cb and cancel_cb():
            raise Exception("Upload cancelled by user.")
        enrollment = _clean_enrollment(row.get("enrollment"))
        if not enrollment:
            continue
        rows_total += 1

        student = Student.objects.filter(module=upload.module, enrollment=enrollment).select_related("mentor").first()
        if progress_cb:
            progress_cb(
                current=idx,
                total=total_rows,
                enrollment=enrollment,
                student_name=(student.name if student else ""),
                message="Reading marks and preparing result call list...",
            )
        if not student:
            continue
        rows_matched += 1

        current_mark = row.get("current_mark")
        m1 = row.get("m1")
        m2 = row.get("m2")
        m3 = row.get("m3")
        m4 = row.get("m4")
        mtotal = row.get("mtotal")
        is_absent = bool(row.get("is_absent", False))

        if upload.test_name == "T2" and mtotal is None and m1 is not None and current_mark is not None:
            mtotal = m1 + current_mark
        if upload.test_name == "T3" and mtotal is None and all(v is not None for v in [m1, m2, current_mark]):
            mtotal = m1 + m2 + current_mark
        if upload.test_name == "T4":
            if mtotal is None and all(v is not None for v in [m1, m2, m3, current_mark]):
                mtotal = m1 + m2 + m3 + (current_mark / 2.0)

        fail_flag, fail_reason = _fail_rule(upload.test_name, current_mark, mtotal)

        StudentResult.objects.create(
            upload=upload,
            student=student,
            enrollment=enrollment,
            marks_current=current_mark,
            marks_t1=m1,
            marks_t2=m2,
            marks_t3=m3,
            marks_t4=m4,
            marks_total=mtotal,
            is_absent=is_absent,
            fail_flag=fail_flag,
            fail_reason=fail_reason,
        )

        if fail_flag:
            rows_failed += 1
            ResultCallRecord.objects.create(
                upload=upload,
                student=student,
                fail_reason=fail_reason,
                marks_current=current_mark or 0,
                marks_total=mtotal,
            )

    upload.rows_total = rows_total
    upload.rows_matched = rows_matched
    upload.rows_failed = rows_failed
    upload.save(update_fields=["rows_total", "rows_matched", "rows_failed", "uploaded_at"])

    return {
        "rows_total": rows_total,
        "rows_matched": rows_matched,
        "rows_failed": rows_failed,
    }


def _read_compiled_layout(file_obj):
    xls = pd.ExcelFile(file_obj)
    if "COMPILED" not in xls.sheet_names:
        raise Exception("COMPILED sheet not found. Please upload compiled file with exact tab name COMPILED.")

    raw = pd.read_excel(xls, sheet_name="COMPILED", header=None)
    if len(raw) < 9:
        raise Exception("Compiled sheet format invalid. Expected headers in row 7-8 and data from row 9.")

    row_subject = raw.iloc[6].tolist()  # row 7
    row_exam = raw.iloc[7].tolist()  # row 8

    enrollment_idx = None
    for idx, v in enumerate(row_subject):
        txt = str(v).lower()
        if "enroll" in txt or "enrol" in txt:
            enrollment_idx = idx
            break
    if enrollment_idx is None:
        for idx, v in enumerate(row_exam):
            txt = str(v).lower()
            if "enroll" in txt or "enrol" in txt:
                enrollment_idx = idx
                break
    if enrollment_idx is None:
        raise Exception("Enrollment column not found in COMPILED row 7/8 headers.")

    blocks = {}
    current_subject = ""
    for idx in range(len(row_exam)):
        s_text = str(row_subject[idx]).strip() if idx < len(row_subject) else ""
        if s_text and s_text.lower() != "nan":
            current_subject = s_text
        exam_key = _exam_key_from_header(row_exam[idx] if idx < len(row_exam) else "")
        if exam_key and current_subject:
            blocks.setdefault(current_subject, {})
            blocks[current_subject][exam_key] = idx

    found_subjects = sorted(blocks.keys())
    if not found_subjects:
        raise Exception("No subject blocks with TEST headers found in COMPILED row 7/8.")

    data_df = raw.iloc[8:].copy()  # row 9 onwards
    return {
        "raw": raw,
        "enrollment_idx": enrollment_idx,
        "blocks": blocks,
        "found_subjects": found_subjects,
        "data_df": data_df,
    }


def _match_compiled_subject(selected_subject_name, found_subjects):
    selected_key = _norm_key(_subject_base_name(selected_subject_name))
    for s in found_subjects:
        s_key = _norm_key(_subject_base_name(s))
        if s_key == selected_key:
            return s
    for s in found_subjects:
        s_key = _norm_key(_subject_base_name(s))
        if selected_key in s_key or s_key in selected_key:
            return s
    return None


def _build_rows_from_compiled_block(data_df, enrollment_idx, cols, test_name):
    parsed_rows = []
    for _, row in data_df.iterrows():
        enrollment = _clean_enrollment(row.iloc[enrollment_idx]) if enrollment_idx < len(row) else ""
        if not enrollment:
            continue

        m1 = m2 = m3 = m4 = mtotal = current_mark = None
        is_absent = False

        if "t1" in cols:
            m1, ab = _to_mark(row.iloc[cols["t1"]]); is_absent = is_absent or ab
        if "t2" in cols:
            m2, ab = _to_mark(row.iloc[cols["t2"]]); is_absent = is_absent or ab
        if "t3" in cols:
            m3, ab = _to_mark(row.iloc[cols["t3"]]); is_absent = is_absent or ab
        if "t4_50" in cols:
            m4, ab = _to_mark(row.iloc[cols["t4_50"]]); is_absent = is_absent or ab
        if "total" in cols:
            mtotal, ab = _to_mark(row.iloc[cols["total"]]); is_absent = is_absent or ab

        c12 = c123 = None
        if "t12" in cols:
            c12, ab = _to_mark(row.iloc[cols["t12"]]); is_absent = is_absent or ab
        if "t123" in cols:
            c123, ab = _to_mark(row.iloc[cols["t123"]]); is_absent = is_absent or ab

        if test_name == "T1":
            current_mark = m1
            mtotal = m1
        elif test_name == "T2":
            current_mark = m2
            mtotal = c12 if c12 is not None else (m1 + m2 if m1 is not None and m2 is not None else mtotal)
        elif test_name == "T3":
            current_mark = m3
            mtotal = c123 if c123 is not None else (m1 + m2 + m3 if m1 is not None and m2 is not None and m3 is not None else mtotal)
        elif test_name == "T4":
            current_mark = m4
        elif test_name == "REMEDIAL":
            current_mark = mtotal

        parsed_rows.append(
            {
                "enrollment": enrollment,
                "current_mark": current_mark,
                "m1": m1,
                "m2": m2,
                "m3": m3,
                "m4": m4,
                "mtotal": mtotal,
                "is_absent": is_absent,
            }
        )
    return parsed_rows


@transaction.atomic
def import_result_sheet(file_obj, upload: ResultUpload, progress_cb=None, cancel_cb=None):
    if upload.test_name not in TESTS:
        raise Exception("Invalid test")

    df = _build_df(file_obj)
    if df.empty:
        raise Exception("Excel file is empty")

    cols = list(df.columns)
    enroll_idx = _resolve_col(cols, ["enrol"])
    if enroll_idx is None:
        raise Exception("Enrollment column not found")

    col_t1 = _find_col_any(cols, [["test-1", "25"], ["test 1", "25"], ["t1"], ["test-1"], ["test 1"]])
    col_t2 = _find_col_any(cols, [["test-2", "25"], ["test 2", "25"], ["t2"], ["test-2"], ["test 2"]])
    col_t3 = _find_col_any(cols, [["test-3", "25"], ["test 3", "25"], ["t3"], ["test-3"], ["test 3"]])
    col_t4 = _find_col_any(cols, [["test-4", "50"], ["test 4", "50"], ["see", "50"], ["t4", "50"], ["t4"], ["test-4"], ["test 4"]])
    col_total = _find_col_any(cols, [["total", "100"], ["total"]])
    col_current = _current_mark_col(upload.test_name, upload.subject.name, cols)

    usable_cols = [c for c in cols if c is not None]
    if col_current is None:
        best_idx = None
        best_score = -1
        for idx, _ in enumerate(usable_cols):
            series = df.iloc[:, idx].dropna().head(100)
            score = 0
            for v in series:
                mark, _abs = _to_mark(v)
                if mark is not None:
                    score += 1
            if score > best_score:
                best_score = score
                best_idx = idx
        col_current = best_idx

    parsed_rows = []
    for _, row in df.iterrows():
        enrollment = _clean_enrollment(row.iloc[enroll_idx])
        if not enrollment:
            continue

        current_mark, is_absent = _to_mark(row.iloc[col_current]) if col_current is not None else (None, False)
        m1, _ = _to_mark(row.iloc[col_t1]) if col_t1 is not None else (None, False)
        m2, _ = _to_mark(row.iloc[col_t2]) if col_t2 is not None else (None, False)
        m3, _ = _to_mark(row.iloc[col_t3]) if col_t3 is not None else (None, False)
        m4, _ = _to_mark(row.iloc[col_t4]) if col_t4 is not None else (None, False)
        mtotal, _ = _to_mark(row.iloc[col_total]) if col_total is not None else (None, False)

        parsed_rows.append(
            {
                "enrollment": enrollment,
                "current_mark": current_mark,
                "m1": m1,
                "m2": m2,
                "m3": m3,
                "m4": m4,
                "mtotal": mtotal,
                "is_absent": is_absent,
            }
        )

    return _save_import_rows(upload, parsed_rows, progress_cb=progress_cb, cancel_cb=cancel_cb)


def _exam_key_from_header(text):
    raw = str(text or "").lower()
    t = raw.replace("\n", " ").replace(" ", "")
    token = "".join(ch for ch in t if ch.isalnum())
    if not t or t == "nan" or token == "nan":
        return ""
    # cumulative columns (most specific first)
    if ("t1+t2+t3" in t or "t1t2t3" in token) and ("75" in t or "75" in token or "t1t2t3" in token):
        return "t123"
    if ("t1+t2" in t or "t1t2" in token) and ("t3" not in t and "t3" not in token) and ("50" in t or "50" in token or "t1t2" in token):
        return "t12"
    if ("test-1" in t or "test1" in t) and ("25" in t or "25" in token):
        return "t1"
    if ("test-2" in t or "test2" in t) and ("25" in t or "25" in token):
        return "t2"
    if ("test-3" in t or "test3" in t) and ("25" in t or "25" in token):
        return "t3"
    if ("test-4" in t or "test4" in t):
        if "50" in t or "50" in token:
            return "t4_50"
        if "25" in t or "25" in token:
            return "t4_25"
        return "t4_50"
    if t.startswith("total") or token.startswith("total"):
        return "total"
    return ""


@transaction.atomic
def import_compiled_result_sheet(file_obj, upload: ResultUpload, progress_cb=None, cancel_cb=None):
    layout = _read_compiled_layout(file_obj)
    found_subjects = layout["found_subjects"]
    selected_block_name = _match_compiled_subject(upload.subject.name, found_subjects)

    if not selected_block_name:
        raise Exception(
            f"Selected subject '{upload.subject.name}' not found in COMPILED row 7. "
            f"Found subjects: {', '.join(found_subjects)}"
        )

    cols = layout["blocks"][selected_block_name]
    if upload.test_name == "T1":
        required = ["t1"]
    elif upload.test_name == "T2":
        required = ["t2", "t1", "t12"]
    elif upload.test_name == "T3":
        required = ["t3", "t1", "t2", "t123"]
    elif upload.test_name == "T4":
        required = ["t4_50", "t4_25", "t1", "t2", "t3", "total"]
    else:
        required = ["total"]

    missing = [k for k in required if k not in cols]
    if missing:
        raise Exception(
            f"Missing required columns for {upload.test_name} in subject '{selected_block_name}': {', '.join(missing)}"
        )

    parsed_rows = _build_rows_from_compiled_block(
        layout["data_df"],
        layout["enrollment_idx"],
        cols,
        upload.test_name,
    )

    summary = _save_import_rows(upload, parsed_rows, progress_cb=progress_cb, cancel_cb=cancel_cb)
    summary["found_subjects"] = found_subjects
    summary["used_subject"] = selected_block_name
    return summary


@transaction.atomic
def import_compiled_bulk_all(file_obj, uploaded_by="", module=None, progress_cb=None, cancel_cb=None):
    if module is None:
        raise Exception("Module is required for bulk import")
    layout = _read_compiled_layout(file_obj)
    found_subjects = layout["found_subjects"]

    subjects = list(Subject.objects.filter(module=module, is_active=True).order_by("name"))
    subject_to_block = {}
    for s in subjects:
        block = _match_compiled_subject(s.name, found_subjects)
        if block:
            subject_to_block[s.id] = block

    # Replace all old result uploads as requested.
    ResultUpload.objects.filter(module=module).delete()

    uploads_created = 0
    rows_total = 0
    rows_matched = 0
    rows_failed = 0
    processed = []

    for s in subjects:
        block = subject_to_block.get(s.id)
        if not block:
            continue
        cols = layout["blocks"][block]
        tests = ["T4"] if s.result_format == Subject.FORMAT_T4_ONLY else ["T1", "T2", "T3", "T4"]
        for test_name in tests:
            if cancel_cb and cancel_cb():
                raise Exception("Upload cancelled by user.")
            upload = ResultUpload.objects.create(
                module=module,
                test_name=test_name,
                subject=s,
                uploaded_by=uploaded_by,
            )
            parsed_rows = _build_rows_from_compiled_block(
                layout["data_df"],
                layout["enrollment_idx"],
                cols,
                test_name,
            )
            summary = _save_import_rows(upload, parsed_rows, progress_cb=progress_cb, cancel_cb=cancel_cb)
            uploads_created += 1
            rows_total += summary["rows_total"]
            rows_matched += summary["rows_matched"]
            rows_failed += summary["rows_failed"]
            processed.append(f"{test_name}-{s.name}")

    return {
        "uploads_created": uploads_created,
        "rows_total": rows_total,
        "rows_matched": rows_matched,
        "rows_failed": rows_failed,
        "found_subjects": found_subjects,
        "processed": processed,
    }
