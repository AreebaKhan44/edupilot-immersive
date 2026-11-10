"""Roles from the roadmap (s.6). A user's role is a Django Group; staff = platform administrator.

  Teacher               plans, adapts, assigns, reviews learner work
  Creator               drafts lessons / 3D assets (cannot approve their own publication)
  Reviewer              curriculum reviewer: accuracy + mapping approval (alias: "Curriculum reviewer")
  Device supervisor     bookings, equipment readiness, faults
  Institution admin     users, classes, policies (sees reports and the lab)
  Student / Guardian    learner and parent (a guardian sees only linked learners)
"""
TEACHER_GROUPS = ("Teacher", "Reviewer", "Curriculum reviewer", "Creator", "Institution admin")
REVIEWER_GROUPS = ("Reviewer", "Curriculum reviewer")
SUPERVISOR_GROUPS = ("Device supervisor",)
ALL_GROUPS = ("Teacher", "Student", "Reviewer", "Guardian", "Creator", "Device supervisor", "Institution admin")


def in_groups(user, names):
    return user.is_authenticated and user.groups.filter(name__in=names).exists()


def is_reviewer(user):
    return user.is_staff or in_groups(user, REVIEWER_GROUPS)


def is_teacher(user):
    return user.is_staff or in_groups(user, TEACHER_GROUPS)


def is_lab_manager(user):
    return is_reviewer(user) or in_groups(user, SUPERVISOR_GROUPS) or in_groups(user, ("Institution admin",))


def can_use_lab(user):
    return is_teacher(user) or in_groups(user, SUPERVISOR_GROUPS)
