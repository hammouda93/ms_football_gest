from django.shortcuts import render, redirect, get_object_or_404
from .models import Video, VideoEditor, VideoStatusHistory, Player,Payment
from .forms import VideoForm, VideoEditorRegistrationForm, PlayerForm, User, PaymentForm
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
    player = None  # Initialize player to None
    selected_player_id = request.POST.get('selected_player_id')

    if request.method == 'POST':
        if 'add_player' in request.POST:
            # Get player ID from the hidden input
            
            if selected_player_id:  # Si un joueur a été sélectionné
                try:
                    # Récupérer le joueur existant et mettre à jour ses infos
                    player = Player.objects.get(id=selected_player_id)
                    player_form = PlayerForm(request.POST, instance=player)  # Lier le formulaire au joueur existant
                    if player_form.is_valid():
                        player_form.save()  # Mettre à jour les infos du joueur
                        messages.success(request, "Les informations du joueur ont été mises à jour avec succès !")
                except Player.DoesNotExist:
                    messages.error(request, "Le joueur sélectionné n'existe pas.")
            else:  # Si aucun joueur n'a été sélectionné, créer un nouveau joueur
                player_form = PlayerForm(request.POST)
                if player_form.is_valid():
                    player = player_form.save()  # Enregistrer le nouveau joueur
                    messages.success(request, "Le nouveau joueur a été ajouté avec succès !")

            # Prepare the video form and render the page again
            video_form = VideoForm(user=request.user)  # Reset the video form
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
                    
                    # Obtenir ou créer l'éditeur
                    editor, created = VideoEditor.objects.get_or_create(user=request.user)
                    video.editor = editor  # Assurez-vous que l'éditeur est une instance de VideoEditor
                    
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
    if request.method == 'POST':
        form = PlayerForm(request.POST, instance=player)
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations du joueur ont été mises à jour avec succès.")
            return redirect('dashboard')  # Rediriger vers le tableau de bord ou une autre page
    else:
        form = PlayerForm(instance=player)
    return render(request, 'gestion_joueurs/edit_player.html', {'form': form, 'player': player})

@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if request.method == 'POST':
        form = VideoForm(request.POST, instance=video, user=request.user)  # Passer l'utilisateur ici
        if form.is_valid():
            form.save()
            messages.success(request, "Les informations de la vidéo ont été mises à jour avec succès.")
            return redirect('dashboard')
    else:
        form = VideoForm(instance=video, user=request.user)  # Passer l'utilisateur ici
    return render(request, 'gestion_joueurs/edit_video.html', {'form': form, 'video': video})  # Assurez-vous que "form" est bien passé

@login_required
def record_payment(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.created_by = request.user
            payment.save()
            messages.success(request, "Paiement enregistré avec succès.")
            return redirect('dashboard')
    else:
        form = PaymentForm()

    players = Player.objects.all()
    player_id = request.GET.get('player_id')  # Récupérer le player_id à partir des paramètres GET

    # Si un joueur est sélectionné, filtrer les vidéos correspondantes
    if player_id:
        videos = Video.objects.filter(player_id=player_id)
    else:
        videos = Video.objects.none()  # Aucun vidéo par défaut

    # Mettre à jour le queryset du champ vidéo
    form.fields['video'].queryset = videos

    return render(request, 'gestion_joueurs/record_payment.html', {
        'form': form,
        'players': players,
        'selected_player_id': player_id,
    })

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

def search_players(request):
    query = request.GET.get('q', '')
    players = Player.objects.filter(name__icontains=query).values('id', 'name', 'date_of_birth', 'league', 'club', 'whatsapp_number')[:10]
    return JsonResponse({'players': list(players)})



