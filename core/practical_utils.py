import pandas as pd
from django.db import transaction

from .models import PracticalMarkUpload, Student, StudentPracticalMark, Subject


def _norm(text):
    return "".join(ch for ch in str(text or "").strip().lower() if ch.isalnum())


def _to_float_or_none(val):
    if pd.isna(val):
        return None
    txt = str(val).strip()
    if not txt or txt.lower() == "nan" or txt == "-":
        return None
    try:
        return float(txt)
    except Exception:
        return None


def _find_header_row(raw):
    for i in range(len(raw)):
        row = [str(x).strip().lower() for x in raw.iloc[i].tolist()]
        joined = " ".join(row)
        if "sr" in joined and "no" in joined and ("enroll" in joined or "enrollment" in joined):
            return i
    return None


def _find_col_idx(columns, tokens):
    for i, c in enumerate(columns):
        name = _norm(c)
        if all(t in name for t in tokens):
            return i
    return None


def _subject_key_candidates(subject):
    short = (subject.short_name or "").strip()
    name = (subject.name or "").strip()
    out = set()
    if short:
        out.add(_norm(short))
    if name:
        out.add(_norm(name))
    if "(" in name:
        out.add(_norm(name.split("(", 1)[0].strip()))
    # Common aliases for practical/theory sheet naming
    n = _norm(name)
    s = _norm(short)
    alias_map = {
        "cws": ["computerworkshop", "workshop"],
        "phy": ["physics"],
        "maths1": ["mathematics1", "mathematics", "maths"],
        "java1": ["java"],
        "se": ["softwareengineering"],
        "es": ["environmentalscience", "environmentscience"],
        "iot": ["internetofthings"],
    }
    for base, aliases in alias_map.items():
        if s == base or n == base or base in n:
            out.update({_norm(a) for a in aliases})
        if any(_norm(a) in n for a in aliases):
            out.add(base)
    return {x for x in out if x}


def _match_subject_by_text(text, subjects):
    key = _norm(text)
    if not key:
        return None
    for s in subjects:
        keys = _subject_key_candidates(s)
        if any(k == key for k in keys):
            return s
    for s in subjects:
        keys = _subject_key_candidates(s)
        if any((k and (k in key or key in k)) for k in keys):
            return s
    return None


def _subject_priority(subject):
    key = _norm(subject.short_name or subject.name)
    order = [
        "maths1",
        "maths",
        "phy",
        "physics",
        "java1",
        "java",
        "se",
        "softwareengineering",
        "es",
        "environmentalscience",
        "iot",
        "cws",
    ]
    for idx, token in enumerate(order, start=1):
        if token in key:
            return idx
    return 99


def ordered_subjects(module):
    subjects = list(Subject.objects.filter(module=module, is_active=True))
    subjects.sort(key=lambda s: ((s.display_order if s.display_order and s.display_order > 0 else 999999), _subject_priority(s), (s.short_name or s.name or "").lower()))
    return subjects


