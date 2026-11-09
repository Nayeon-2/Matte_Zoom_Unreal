"""Rebuild the person plate and the pillar materials (see zoom_video.py).

- M_Zoom_Person: masked cutout on the matte alpha again (as it was before apply_video_quality.py
  made it translucent by mistake), keeping the quality fixes (exact sRGB, screen-pixel sampling).
  Masked writes depth where the person is: F puts the pillar between background and person.
- M_Zoom_Pillar: translucent walk-through instead of dithered masked, so the fade stays smooth
  with anti-aliasing off. Fades only where the person is behind it within PassBand.

Run with the editor open (stop Play first), Output Log in "Cmd" mode:
  py "D:/body tracking/Unreal/Matte_Zoom/Tools/fix_walkthrough_materials.py"
or headless with the editor closed:
  UnrealEditor-Cmd.exe Matte_Zoom.uproject -run=pythonscript -script="<this file>"
"""
import os
import sys
import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib  # noqa: E402
import zoom_video  # noqa: E402
importlib.reload(zoom_video)   # the editor keeps modules between runs: always use the file as it is now
from zoom_video import build_pillar_material, build_video_material  # noqa: E402

load = unreal.load_asset
rt_out = load("/Game/Zoom/Core/RT_RVM_OUTPUT")
person = build_video_material(load("/Game/Zoom/Core/M_Zoom_Person"), rt_out, True)
pillar = build_pillar_material(load("/Game/Zoom/Test/M_Zoom_Pillar"), rt_out, load("/Game/Zoom/Core/MPC_Zoom"))
unreal.log_warning(f"WALKTHROUGH person={person.get_editor_property('blend_mode')} (must be MASKED), "
                   f"pillar={pillar.get_editor_property('blend_mode')} (TRANSLUCENT): done")
