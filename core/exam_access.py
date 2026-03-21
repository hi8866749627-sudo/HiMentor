from django.db.models import Q

from .models import AcademicModule, ExamBlock, ModuleExamManager


def exam_modules_for_user(user):
    if not user or not user.is_authenticated:
        return AcademicModule.objects.none()
    return AcademicModule.objects.filter(
        Q(exam_managers__user=user) | Q(exam_sessions__entries__blocks__evaluator=user),
        is_active=True,
    ).distinct().order_by("-id")


def has_exam_section_access(user):
    if not user or not user.is_authenticated:
        return False
    return ModuleExamManager.objects.filter(user=user).exists() or ExamBlock.objects.filter(evaluator=user).exists()


def can_manage_exam_module(user, module):
    if not user or not user.is_authenticated or not module:
        return False
    return ModuleExamManager.objects.filter(module=module, user=user).exists()


def can_enter_exam_block(user, block):
    if not user or not user.is_authenticated or not block:
        return False
    return block.evaluator_id == user.id
