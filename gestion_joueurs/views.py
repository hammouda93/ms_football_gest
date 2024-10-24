from django.shortcuts import render, redirect, get_object_or_404
from .models import Video, VideoEditor, VideoStatusHistory, Player,Payment,Invoice,Expense,Salary
from .forms import VideoForm, VideoEditorRegistrationForm, PlayerForm, User, PaymentForm, InvoiceForm,ExpenseForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q,Count,F
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse


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
                    
                    editor, _ = VideoEditor.objects.get_or_create(user=request.user)
                    video.editor = editor
                    
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

""" @login_required """
def dashboard(request):
    videos = Video.objects.all()
    today = timezone.now().date()  # Récupérer la date d'aujourd'hui
    three_days_from_now = today + timedelta(days=3)  # Date dans trois jours
    deadline_filter = request.GET.get('deadline_filter', 'all')

    # Récupérer les paramètres de filtrage
    status_filter = request.GET.get('status')
    league_filter = request.GET.get('league')
    search_query = request.GET.get('search')
    
    if deadline_filter == 'today':
        videos = videos.filter(deadline=today)
    elif deadline_filter == '3_days':
        videos = videos.filter(deadline__lte=today + timedelta(days=3), deadline__gt=today)
    elif deadline_filter == '1_week':
        videos = videos.filter(deadline__lte=today + timedelta(weeks=1), deadline__gt=today)
    elif deadline_filter == '2_weeks':
        videos = videos.filter(deadline__lte=today + timedelta(weeks=2), deadline__gt=today)
    elif deadline_filter == '1_month':
        videos = videos.filter(deadline__lte=today + timedelta(days=30), deadline__gt=today)

    if status_filter:
        videos = videos.filter(status=status_filter)

    if league_filter:
        videos = videos.filter(player__league=league_filter)

    if search_query:
        videos = videos.filter(
            Q(player__name__icontains=search_query) | 
            Q(editor__user__username__icontains=search_query)
        )

    return render(request, 'gestion_joueurs/dashboard.html', {
        'videos': videos,
        'today': today,
        'three_days_from_now': three_days_from_now,
        'deadline_filter': deadline_filter,
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
    return redirect('dashboard')

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
            comment = request.POST.get('comment')
            
            # Mettre à jour le statut de la vidéo
            video.status = new_status
            video.save()

            # Enregistrer l'historique avec l'éditeur
            """ editor = request.user.videoeditor  # Assurez-vous que l'utilisateur est un VideoEditor
            VideoStatusHistory.objects.create(video=video, editor=editor, status=new_status, comment=comment) """

            messages.success(request, "Le statut de la vidéo a été mis à jour avec succès.")
            return redirect('video_status', video_id=video.id)
        else:
            messages.error(request, "Vous devez être connecté pour mettre à jour le statut de la vidéo.")

    return render(request, 'gestion_joueurs/update_video_status.html', {'video': video})

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

# ... (les autres fonctions existantes) ...
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

@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    video_status_history = video.status_history.all()  # Utiliser le related_name
    payments = video.payments.all()  # Assure-toi que le modèle Payment a la relation correcte

    if request.method == 'POST':
        form = VideoForm(request.POST, instance=video, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations de la vidéo ont été mises à jour avec succès.")
            return redirect('dashboard')
    else:
        form = VideoForm(instance=video, user=request.user)

    return render(request, 'gestion_joueurs/edit_video.html', {
        'form': form,
        'video': video,
        'video_status_history': video_status_history,
        'payments': payments,
    })

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

@login_required
def get_videos_by_player(request, player_id):
    videos = Video.objects.filter(player_id=player_id)
    video_data = [{'id': video.id, 'info': video.info} for video in videos]
    return JsonResponse({'videos': video_data})

@login_required
def get_remaining_balance(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    remaining_balance = video.total_payment - video.advance_payment
    return JsonResponse({'remaining_balance': remaining_balance})

@login_required
def search_players(request):
    query = request.GET.get('q', '')
    players = Player.objects.filter(name__icontains=query).values('id', 'name', 'date_of_birth', 'league', 'club', 'whatsapp_number')[:10]
    return JsonResponse({'players': list(players)})

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

@login_required
def view_payments(request):
    payments = Payment.objects.all()
    return render(request, 'gestion_joueurs/view_payments.html', {'payments': payments})

@login_required
def view_invoices(request):
    invoices = Invoice.objects.all()
    return render(request, 'gestion_joueurs/view_invoices.html', {'invoices': invoices})

@login_required
def add_expense(request):
    editors = VideoEditor.objects.all()
    videos = Video.objects.all()

    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user)

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
                if salary_amount is not None and video_id is not None:
                    # Create Salary record
                    salary = Salary.objects.create(
                        user_id=request.user.id,  # Assuming the salary is linked to the user creating the expense
                        amount=salary_amount,
                        video_id =video_id,
                        created_by=request.user
                    )
                    expense.salary = salary  # Link the salary to the expense
                    expense.save()  # Save the expense with the linked salary

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



@login_required
def edit_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    form = ExpenseForm(instance=expense, user=request.user)

    salary = None
    video = None
    video_editor = None

    if expense.salary:
        salary = expense.salary
        video = salary.video
        if video:
            video_editor = video.editor

        form.fields['salary_amount'].initial = salary.amount if expense.category == 'salary' else None
        form.fields['video'].initial = video.id if video else None
        form.fields['video_editor'].initial = video_editor.id if video_editor else None
        form.fields['salary_paid_status'].initial = video.salary_paid_status if video else None

    form.fields['date'].initial = expense.date.strftime('%Y-%m-%d')

    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            expense.amount = form.cleaned_data['amount']
            expense.date = form.cleaned_data['date']
            expense.category = form.cleaned_data['category']
            expense.description = form.cleaned_data['description']

            # Check if category is salary before updating salary details
            if expense.category == 'salary' and salary:
                salary.amount = form.cleaned_data['salary_amount']
                salary.video = form.cleaned_data['video']
                salary.date = form.cleaned_data['date']
                salary.save()

            expense.save()
            if video:
                    Video.objects.filter(id=video.id).update(salary_paid_status=form.cleaned_data.get('salary_paid_status'))
                    print(f"Salary created with ID: {salary.id}")  
            return redirect('view_expenses')

    videos = Video.objects.all()
    return render(request, 'gestion_joueurs/edit_expense.html', {
        'form': form,
        'expense': expense,
        'videos': videos,
        'salary': salary,
        'video': video,
        'video_editor': video_editor,
    })




@login_required
def view_expenses(request):
    expenses = Expense.objects.filter(created_by=request.user).order_by('-date')
    return render(request, 'gestion_joueurs/view_expenses.html', {'expenses': expenses})

@login_required
def manage_salaries(request):
    salaries = Salary.objects.all().order_by('-date')

    # Fetch the related expense for each salary
    for salary in salaries:
        salary.expense = Expense.objects.filter(salary=salary).first()  # Get the first related expense

    return render(request, 'gestion_joueurs/manage_salaries.html', {
        'salaries': salaries,
    })