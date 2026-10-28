import unittest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.executor import MigrationExecutor

class MigrationTests(unittest.TestCase):
 def test_actions_has_distributable_initial_migration(self):
  loader=MigrationLoader(connection)
  self.assertIn(('actions','0001_initial'),loader.disk_migrations)
  migration=loader.disk_migrations[('actions','0001_initial')]
  self.assertEqual({op.name for op in migration.operations if hasattr(op,'name')},{'Plan','Audit'})
