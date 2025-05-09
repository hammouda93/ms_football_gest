from django.shortcuts import render, redirect, get_object_or_404
from .models import Video, VideoEditor, VideoStatusHistory, Player,Payment,Invoice,Expense,Salary,FinancialReport, NonVideoIncome, Notification
from .forms import VideoForm, VideoEditorRegistrationForm, PlayerForm, User, PaymentForm, InvoiceForm,ExpenseForm, NonVideoIncomeForm,NotificationForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q,Count,F,Sum
from django.utils import timezone
from datetime import timedelta,datetime
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from .decorators import superadmin_required
from .models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.views.decorators.http import require_POST 
from django.views.decorators.csrf import csrf_exempt
import threading
from .tasks import add, test_taskk
from .utils import set_signal_processing
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import logging
from .tasks import (
    notify_birthday,
    notify_pending_videos,
    notify_in_progress_or_completed_collab_videos,
    notify_past_deadline_status_videos,
    check_video_count,
    notify_salary_due_for_delivered_videos,
    generate_first_day_of_current_month_report
)


@superadmin_required
@login_required
def create_video_highlight(request):
    player_form = PlayerForm()
    video_form = VideoForm(user=request.user)
    player = None
    selected_player_id = request.POST.get('selected_player_id')

    # Débogage : afficher la valeur de selected_player_id
    print(f'Selected Player ID: {selected_player_id}')

    if request.method == 'POST':
        if 'add_player' in request.POST:
            if selected_player_id:
                try:
                    player = Player.objects.get(id=selected_player_id)
                    player_form = PlayerForm(request.POST, instance=player)  # Lier au joueur existant
                    if player_form.is_valid():
                        player_form.save()  # Mettre à jour les infos du joueur
                        messages.success(request, "Les informations du joueur ont été mises à jour avec succès !")
                    else:
                        messages.error(request, "Veuillez corriger les erreurs dans le formulaire du joueur.")
                except Player.DoesNotExist:
                    messages.error(request, "Le joueur sélectionné n'existe pas.")
            else:
                player_form = PlayerForm(request.POST)
                if player_form.is_valid():
                    player = player_form.save()  # Enregistrer le nouveau joueur
                    messages.success(request, "Le nouveau joueur a été ajouté avec succès !")

            video_form = VideoForm(user=request.user)  # Réinitialiser le formulaire vidéo
            return render(request, 'gestion_joueurs/create_video.html', {
                'video_form': video_form,
                'player_form': player_form,
                'players': Player.objects.all(),
                'new_player_added': True,
                'added_player': player,
            })

        elif 'create_video' in request.POST:
            player_id = request.POST.get('player')
            if player_id:
                video_form = VideoForm(request.POST)
                if video_form.is_valid():
                    video = video_form.save(commit=False)
                    video.player = Player.objects.get(id=player_id)
                    
                    # Capture the selected editor from the form
                    editor_id = request.POST.get('editor')  # Ensure the editor is being passed in the form
                    if editor_id:
                        try:
                            video.editor = VideoEditor.objects.get(id=editor_id)
                        except VideoEditor.DoesNotExist:
                            messages.error(request, "L'éditeur sélectionné n'existe pas.")
                            return render(request, 'gestion_joueurs/create_video.html', {
                                'video_form': video_form,
                                'player_form': player_form,
                                'players': Player.objects.all(),
                                'new_player_added': False,
                                'added_player': None,
                            })
                    else:
                        messages.error(request, "Aucun éditeur sélectionné. Veuillez réessayer.")
                        return render(request, 'gestion_joueurs/create_video.html', {
                            'video_form': video_form,
                            'player_form': player_form,
                            'players': Player.objects.all(),
                            'new_player_added': False,
                            'added_player': None,
                        })
                    
                    video.save()
                    messages.success(request, "La vidéo a été créée avec succès !")
                    return redirect('dashboard')
                else:
                    messages.error(request, "Erreur lors de la création de la vidéo. Veuillez vérifier les informations.")
                    player = Player.objects.get(id=player_id)
            else:
                messages.error(request, "Aucun joueur sélectionné. Veuillez réessayer.")

    players = Player.objects.all()
    return render(request, 'gestion_joueurs/create_video.html', {
        'video_form': video_form,
        'player_form': player_form,
        'players': players,
        'new_player_added': player is not None,
        'added_player': player,
    })



