from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def superadmin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if user is a superuser
        if request.user.is_superuser:
            # If the user is a superuser, check if they are in video_editors group
            if request.user.groups.filter(name='video_editors').exists():
                return view_func(request, *args, **kwargs)
            else:
                # Superuser but not in video_editors; still allow access
                return view_func(request, *args, **kwargs)
        else:
            # If not a superuser, deny access
            messages.error(request, 'Vous n\'avez pas la permission d\'accéder à cette page.')
            return redirect('dashboard')

    return _wrapped_view