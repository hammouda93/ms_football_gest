def validate(row,expected,system,version):
 assert system=='Linux' and tuple(version)==(3,10,22),'runtime identity'
 assert set(expected)=={'serverAddress'},'attestation keys'
 import ipaddress
 address=ipaddress.ip_address(expected['serverAddress'])
 assert address.version==4 and address.is_private and not address.is_loopback,'container address'
 assert len(row)==6 and row[:2]==('msf_action03_fiction','msf_action01_fixture_owner'),'database identity'
 assert row[2]==str(address) and row[3]==5432,'server endpoint'
 assert row[4]=='/var/lib/postgresql/data','data directory'
 assert row[5].split()[0]=='16.14','postgresql version'
 return row