def dashboard(request):
    # Check if we should show only problematic videos
    show_only_problematic = request.GET.get('show_problematic') == 'true'
    # Fetch videos based on user type
    if request.user.is_superuser:
        if show_only_problematic:
            videos = Video.objects.filter(status='problematic').order_by('-video_creation_date')
        else:
            videos = Video.objects.exclude(status='problematic').order_by('-video_creation_date')
        selected_editor = request.GET.get('editor')
        if selected_editor:
            videos = videos.filter(editor__user__username=selected_editor)
    elif hasattr(request.user, 'videoeditor'):
        videos = Video.objects.filter(editor=request.user.videoeditor).exclude(status='problematic').order_by('-video_creation_date')
    else:
        videos = Video.objects.none()

    # Filter logic
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    deadline_filter = request.GET.get('deadline_filter', '')
    league_filter = request.GET.get('league', '')
    tab = request.GET.get('tab', 'ongoing')
    # Filter by selected user if a user is selected
    
    # Apply deadline filter logic
    if deadline_filter:
        today = datetime.now().date()
        if deadline_filter == 'past':
            videos = videos.filter(deadline__lt=today)
        elif deadline_filter == 'today':
            videos = videos.filter(deadline=today)
        elif deadline_filter == '3_days':
            three_days_from_now = today + timedelta(days=3)
            # Include videos with deadlines that are today or within the next 3 days
            videos = videos.filter(deadline__gte=today, deadline__lte=three_days_from_now)
        elif deadline_filter == '1_week':
            one_week_from_now = today + timedelta(weeks=1)
            videos = videos.filter(deadline__gte=today, deadline__lte=one_week_from_now)
        elif deadline_filter == '2_weeks':
            two_weeks_from_now = today + timedelta(weeks=2)
            videos = videos.filter(deadline__gte=today, deadline__lte=two_weeks_from_now)
        elif deadline_filter == '1_month':
            one_month_from_now = today + timedelta(days=30)  # Approximation
            videos = videos.filter(deadline__gte=today, deadline__lte=one_month_from_now)

    # Apply filters based on request parameters
    if search_query:
        videos = videos.filter(
            Q(player__name__icontains=search_query)
        )

    if status_filter:
        videos = videos.filter(status=status_filter)

    if league_filter:
        videos = videos.filter(league=league_filter)

    # Separate videos based on tab selection
    if tab == 'ongoing':
        videos = videos.exclude(status='delivered')
    elif tab == 'delivered':
        videos = videos.filter(status='delivered')

    # Set up pagination
    paginator = Paginator(videos, 20)  # Show 20 videos per page
    page_number = request.GET.get('page')  # Get the page number from the query parameters
    page_obj = paginator.get_page(page_number)  # This is the page object

    ongoing_videos_count  = videos.exclude(status='delivered').count()
    delivered_videos_count = videos.filter(status='delivered').count()

    # Fetch editors for filter (to populate the dropdown)
    editors = VideoEditor.objects.all()
    return render(request, 'gestion_joueurs/dashboard.html', {
        'videos': page_obj,
        'tab': tab,
        'search': search_query,
        'status': status_filter,
        'deadline_filter': deadline_filter,
        'league': league_filter,
        'delivered_videos_count': delivered_videos_count,
        'ongoing_videos_count': ongoing_videos_count,
        'editors': editors,  # Pass editors to the template
        'show_problematic': show_only_problematic,
    })


@superadmin_required
@login_required
def player_dashboard(request):
    players = Player.objects.all().order_by('-player_creation_date')
    
    search_query = request.GET.get('search')
    league_filter = request.GET.get('league')
    position_filter = request.GET.get('position')
    client_fidel_filter = request.GET.get('client_fidel')
    client_vip_filter = request.GET.get('client_vip')

    if search_query:
        players = players.filter(
            Q(name__icontains=search_query) | 
            Q(club__icontains=search_query)
        )

    if league_filter:
        players = players.filter(league=league_filter)
    
    if position_filter:
        players = players.filter(position=position_filter)
    
    if client_fidel_filter:
        players = players.filter(client_fidel=(client_fidel_filter == 'true'))
    
    if client_vip_filter:
        players = players.filter(client_vip=(client_vip_filter == 'true'))

    # Set up pagination
    paginator = Paginator(players, 20)  # Show 20 players per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    players_count = len(players)

    return render(request, 'gestion_joueurs/player_dashboard.html', {
        'page_obj': page_obj,
        'messages': [],
        'request': request,
        'players_count' : players_count,
    })

def user_login(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('dashboard')
    else:
        form = AuthenticationForm()
    
    if request.user.is_authenticated:
        return redirect('dashboard')  # Rediriger si déjà connecté
    
    return render(request, 'gestion_joueurs/login.html', {'form': form})


def user_logout(request):
    logout(request)
    return redirect('user_login')

@login_required
def view_profile(request):
    return render(request, 'gestion_joueurs/view_profile.html', {
        'user': request.user,
    })

@login_required
def video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    return render(request, 'gestion_joueurs/video_status.html', {'video': video})

@login_required
def update_video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)

    if request.method == 'POST':
        # Vérifiez que l'utilisateur est authentifié
        if request.user.is_authenticated:
            new_status = request.POST.get('status')
            video_link = request.POST.get('video_link')  # Get the video link
            set_signal_processing(False)  # Disable signal processing
            # Mettre à jour le statut de la vidéo
            video.video_link = video_link if new_status == 'delivered' else ''  # Set video_link if status is 'delivered'
            video.status = new_status
            video.save()

            messages.success(request, "Le statut de la vidéo a été mis à jour avec succès.")
            return redirect('video_status', video_id=video.id)
        else:
            messages.error(request, "Vous devez être connecté pour mettre à jour le statut de la vidéo.")

    return render(request, 'gestion_joueurs/update_video_status.html', {'video': video})

@superadmin_required
@login_required
def register_video_editor(request):
    if not request.user.is_superuser:
        messages.error(request, "Vous n'avez pas les permissions nécessaires pour accéder à cette page.")
        return redirect('dashboard')

    users = User.objects.exclude(videoeditor__isnull=False)  # Utilisateurs qui ne sont pas encore éditeurs vidéo
    editors = VideoEditor.objects.all()

    if request.method == 'POST':
        user_id = request.POST.get('user')
        if user_id:
            user = User.objects.get(id=user_id)
            editor = VideoEditor(user=user)
            editor.save()
            messages.success(request, f"{user.username} a été ajouté comme éditeur vidéo.")
            return redirect('register_video_editor')

    return render(request, 'gestion_joueurs/register_video_editor.html', {
        'users': users,
        'editors': editors,
    })


@superadmin_required
@login_required
def edit_player(request, player_id):
    player = get_object_or_404(Player, id=player_id)
    videos = Video.objects.filter(player=player).prefetch_related('status_history')  # Utiliser le related_name

    # Ajouter le dernier statut pour chaque vidéo
    for video in videos:
        video.last_status = video.status_history.order_by('-changed_at').first()  # Accéder au bon nom

    if request.method == 'POST':
        form = PlayerForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations du joueur ont été mises à jour avec succès.")
            return redirect('dashboard')
    else:
        form = PlayerForm(instance=player)

    return render(request, 'gestion_joueurs/edit_player.html', {
        'form': form,
        'player': player,
        'videos': videos,
    })
thread_local = threading.local()


