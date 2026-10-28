import unittest
from actions.engine import Engine

class ValidationTests(unittest.TestCase):
 def test_video_amend_requires_info(self):
  e=Engine(1)
  self.assertIn('info',e.catalogue()['video.amend']['required'])
  with self.assertRaisesRegex(ValueError,'missing_field'):
   e.validate([{'as':'v','op':'video.amend','values':{'id':1}}])
 def test_operation_json_types_are_structured_refusals(self):
  for op in [[],{},True,1,None]:
   with self.subTest(op=op):
    with self.assertRaisesRegex(ValueError,'operation_forbidden'):
     Engine(1).validate([{'as':'v','op':op,'values':{}}])
 def test_reference_json_types_are_structured_refusals(self):
  for ref in [[],{},True,1,None]:
   with self.subTest(ref=ref):
    with self.assertRaisesRegex(ValueError,'invalid_reference'):
     Engine(1).validate([{'as':'p','op':'player.create','values':{'name':'FICTION','club':'FICTION','league':'OC','position':'MF','date_of_birth':'2002-01-02'}},{'as':'link','op':'organization.link','values':{'player':{'ref':ref},'organization':1,'expected_matches':5}}])
