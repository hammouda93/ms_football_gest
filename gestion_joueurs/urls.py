from django.urls import path
#from .views import dashboard, create_video_request, video_status, update_video_status, register_video_editor, user_login, user_logout
from .views import dashboard, create_video_highlight, video_status, update_video_status,add_expense,edit_expense,view_expenses,player_dashboard,notification_center
from. views import register_video_editor,search_players,view_invoices,view_payments,manage_salaries,get_videos_by_editor,view_profile,generate_financial_report,view_video
from .views import user_login, user_logout,edit_player,edit_video,record_payment,get_videos_by_player,get_remaining_balance,create_invoice,StatisticalDashboardView,get_months
from .views import mark_notification_as_read,test_task, non_video_income_list,add_non_video_income,edit_non_video_income,financial_report_list,view_financial_report,get_days
from .views import add_notification, notification_list, view_notification,run_all_tasks

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('players/', player_dashboard, name='player_dashboard'),
    path('create/', create_video_highlight, name='create_video_request'),
    path('status/<int:video_id>/', video_status, name='video_status'),
    path('update_status/<int:video_id>/', update_video_status, name='update_video_status'),
    path('register/editor/', register_video_editor, name='register_video_editor'),
    path('player/edit/<int:player_id>/', edit_player, name='edit_player'),
    path('video/edit/<int:video_id>/', edit_video, name='edit_video'),
    path('login/', user_login, name='user_login'),
    path('logout/', user_logout, name='user_logout'),
    path('profile/', view_profile, name='view_profile'),
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
    path('financial-report/', generate_financial_report, name='financial_report'),
    path('financial_reports/', financial_report_list, name='financial_report_list'),
    path('financial_report/<int:pk>/', view_financial_report, name='view_financial_report'),
    path('get_months/', get_months, name='get_months'),
    path('get_days/', get_days, name='get_days'),
    path('statistical_dashboard/', StatisticalDashboardView, name='statistical_dashboard'),
    path('notification/read/<int:notification_id>/', mark_notification_as_read, name='mark_notification_as_read'),
    path('notifications/', notification_list, name='notification_list'),
    path('notifications/add/', add_notification, name='add_notification'),
    path('notification/<int:notification_id>/', view_notification, name='view_notification'),
    path('video/<int:video_id>/', view_video, name='view_video'),
    path('test/', test_task, name='test_task'),
    path('non_video_income/', non_video_income_list, name='non_video_income_list'),
    path('non_video_income/add/', add_non_video_income, name='add_non_video_income'),
    path('non_video_income/edit/<int:pk>/', edit_non_video_income, name='edit_non_video_income'),
    path('run-tasks/', run_all_tasks, name='run_all_tasks'),
]