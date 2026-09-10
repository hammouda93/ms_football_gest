from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {'1', 'true', 'yes', 'on', 'oui'}


def ffprobe_path():
    configured = os.getenv('FFPROBE_EXE', '').strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which('ffprobe')


def probe_media(path):
    executable = ffprobe_path()
    if not executable:
        return None
    completed = subprocess.run(
        [
            executable,
            '-v',
            'error',
            '-print_format',
            'json',
            '-show_format',
            '-show_streams',
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or 'ffprobe a refusé le fichier.')
    return json.loads(completed.stdout or '{}')


def validate_video_file(
    path,
    *,
    min_size_bytes=100_000,
    require_audio=False,
    require_full_hd=False,
    require_probe=None,
):
    candidate = Path(path) if path else None
    result = {
        'valid': False,
        'path': str(candidate) if candidate else '',
        'file_size_bytes': 0,
        'duration_seconds': None,
        'width': None,
        'height': None,
        'has_audio': False,
        'errors': [],
        'warnings': [],
    }
    if not candidate or not candidate.is_file():
        result['errors'].append('Fichier vidéo introuvable.')
        return result
    if candidate.suffix.casefold() != '.mp4':
        result['errors'].append('Le fichier final doit être au format MP4.')
    result['file_size_bytes'] = candidate.stat().st_size
    if result['file_size_bytes'] < int(min_size_bytes):
        result['errors'].append('Le fichier vidéo est vide ou anormalement petit.')

    if require_probe is None:
        require_probe = _env_bool('FINAL_EXPORT_REQUIRE_FFPROBE', True)
    try:
        probe = probe_media(candidate)
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        result['errors'].append(f'Lecture technique impossible : {exc}')
        probe = None

    if probe is None:
        message = 'ffprobe est introuvable ; durée, image et audio ne sont pas vérifiés.'
        if require_probe:
            result['errors'].append(message)
        else:
            result['warnings'].append(message)
    else:
        streams = probe.get('streams') or []
        video_stream = next(
            (stream for stream in streams if stream.get('codec_type') == 'video'),
            None,
        )
        audio_stream = next(
            (stream for stream in streams if stream.get('codec_type') == 'audio'),
            None,
        )
        if not video_stream:
            result['errors'].append('Aucune piste vidéo détectée.')
        else:
            result['width'] = int(video_stream.get('width') or 0) or None
            result['height'] = int(video_stream.get('height') or 0) or None
            if require_full_hd and (
                (result['width'] or 0) < 1920 or (result['height'] or 0) < 1080
            ):
                result['errors'].append('La résolution finale est inférieure à 1920×1080.')
        result['has_audio'] = bool(audio_stream)
        if require_audio and not result['has_audio']:
            result['errors'].append('Aucune piste audio détectée.')
        duration = (probe.get('format') or {}).get('duration')
        try:
            result['duration_seconds'] = round(float(duration), 3)
        except (TypeError, ValueError):
            result['duration_seconds'] = None
        if not result['duration_seconds'] or result['duration_seconds'] <= 0:
            result['errors'].append('La durée vidéo est invalide.')

    result['valid'] = not result['errors']
    return result
