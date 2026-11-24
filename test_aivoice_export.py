"""Run the real HTTP/save/export regression, using local audio only."""
import unittest

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromName(
        'test_voice_integration.VoiceIntegrationTests.test_voice_real_save_export_waveform_and_privacy')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
