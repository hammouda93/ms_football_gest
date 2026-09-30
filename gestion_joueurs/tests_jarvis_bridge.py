from django.test import SimpleTestCase

from gestion_joueurs.jarvis_bridge import (
    BridgeError,
    _validate_readonly_sql,
    describe_schema,
    list_routes,
)


class JarvisBridgeSafetyTests(SimpleTestCase):
    def test_player_schema_is_discoverable(self):
        payload = describe_schema(search="Player")
        model_names = {item["model"] for item in payload["models"]}
        self.assertTrue(
            any(name.endswith(".Player") for name in model_names),
            model_names,
        )

    def test_routes_are_discoverable(self):
        payload = list_routes(search="player", limit=20)
        self.assertGreater(payload["count"], 0)

    def test_select_is_allowed(self):
        sql = _validate_readonly_sql(
            "SELECT id, name FROM gestion_joueurs_player LIMIT 5"
        )
        self.assertTrue(sql.startswith("SELECT"))

    def test_update_is_rejected(self):
        with self.assertRaises(BridgeError):
            _validate_readonly_sql(
                "UPDATE gestion_joueurs_player SET name='x'"
            )

    def test_sensitive_auth_table_is_rejected(self):
        with self.assertRaises(BridgeError):
            _validate_readonly_sql(
                "SELECT username, password FROM auth_user"
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
