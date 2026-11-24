"""Versioned consent markers for native-video processing.

A previous sampled-frame consent does not authorize sending source video/audio.
Do not infer permission from old flags or an unverified parent job.
"""
import json
POLICY='a6-native-video-audio-v1'

def approved(options):
    if isinstance(options,str):
        try: options=json.loads(options)
        except (ValueError,TypeError):return False
    return isinstance(options,dict) and options.get('native_video_consent') is True and options.get('native_video_policy')==POLICY

def from_parent(options,parent_id):
    result={'parent':parent_id}
    if approved(options): result.update(native_video_consent=True,native_video_policy=POLICY)
    return result
