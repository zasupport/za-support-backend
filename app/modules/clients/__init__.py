"""
Clients module — onboarding intake, client profiles, task checklists, pre-visit check-ins.
Receives submissions from Formbricks (Form 1: intake, Form 2: pre-visit check-in).
"""
# Import notifications so event bus subscriptions register at startup
from app.modules.clients import notifications as _notifications  # noqa: F401
