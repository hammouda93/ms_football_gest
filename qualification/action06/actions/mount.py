"""Closed deployment mount: no environment flag can activate this staging package."""

def configure(namespace):
    namespace['INSTALLED_APPS']=[*namespace['INSTALLED_APPS'],'actions']
    middleware=list(namespace['MIDDLEWARE'])
    middleware.insert(middleware.index('django.middleware.security.SecurityMiddleware')+1,'actions.http.OperationalWriterBoundary')
    namespace['MIDDLEWARE']=middleware
    namespace['ACTIONS_ENABLED']=False
    namespace['ACTIONS_CREDENTIALS']={}
    namespace['ACTIONS_APPROVAL_KEY']=''
