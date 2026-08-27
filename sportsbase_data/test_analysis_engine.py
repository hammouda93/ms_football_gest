import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from .analysis_engine import analyse_match_dataset
from .report_pdf import render_performance_pdf
from .xlsx_statistics import read_players_statistics_xlsx


def _row(player, team, position, minutes=90, **metrics):
    row = {
        "Player": player,
        "Team": team,
        "Position": position,
        "Minutes played": minutes,
        "Passes": 10,
        "Passes accurate, %": 0.8,
        "Actions": 12,
        "Actions successful, %": 0.75,
        "Lost balls": 2,
        "Lost balls in own half": 0,
    }
    row.update(metrics)
    return row


class PlayersWorkbookReaderTests(unittest.TestCase):
    def test_reads_inline_strings_and_numeric_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "players.xlsx"
            with ZipFile(path, "w") as workbook:
                workbook.writestr(
                    "xl/workbook.xml",
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="Main statistics" sheetId="1" r:id="rId1"/></sheets></workbook>',
                )
                workbook.writestr(
                    "xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
                )
                workbook.writestr(
                    "xl/worksheets/sheet1.xml",
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                    '<row r="1"><c r="A1" t="inlineStr"><is><t>Player</t></is></c>'
                    '<c r="B1" t="inlineStr"><is><t>Minutes played</t></is></c></row>'
                    '<row r="2"><c r="A2" t="inlineStr"><is><t>Test Player</t></is></c>'
                    '<c r="B2"><v>29</v></c></row>'
                    '</sheetData></worksheet>',
                )
            result = read_players_statistics_xlsx(path)
        self.assertEqual(result["headers"], ["Player", "Minutes played"])
        self.assertEqual(result["rows"][0]["Player"], "Test Player")
        self.assertEqual(result["rows"][0]["Minutes played"], 29)


class PositionAnalysisTests(unittest.TestCase):
    def test_all_role_families_have_a_position_specific_profile(self):
        positions = ("GK", "LCB", "RWB", "CDM", "RCM", "RW", "RCF")
        for position in positions:
            rows = [
                _row(f"Target {position}", "Team A", position, 90),
                _row(f"Peer {position}", "Team A", position, 80),
                _row(f"Opponent {position}", "Team B", position, 90),
            ]
            analysis = analyse_match_dataset(rows, f"Target {position}", "en")
            self.assertTrue(analysis["available"], position)
            self.assertGreaterEqual(len(analysis["dimensions"]), 4, position)
            self.assertIsNotNone(analysis["player"]["profile_score"], position)

    def test_short_substitute_is_explicitly_low_confidence(self):
        rows = [
            _row(
                "Wing Back",
                "Team A",
                "RWB",
                13,
                **{
                    "Passes into the penalty box": 1,
                    "Passes into the penalty box accurate, %": 1,
                    "Defensive challenges": 1,
                    "Defensive challenges won, %": 1,
                    "Interceptions": 1,
                },
            ),
            _row("Team Peer", "Team A", "RWB", 77),
            _row("Opponent Right", "Team B", "RB", 60),
            _row("Opponent Left", "Team B", "LB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Wing Back", "en")
        self.assertEqual(analysis["confidence"]["code"], "very_low")
        self.assertIn("Very short appearance", analysis["confidence"]["explanation"])
        self.assertGreaterEqual(len(analysis["matchups"]), 2)
        self.assertIn("forecast", analysis["narrative"]["sample_caution"])

    def test_rate_aggregation_uses_attempts_not_simple_average(self):
        rows = [
            _row("Target", "Team A", "RWB", 90),
            _row("A1", "Team A", "LCB", 90, **{"Passes": 100, "Passes accurate, %": 0.9}),
            _row("A2", "Team A", "RCB", 90, **{"Passes": 10, "Passes accurate, %": 0.5}),
            _row("B1", "Team B", "LCB", 90, **{"Passes": 50, "Passes accurate, %": 0.7}),
            _row("B2", "Team B", "RCB", 90, **{"Passes": 50, "Passes accurate, %": 0.7}),
        ]
        analysis = analyse_match_dataset(rows, "Target", "en")
        defence = next(item for item in analysis["unit_comparisons"] if item["key"] == "defence")
        passing = next(item for item in defence["metrics"] if item["metric"] == "Passes accurate, %")
        self.assertEqual(passing["display"]["Team A"], "86%")
        self.assertEqual(passing["display"]["Team B"], "70%")


class PerformancePdfTests(unittest.TestCase):
    def test_professional_report_is_a_multipage_pdf(self):
        rows = [
            _row("Target", "Team A", "RCF", 29, **{"Actions in opponent's box": 4}),
            _row("Peer", "Team A", "LCF", 80),
            _row("Opponent", "Team B", "CF", 90),
            _row("Opponent Left", "Team B", "LCB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Target", "fr")
        report = SimpleNamespace(
            language="fr",
            report_type="match",
            subscription=SimpleNamespace(player=SimpleNamespace(name="Target")),
            match=SimpleNamespace(
                home_team="Team A",
                away_team="Team B",
                score="1–1",
                match_date=date(2026, 8, 22),
                player_stats=SimpleNamespace(
                    heatmap_png=None,
                    ball_touches_png=None,
                ),
            ),
            title="Rapport de performance — Team A 1–1 Team B",
            executive_summary=analysis["narrative"]["executive_summary"],
            strengths="",
            improvement_areas="",
            analyst_notes="",
            metrics={},
            analysis_payload=analysis,
            updated_at=datetime(2026, 8, 27, 1, 30),
        )
        pdf = render_performance_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 15_000)


if __name__ == "__main__":
    unittest.main()
