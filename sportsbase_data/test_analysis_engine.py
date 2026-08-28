import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from .analysis_engine import (
    SPORTSBASE_PLAYER_COLUMNS,
    analyse_match_dataset,
    platform_index,
)
from .report_pdf import PDF_COPY, render_performance_pdf
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
    def test_ms_index_uses_fixed_display_offset_without_changing_missing_values(self):
        self.assertEqual(platform_index(180), 200)
        self.assertEqual(platform_index("201"), 221)
        self.assertIsNone(platform_index("—"))

    def test_extended_central_position_codes_use_the_correct_role_family(self):
        expected = {
            "LCDM": "holding_midfielder",
            "RCDM": "holding_midfielder",
            "LCAM": "attacking_midfielder",
            "RCAM": "attacking_midfielder",
        }
        for position, role in expected.items():
            rows = [
                _row("Target", "Team A", position, 90, **{"Index": 180}),
                _row("Opponent", "Team B", position, 90, **{"Index": 170}),
            ]
            analysis = analyse_match_dataset(rows, "Target", "fr")
            self.assertEqual(analysis["player"]["role_group"], role)
            self.assertEqual(analysis["player"]["index"], 200)

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

    def test_multiple_match_positions_are_preserved_for_pitch_visualisation(self):
        rows = [
            _row("Versatile Full Back", "Team A", "RB / RWB", 75),
            _row("Opponent", "Team B", "RB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Versatile Full Back", "fr")
        self.assertEqual(analysis["player"]["position"], "RB")
        self.assertEqual(analysis["player"]["positions"], ["RB", "RWB"])
        self.assertEqual(analysis["player"]["role_group"], "full_back")

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
            _row("Opponent Right", "Team B", "RWB", 60),
            _row("Opponent Left", "Team B", "LW", 90),
        ]
        analysis = analyse_match_dataset(rows, "Wing Back", "en")
        self.assertEqual(analysis["confidence"]["code"], "very_low")
        self.assertIn("immediate-impact", analysis["confidence"]["explanation"])
        self.assertEqual(analysis["verdict"]["appearance_type"], "entry")
        self.assertEqual(analysis["same_position_comparison"]["player"], "Opponent Right")
        self.assertEqual(analysis["same_position_comparison"]["position"], "RWB")
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

    def test_striker_finishing_reads_box_shots_and_headers_with_denominators(self):
        striker = _row(
            "Aerial Striker",
            "Team A",
            "CF",
            90,
            **{
                "Goals": 1,
                "Goals by head": 1,
                "Shots": 5,
                "Shots on target, %": "60%",
                "Shots from the penalty area": 4,
                "Shots on target from the penalty area, %": "50%",
                "Shots from outside the penalty area": 1,
                "Shots on target from outside the penalty area, %": "100%",
                "Headers": 3,
                "Headers on target, %": "66.67%",
                "Shots on post / bar": 1,
                "Short passes": 12,
                "Short passes accurate, %": "83.33%",
            },
        )
        rows = [
            striker,
            _row("Peer", "Team A", "CF", 90),
            _row("Opponent", "Team B", "CF", 90),
        ]
        analysis = analyse_match_dataset(rows, "Aerial Striker", "fr")
        dimensions = {item["key"]: item for item in analysis["dimensions"]}
        finishing = {
            item["metric"]: item for item in dimensions["finishing"]["evidence"]
        }
        link_play = {
            item["metric"]: item for item in dimensions["link_play"]["evidence"]
        }

        self.assertEqual(
            finishing["Shots on target from the penalty area, %"]["display"],
            "2/4 · 50%",
        )
        self.assertEqual(
            finishing["Headers on target, %"]["display"],
            "2/3 · 66.67%",
        )
        self.assertEqual(
            link_play["Short passes accurate, %"]["display"],
            "10/12 · 83.33%",
        )
        offensive_lens = next(
            item for item in analysis["performance_lenses"] if item["key"] == "offensive"
        )
        self.assertTrue(
            any("Menace aérienne" in line for line in offensive_lens["interpretation"])
        )

        appendix = {
            item["metric"]: item
            for group in analysis["appendix_groups"]
            for item in group["items"]
        }
        self.assertEqual(appendix["Goals by head"]["display"], "1")
        self.assertEqual(
            appendix["Headers on target, %"]["display"], "2/3 · 66.67%"
        )

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

    def test_external_index_rank_is_a_bounded_validation_not_the_position_score(self):
        base = _row("Player", "A", "RB", 90, **{"Index": 50, "Defensive challenges": 6, "Defensive challenges won, %": 0.7})
        rows = [
            base,
            _row("Team Mate 1", "A", "CB", 90, **{"Index": 90}),
            _row("Team Mate 2", "A", "CM", 90, **{"Index": 80}),
            _row("Opponent", "B", "RB", 90, **{"Index": 70}),
            _row("Opponent 2", "B", "CB", 90, **{"Index": 60}),
            _row("Opponent 3", "B", "CM", 90, **{"Index": 55}),
        ]
        first = analyse_match_dataset(rows, "Player", "en")
        rows[0]["Index"] = 250
        second = analyse_match_dataset(rows, "Player", "en")
        self.assertEqual(first["player"]["profile_score"], second["player"]["profile_score"])
        self.assertTrue(second["rankings"]["index_used_as_verdict_signal"])
        self.assertEqual(second["rankings"]["index_match"]["rank"], 1)
        self.assertEqual(second["score_breakdown"]["context_adjustment"], 2)
        self.assertEqual(second["player"]["ms_score"] - first["player"]["ms_score"], 2)
        self.assertIn("index_rank_one", second["verdict"]["reasons"])

    def test_no_aerial_opportunity_is_not_scored_as_a_weakness(self):
        rows = [
            _row("Centre Back", "A", "CB", 90, **{"Aerial challenges": 0, "Aerial challenges won, %": "-"}),
            _row("Opponent", "B", "CB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Centre Back", "en")
        aerial = next(item for item in analysis["dimensions"] if item["key"] == "aerial_control")
        self.assertEqual(aerial["coverage"], 0)
        self.assertEqual(aerial["grade_code"], "unseen")

    def test_global_success_rate_leader_requires_attempts_and_keeps_denominator(self):
        rows = [
            _row("Target", "Team A", "CB", 13, **{"Challenges": 1, "Challenges won, %": 1.0}),
            _row("A1", "Team A", "CM", 90, **{"Challenges": 10, "Challenges won, %": 0.8}),
            _row("B1", "Team B", "CB", 90, **{"Challenges": 10, "Challenges won, %": 0.7}),
        ]
        analysis = analyse_match_dataset(rows, "Target", "en")
        rate = next(item for item in analysis["global_benchmarks"] if item["metric"] == "Challenges won, %")
        self.assertEqual(rate["leaders"][0]["name"], "A1")
        self.assertEqual(rate["leaders"][0]["display"], "8/10 · 80%")
        self.assertFalse(rate["target_rank"]["available"])
        won = next(item for item in analysis["global_benchmarks"] if item["metric"] == "__duels_won__")
        self.assertEqual(won["leaders"][0]["name"], "A1")

    def test_only_exact_opposition_position_is_compared(self):
        rows = [
            _row("Target", "A", "RWB", 70),
            _row("Exact", "B", "RWB", 65),
            _row("Full Back", "B", "RB", 90),
            _row("Zone Opponent", "B", "LW", 90),
        ]
        analysis = analyse_match_dataset(rows, "Target", "en")
        comparison = analysis["same_position_comparison"]
        self.assertEqual(comparison["player"], "Exact")
        self.assertEqual(comparison["position"], "RWB")
        self.assertEqual(comparison["position_match"], "exact")
        self.assertNotIn("same_compartment", analysis)
        self.assertNotIn("unit_comparisons", analysis)
        self.assertNotIn("matchups", analysis)

    def test_strict_position_equivalent_is_used_when_shapes_differ(self):
        rows = [
            _row("Target", "A", "RWB", 70),
            _row("Equivalent", "B", "RB", 90),
            _row("Zone Opponent", "B", "LW", 90),
        ]
        analysis = analyse_match_dataset(rows, "Target", "en")
        comparison = analysis["same_position_comparison"]
        self.assertEqual(comparison["player"], "Equivalent")
        self.assertEqual(comparison["position_match"], "equivalent")

    def test_match_score_is_identification_only_not_analysis(self):
        rows = [_row("Target", "A", "CM", 90), _row("Opponent", "B", "CM", 90)]
        analysis = analyse_match_dataset(
            rows,
            "Target",
            "en",
            context={"home_team": "A", "away_team": "B", "score": "4–0"},
        )
        self.assertFalse(analysis["context"]["performance_context_analysis"])
        self.assertNotIn("result", analysis["context"])
        self.assertNotIn("score_state_note", analysis["narrative"])

    def test_short_attacking_appearance_is_judged_as_an_entry(self):
        rows = [
            _row(
                "Sub Striker",
                "A",
                "ST",
                18,
                **{
                    "Goals": 1,
                    "Shots": 2,
                    "Shots from the penalty area": 2,
                    "Actions in opponent's box": 4,
                },
            ),
            _row("Opponent", "B", "ST", 90),
        ]
        analysis = analyse_match_dataset(rows, "Sub Striker", "fr")
        self.assertEqual(analysis["verdict"]["appearance_type"], "entry")
        self.assertEqual(analysis["verdict"]["label"], "ENTRÉE DÉCISIVE")
        self.assertGreaterEqual(analysis["verdict"]["score"], 65)
        self.assertLessEqual(analysis["verdict"]["score"], 100)

    def test_creative_short_attacking_appearance_can_be_very_good_without_goal(self):
        rows = [
            _row(
                "Creative Sub",
                "A",
                "RW",
                24,
                **{
                    "Key passes": 2,
                    "Passes for a shot": 1,
                    "Passes into the penalty box": 2,
                    "Dribbles": 2,
                    "Dribbles successful, %": 1.0,
                    "Actions in opponent's box": 2,
                },
            ),
            _row("Opponent", "B", "RW", 90),
        ]
        analysis = analyse_match_dataset(rows, "Creative Sub", "fr")
        self.assertIn(analysis["verdict"]["label"], {"TRÈS BONNE ENTRÉE", "ENTRÉE DÉCISIVE"})
        self.assertGreaterEqual(analysis["verdict"]["score"], 65)
        self.assertLessEqual(analysis["verdict"]["score"], 100)

    def test_short_zero_losses_are_not_scored_as_positive_evidence(self):
        rows = [_row("Sub", "A", "ST", 13, **{"Lost balls": 0}), _row("Opponent", "B", "ST", 90)]
        analysis = analyse_match_dataset(rows, "Sub", "en")
        defensive = next(item for item in analysis["dimensions"] if item["key"] == "defensive_work")
        losses = next(item for item in defensive["evidence"] if item["metric"] == "Lost balls")
        self.assertIsNone(losses["score"])

    def test_player_facing_kpi_definition_explains_progressive_passes(self):
        rows = [_row("Target", "A", "CM", 90, **{"Progressive passes": 8}), _row("Opponent", "B", "CM", 90)]
        analysis = analyse_match_dataset(rows, "Target", "fr")
        metric = next(item for item in analysis["key_metrics"] if item["metric"] == "Progressive passes")
        self.assertIn("vers le but adverse", metric["definition"])

    def test_mission_score_exposes_every_used_criterion_and_its_contribution(self):
        rows = [
            _row(
                "Target",
                "A",
                "RB",
                90,
                **{
                    "Defensive challenges": 8,
                    "Defensive challenges won, %": 0.75,
                    "Crosses": 6,
                    "Crosses accurate, %": 0.5,
                    "Progressive passes": 9,
                    "Progressive passes accurate, %": 0.78,
                },
            ),
            _row("Opponent", "B", "RB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Target", "fr")
        breakdown = analysis["score_breakdown"]
        exposed = {
            criterion["metric"]
            for mission in breakdown["dimensions"]
            for criterion in mission["criteria"]
        }
        configured = {
            evidence["metric"]
            for mission in analysis["dimensions"]
            for evidence in mission["evidence"]
        }
        self.assertEqual(exposed, configured)
        self.assertEqual(breakdown["rounded_score"], analysis["player"]["profile_score"])
        self.assertLess(abs(breakdown["contribution_total"] - breakdown["rounded_score"]), 0.51)
        self.assertTrue(all("effect" in criterion for mission in breakdown["dimensions"] for criterion in mission["criteria"]))

    def test_full_xlsx_appendix_preserves_all_columns_and_explicit_zero_events(self):
        target = {column: "-" for column in SPORTSBASE_PLAYER_COLUMNS}
        target.update(
            {
                "№": 7,
                "Player": "Target",
                "Team": "A",
                "Index": 141,
                "Minutes played": 70,
                "Position": "RB",
                "Passes": 30,
                "Passes accurate, %": 0.8,
                "Actions": 40,
                "Actions successful, %": 0.75,
            }
        )
        analysis = analyse_match_dataset([target, _row("Opponent", "B", "RB", 70)], "Target", "fr")
        appendix = {item["metric"]: item for item in analysis["appendix_metrics"]}
        self.assertEqual(analysis["appendix_total_columns"], 81)
        self.assertEqual(set(appendix), set(SPORTSBASE_PLAYER_COLUMNS))
        self.assertEqual(appendix["Shots"]["display"], "0")
        self.assertEqual(appendix["Goals"]["display"], "0")
        self.assertEqual(appendix["Shots on target, %"]["display"], "0 tentative · non évalué")
        self.assertTrue(appendix["Goals"]["decisive"])
        self.assertTrue(appendix["Crosses"]["role_specific"])

    def test_goal_is_prominent_but_claim_is_limited_to_this_match(self):
        rows = [
            _row("Scorer", "A", "ST", 90, **{"Goals": 1, "Shots": 2, "Shots on target": 1}),
            _row("Opponent", "B", "ST", 90),
        ]
        analysis = analyse_match_dataset(rows, "Scorer", "fr")
        highlight = next(item for item in analysis["decisive_highlights"] if item["type"] == "goals")
        self.assertEqual(highlight["label"], "BUTTEUR DÉCISIF — 1 BUT")
        self.assertIn("ce match", highlight["explanation"])
        self.assertIn("pas le niveau de finition sur une saison complète", highlight["explanation"])
        self.assertGreater(analysis["score_breakdown"]["decisive_adjustment"], 4)
        self.assertEqual(analysis["score_breakdown"]["decisive_role_scale"], 1.15)
        self.assertEqual(analysis["verdict"]["code"], "solid")
        self.assertLessEqual(analysis["verdict"]["score"], 100)

    def test_decisive_creation_actions_raise_the_mission_score_for_every_role(self):
        positions = ("GK", "CB", "RB", "RWB", "CDM", "LCM", "CAM", "RW", "ST")
        for position in positions:
            base_target = _row(f"Target {position}", "A", position, 90)
            opponent = _row(f"Opponent {position}", "B", position, 90)
            baseline = analyse_match_dataset([base_target, opponent], f"Target {position}", "fr")
            impact_target = dict(base_target)
            impact_target.update(
                {
                    "Goals": 1,
                    "Assists": 1,
                    "Key passes": 3,
                    "Chances created": 2,
                    "Chances": 2,
                    "Chances successful, %": 0.5,
                    "Dribbles": 3,
                    "Dribbles successful, %": 2 / 3,
                }
            )
            impacted = analyse_match_dataset([impact_target, opponent], f"Target {position}", "fr")
            self.assertGreater(
                impacted["player"]["profile_score"],
                baseline["player"]["profile_score"],
                position,
            )
            impact_mission = next(item for item in impacted["dimensions"] if item["key"] == "impact")
            self.assertGreater(impact_mission["coverage"], 0, position)
            exposed = {item["metric"] for item in impact_mission["evidence"]}
            self.assertTrue({"Goals", "Assists", "Key passes"}.issubset(exposed), position)

    def test_missions_are_always_ordered_by_position_importance(self):
        for position in ("GK", "CB", "RB", "RWB", "CDM", "LCM", "CAM", "RW", "ST"):
            rows = [
                _row(f"Target {position}", "A", position, 90, **{"Goals": 1}),
                _row(f"Opponent {position}", "B", position, 90),
            ]
            analysis = analyse_match_dataset(rows, f"Target {position}", "en")
            weights = [item["weight"] for item in analysis["dimensions"]]
            self.assertEqual(weights, sorted(weights, reverse=True), position)

    def test_goal_key_passes_and_dribbles_are_named_in_score_drivers(self):
        rows = [
            _row(
                "Relayeur",
                "A",
                "LCM",
                90,
                **{
                    "Goals": 1,
                    "Key passes": 3,
                    "Dribbles": 3,
                    "Dribbles successful, %": 2 / 3,
                    "Chances": 2,
                    "Chances successful, %": 0.5,
                },
            ),
            _row("Opponent", "B", "LCM", 90),
        ]
        analysis = analyse_match_dataset(rows, "Relayeur", "fr")
        drivers = analysis["score_breakdown"]["impact_drivers"]
        driver_metrics = {item["metric"] for item in drivers}
        self.assertTrue({"Goals", "Key passes", "Dribbles", "Chances"}.issubset(driver_metrics))
        goal = next(item for item in drivers if item["metric"] == "Goals")
        self.assertIn("impact direct", goal["explanation"])
        self.assertIn("MS Score", goal["score_sentence"])
        self.assertGreater(goal["ms_points"], 0)
        self.assertLessEqual(analysis["score_breakdown"]["decisive_adjustment"], 8)

    def test_match_radar_uses_highest_percentage_position_and_stored_average(self):
        rows = [
            _row(
                "Mohamed Trabelsi",
                "A",
                "LCM",
                90,
                **{
                    "Chances": 1,
                    "Chances successful, %": 1,
                    "Passes into the penalty box": 2,
                    "Passes into the penalty box accurate, %": 0.5,
                    "Defensive challenges": 8,
                    "Defensive challenges won, %": 0.75,
                    "Dribbling in the final third": 2,
                    "Dribbling in the final third successful, %": 0.5,
                    "Interceptions": 3,
                },
            ),
            _row("Opponent", "B", "LCM", 90),
        ]
        context = {
            "position_benchmark": {
                "season": "2026/2027",
                "positions": [
                    {"code": "LCM", "name": "Left central midfielder", "percent": 53},
                    {"code": "LCDM", "name": "Left central defensive midfielder", "percent": 31},
                    {"code": "RCM", "name": "Right central midfielder", "percent": 16},
                ],
                "radar_metrics": [
                    {"name": "Chances", "player": 0.14, "average": 0.37, "player_normalized": 14.7, "average_normalized": 38.9, "scale_max": 0.95, "precision": 2, "unit": "per_90"},
                    {"name": "Passes into the penalty box accurate...", "player": 93, "average": 71, "player_normalized": 93, "average_normalized": 71, "scale_max": 100, "precision": 0, "unit": "%"},
                    {"name": "Defensive challenges", "player": 9.14, "average": 7.18, "player_normalized": 89.9, "average_normalized": 70.6, "scale_max": 10.17, "precision": 2, "unit": "per_90"},
                    {"name": "Dribbling in the final third successf...", "player": 46, "average": 59, "player_normalized": 46, "average_normalized": 59, "scale_max": 100, "precision": 0, "unit": "%"},
                    {"name": "Interceptions", "player": 3.37, "average": 3.36, "player_normalized": 55.4, "average_normalized": 55.3, "scale_max": 6.10, "precision": 2, "unit": "per_90", "value_source": "sportsbase_tooltip"},
                ],
            }
        }
        analysis = analyse_match_dataset(rows, "Mohamed Trabelsi", "fr", context=context)
        benchmark = analysis["position_benchmark"]
        self.assertTrue(benchmark["available"])
        self.assertEqual(benchmark["position_code"], "LCM")
        self.assertEqual(benchmark["position_percent"], 53)
        self.assertEqual(
            benchmark["scale"],
            "real_per_90_values_axis_normalized_for_shape_only",
        )
        metrics = {item["metric"]: item for item in benchmark["metrics"]}
        self.assertIn("Passes into the penalty box accurate, %", metrics)
        self.assertIn("Dribbling in the final third successful, %", metrics)
        self.assertEqual(metrics["Defensive challenges"]["position_average"], 7.18)
        self.assertEqual(metrics["Interceptions"]["season_player"], 3.37)
        self.assertEqual(metrics["Interceptions"]["position_average"], 3.36)
        self.assertEqual(metrics["Interceptions"]["difference"], 0.01)
        self.assertEqual(metrics["Interceptions"]["player_normalized"], 55.4)
        self.assertIn("valeurs saisonnières par 90 minutes", benchmark["note"])

    def test_ms_score_is_bounded_and_decisive_returns_are_diminishing(self):
        opponent = _row("Opponent", "B", "ST", 90)
        scores = []
        for goals in (0, 1, 2):
            target = _row(
                "Scorer",
                "A",
                "ST",
                90,
                **{
                    "Goals": goals,
                    "Shots": 4,
                    "Shots from the penalty area": 3,
                    "Shots on target, %": 0.5,
                    "Actions in opponent's box": 7,
                },
            )
            analysis = analyse_match_dataset([target, opponent], "Scorer", "fr")
            scores.append(analysis["player"]["ms_score"])
            self.assertEqual(analysis["verdict"]["score"], analysis["player"]["ms_score"])
            self.assertEqual(analysis["score_breakdown"]["scale"], "bounded_0_100")
            self.assertGreaterEqual(analysis["player"]["ms_score"], 0)
            self.assertLessEqual(analysis["player"]["ms_score"], 100)
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[2], scores[1])
        self.assertLess(scores[2] - scores[1], scores[1] - scores[0])

    def test_ms_score_keeps_position_missions_and_exposes_bounded_adjustments(self):
        rows = [
            _row(
                "Centre Back",
                "A",
                "CB",
                90,
                **{
                    "Goals": 1,
                    "Defensive challenges": 6,
                    "Defensive challenges won, %": 0.75,
                    "Tackles": 5,
                    "Tackles successful, %": 0.8,
                    "Interceptions": 4,
                    "Progressive passes": 8,
                    "Progressive passes accurate, %": 0.75,
                    "Long passes": 7,
                    "Long passes accurate, %": 0.57,
                },
            ),
            _row("Opponent", "B", "CB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Centre Back", "en")
        breakdown = analysis["score_breakdown"]
        criteria = {
            criterion["metric"]: criterion
            for mission in breakdown["dimensions"]
            for criterion in mission["criteria"]
        }
        self.assertGreater(criteria["Tackles"]["ms_points"], 0)
        self.assertGreater(criteria["Interceptions"]["ms_points"], 0)
        self.assertGreater(criteria["Progressive passes"]["ms_points"], 0)
        self.assertEqual(criteria["Goals"]["points_source"], "position_mission")
        direct = next(item for item in breakdown["point_events"] if item["metric"] == "Direct outcome")
        self.assertEqual(direct["points"], 2.8)
        self.assertEqual(breakdown["decisive_role_scale"], 0.70)
        self.assertLessEqual(breakdown["decisive_adjustment"], 8)
        expected = (
            breakdown["position_score"]
            + breakdown["decisive_adjustment"]
            + breakdown["context_adjustment"]
        )
        self.assertLess(abs(expected - breakdown["raw_total_points"]), 0.02)

    def test_complete_decisive_match_is_not_anchored_to_historical_scores(self):
        trabelsi = _row(
            "Mohamed Trabelsi", "CS Sfaxien", "LCM", 85,
            **{
                "Index": 201,
                "Actions": 62, "Actions successful, %": 0.66,
                "Passes": 32, "Passes accurate, %": 0.75, "Lost balls": 13,
                "Progressive passes": 11, "Progressive passes accurate, %": 0.45,
                "Final third entries": 2, "Final third entries through pass": 2,
                "Final third entries through carry": 0,
                "Actions in opponent's box": 4,
                "Actions in opponent's box successful, %": 1,
                "Shots": 2, "Dribbles": 3, "Dribbles successful, %": 1,
                "Passes for a shot": 1, "Passes into the penalty box": 1,
                "Passes into the penalty box accurate, %": 1,
                "Defensive challenges": 10, "Defensive challenges won, %": 0.4,
                "Tackles": 6, "Tackles successful, %": 0.5,
                "Interceptions": 1, "Ball recoveries": 3,
                "Ball recoveries in opponent's half": 1,
                "Goals": 1, "Chances": 1, "Chances successful, %": 1,
                "Involvement in scoring attacks": 1, "xG (expected goals)": 0.09,
            },
        )
        mhadhebi = _row(
            "Mohamed Salah Mhadhebi", "CS Sfaxien", "RWB", 13,
            **{
                "Index": "-", "Actions": 9, "Actions successful, %": 0.67,
                "Passes": 6, "Passes accurate, %": 0.67, "Lost balls": 1,
                "Progressive passes": 1, "Progressive passes accurate, %": 0,
                "Passes into the penalty box": 1,
                "Passes into the penalty box accurate, %": 1,
                "Defensive challenges": 1, "Defensive challenges won, %": 1,
                "Interceptions": 1,
            },
        )
        rows = [trabelsi, mhadhebi] + [
            _row(f"Opponent {index}", "Stade Tunisien", "CM", 90, **{"Index": value})
            for index, value in enumerate((180, 170, 160, 150, 140), start=1)
        ]
        full_match = analyse_match_dataset(rows, "Mohamed Trabelsi", "fr")
        short_entry = analyse_match_dataset(rows, "Mohamed Salah Mhadhebi", "fr")

        self.assertGreater(full_match["player"]["ms_score"], short_entry["player"]["ms_score"])
        self.assertGreaterEqual(full_match["player"]["ms_score"] - short_entry["player"]["ms_score"], 10)
        self.assertEqual(short_entry["confidence"]["code"], "very_low")

    def test_decisive_bonus_is_role_scaled_without_replacing_position_missions(self):
        centre_back = _row("Centre Back", "A", "CB", 90, **{"Goals": 1})
        forward = _row("Forward", "A", "ST", 90, **{"Goals": 1})
        cb_analysis = analyse_match_dataset([centre_back, _row("CB Opponent", "B", "CB", 90)], "Centre Back", "en")
        forward_analysis = analyse_match_dataset([forward, _row("ST Opponent", "B", "ST", 90)], "Forward", "en")
        self.assertLess(
            cb_analysis["score_breakdown"]["decisive_adjustment"],
            forward_analysis["score_breakdown"]["decisive_adjustment"],
        )
        self.assertEqual(cb_analysis["score_breakdown"]["decisive_role_scale"], 0.70)
        self.assertEqual(forward_analysis["score_breakdown"]["decisive_role_scale"], 1.15)

    def test_missions_explain_the_phase_and_football_objective(self):
        rows = [_row("Full Back", "A", "RB", 90), _row("Opponent", "B", "RB", 90)]
        analysis = analyse_match_dataset(rows, "Full Back", "fr")
        self.assertTrue(all(item.get("description") for item in analysis["dimensions"]))
        self.assertTrue(all(item.get("phase_label") for item in analysis["dimensions"]))
        impact = next(item for item in analysis["dimensions"] if item["key"] == "impact")
        self.assertIn("buts", impact["description"])

    def test_symmetric_teammate_profile_is_compared_on_role_kpis_only(self):
        rows = [
            _row("Right Back", "A", "RB", 90, **{"Final third entries": 6}),
            _row("Left Back", "A", "LB", 88, **{"Final third entries": 4}),
            _row("Unrelated Winger", "A", "RW", 90, **{"Final third entries": 10}),
            _row("Opponent Right Back", "B", "RB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Right Back", "fr")
        teammate = analysis["teammate_profile_comparison"]
        self.assertEqual(teammate["player"], "Left Back")
        self.assertEqual(teammate["position"], "LB")
        self.assertEqual(teammate["position_match"], "symmetric")
        compared = {item["metric"] for item in teammate["metrics"]}
        self.assertIn("Final third entries", compared)
        self.assertNotIn("Aerial challenges", compared)

    def test_legacy_normalized_radar_is_not_presented_as_a_real_value(self):
        rows = [_row("Target", "A", "LCM", 90), _row("Opponent", "B", "LCM", 90)]
        context = {
            "position_benchmark": {
                "positions": [{"code": "LCM", "percent": 100}],
                "radar_metrics": [
                    {"name": "Chances", "player": 22.5, "average": 44.5},
                    {"name": "Shots", "player": 60.0, "average": 50.0},
                    {"name": "Interceptions", "player": 59.5, "average": 59.3},
                ],
            }
        }
        benchmark = analyse_match_dataset(rows, "Target", "fr", context=context)["position_benchmark"]
        self.assertFalse(benchmark["available"])
        self.assertFalse(any(item["comparable"] for item in benchmark["metrics"]))

    def test_trabelsi_style_involvement_and_box_actions_are_read_exactly(self):
        rows = [
            _row(
                "Mohamed Trabelsi",
                "CS Sfaxien",
                "LCM",
                85,
                **{
                    "Actions": 62,
                    "Actions successful, %": 0.66,
                    "Actions in opponent's box": 4,
                    "Actions in opponent's box successful, %": 1.0,
                    "Final third entries": 2,
                    "Final third entries through pass": 2,
                    "Final third entries through carry": 0,
                    "xG (expected goals)": 0.09,
                },
            ),
            _row("Opponent", "Stade Tunisien", "LCM", 90),
        ]
        analysis = analyse_match_dataset(rows, "Mohamed Trabelsi", "fr")
        lenses = {item["key"]: item for item in analysis["performance_lenses"]}
        global_text = " ".join(lenses["global"]["interpretation"])
        attacking_text = " ".join(lenses["offensive"]["interpretation"])
        self.assertIn("62 actions", global_text)
        self.assertIn("41/62 · 66%", global_text)
        self.assertIn("4/4 · 100%", attacking_text)
        self.assertIn("2 par la passe", attacking_text)
        self.assertIn("0.09 xG", attacking_text)

    def test_same_four_box_actions_are_role_calibrated(self):
        common = {
            "Actions in opponent's box": 4,
            "Actions in opponent's box successful, %": 1.0,
        }
        midfielder = analyse_match_dataset(
            [_row("Midfielder", "A", "LCM", 85, **common), _row("Opponent", "B", "LCM", 85)],
            "Midfielder",
            "en",
        )
        forward = analyse_match_dataset(
            [_row("Forward", "A", "ST", 85, **common), _row("Opponent", "B", "ST", 85)],
            "Forward",
            "en",
        )
        midfielder_dimension = next(item for item in midfielder["dimensions"] if item["key"] == "final_third_presence")
        forward_dimension = next(item for item in forward["dimensions"] if item["key"] == "box_presence")
        midfielder_score = next(item["score"] for item in midfielder_dimension["evidence"] if item["metric"] == "Actions in opponent's box")
        forward_score = next(item["score"] for item in forward_dimension["evidence"] if item["metric"] == "Actions in opponent's box")
        self.assertGreater(midfielder_score, forward_score)
        self.assertIn("strong presence for this role", " ".join(midfielder["performance_lenses"][1]["interpretation"]))
        self.assertIn("below the role reference", " ".join(forward["performance_lenses"][1]["interpretation"]))

    def test_xg_is_a_scored_offensive_signal_for_attacking_roles(self):
        for position in ("LCM", "CAM", "RW", "ST"):
            baseline = _row(f"Target {position}", "A", position, 90, **{"Shots": 2, "xG (expected goals)": 0})
            with_xg = dict(baseline)
            with_xg["xG (expected goals)"] = 0.55
            opponent = _row(f"Opponent {position}", "B", position, 90)
            first = analyse_match_dataset([baseline, opponent], f"Target {position}", "en")
            second = analyse_match_dataset([with_xg, opponent], f"Target {position}", "en")
            self.assertGreater(second["player"]["profile_score"], first["player"]["profile_score"], position)
            drivers = {item["metric"] for item in second["score_breakdown"]["impact_drivers"]}
            self.assertIn("xG (expected goals)", drivers, position)

    def test_defender_profile_scores_intervention_and_distribution_quality(self):
        rows = [
            _row(
                "Centre Back",
                "A",
                "CB",
                90,
                **{
                    "Defensive challenges": 6,
                    "Defensive challenges won, %": 0.75,
                    "Tackles": 5,
                    "Tackles successful, %": 0.8,
                    "Interceptions": 4,
                    "Progressive passes": 8,
                    "Progressive passes accurate, %": 0.75,
                    "Long passes": 7,
                    "Long passes accurate, %": 0.57,
                    "Super long passes": 3,
                    "Super long passes accurate, %": 2 / 3,
                },
            ),
            _row("Opponent", "B", "CB", 90),
        ]
        analysis = analyse_match_dataset(rows, "Centre Back", "en")
        configured = {
            item["metric"]
            for dimension in analysis["dimensions"]
            for item in dimension["evidence"]
        }
        expected = {
            "Tackles", "Tackles successful, %", "Interceptions", "Progressive passes",
            "Progressive passes accurate, %", "Long passes", "Long passes accurate, %",
            "Super long passes", "Super long passes accurate, %",
        }
        self.assertTrue(expected.issubset(configured))
        phase_metrics = [
            item["metric"]
            for lens in analysis["performance_lenses"]
            for item in lens["metrics"]
        ]
        self.assertEqual(len(phase_metrics), len(set(phase_metrics)))

    def test_dominant_centre_back_can_score_very_good_without_decisive_action(self):
        centre_back = _row(
            "Dominant Centre Back", "A", "CB", 90,
            **{
                "Actions": 70, "Actions successful, %": 0.90,
                "Passes": 55, "Passes accurate, %": 0.90,
                "Lost balls in own half": 0,
                "Defensive challenges": 10, "Defensive challenges won, %": 0.90,
                "Tackles": 6, "Tackles successful, %": 0.90,
                "Interceptions": 5,
                "Aerial challenges": 6, "Aerial challenges won, %": 0.90,
                "Progressive passes": 12, "Progressive passes accurate, %": 0.90,
                "Long passes": 10, "Long passes accurate, %": 0.80,
                "Super long passes": 4, "Super long passes accurate, %": 0.75,
            },
        )
        analysis = analyse_match_dataset(
            [centre_back, _row("Opponent", "B", "CB", 90)],
            "Dominant Centre Back",
            "fr",
        )
        self.assertGreaterEqual(analysis["player"]["ms_score"], 85)
        self.assertEqual(analysis["verdict"]["code"], "very_good")
        self.assertEqual(analysis["score_breakdown"]["decisive_adjustment"], 0)


class PerformancePdfTests(unittest.TestCase):
    def test_report_copy_is_source_brand_neutral(self):
        visible_copy = str(PDF_COPY).lower()
        self.assertNotIn("sportsbase", visible_copy)
        self.assertNotIn("سبورتس", visible_copy)

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
