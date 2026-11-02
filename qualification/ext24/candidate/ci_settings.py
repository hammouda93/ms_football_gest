from settings_fixture import *
from copy import deepcopy
DATABASES={'default':{'ENGINE':'django.db.backends.postgresql','NAME':'msf_ext24_fiction','USER':'msf_ext24_fixture','HOST':'127.0.0.1','PORT':'55951','CONN_MAX_AGE':0}}
DATABASES['verification']=deepcopy(DATABASES['default']);DATABASES['data_access']=deepcopy(DATABASES['default'])