@transaction.atomic
def import_practical_marks(file_obj, module, uploaded_by=""):
    # Prefer a compiled sheet if present in workbook (contains multiple PR/% columns).
    raw = None
    try:
        xls = pd.ExcelFile(file_obj)
        preferred_names = ["PRACTICLE COMPILED", "PRACTICAL COMPILED"]
        for pname in preferred_names:
            if pname in xls.sheet_names:
                raw = pd.read_excel(xls, sheet_name=pname, header=None)
                break

        if raw is not None:
            header_row = _find_header_row(raw)
            if header_row is None:
                raise Exception("Header row not found in PRACTICLE COMPILED sheet.")

        if raw is not None:
            pass
        else:
            # auto-pick compiled-like sheet if exact name is not present
            best = None
            best_score = -1
            for sh in xls.sheet_names:
                raw_sh = pd.read_excel(xls, sheet_name=sh, header=None)
                hr = _find_header_row(raw_sh)
                if hr is None:
                    continue
                cols = [str(x).strip() for x in raw_sh.iloc[hr].tolist()]
                pr_count = sum(1 for c in cols if "pr" in _norm(c))
                pct_count = sum(1 for c in cols if "%" in str(c) or "percent" in _norm(c))
                score = (pr_count * 10) + pct_count
                if pr_count >= 2 and score > best_score:
                    best_score = score
                    best = raw_sh
            if best is not None:
                raw = best
    except Exception:
        raw = None

    if raw is None:
        raw = pd.read_excel(file_obj, header=None)
    header_row = _find_header_row(raw)
    if header_row is None:
        raise Exception("Header row with 'Sr No' and 'Enrollment Number' not found.")

    columns = [str(x).strip() for x in raw.iloc[header_row].tolist()]
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = columns[: len(data.columns)]
    data = data.dropna(how="all")

    enrollment_idx = _find_col_idx(columns, ["enroll"])
    if enrollment_idx is None:
        raise Exception("Enrollment Number column not found.")

    subjects = ordered_subjects(module)
    if not subjects:
        raise Exception("No subjects configured for selected module. Please add subjects first.")
    subject_map = {s.id: s for s in subjects}

    # Build column map using SHORTNAME-PR and SHORTNAME-% (combined layout).
    col_map = {}
    unknown_headers = []
    norm_columns = [_norm(c) for c in columns]
    for s in subjects:
        keys = _subject_key_candidates(s)
        pr_idx = None
        att_idx = None
        for idx, nc in enumerate(norm_columns):
            for key in keys:
                if not key:
                    continue
                if (key in nc or nc.startswith(key)) and "pr" in nc:
                    pr_idx = idx if pr_idx is None else pr_idx
                if (key in nc or nc.startswith(key)) and (
                    nc.endswith("percent") or nc.endswith("%") or nc.endswith("pct") or "percent" in nc
                ):
                    att_idx = idx if att_idx is None else att_idx
                if (key in nc or nc.startswith(key)) and ("%" in columns[idx] or "percent" in nc):
                    att_idx = idx if att_idx is None else att_idx
        col_map[s.id] = {"pr": pr_idx, "att": att_idx}

    for c in columns:
        n = _norm(c)
        if n.endswith("pr") or "%" in c or "percent" in n:
            matched = False
            for s in subjects:
                keys = _subject_key_candidates(s)
                if any(k and (k in n or n.startswith(k)) for k in keys):
                    matched = True
                    break
            if not matched:
                unknown_headers.append(c)

    has_combined_pattern = any("-" in str(c) and ("PR" in str(c).upper() or "%" in str(c)) for c in columns)
    upload = PracticalMarkUpload.objects.create(module=module, uploaded_by=uploaded_by)

    rows_total = 0
    rows_matched = 0
    bulk = []
    touched_subject_ids = set()

    if has_combined_pattern:
        # Combined upload replaces full practical dataset.
        StudentPracticalMark.objects.filter(module=module).delete()
        for _, row in data.iterrows():
            enrollment = str(row.iloc[enrollment_idx]).strip() if enrollment_idx < len(row) else ""
            if not enrollment or enrollment.lower() == "nan":
                continue
            if enrollment.endswith(".0"):
                enrollment = enrollment[:-2]
            rows_total += 1

            student = Student.objects.filter(module=module, enrollment=enrollment).first()
            if not student:
                continue
            rows_matched += 1

            for sid, idxs in col_map.items():
                pr_val = _to_float_or_none(row.iloc[idxs["pr"]]) if idxs["pr"] is not None else None
                att_val = _to_float_or_none(row.iloc[idxs["att"]]) if idxs["att"] is not None else None
                if pr_val is None and att_val is None:
                    continue
                bulk.append(
                    StudentPracticalMark(
                        module=module,
                        upload=upload,
                        student=student,
                        subject=subject_map[sid],
                        pr_marks=pr_val,
                        attendance_percentage=att_val,
                    )
                )
    else:
        # Subject-wise practical sheet:
        # - detect subject from title rows
        # - detect "Final Practical Marks (out of 100)" column
        subject_text = ""
        for i in range(min(12, len(raw))):
            cells = [str(x).strip() for x in raw.iloc[i].tolist()]
            target_cell = ""
            for cell in cells:
                if "subject name" in cell.lower():
                    target_cell = cell
                    break
            if target_cell:
                # parse only the subject-name cell, not full row (which may include DATE: etc.)
                parts = target_cell.split(":", 1)
                subject_text = (parts[1] if len(parts) > 1 else target_cell).strip()
                break
        subject = _match_subject_by_text(subject_text, subjects)
        if not subject:
            raise Exception(f"Could not map subject from sheet title '{subject_text}'. Set proper short name in Manage Subjects.")

        # find final practical column from row under header (usually next row)
        subheader = raw.iloc[header_row + 1].tolist() if header_row + 1 < len(raw) else []
        scan_cols = [str(c) for c in columns]
        for i, c in enumerate(subheader):
            if i < len(scan_cols) and (not scan_cols[i] or scan_cols[i].lower() == "nan"):
                scan_cols[i] = str(c)
        final_pr_idx = None
        for i, c in enumerate(scan_cols):
            n = _norm(c)
            if "finalpracticalmarks" in n or ("practical" in n and "100" in n):
                final_pr_idx = i
                break
        if final_pr_idx is None:
            # fallback: last numeric-looking column
            final_pr_idx = len(scan_cols) - 1

        touched_subject_ids.add(subject.id)
        StudentPracticalMark.objects.filter(module=module, subject=subject).delete()

        for _, row in data.iterrows():
            enrollment = str(row.iloc[enrollment_idx]).strip() if enrollment_idx < len(row) else ""
            if not enrollment or enrollment.lower() == "nan":
                continue
            if enrollment.endswith(".0"):
                enrollment = enrollment[:-2]
            rows_total += 1
            student = Student.objects.filter(module=module, enrollment=enrollment).first()
            if not student:
                continue
            rows_matched += 1
            pr_val = _to_float_or_none(row.iloc[final_pr_idx]) if final_pr_idx < len(row) else None
            bulk.append(
                StudentPracticalMark(
                    module=module,
                    upload=upload,
                    student=student,
                    subject=subject,
                    pr_marks=pr_val,
                    attendance_percentage=None,
                )
            )

    if bulk:
        StudentPracticalMark.objects.bulk_create(bulk, batch_size=1000)
    # remove stale blank rows if any older imports produced them
    StudentPracticalMark.objects.filter(module=module, pr_marks__isnull=True, attendance_percentage__isnull=True).delete()

    upload.rows_total = rows_total
    upload.rows_matched = rows_matched
    upload.save(update_fields=["rows_total", "rows_matched", "uploaded_at"])

    return {
        "rows_total": rows_total,
        "rows_matched": rows_matched,
        "unknown_headers": unknown_headers,
        "mode": ("combined" if has_combined_pattern else "subject"),
        "uploaded_at": upload.uploaded_at,
    }
