"""Small cross-app utilities (kept here to avoid circular imports)."""
from .models import Notification


def notify(user, message, notification_type='INJURY', link=''):
    """Create an in-app Notification row. No-op if user is missing/anonymous.

    notification_type must be one of Notification.TYPE_CHOICES keys
    (INJURY, APPOINTMENT, CLEARANCE, EVENT).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    return Notification.objects.create(
        user=user,
        message=message,
        notification_type=notification_type,
        link=link or '',
    )
