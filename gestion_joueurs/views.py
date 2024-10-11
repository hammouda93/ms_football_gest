from django.shortcuts import render, redirect, get_object_or_404
from .models import Video, VideoEditor, VideoStatusHistory, Player
from .forms import VideoForm, VideoEditorRegistrationForm, PlayerForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm

from django.shortcuts import render, redirect
from .forms import VideoForm, PlayerForm
from .models import Video, Player
from django.contrib import messages


from django.contrib import messages
from django.shortcuts import render, redirect
from .forms import VideoForm, PlayerForm
from .models import Video, Player


















def create_video_highlight(request):
    player_form = PlayerForm()  # Initialiser ici pour éviter l'erreur
    video_form = VideoForm()  # Initialiser ici pour éviter l'erreur

    if request.method == 'POST':
        if 'add_player' in request.POST:  # Ajouter un nouveau joueur
            player_form = PlayerForm(request.POST)
            if player_form.is_valid():
                player = player_form.save()  # Enregistrer le nouveau joueur
                video_form = VideoForm()  # Préparer un formulaire de vidéo vide pour affichage
                return render(request, 'gestion_joueurs/create_video.html', {
                    'video_form': video_form,
                    'player_form': player_form,
                    'players': Player.objects.all(),
                    'new_player_added': True,
                    'added_player': player,  # Passer le joueur ajouté pour remplir les données
                })
        elif 'create_video' in request.POST:  # Créer la vidéo pour un joueur
            messages.success(request, "entréé au boucle avec succée videoforme fonctionne correctement !")
            player_id = request.POST['player']  # Récupérer l'ID du joueur
            video_form = VideoForm(request.POST)
            if video_form.is_valid(): 
                messages.success(request, "La videoforme fonctionne correctement !")
                video = video_form.save(commit=False)
                video.player = Player.objects.get(id=player_id)  # Associer le joueur à la vidéo
                #video.editor = request.user.videoeditor  # Assurez-vous que l'utilisateur est un éditeur vidéo
                video.save()
                # Ajouter un message de succès
                messages.success(request, "La vidéo a été créée avec succès !")
                return redirect('dashboard')
            else:
                # Ajouter un message d'erreur si le formulaire n'est pas valide
                print(video_form.errors)
                messages.error(request, "Erreur lors de la création de la vidéo. Veuillez vérifier les informations.")

    players = Player.objects.all()  # Récupérer tous les joueurs existants
    return render(request, 'gestion_joueurs/create_video.html', {
        'video_form': video_form,
        'player_form': player_form,
        'players': players,
    })














def dashboard(request):
    videos = Video.objects.all()
    return render(request, 'gestion_joueurs/dashboard.html', {'videos': videos})

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
    return render(request, 'gestion_joueurs/login.html', {'form': form})

def user_logout(request):
    logout(request)
    return redirect('dashboard')

def video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    return render(request, 'gestion_joueurs/video_status.html', {'video': video})

def update_video_status(request, video_id):
    video = get_object_or_404(Video, id=video_id)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        comment = request.POST.get('comment')
        
        # Mettre à jour le statut de la vidéo
        video.status = new_status
        video.save()

        # Enregistrer l'historique avec l'éditeur
        editor = request.user  # Assurez-vous que l'utilisateur connecté est un VideoEditor
        VideoStatusHistory.objects.create(video=video, editor=editor, status=new_status, comment=comment)

        return redirect('video_status', video_id=video.id)

    return render(request, 'gestion_joueurs/update_video_status.html', {'video': video})

def register_video_editor(request):
    if request.method == 'POST':
        form = VideoEditorRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            editor = VideoEditor(user=user)
            editor.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = VideoEditorRegistrationForm()
    return render(request, 'gestion_joueurs/register_video_editor.html', {'form': form})