import json
from pathlib import Path

from premiere_automation import PremiereAutomation

PLAYER_FOLDER = Path(
    r"D:\Django_Projects\ms_football_gest\gestion_joueurs\automated_players\1745_Islem_Chelghoumi"
)

def main():
    premiere_dir = PLAYER_FOLDER / "premiere"
    job_file = premiere_dir / "premiere_job.json"

    if not job_file.exists():
        print(f"[ERROR] Job introuvable: {job_file}")
        return

    job = json.loads(job_file.read_text(encoding="utf-8"))

    premiere = PremiereAutomation()
    result = premiere.run_for_player(
        player_name=job["player_name"],
        target_dir=str(PLAYER_FOLDER),
        downloaded_files=job["clips"],
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()