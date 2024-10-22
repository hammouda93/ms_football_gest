from django.urls import path
#from .views import dashboard, create_video_request, video_status, update_video_status, register_video_editor, user_login, user_logout
from .views import dashboard, create_video_highlight, video_status, update_video_status,add_expense,edit_expense,view_expenses
from. views import register_video_editor,search_players,view_invoices,view_payments,manage_salaries,get_videos_by_editor
from .views import user_login, user_logout,edit_player,edit_video,record_payment,get_videos_by_player,get_remaining_balance,create_invoice

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
    path('payment/record/', record_payment, name='record_payment'),
    path('record_payment/<int:video_id>/', record_payment, name='record_payment'),
    path('invoice/create/', create_invoice, name='create_invoice'),  # Nouvelle URL pour créer une facture
    path('payments/', view_payments, name='view_payments'),  # Nouvelle URL pour voir les paiements
    path('invoices/', view_invoices, name='view_invoices'),  # Nouvelle URL pour voir les factures
    path('get_videos/<int:player_id>/', get_videos_by_player, name='get_videos'),
    path('get_balance/<int:video_id>/', get_remaining_balance, name='get_balance'),
    path('search_players/', search_players, name='search_players'),
    path('expenses/add/', add_expense, name='add_expense'),
    path('expenses/edit/<int:expense_id>/', edit_expense, name='edit_expense'),
    path('expenses/', view_expenses, name='view_expenses'),
    path('salaries/', manage_salaries, name='manage_salaries'),
    path('expenses/get_videos/', get_videos_by_editor, name='get_videos_by_editor'),
]