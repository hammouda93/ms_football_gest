from django.urls import path
#from .views import dashboard, create_video_request, video_status, update_video_status, register_video_editor, user_login, user_logout
from .views import dashboard, create_video_highlight, video_status, update_video_status, register_video_editor,search_players 
from .views import user_login, user_logout,edit_player,edit_video,record_payment,get_videos_by_player,get_remaining_balance

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('create/', create_video_highlight, name='create_video_request'),
    path('status/<int:video_id>/', video_status, name='video_status'),
    path('update_status/<int:video_id>/', update_video_status, name='update_video_status'),
    path('register/editor/', register_video_editor, name='register_video_editor'),
    path('player/edit/<int:player_id>/', edit_player, name='edit_player'),
    path('video/edit/<int:video_id>/', edit_video, name='edit_video'),
    path('login/', user_login, name='user_login'),
    path('logout/', user_logout, name='user_logout'),
    path('dashboard/', dashboard, name='dashboard'),
    path('payment/record/', record_payment, name='record_payment'),
    path('get_videos/<int:player_id>/', get_videos_by_player, name='get_videos'),
    path('get_balance/<int:video_id>/', get_remaining_balance, name='get_balance'),
    path('search_players/', search_players, name='search_players'),
    
]