@superadmin_required
@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video_status_history = video.status_history.all()  # Utiliser le related_name
    payments = video.payments.all()  # Assure-toi que le modèle Payment a la relation correcte
    previous_editor = video.editor
    # Get the last invoice for the video
    last_invoice = Invoice.objects.filter(video=video).order_by('-invoice_date').first()
     
    # Fetch salaries related to the current video
    salaries = Salary.objects.filter(video=video)
    video_paid = video.invoices.status
    print(previous_editor.user.username)
    # Store the previous editor in thread-local storage
    thread_local.previous_editor = previous_editor
    if request.method == 'POST':
        form = VideoForm(request.POST, instance=video, user=request.user)
        if form.is_valid():
            last_invoice.total_amount = form.cleaned_data.get('total_payment')
            form.save()
            last_invoice.save()
            messages.success(request, "Les informations de la vidéo ont été mises à jour avec succès.")
            return redirect('dashboard')
    else:
        form = VideoForm(instance=video, user=request.user)

    return render(request, 'gestion_joueurs/edit_video.html', {
        'form': form,
        'video': video,
        'video_status_history': video_status_history,
        'payments': payments,
        'salaries': salaries,  # Pass salaries to the template
    })


@login_required
def view_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video_status_history = video.status_history.all()  # Use the related_name for status history
    payments = video.payments.all()  # Ensure the Payment model has the correct relation
    # Get the last invoice for the video
    last_invoice = Invoice.objects.filter(video=video).order_by('-invoice_date').first()
    # Fetch salaries related to the current video
    salaries = Salary.objects.filter(video=video)
    # Extract YouTube video ID
    if video.video_link and 'v=' in video.video_link:
        video_id = video.video_link.split('v=')[-1]
    else:
        video_id = None

    # Calculate the modified deadline (2 days before the original deadline)
    if video.deadline:
        modified_deadline = video.deadline - timedelta(days=2)
    else:
        modified_deadline = None
    # Get today's date
    today = datetime.now().date()


    return render(request, 'gestion_joueurs/view_video.html', {
        'video': video,
        'video_status_history': video_status_history if request.user.is_superuser else None,
        'payments': payments if request.user.is_superuser else None,
        'video_id': video_id,
        'modified_deadline': modified_deadline,
        'today': today,
        'last_invoice': last_invoice,
        'salaries': salaries,  # Pass salaries to the template
    })



