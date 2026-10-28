from __future__ import annotations

import os
import re

import requests


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {'1', 'true', 'yes', 'on', 'oui'}


def normalized_recipient(value):
    return re.sub(r'\D', '', str(value or ''))


def whatsapp_cloud_configuration():
    token = os.getenv('WHATSAPP_CLOUD_API_TOKEN', '').strip()
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '').strip()
    graph_version = os.getenv('WHATSAPP_GRAPH_API_VERSION', '').strip()
    explicit_url = os.getenv('WHATSAPP_SEND_API_URL', '').strip()
    if explicit_url:
        api_url = explicit_url
    elif phone_number_id and graph_version:
        api_url = (
            f'https://graph.facebook.com/{graph_version}/'
            f'{phone_number_id}/messages'
        )
    else:
        api_url = ''
    return {
        'enabled': _env_bool('WHATSAPP_AUTO_SEND_ENABLED', False),
        'configured': bool(token and api_url),
        'token': token,
        'api_url': api_url,
    }


def send_whatsapp_text(recipient, message, *, timeout=30):
    configuration = whatsapp_cloud_configuration()
    if not configuration['enabled']:
        return {
            'sent': False,
            'configured': configuration['configured'],
            'reason': 'Envoi WhatsApp automatique désactivé.',
        }
    if not configuration['configured']:
        return {
            'sent': False,
            'configured': False,
            'reason': 'Identifiants WhatsApp Business incomplets.',
        }
    target = normalized_recipient(recipient)
    if not target:
        return {
            'sent': False,
            'configured': True,
            'reason': 'Numéro WhatsApp du joueur manquant.',
        }

    response = requests.post(
        configuration['api_url'],
        headers={
            'Authorization': f"Bearer {configuration['token']}",
            'Content-Type': 'application/json',
        },
        json={
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': target,
            'type': 'text',
            'text': {
                'preview_url': True,
                'body': str(message)[:4000],
            },
        },
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        error = payload.get('error') or {}
        return {
            'sent': False,
            'configured': True,
            'reason': error.get('message') or f'Erreur WhatsApp HTTP {response.status_code}.',
        }
    messages = payload.get('messages') or []
    message_id = messages[0].get('id', '') if messages else ''
    return {
        'sent': True,
        'configured': True,
        'message_id': message_id,
    }
