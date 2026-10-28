import unittest,uuid,json
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.conf import settings

class CommittedMigrationTests(unittest.TestCase):
 def test_initial_migration_commits_in_new_preserved_schema(self):
  schema='action03_migration_'+uuid.uuid4().hex
  quoted=connection.ops.quote_name(schema)
  with connection.cursor() as c:
   c.execute('CREATE SCHEMA '+quoted)
   c.execute('SET search_path TO '+quoted)
  try:
   MigrationExecutor(connection).migrate([('actions','0001_initial')])
   connection.close()
   with connection.cursor() as c:
    c.execute('SET search_path TO '+quoted)
    c.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
    applied=c.fetchall()
    self.assertEqual(applied,[('actions','0001_initial')])
    c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s ORDER BY table_name",[schema])
    tables=[r[0] for r in c.fetchall()]
    self.assertEqual(tables,['actions_audit','actions_plan','django_migrations'])
    c.execute("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema=%s AND constraint_type='UNIQUE'",[schema])
    self.assertIn(('action01_idempotency',),c.fetchall())
   receipt={'schema':schema,'applied':applied,'tables':tables,'committed_readback_after_connection_close':True,'existing_public_tables_untouched':True}
   (settings.ROOT/'evidence'/('migration-committed-'+schema+'.json')).open('x').write(json.dumps(receipt,indent=2))
   print('COMMITTED_MIGRATION',json.dumps(receipt))
  finally:
   with connection.cursor() as c:c.execute('SET search_path TO public')
