release: python manage.py migrate --noinput
web: gunicorn ms_football_gest.wsgi
worker: python gestion_joueurs/telegram_bot.py
