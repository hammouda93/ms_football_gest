from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ProspectRequestForm, ProspectStatusForm
from .models import Prospect


def superuser_required(view_func):
    """Allow anonymous users to log in and reject authenticated non-admins."""

    @login_required(login_url="user_login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def request_create(request):
    form = ProspectRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("prospects:request_success")

    return render(request, "prospects/request_form.html", {"form": form})


def request_success(request):
    return render(request, "prospects/request_success.html")


@superuser_required
def prospect_list(request):
    prospects = Prospect.objects.all()
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "").strip()
    valid_statuses = {value for value, _label in Prospect.Status.choices}

    if query:
        prospects = prospects.filter(
            Q(full_name__icontains=query)
            | Q(whatsapp_number__icontains=query)
            | Q(email__icontains=query)
            | Q(country__icontains=query)
            | Q(club__icontains=query)
        )

    if selected_status in valid_statuses:
        prospects = prospects.filter(status=selected_status)
    else:
        selected_status = ""

    page = Paginator(prospects, 25).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "query": query,
        "selected_status": selected_status,
        "status_choices": Prospect.Status.choices,
        "total_count": prospects.count(),
    }
    return render(request, "prospects/prospect_list.html", context)


@superuser_required
@require_POST
def prospect_status_update(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    form = ProspectStatusForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Le statut demandé n’est pas valide.")
        return redirect("prospects:prospect_list")

    prospect.status = form.cleaned_data["status"]
    prospect.save(update_fields=("status", "updated_at"))
    messages.success(
        request,
        f"Le statut de {prospect.full_name} a été mis à jour.",
    )
    return redirect("prospects:prospect_list")
