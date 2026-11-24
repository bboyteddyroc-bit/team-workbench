"""Pinned upstream Kalodata skill helpers; transport stays one-shot in the host app.
No config-file/key loading, background update checks, CLI retry loop or private history.
"""
import importlib.util
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'vendor/kalodata-skill/skills/kalodata/scripts/kalodata'
NAME='_case_kalodata_skill'
if NAME not in sys.modules:
    spec=importlib.util.spec_from_file_location(NAME,ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
    module=importlib.util.module_from_spec(spec);sys.modules[NAME]=module;spec.loader.exec_module(module)
from _case_kalodata_skill.config import Config
from _case_kalodata_skill.commands.common import base_body,coerce_numbers,flatten_rich_text
from _case_kalodata_skill import __version__


def detail_body(video,start,end):
    # Same builder/validation and need_extra setting used by upstream video.detail.
    cfg=Config(region='US',language='en-US',currency='USD',update_check=False)
    body=base_body(cfg,{'range':f'{start}~{end}'},'detail')
    body.update(video_id=video,need_extra=True)
    return body


def headers():
    return {'source-type':'SKILL','skill-version':__version__}
