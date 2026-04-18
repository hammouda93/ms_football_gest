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

        written = self._write_job_file(
            player_name=player_name,
            target_dir=target_path,
            downloaded_files=downloaded_files,
        )

        premiere_dir = Path(written["premiere_dir"])
        command_file = self._write_command_file(
            premiere_dir=premiere_dir,
            job_file=written["job_file"],
        )
        current_command_file = self._write_current_command_file(command_file)

        self._launch_premiere()

        print(f"[INFO] Job Premiere préparé: {written['job_file']}")
        print(f"[INFO] Commande Premiere préparée: {command_file}")
        print(f"[INFO] Current command file: {current_command_file}")

        return {
            "success": True,
            "project_path": written["project_path"],
            "job_file": written["job_file"],
            "command_file": command_file,
            "current_command_file": current_command_file,
            "clips_count": len(downloaded_files),
        }