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
        positions = ("GK", "LCB", "RB", "RWB", "CDM", "RCM", "CAM", "RW", "RCF")
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

        expected_groups = {
            "RB": "full_back",
            "RWB": "wing_back",
            "RCM": "box_to_box_midfielder",
            "CAM": "attacking_midfielder",
            "RW": "winger",
            "RCF": "forward",
        }
        for position, group in expected_groups.items():
            rows = [
                _row(f"Target {position}", "Team A", position, 90),
                _row(f"Opponent {position}", "Team B", position, 90),
            ]
            analysis = analyse_match_dataset(rows, f"Target {position}", "en")
            self.assertEqual(analysis["player"]["role_group"], group)

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
            _row("Opponent Left", "Team B", "LW", 90),
        ]
        analysis = analyse_match_dataset(rows, "Wing Back", "en")
        self.assertEqual(analysis["confidence"]["code"], "very_low")
        self.assertIn("immediate-impact", analysis["confidence"]["explanation"])
        self.assertGreaterEqual(len(analysis["matchups"]), 2)
        self.assertIn("No event is projected", analysis["narrative"]["sample_caution"])

    def test_playing_time_reliability_uses_six_agreed_bands(self):
        expected = {
            13: "very_low",
            30: "low",
            50: "medium",
            65: "good",
            80: "very_good",
            90: "very_high",
        }
        for minutes, code in expected.items():
            rows = [_row("Target", "A", "CM", minutes), _row("Opponent", "B", "CM", 90)]
            self.assertEqual(analyse_match_dataset(rows, "Target", "en")["confidence"]["code"], code)

    def test_real_totals_are_never_projected_to_per_90(self):
        rows = [
            _row("Short Forward", "A", "ST", 13, **{"Lost balls": 0, "Passes": 4}),
            _row("Opponent", "B", "ST", 90),
        ]
        analysis = analyse_match_dataset(rows, "Short Forward", "en")
        passes = next(item for item in analysis["appendix_metrics"] if item["metric"] == "Passes")
        losses = next(item for item in analysis["appendix_metrics"] if item["metric"] == "Lost balls")
        self.assertEqual(passes["display"], "4")
        self.assertEqual(losses["display"], "0")
        self.assertNotIn("/90", str(analysis))

    def test_rate_evidence_always_exposes_denominator_and_sample(self):
        rows = [
            _row("Wing Back", "A", "RWB", 13, **{"Defensive challenges": 1, "Defensive challenges won, %": 1}),
            _row("Opponent", "B", "RWB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Wing Back", "en")
        metric = next(item for item in analysis["key_metrics"] if item["metric"] == "Defensive challenges won, %")
        self.assertEqual(metric["display"], "1/1 · 100%")
        self.assertEqual(metric["sample"]["code"], "very_low")

    def test_six_box_shots_without_goal_preserve_presence_but_flag_finishing(self):
        striker = _row(
            "Striker",
            "Team A",
            "ST",
            90,
            **{
                "Goals": 0,
                "Shots": 6,
                "Shots on target": 2,
                "Shots on target, %": 2 / 6,
                "Shots from the penalty area": 6,
                "xG (expected goals)": 0.9,
                "Actions in opponent's box": 10,
                "Attacking challenges": 5,
                "Attacking challenges won, %": 0.4,
            },
        )
        rows = [striker, _row("Peer", "Team A", "ST", 90), _row("Opponent", "Team B", "ST", 90)]
        analysis = analyse_match_dataset(rows, "Striker", "en")
        dimensions = {item["key"]: item for item in analysis["dimensions"]}
        self.assertGreaterEqual(dimensions["box_presence"]["score"], 80)
        self.assertNotEqual(analysis["verdict"]["code"], "difficult")
        self.assertTrue(any("6" in line for line in analysis["narrative"]["strengths"]))
        self.assertTrue(any("6" in line for line in analysis["narrative"]["risks"]))

    def test_number_eight_is_rewarded_for_final_third_presence(self):
        rows = [
            _row(
                "Relayeur",
                "A",
                "RCM",
                70,
                **{
                    "Final third entries": 5,
                    "Actions in opponent's box": 3,
                    "Passes into the penalty box": 2,
                    "Shots": 2,
                    "Progressive passes": 7,
                    "Passes for a shot": 2,
                },
            ),
            _row("Opponent", "B", "RCM", 70),
        ]
        analysis = analyse_match_dataset(rows, "Relayeur", "fr")
        final_third = next(item for item in analysis["dimensions"] if item["key"] == "final_third_presence")
        self.assertGreaterEqual(final_third["score"], 65)
        self.assertTrue(any("Projection offensive" in line for line in analysis["narrative"]["strengths"]))

    def test_sportsbase_index_validates_but_does_not_change_mission_score(self):
        base = _row("Player", "A", "RB", 90, **{"Index": 100, "Defensive challenges": 6, "Defensive challenges won, %": 0.7})
        rows = [base, _row("Opponent", "B", "RB", 90)]
        first = analyse_match_dataset(rows, "Player", "en")
        rows[0]["Index"] = 250
        second = analyse_match_dataset(rows, "Player", "en")
        self.assertEqual(first["player"]["profile_score"], second["player"]["profile_score"])
        self.assertTrue(second["rankings"]["index_not_in_score"])

    def test_no_aerial_opportunity_is_not_scored_as_a_weakness(self):
        rows = [
            _row("Centre Back", "A", "CB", 90, **{"Aerial challenges": 0, "Aerial challenges won, %": "-"}),
            _row("Opponent", "B", "CB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Centre Back", "en")
        aerial = next(item for item in analysis["dimensions"] if item["key"] == "aerial_control")
        self.assertEqual(aerial["coverage"], 0)
        self.assertEqual(aerial["grade_code"], "unseen")

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
        self.assertEqual(passing["display"]["Team A"], "95/110 · 86.36%")
        self.assertEqual(passing["display"]["Team B"], "70/100 · 70%")


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

    def test_report_renderer_supports_subscription_languages(self):
        rows = [
            _row("Target", "Team A", "RWB", 65, **{"Defensive challenges": 5, "Defensive challenges won, %": 0.8}),
            _row("Opponent", "Team B", "RWB", 65),
            _row("Direct", "Team B", "LW", 65),
        ]
        for language in ("fr", "en", "ar"):
            analysis = analyse_match_dataset(rows, "Target", language)
            report = SimpleNamespace(
                language=language,
                report_type="match",
                subscription=SimpleNamespace(player=SimpleNamespace(name="Target")),
                match=SimpleNamespace(
                    home_team="Team A",
                    away_team="Team B",
                    score="1–0",
                    match_date=date(2026, 8, 22),
                    player_stats=SimpleNamespace(heatmap_png=None, ball_touches_png=None),
                ),
                title="Match report",
                executive_summary=analysis["narrative"]["executive_summary"],
                analysis_payload=analysis,
            )
            pdf = render_performance_pdf(report)
            self.assertTrue(pdf.startswith(b"%PDF"), language)
            self.assertGreater(len(pdf), 12_000, language)


if __name__ == "__main__":
    unittest.main()