@superadmin_required
@login_required
def record_payment(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    player = video.player

    # Fetch all payments related to the video
    payments = Payment.objects.filter(video=video)

    # Get the last invoice for the video
    last_invoice = Invoice.objects.filter(video=video).order_by('-invoice_date').first()

    # Calculate the remaining amount based on the last invoice
    if last_invoice:
        remaining_amount = last_invoice.total_amount - last_invoice.amount_paid
    else:
        remaining_amount = 0.00

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.video = video
            payment.player = player
            payment.created_by = request.user  # Set the user who created the payment
            payment.invoice_id = last_invoice.id

            # Update the invoice based on the new payment
            if last_invoice:
                # Add the new payment amount to the invoice
                last_invoice.amount_paid += payment.amount
                last_invoice.status = (
                    'partially_paid' if last_invoice.amount_paid < last_invoice.total_amount 
                    else 'paid'
                )
                last_invoice.save()  # Save the updated invoice

                # Calculate the new remaining balance for the payment
                payment.remaining_balance = last_invoice.total_amount - last_invoice.amount_paid
            else:
                # If no invoice exists, handle accordingly (e.g., create a new invoice)
                payment.remaining_balance = remaining_amount  # Keep the logic as needed

            payment.save()  # Save the payment after all attributes are set

            messages.success(request, "Le paiement a été enregistré avec succès.")
            return redirect('view_payments')
    else:
        form = PaymentForm()

    return render(request, 'gestion_joueurs/record_payment.html', {
        'form': form,
        'player': player,
        'video': video,
        'payments': payments,
        'last_invoice': last_invoice,
        'remaining_amount': remaining_amount,
    })

@superadmin_required
@login_required
def get_videos_by_editor(request):
    editor_id = request.GET.get('editor_id')

    # Filter videos by editor and exclude those with salary_paid_status as 'paid'
    videos = Video.objects.filter(
        editor_id=editor_id
    ).exclude(
        salary_paid_status=Video.SalaryPaidStatusChoices.PAID  # Ensure this matches your enum or choice field
    ).values('id', 'player__name','season')  # Select only the fields you need

    video_list = list(videos)  # Convert to list for JSON response
    return JsonResponse({'videos': video_list})

@superadmin_required
@login_required
def get_videos_by_player(request, player_id):
    videos = Video.objects.filter(player_id=player_id)
    video_data = [{'id': video.id, 'info': video.info} for video in videos]
    return JsonResponse({'videos': video_data})

@superadmin_required
@login_required
def get_remaining_balance(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    remaining_balance = video.total_payment - video.advance_payment
    return JsonResponse({'remaining_balance': remaining_balance})

@superadmin_required
@login_required
def search_players(request):
    query = request.GET.get('q', '')
    players = Player.objects.filter(name__icontains=query).values('id', 'name', 'date_of_birth', 'league', 'club', 'whatsapp_number')[:10]
    return JsonResponse({'players': list(players)})

@superadmin_required
@login_required
def create_invoice(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('view_invoices')
    else:
        form = InvoiceForm()
    return render(request, 'gestion_joueurs/create_invoice.html', {'form': form})

@superadmin_required
@login_required
def view_payments(request):
    # Get search terms for video and player from GET parameters
    search_video = request.GET.get('search_video', '')
    search_player = request.GET.get('search_player', '')
    # Initialize the filter condition using Q objects
    filter_conditions = Q()
    # Start with all payments
    payments = Payment.objects.all().order_by('-payment_date')

    # Apply filter by video if search term exists
    if search_video:
        filter_conditions &= (
            Q(video__player__name__icontains=search_video) |  # Match by player name
            Q(video__editor__user__username__icontains=search_video) |  # Match by editor username
            Q(video__season__icontains=search_video)  # Match by editor username
        )

    # Apply filter by player if search term exists
    if search_player:
        filter_conditions &= Q(player__name__icontains=search_player)

    payments = Payment.objects.filter(filter_conditions).order_by('-payment_date')

     # Pagination
    paginator = Paginator(payments, 20)  # Show 20 payments per page
    page_number = request.GET.get('page')  # Get the current page number from the GET request
    page_obj = paginator.get_page(page_number)  # Get the Page object for the current page
    # Filter payments based on the combined Q object conditions
    
    

    return render(request, 'gestion_joueurs/view_payments.html', {
        'payments': page_obj,
        'search_video': search_video,
        'search_player': search_player,
    })


@superadmin_required
@login_required
def view_invoices(request):
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    video_status_filter = request.GET.get('video_status', '')
    tab = request.GET.get('tab', 'not_delivered')  # Default to 'not_delivered'

    # Start with all invoices
    invoices = Invoice.objects.all()

    # Apply search query
    if search_query:
        invoices = invoices.filter(
            Q(video__player__name__icontains=search_query) | 
            Q(video__editor__user__username__icontains=search_query)
        )

    # Filter by invoice status if provided
    if status_filter:
        invoices = invoices.filter(status=status_filter)

    # Filter by video status if provided
    if video_status_filter:
        invoices = invoices.filter(video__status=video_status_filter)

    # Separate invoices based on tab selection
    if tab == 'delivered':
        invoices = invoices.filter(video__status='delivered')
    else:  # Default to 'not_delivered'
        invoices = invoices.exclude(video__status='delivered')

    # Set up pagination
    paginator = Paginator(invoices, 20)  # Show 20 invoices per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Count items
    delivered_invoices_count = invoices.filter(video__status='delivered').count()
    not_delivered_invoices_count = invoices.exclude(video__status='delivered').count()

    return render(request, 'gestion_joueurs/view_invoices.html', {
        'invoices': page_obj,  # Use the paginated invoices
        'search_query': search_query,
        'status_filter': status_filter,
        'video_status_filter': video_status_filter,
        'tab': tab,
        'delivered_invoices_count': delivered_invoices_count,
        'not_delivered_invoices_count': not_delivered_invoices_count,
        'page_obj': page_obj,  # Pass page_obj to the template for pagination
    })

@superadmin_required
@login_required
def add_expense(request):
    editors = VideoEditor.objects.all()
    videos = Video.objects.all()

    if request.method == 'POST':
        video_editor_id = request.POST.get('editor')
        form = ExpenseForm(request.POST, video_editor_id=video_editor_id)

        print("Request POST data:", request.POST)  # Debugging line
        
        if form.is_valid():
            # Create the expense instance
            expense = form.save(commit=False)
            expense.created_by = request.user
            
            # Extract cleaned data
            salary_amount = form.cleaned_data.get('salary_amount')  
            video = form.cleaned_data.get('video')  # Video object
            video_id = video.id if video else None  # Get the ID of the Video object
            
            print(f"Form data: {form.cleaned_data}")  
            print(f"Video ID: {video_id}, Salary Amount: {salary_amount}")
            
            
            
            if expense.category == 'salary':
                # Fetch the VideoEditor object based on the selected editor
                video_editor = VideoEditor.objects.filter(id=video_editor_id).first()
                if video_editor:
                    video_editor_user_id = video_editor.user.id  # Get the user ID related to the video editor
                if salary_amount is not None and video_id is not None:
                    # Create Salary record
                    salary = Salary.objects.create(
                        user_id=video_editor.user.id,  # Assuming the salary is linked to the user creating the expense
                        amount=salary_amount,
                        video_id =video_id,
                        created_by=request.user
                    )
                    expense.salary = salary  # Link the salary to the expense
                    expense.save()  # Save the expense with the linked salary
                    messages.success(request, "Salaire enregistré avec succès.")  # Success message
    
                    # Optionally update the salary paid status if a video is selected
                    if video_id:
                        Video.objects.filter(id=video_id).update(salary_paid_status=form.cleaned_data.get('salary_paid_status'))
                    print(f"Salary created with ID: {salary.id}")  
                else:
                    print("Error: Missing salary information.")
                    messages.error(request, "Please provide both a salary amount and select a video.")
            else:
                # For non-salary categories, save the expense without needing a video
                expense.description = form.cleaned_data.get('description')
                expense.amount = form.cleaned_data.get('amount')
                expense.category = form.cleaned_data.get('category')
                expense.save()  # Save the expense normally
                messages.success(request, "Depense enregistré avec succès.")  # Success message
            return redirect('view_expenses')
        else:
            print("Form errors:", form.errors)  
            messages.error(request, "There was an error with your submission. Please check the form.")

    else:
        form = ExpenseForm(user=request.user)

    return render(request, 'gestion_joueurs/add_expense.html', {
        'form': form,
        'videos': videos,
        'editors': editors
    })


@superadmin_required
@login_required
def edit_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    salary = None
    selected_video = None
    video_editor = None

    if expense.salary:
        salary = expense.salary
        selected_video = salary.video
        if selected_video:
            video_editor = selected_video.editor
    form = ExpenseForm(instance=expense, user=request.user)

    # Set initial form fields
    if expense.category == 'salary':
        form.fields['salary_amount'].initial = salary.amount if salary else None
        form.fields['video'].initial = selected_video.id if selected_video else None
        form.fields['video_editor'].initial = video_editor.id if video_editor else None
        form.fields['salary_paid_status'].initial = selected_video.salary_paid_status if selected_video else None

    form.fields['date'].initial = expense.date.strftime('%Y-%m-%d')

    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user)
        print("Request method is POST.")  # Debugging line
        print("POST data:", request.POST)
        # Update the queryset for video based on the video_editor selected in POST data
        video_editor_id = form.data.get('video_editor')
        if video_editor_id:
            form.fields['video'].queryset = Video.objects.filter(editor_id=video_editor_id)

        print("Available video IDs in form queryset:", form.fields['video'].queryset.values_list('id', flat=True))
        if form.is_valid():
            print("Form is valid.")  # Debugging line
            category = form.cleaned_data['category']

            # Update basic expense fields
            expense.amount = form.cleaned_data['amount']
            expense.date = form.cleaned_data['date']
            expense.category = category
            expense.description = form.cleaned_data['description']

            # Check if category is salary before updating salary details
            if category == 'salary' and salary:
                salary.amount = form.cleaned_data['salary_amount']
                salary.video = form.cleaned_data['video']  # Ensure video is valid
                salary.save()
                print("Salary updated.")  # Debugging line
                
            if category == 'salary' and salary:
                messages.success(request, "Salaire mise à jour avec succès.")  # Success message
            else:
                messages.success(request, "Dépense mise à jour avec succès.")  # Success message
            expense.save()  # Save the expense instance
            print("Expense saved.")  # Debugging line
            
            # Update the video salary paid status if applicable
            if selected_video:
                Video.objects.filter(id=selected_video.id).update(salary_paid_status=form.cleaned_data.get('salary_paid_status'))
                print("Video salary paid status updated.")  # Debugging line

            return redirect('view_expenses')
        else:
            print("Form errors:", form.errors)  # Log form errors for debugging
            messages.error(request, "Erreur lors de la mise à jour de la dépense. Veuillez vérifier le formulaire.")
    if video_editor:
        form.fields['video'].queryset = Video.objects.filter(editor_id=video_editor.id)
    else:
        form.fields['video'].queryset = Video.objects.none()
    videos = Video.objects.all()
    print("Selected video ID:", selected_video.id if selected_video else "None")
    return render(request, 'gestion_joueurs/edit_expense.html', {
        'form': form,
        'expense': expense,
        'videos': videos,
        'salary': salary,
        'video': selected_video,
        'video_editor': video_editor,
        'selected_video': selected_video,
    })


@superadmin_required
@login_required
def view_expenses(request):
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')

    # Start with all expenses created by the user
    expenses = Expense.objects.filter()

    # Filter by search query if it exists
    if search_query:
        expenses = expenses.filter(description__icontains=search_query)

    # Filter by category if it exists
    if category_filter:
        expenses = expenses.filter(category=category_filter)

    # Order the results by date
    expenses = expenses.order_by('-date')
    expenses_count = len(expenses)
    # Pagination
    paginator = Paginator(expenses, 20)  # Show 20 payments per page
    page_number = request.GET.get('page')  # Get the current page number from the GET request
    page_obj = paginator.get_page(page_number)  # Get the Page object for the current page

    return render(request, 'gestion_joueurs/view_expenses.html', {
        'expenses': page_obj,
        'search': search_query,
        'category': category_filter,
        'expenses_count':expenses_count,
    })


@login_required
def manage_salaries(request):
    # Handle user selection and search
    selected_user_id = request.GET.get('user')
    search_description = request.GET.get('search')
    
    if request.user.is_superuser:
        salaries = Salary.objects.all().order_by('-date')
    else:
        # Non-superadmin users should only see their own salaries
        salaries = Salary.objects.filter(user=request.user)

    # Filter by selected user if a user is selected
    if selected_user_id:
        salaries = salaries.filter(user__id=selected_user_id)

    # If there's a search term, filter by description of expenses
    if search_description:
        salaries = salaries.filter(
            Q(expense__description__icontains=search_description) |
            Q(amount__icontains=search_description)
        )

    # Paginate salaries - 20 per page
    paginator = Paginator(salaries, 20)  # Show 20 salaries per page
    page_number = request.GET.get('page')  # Get the page number from the request
    try:
        page_obj = paginator.get_page(page_number)  # Get the salaries for the current page
    except EmptyPage:
        page_obj = paginator.get_page(1)  # If page is out of range, show the first page

    # Fetch the related expense for each salary only after filtering
    for salary in page_obj:
        salary.expense = Expense.objects.filter(salary=salary).first()

    return render(request, 'gestion_joueurs/manage_salaries.html', {
        'salaries': page_obj,
        'users': User.objects.all(),  # Pass all users for the dropdown
        'selected_user_id': selected_user_id,
        'search_description': search_description,
    })

@superadmin_required
@login_required  # Ensure that only logged-in users can add income
def add_non_video_income(request):
    if request.method == 'POST':
        form = NonVideoIncomeForm(request.POST)
        if form.is_valid():
            # Set the user who created the income
            non_video_income = form.save(commit=False)
            non_video_income.created_by = request.user
            non_video_income.save()
            messages.success(request, "Le revenu non-vidéo a été ajouté avec succès.")
            return redirect('non_video_income_list')  # Redirect after saving
        else:
            messages.error(request, "Une erreur s'est produite lors de l'ajout du revenu non-vidéo.")

    else:
        
        # Pre-fill the date field with today's date
        form = NonVideoIncomeForm(initial={'date': timezone.now().date()})

    return render(request, 'gestion_joueurs/add_non_video_income.html', {'form': form})

@superadmin_required
@login_required
def edit_non_video_income(request, pk):
    # Fetch the NonVideoIncome instance based on the primary key (pk)
    non_video_income = get_object_or_404(NonVideoIncome, pk=pk)

    if request.method == 'POST':
        form = NonVideoIncomeForm(request.POST, instance=non_video_income)
        if form.is_valid():
            # Save the updated NonVideoIncome instance
            form.save()
            messages.success(request, "Le revenu non-vidéo a été mis à jour avec succès.")
            return redirect('non_video_income_list')  # Redirect after saving
        else:
            messages.error(request, "Une erreur s'est produite lors de la mise à jour du revenu non-vidéo.")
    else:
        form = NonVideoIncomeForm(instance=non_video_income)  # Prefill the form with the existing data

    return render(request, 'gestion_joueurs/edit_non_video_income.html', {'form': form, 'non_video_income': non_video_income})

# Set up a logger for debugging
logger = logging.getLogger('msfootball')

@superadmin_required
@login_required
def non_video_income_list(request):
    # Get the search term and category filter from GET parameters
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')

    # Print the filters to debug
    print(f"Search term: {search}")
    print(f"Category filter: {category}")
    
    # Get all the NonVideoIncome records
    incomes = NonVideoIncome.objects.all().order_by('-created_at')

    # Search filter: search by description
    if search:
        incomes = incomes.filter(description__icontains=search)
    
    # Print after applying the search filter
    print(f"Incomes after search filter: {incomes.count()}")

    # Category filter
    if category:
        incomes = incomes.filter(category=category)
    
    # Print after applying the category filter
    print(f"Incomes after category filter: {incomes.count()}")
    
    # Print after filtering by user
    print(f"Incomes after user filter (created_by={request.user.id}): {incomes.count()}")

    # Paginate the filtered query set
    paginator = Paginator(incomes, 20)  # Show 20 items per page
    page_number = request.GET.get('page')  # Get the page number from the URL
    page_obj = paginator.get_page(page_number)

    # Print the total count of records after pagination
    print(f"Total records after pagination: {page_obj.paginator.count}")

    # Get the category choices
    non_video_income_categories = NonVideoIncome.category_choices

    return render(request, 'gestion_joueurs/non_video_income_list.html', {
        'non_video_incomes': page_obj,
        'search': search,
        'category': category,
        'non_video_income_categories': non_video_income_categories,  # Pass the categories to the template
        'incomes_count': len(incomes),
        'incomes': incomes,
    })


@superadmin_required
@login_required
def generate_financial_report(request):
    # Calculer le total des revenus des factures
    total_invoice_income = 0
    for invoice in Invoice.objects.all():
        if invoice.amount_paid > invoice.total_amount:
            total_invoice_income += invoice.amount_paid  # Only add total_amount if amount_paid > total_amount
        else:
            total_invoice_income += invoice.total_amount  # Otherwise, add the amount_paid
    total_paid_income = Invoice.objects.aggregate(total=Sum('amount_paid'))['total'] or 0

    # Calculer le total des dépenses par catégorie
    expenses = Expense.objects.values('category').annotate(total=Sum('amount'))
    total_expenses = sum(expense['total'] for expense in expenses)

    # Calculer les salaires par utilisateur
    salaries = Salary.objects.values('user__username').annotate(total=Sum('amount'))

    # Calculate additional fields
    total_outstanding_payments = total_invoice_income - total_paid_income
    other_income = NonVideoIncome.objects.aggregate(total=Sum('amount'))['total'] or 0
    global_income = total_paid_income + NonVideoIncome.objects.aggregate(total=Sum('amount'))['total'] or 0


    net_revenue_if_all_paid = total_invoice_income - total_expenses
    # Créer ou mettre à jour le rapport financier
    report = FinancialReport.objects.create(
        global_income=global_income,
        total_outstanding_income=total_outstanding_payments,
        total_income=total_paid_income,
        total_expenses=total_expenses,
        created_by=request.user,
        net_revenue_if_all_paid = net_revenue_if_all_paid
    )
    report.calculate_net_profit()
    messages.success(request, "Le rapport financier généré avec succès.")
    # Calculer la différence avec le total des vidéos
    difference = total_invoice_income - report.total_income

    # Calculer le revenu net
    net_revenue = report.total_income - total_expenses
    return render(request, 'gestion_joueurs/financial_report.html', {
        'report': report,
        'expenses': expenses,
        'salaries': salaries,
        'total_invoice_income': total_invoice_income,
        'difference': difference,
        'net_revenue': net_revenue,  # Passer le revenu net à la template
        'net_revenue_if_all_paid': net_revenue_if_all_paid,
        'global_income': global_income,
        'other_income' : other_income,
    })

@superadmin_required
@login_required
def view_financial_report(request, pk):
    # Fetch the existing financial report by its primary key
    report = get_object_or_404(FinancialReport, pk=pk)
    expenses = Expense.objects.filter(date__lte=report.report_date).values('category').annotate(total=Sum('amount'))
    # Aggregate the total of paid invoices if needed (this can be redundant if stored in the model)
    total_invoice_income = Invoice.objects.filter(invoice_date__lte=report.report_date).aggregate(total=Sum('amount_paid'))['total'] or 0

    # Total salaries (if applicable for charts or display)
    salaries = Salary.objects.filter(date__lte=report.report_date).values('user__username').annotate(total=Sum('amount'))
    other_income = NonVideoIncome.objects.filter(date__lte=report.report_date).aggregate(total=Sum('amount'))['total'] or 0
    # Use the values directly from the report for rendering
    return render(request, 'gestion_joueurs/financial_report.html', {
        'report': report,
        'expenses':expenses,
        'salaries': salaries,
        'total_invoice_income': total_invoice_income,
        'other_income' : other_income,
    })



@superadmin_required
@login_required
def financial_report_list(request):
    selected_year = request.GET.get('year', '')
    selected_month = request.GET.get('month', '')
    selected_day = request.GET.get('day', '')

    # Convert to integers if not empty
    if selected_year:
        selected_year = int(selected_year)
    if selected_month:
        selected_month = int(selected_month)
    if selected_day:
        selected_day = int(selected_day)

    # Ensure that the filters are applied only if the values are not empty
    reports = FinancialReport.objects.all().order_by('-report_date')

    if selected_year:
        reports = reports.filter(report_date__year=selected_year)
    if selected_month:
        reports = reports.filter(report_date__month=selected_month)
    if selected_day:
        reports = reports.filter(report_date__day=selected_day)

    # Get distinct years, months, and days
    distinct_years = FinancialReport.objects.values_list('report_date__year', flat=True).distinct()
    distinct_months = FinancialReport.objects.filter(report_date__year=selected_year).values_list('report_date__month', flat=True).distinct() if selected_year else []
    distinct_days = FinancialReport.objects.filter(report_date__year=selected_year, report_date__month=selected_month).values_list('report_date__day', flat=True).distinct() if selected_month else []

    # Pass the filtered reports and distinct years, months, days to the template
    return render(request, 'gestion_joueurs/financial_report_list.html', {
        'reports': reports,
        'distinct_years': distinct_years,
        'distinct_months': distinct_months,
        'distinct_days': distinct_days,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'selected_day': selected_day,
    })


def get_months(request):
    year = request.GET.get('year')

    if not year:
        return JsonResponse({'error': 'Year is required'}, status=400)

    # Fetch distinct months for the selected year
    months = FinancialReport.objects.filter(report_date__year=year).values_list('report_date__month', flat=True).distinct()

    return JsonResponse({'months': sorted(months)})


def get_days(request):
    year = request.GET.get('year')
    month = request.GET.get('month')

    if not year or not month:
        return JsonResponse({'error': 'Year and Month are required'}, status=400)

    # Fetch distinct days for the selected year and month
    days = FinancialReport.objects.filter(report_date__year=year, report_date__month=month).values_list('report_date__day', flat=True).distinct()

    return JsonResponse({'days': sorted(days)})










@superadmin_required
@login_required
def StatisticalDashboardView(request):
    # Statistiques des joueurs
    total_players = Player.objects.count()
    players_by_position = Player.objects.values('position').annotate(count=Count('id'))
    players_by_league = Player.objects.values('league').annotate(count=Count('id'))
    # Count of VIP and Loyal clients
    total_vip_clients = Player.objects.filter(client_vip=True).count()
    total_loyal_clients = Player.objects.filter(client_fidel=True).count()
    other_clients = total_players - (total_vip_clients + total_loyal_clients)
    top_loyal_players = Player.objects.annotate(video_count=Count('video')).filter(client_fidel=True).order_by('-video_count')[:3]

    # Count of videos in progress
    total_videos_in_progress = Video.objects.exclude(status__in=['delivered', 'problematic']).count()
    # Count of videos with collaborators (excluding the super admin)
    total_videos_with_collaborators = Video.objects.filter(
        editor__user__is_superuser=False
    ).exclude(status__in=['delivered', 'problematic']).count()
    # Video status distribution (excluding delivered)
    video_status_distribution_in_progress = Video.objects.exclude(status__in=['delivered', 'problematic']).values('status').annotate(count=Count('id'))



    # Statistiques des vidéos
    total_videos_delivered = Video.objects.filter(status='delivered').count()
    total_videos_in_progress = Video.objects.exclude(status__in=['delivered', 'problematic']).count()
    video_status_distribution = Video.objects.values('status').annotate(count=Count('id'))

    # Statistiques financières
    total_expenses = Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_revenue = Invoice.objects.aggregate(Sum('amount_paid'))['amount_paid__sum'] or 0
    total_invoice_income = 0
    for invoice in Invoice.objects.all():
        if invoice.video.status == 'problematic':
        # If the invoice status is problematic, only add the amount_paid
            total_invoice_income += invoice.amount_paid
        else:
            # If the invoice status is not problematic, apply the existing logic
            if invoice.amount_paid > invoice.total_amount:
                total_invoice_income += invoice.amount_paid  # Only add amount_paid if it's greater than total_amount
            else:
                total_invoice_income += invoice.total_amount  # Otherwise, add the total_amount
            
    total_outstanding_payments = total_invoice_income - total_revenue
    total_gain = total_revenue - total_expenses
    
    # Récupérer les vidéos avec le deadline le plus proche (excluant "completed" et "delivered")
    upcoming_deadlines = Video.objects.filter(
        deadline__gte=timezone.now()
    ).exclude(
        status__in=['completed', 'delivered', 'problematic']
    ).order_by('deadline')[:10]

    # Récupérer les vidéos avec deadline passée
    past_deadline_videos = Video.objects.filter(deadline__lt=timezone.now()).exclude(
        status__in=['delivered', 'problematic']).order_by('deadline')
    count_past_deadline_videos = past_deadline_videos.count()

    # Rapport financier
    financial_reports = FinancialReport.objects.all()
    latest_financial_report = financial_reports.order_by('-report_date').first()

    # Statistiques des vidéos
    total_videos_delivered = Video.objects.filter(status='delivered').count()
    total_videos_in_progress = Video.objects.exclude(status__in=['delivered', 'problematic']).count()

    # Vidéos en attente de livraison (deadline passé et non livrées)
    total_videos_pending_delivery = Video.objects.filter(
        deadline__lt=timezone.now()
    ).exclude(status__in=['delivered', 'problematic']).count()

    # Vidéos non finies (statuts différents de 'completed' et 'delivered')
    total_videos_not_finished = Video.objects.exclude(
        status__in=['completed', 'delivered', 'problematic']
    ).filter(deadline__lt=timezone.now()).count()  # Anciens et non finis

    # Count of completed collaboration videos
    completed_collab_videos = Video.objects.filter(status='completed_collab').order_by('deadline')
    count_completed_collab = completed_collab_videos.count()

    # Récupérer les 15 vidéos avec le deadline le plus proche (excluant "completed" et "delivered")
    upcoming_deadlines = Video.objects.filter(
        deadline__gte=timezone.now()
    ).exclude(
        status__in=['completed', 'delivered', 'problematic']
    ).order_by('deadline')[:15]

    completed_videos_not_paid = Video.objects.filter(
        status='completed',
        invoices__status__in=['unpaid', 'partially_paid'],  # Filtering based on the invoice status
    )
    count_completed_not_paid = completed_videos_not_paid.count()

    delivered_videos_not_paid = Video.objects.filter(
        status='delivered',
        invoices__status__in=['unpaid', 'partially_paid']  # Filtering based on the invoice status
    )

    count_delivered_not_paid = delivered_videos_not_paid.count()

    # Pending videos with advance = 0
    pending_videos_no_advance = Video.objects.filter(
        status__in=['pending','in_progress','completed_collab'],
        invoices__status='unpaid'
    )
    count_pending_no_advance = pending_videos_no_advance.count()

    # Get videos where the invoice is paid or partially paid, but the editor's salary is not paid
    videos_delivered_not_paid = Video.objects.filter(
        status='delivered',
    ).exclude(
        salary_paid_status='paid'  # Exclude videos where the editor's salary is marked as 'paid'
    ).filter(
        invoices__status__in=['paid', 'partially_paid']  # Filter for videos with invoices that are 'paid' or 'partially_paid'
    ).select_related('editor', 'invoices').filter(
        editor__user__is_superuser=False  # Filter where the editor's user is not a superuser
    )

    # Completed collaboration videos with pending payments for editor and the invoice status
    completed_collab_videos_not_paid = Video.objects.filter(
        status='completed_collab',
    ).exclude(
        salary_paid_status='paid'  # Exclude where the editor's salary is 'paid'
    ).select_related('editor', 'invoices').filter(
        editor__user__is_superuser=False  # Filter where the editor's user is not a superuser
    )


    # Préparer le contexte pour le template
    context = {
        'total_players': total_players,
        'total_vip_clients': total_vip_clients,
        'total_loyal_clients': total_loyal_clients,
        'other_clients': other_clients,
        'top_loyal_players': top_loyal_players,
        
        'players_by_position': players_by_position,
        'players_by_league': players_by_league,
        
        'total_videos_delivered': total_videos_delivered,
        'total_videos_in_progress': total_videos_in_progress,
        'video_status_distribution': video_status_distribution,
        'total_expenses': total_expenses,
        'total_revenue': total_revenue,
        'total_outstanding_payments': total_outstanding_payments,
        'total_gain': total_gain,
        'upcoming_deadlines': upcoming_deadlines,
        'past_deadline_videos': past_deadline_videos,
        'count_past_deadline_videos': count_past_deadline_videos,

        'latest_financial_report': latest_financial_report,
        'total_videos_pending_delivery': total_videos_pending_delivery,
        'total_videos_not_finished': total_videos_not_finished,
        'count_completed_not_paid': count_completed_not_paid,
        'completed_videos_not_paid': completed_videos_not_paid,
        'count_delivered_not_paid': count_delivered_not_paid,
        'delivered_videos_not_paid': delivered_videos_not_paid,
        'count_pending_no_advance': count_pending_no_advance,
        'pending_videos_no_advance': pending_videos_no_advance,
        'count_completed_collab': count_completed_collab,
        'completed_collab_videos': completed_collab_videos,
        'total_videos_in_progress': total_videos_in_progress,
        'total_videos_with_collaborators': total_videos_with_collaborators,
        'video_status_distribution_in_progress': video_status_distribution_in_progress,
        'videos_delivered_not_paid': videos_delivered_not_paid,
        'completed_collab_videos_not_paid': completed_collab_videos_not_paid,
        'count_videos_delivered_not_paid': videos_delivered_not_paid.count(),
        'count_completed_collab_videos': completed_collab_videos_not_paid.count(),
            
    }

    return render(request, 'gestion_joueurs/statistical_dashboard.html', context)


@login_required
def notification_list(request):
    # Check if the user is a superuser
    is_superuser = request.user.is_superuser

    # Filter by user if not superuser, or allow filtering for all users if superuser
    selected_user_id = request.GET.get('user', '')
    search_query = request.GET.get('search', '')

    # Base queryset for notifications
    notifications_list = Notification.objects.all().order_by('-created_at')
    print(f"{notification_list}")
    if not is_superuser:
        notifications_list = notifications_list.filter(user=request.user)
    else:
        if selected_user_id:
            notifications_list = notifications_list.filter(user_id=selected_user_id)
        if search_query:
            notifications_list = notifications_list.filter(Q(message__icontains=search_query))

    # Get all users for superuser filtering options
    users = User.objects.all() if is_superuser else []

    # Pagination (show 20 notifications per page)
    paginator = Paginator(notifications_list, 20)  # Show 20 notifications per page
    page = request.GET.get('page')

    try:
        notifications_page = paginator.page(page)
    except PageNotAnInteger:
        notifications_page = paginator.page(1)  # If page is not an integer, show the first page
    except EmptyPage:
        notifications_page = paginator.page(paginator.num_pages)  # If page is out of range, show the last page

    # Pass context to the template
    return render(request, 'gestion_joueurs/notification_list.html', {
        'notifications_list': notifications_page,
        'users': users,
        'selected_user_id': selected_user_id,
        'search': search_query,
    })

@login_required
def view_notification(request, notification_id):
    # Get the notification by its ID, or 404 if not found
    notification = get_object_or_404(Notification, id=notification_id)
    
    # Mark the notification as read (if not already read)
    if not notification.is_read:
        notification.is_read = True
        notification.save()

    return render(request, 'gestion_joueurs/view_notification.html', {
        'notification': notification,
    })

@login_required
def add_notification(request):
    if request.method == 'POST':
        form = NotificationForm(request.POST)
        if form.is_valid():
            notification = form.save(commit=False)  # Don't save yet, we need to modify some fields
            notification.sent_by = request.user
            notification.sent_at = timezone.now()
            notification.save()
            messages.success(request, "La notification a été envoyé avec succès.")
            return redirect('notification_list')  # Redirect back to notification list after success
    else:
        form = NotificationForm()

    return render(request, 'gestion_joueurs/add_notification.html', {'form': form})


@login_required
def notification_center(request):
    notifications_list = Notification.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'notification_center.html', {'notifications_list': notifications_list})

@login_required
@require_POST
def mark_notification_as_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True  # or however you track read notifications
    notification.save()

    # Return the updated count of unread notifications
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'unread_count': unread_count})

def test_task(request):
    result = add.delay(2,3)
    result1 = test_taskk.delay()
    return render (request, 'gestion_joueurs/test_task.html',{'result': result,'result1':result1})

""" def test_task(request):
    result = add.delay(2,3)
    result1 = test_taskk.delay()
    return render (request, 'gestion_joueurs/test_task.html',{'result': result,'result1':result1}) """
@csrf_exempt
def run_all_tasks(request):
    if request.method == 'POST':
        try:
            notify_birthday()
            notify_pending_videos()
            notify_in_progress_or_completed_collab_videos()
            notify_past_deadline_status_videos()
            check_video_count()
            notify_salary_due_for_delivered_videos()
            generate_first_day_of_current_month_report()

            return JsonResponse({'status': 'success', 'message': 'All tasks executed successfully!'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Invalid method'})





