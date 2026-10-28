import unittest,uuid
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

class QuotaMigrationTests(unittest.TestCase):
    def test_real_initial_and_quota_migrations_commit_in_fresh_schema(self):
        schema='action06_migration_'+uuid.uuid4().hex
        quoted=connection.ops.quote_name(schema)
        with connection.cursor() as c:
            c.execute('CREATE SCHEMA '+quoted);c.execute('SET search_path TO '+quoted)
        try:
            MigrationExecutor(connection).migrate([('actions','0002_quotabucket')])
            connection.close()
            with connection.cursor() as c:
                c.execute('SET search_path TO '+quoted)
                c.execute('SELECT name FROM django_migrations ORDER BY name')
                self.assertEqual(c.fetchall(),[('0001_initial',),('0002_quotabucket',)])
                c.execute("INSERT INTO actions_quotabucket(key,window_start,used) VALUES('migration-proof',clock_timestamp(),1)")
            connection.close()
            with connection.cursor() as c:
                c.execute('SET search_path TO '+quoted)
                c.execute("SELECT used FROM actions_quotabucket WHERE key='migration-proof'")
                self.assertEqual(c.fetchone(),(1,))
            print('QUOTA_MIGRATION_PRESERVED_SCHEMA',schema)
        finally:
            with connection.cursor() as c:c.execute('SET search_path TO public')
