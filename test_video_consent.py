import unittest
from video_consent import approved,from_parent,POLICY
class VideoConsentTests(unittest.TestCase):
 def test_old_and_incomplete_flags_never_authorize(self):
  for obj in ({},{'consent':True},{'native_video_consent':True},{'native_video_policy':POLICY},'invalid'):
   self.assertFalse(approved(obj));self.assertFalse(approved(from_parent(obj,'x')))
 def test_parent_explicit_policy_only(self):
  self.assertTrue(approved(from_parent({'native_video_consent':True,'native_video_policy':POLICY},'x')))
if __name__=='__main__':unittest.main()
