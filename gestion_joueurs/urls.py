from django.urls import path
#from .views import dashboard, create_video_request, video_status, update_video_status, register_video_editor, user_login, user_logout
from .views import dashboard, create_video_highlight, video_status, update_video_status, register_video_editor, user_login, user_logout

urlpatterns = [
    path('', dashboard, name='dashboard'),
    #path('create/', create_video_request, name='create_video_request'),
    path('create/', create_video_highlight, name='create_video_request'),
    path('status/<int:video_id>/', video_status, name='video_status'),
    path('update_status/<int:video_id>/', update_video_status, name='update_video_status'),
    path('register/editor/', register_video_editor, name='register_video_editor'),
    path('login/', user_login, name='login'),
    path('logout/', user_logout, name='logout'),
]