from .models import GlobalAuditLog

def log_action(module, action, user=None, candidate=None, details=None, request=None):
    """
    Centralized logging for all modules.
    """
    ip_address = None
    user_agent = ""
    
    if request:
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        
    return GlobalAuditLog.objects.create(
        module=module,
        action=action,
        performed_by=user,
        candidate=candidate,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent
    )
