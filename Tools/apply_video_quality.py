"""Matte_Zoom: show the Spout video at original quality (same fixes as Matte_2P_v2).

1. M_Zoom_BG / M_Zoom_Person (masked cutout, as before): exact sRGB decode instead of pow(x, 2.2), sampled at exact
   screen pixels (zoom_video.py; setup_zoom_stage.py builds them the same way now).
2. ZoomCamera post process neutral: manual exposure 0, tone curve 0, local exposure contrast 1,
   no bloom / vignette / grain / flare / fringe / motion blur.
3. Config/DefaultEngine.ini: no anti-aliasing (TSR blends frames and softens/ghosts the video,
   worst while zooming), screen percentage 100, Lumen / ray tracing / distance fields off
   (unlit video plates do not need them; frees the GPU).
   The ini is read at editor start: restart the editor after running this.

Leaves the pillar, markers, plates' positions and the camera's Zoom settings alone.

Run headless with the editor closed:
  UnrealEditor-Cmd.exe Matte_Zoom.uproject -run=pythonscript -script="<this file>"
or inside the editor: Output Log > Python > py "<this file>"  (then restart the editor)
Safe to run again.
"""
import os
import re
import sys
import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib  # noqa: E402
import zoom_video  # noqa: E402
importlib.reload(zoom_video)   # the editor keeps modules between runs: always use the file as it is now
from zoom_video import build_video_material, neutral_post_process  # noqa: E402

CORE = "/Game/Zoom/Core"
MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
assets = unreal.EditorAssetLibrary

# ---------- video materials ----------
for name, rt, cutout in (("M_Zoom_BG", "RT_RVM_BG", False), ("M_Zoom_Person", "RT_RVM_OUTPUT", True)):
    build_video_material(assets.load_asset(f"{CORE}/{name}"), assets.load_asset(f"{CORE}/{rt}"), cutout)
    unreal.log_warning(f"QUALITY {name}: exact sRGB, screen-pixel sampling")

# ---------- camera ----------
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(MAP_PATH)
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label() == "ZoomCamera":
        cc = a.get_cine_camera_component()
        cc.set_editor_property("post_process_settings", neutral_post_process(cc.get_editor_property("post_process_settings")))
        unreal.log_warning("QUALITY ZoomCamera post process neutral")
les.save_current_level()

# ---------- project settings ----------
INI_SET = {
    "/Script/Engine.RendererSettings": {
        "r.AntiAliasingMethod": "0",
        "r.DynamicGlobalIlluminationMethod": "0",
        "r.ReflectionMethod": "0",
        "r.RayTracing": "False",
        "r.RayTracing.RayTracingProxies.ProjectEnabled": "False",
        "r.GenerateMeshDistanceFields": "False",
        "r.Lumen.HardwareRayTracing": "False",
    },
    "SystemSettings": {"r.ScreenPercentage": "100"},
}
ini = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir()), "DefaultEngine.ini")
text = open(ini, encoding="utf-8").read()
for section, values in INI_SET.items():
    if f"[{section}]" not in text:
        text = text.rstrip("\n") + f"\n\n[{section}]\n"
    for key, val in values.items():
        pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        if pat.search(text):
            text = pat.sub(f"{key}={val}", text)
        else:
            text = text.replace(f"[{section}]\n", f"[{section}]\n{key}={val}\n", 1)
open(ini, "w", encoding="utf-8").write(text)
unreal.log_warning(f"QUALITY {ini}: AA off, screen 100%, Lumen/RT off (restart the editor)")
unreal.log_warning("QUALITY done")
