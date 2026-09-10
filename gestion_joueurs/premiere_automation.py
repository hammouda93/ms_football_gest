from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


class PremiereAutomation:
    def __init__(
        self,
        premiere_exe: str | None = None,
        jsx_script_path: str | None = None,
        launch_wait_seconds: int = 8,
        current_command_file: str | None = None,
    ):
        self.premiere_exe = premiere_exe or os.getenv(
            "PREMIERE_PRO_EXE",
            r"C:\Program Files\Adobe\Adobe Premiere Pro 2022\Adobe Premiere Pro.exe",
        )
        self.jsx_script_path = jsx_script_path or os.getenv(
            "PREMIERE_JSX_SCRIPT",
            r"D:\Django_Projects\ms_football_gest\gestion_joueurs\premiere_bridge\create_project.jsx",
        )
        self.current_command_file = current_command_file or os.getenv(
            "PREMIERE_CURRENT_COMMAND_FILE",
            r"D:\Django_Projects\ms_football_gest\gestion_joueurs\premiere_bridge\current_command.txt",
        )
        self.launch_wait_seconds = int(os.getenv("PREMIERE_LAUNCH_WAIT_SECONDS", launch_wait_seconds))

    @staticmethod
    def _safe_name(value: str) -> str:
        invalid = '<>:"/\\|?*'
        cleaned = "".join("_" if ch in invalid else ch for ch in value)
        return "_".join(cleaned.split())

    def _ensure_dirs(self, target_dir: Path) -> Path:
        premiere_dir = target_dir / "premiere"
        premiere_dir.mkdir(parents=True, exist_ok=True)
        return premiere_dir

    def _build_project_path(self, premiere_dir: Path, player_name: str) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_player_name = self._safe_name(player_name)
        return premiere_dir / f"{safe_player_name}_{date_str}.prproj"

    def _find_and_prepare_kling_intro_mp4(self, target_dir: Path, player_name: str) -> str | None:
        intro_dir = target_dir / "intro"
        upload_dirs = [
            intro_dir / "Uploads_ChatGPT_Kling",
            intro_dir / "Uploads_Gemini",
        ]
        kling_candidates = sorted(
            [
                path
                for upload_dir in upload_dirs
                if upload_dir.exists()
                for path in upload_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() == ".mp4"
                and path.name.lower().startswith(("kling", "intro"))
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not kling_candidates:
            return None

        source_file = kling_candidates[0]
        safe_player_name = self._safe_name(player_name)
        target_file = intro_dir / f"{safe_player_name}Intro.mp4"

        try:
            target_file.write_bytes(source_file.read_bytes())
            return str(target_file)
        except Exception:
            return str(source_file)
    
    def _write_project_context_file(self, premiere_dir: Path, job_data: dict[str, Any]) -> str:
        project_context_file = premiere_dir / "project_context.json"

        project_context = {
            "player_name": job_data.get("player_name", ""),
            "target_dir": job_data.get("target_dir", ""),
            "premiere_dir": job_data.get("premiere_dir", ""),
            "project_path": job_data.get("project_path", ""),
            "graphics_bin_name": job_data.get("graphics_bin_name", "04_GRAPHICS"),
            "audio_bin_name": job_data.get("audio_bin_name", "05_AUDIO"),
            "player_intro_path": job_data.get("player_intro_path", ""),
            "music_dir": job_data.get("music_dir", ""),
            "logo_path": job_data.get("logo_path", ""),
            "created_at": job_data.get("created_at", ""),
        }

        project_context_file.write_text(
            json.dumps(project_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(project_context_file)

    def _write_job_file(
        self,
        player_name: str,
        target_dir: Path,
        downloaded_files: list[str],
    ) -> dict[str, Any]:
        premiere_dir = self._ensure_dirs(target_dir)
        project_path = self._build_project_path(premiere_dir, player_name)

        logo_path = os.getenv(
            "PREMIERE_LOGO_PATH",
            r"D:\Django_Projects\ms_football_gest\gestion_joueurs\premiere_bridge\assets\logo.mp4",
        )
        music_dir = os.getenv(
            "PREMIERE_MUSIC_DIR",
            r"D:\Django_Projects\ms_football_gest\gestion_joueurs\premiere_bridge\assets\music",
        )

        intro_dir = str(target_dir / "intro")

        safe_player_name = self._safe_name(player_name)
        player_intro_path = str(Path(intro_dir) / f"{safe_player_name}Intro.mp4")
        final_export_path = str(
            target_dir / "exports" / f"{safe_player_name}_Highlights_Final.mp4"
        )

        kling_intro_path = self._find_and_prepare_kling_intro_mp4(target_dir, player_name)
        if kling_intro_path:
            player_intro_path = kling_intro_path

        job_data = {
            "player_name": player_name,
            "target_dir": str(target_dir),
            "premiere_dir": str(premiere_dir),
            "project_path": str(project_path),
            "sequence_name": "REVIEW_TIMELINE",
            "raw_bin_name": "01_RAW",
            "graphics_bin_name": "04_GRAPHICS",
            "selected_bin_name": "02_SELECTED",
            "closeup_bin_name": "03_CLOSEUP",
            "audio_bin_name": "05_AUDIO",
            "export_bin_name": "06_EXPORT",
            "logo_path": logo_path,
            "clips": downloaded_files,
            "created_at": datetime.now().isoformat(),
            "music_dir": music_dir,
            "intro_dir": intro_dir,
            "player_intro_path": player_intro_path,
            "final_export_path": final_export_path,
            "export_preset_path": os.getenv("PREMIERE_EXPORT_PRESET", "").strip(),
        }

        job_file = premiere_dir / "premiere_job.json"
        job_file.write_text(
            json.dumps(job_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "job_file": str(job_file),
            "project_path": str(project_path),
            "premiere_dir": str(premiere_dir),
            "job_data": job_data,
        }

    def _launch_premiere(self) -> None:
        if not Path(self.premiere_exe).exists():
            raise FileNotFoundError(f"Premiere Pro introuvable: {self.premiere_exe}")

        bootstrap_project = Path(
            r"D:\Django_Projects\ms_football_gest\gestion_joueurs\premiere_bridge\bootstrap.prproj"
        )

        if bootstrap_project.exists():
            subprocess.Popen([self.premiere_exe, str(bootstrap_project)])
        else:
            subprocess.Popen([self.premiere_exe])

        time.sleep(self.launch_wait_seconds)

    def _write_command_file(self, premiere_dir: Path, job_file: str) -> str:
        command_file = premiere_dir / "premiere_command.json"
        command_file.write_text(
            json.dumps(
                {
                    "action": "create_project_from_job",
                    "job_file": job_file,
                    "jsx_script_path": self.jsx_script_path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(command_file)

    def _write_current_command_file(self, command_file: str) -> str:
        current_command_path = Path(self.current_command_file)
        current_command_path.parent.mkdir(parents=True, exist_ok=True)
        current_command_path.write_text(command_file, encoding="utf-8")
        return str(current_command_path)

    def run_for_player(self, player_name: str, target_dir: str, downloaded_files: list[str]) -> dict[str, Any]:
        target_path = Path(target_dir)

        if not downloaded_files:
            return {
                "success": False,
                "reason": "Aucun clip téléchargé",
            }

        missing = [clip for clip in downloaded_files if not Path(clip).exists()]
        if missing:
            return {
                "success": False,
                "reason": "Certains clips sont introuvables sur disque",
                "missing_clips": missing,
            }

        existing_result = self.read_project_result(target_path)
        if existing_result and existing_result.get("success"):
            return {
                **existing_result,
                "reused_existing_result": True,
            }

        written = self._write_job_file(
            player_name=player_name,
            target_dir=target_path,
            downloaded_files=downloaded_files,
        )
        project_context_file = self._write_project_context_file(
            premiere_dir=Path(written["premiere_dir"]),
            job_data=written["job_data"],
        )

        premiere_dir = Path(written["premiere_dir"])
        command_file = self._write_command_file(
            premiere_dir=premiere_dir,
            job_file=written["job_file"],
        )
        current_command_file = self._write_current_command_file(command_file)

        result_file = premiere_dir / "premiere_result.txt"
        lock_file = premiere_dir / "premiere_lock.txt"
        if result_file.exists():
            result_file.unlink()
        if existing_result and lock_file.exists():
            lock_file.unlink()
        if lock_file.exists():
            return {
                "success": False,
                "awaiting_result": True,
                "reason": "Un projet Premiere est déjà en cours de création.",
                "lock_file": str(lock_file),
                "job_file": written["job_file"],
            }

        self._launch_premiere()

        print(f"[INFO] Job Premiere préparé: {written['job_file']}")
        print(f"[INFO] Project context file: {project_context_file}")
        print(f"[INFO] Commande Premiere préparée: {command_file}")
        print(f"[INFO] Current command file: {current_command_file}")

        confirmation = self.wait_for_project_result(target_path)
        return {
            **confirmation,
            "project_path": written["project_path"],
            "job_file": written["job_file"],
            "command_file": command_file,
            "current_command_file": current_command_file,
            "clips_count": len(downloaded_files),
            "project_context_file": project_context_file,
            "final_export_path": written["job_data"]["final_export_path"],
        }

    @staticmethod
    def _parse_result_file(result_path: Path) -> dict[str, Any] | None:
        if not result_path.is_file():
            return None
        values = {}
        for line in result_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        if not values:
            return {
                "success": False,
                "reason": "Le résultat Premiere est vide ou illisible.",
                "result_file": str(result_path),
            }
        return {
            "success": values.get("success", "").casefold() == "true",
            "result_file": str(result_path),
            **values,
        }

    def read_project_result(self, target_dir: str | Path) -> dict[str, Any] | None:
        result_path = Path(target_dir) / "premiere" / "premiere_result.txt"
        return self._parse_result_file(result_path)

    def wait_for_project_result(
        self,
        target_dir: str | Path,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = int(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("PREMIERE_RESULT_TIMEOUT_SECONDS", "180")
        )
        deadline = time.monotonic() + max(1, timeout_seconds)
        while time.monotonic() < deadline:
            result = self.read_project_result(target_dir)
            if result is not None:
                return result
            time.sleep(2)
        return {
            "success": False,
            "awaiting_result": True,
            "reason": "Premiere Pro n’a pas encore confirmé la création du projet.",
            "result_file": str(Path(target_dir) / "premiere" / "premiere_result.txt"),
        }

    @staticmethod
    def find_final_export(target_dir: str | Path) -> str | None:
        exports_dir = Path(target_dir) / "exports"
        if not exports_dir.is_dir():
            return None
        candidates = sorted(
            (
                path
                for path in exports_dir.iterdir()
                if path.is_file() and path.suffix.casefold() == ".mp4"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return str(candidates[0]) if candidates else None
