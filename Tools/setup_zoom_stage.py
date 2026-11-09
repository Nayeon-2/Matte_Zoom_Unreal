"""Matte_Zoom: Spout inputs, video plates and BP_ZoomCamera in Zoom_Stage.

Needs the ZoomTracking plugin (Plugins/ZoomTracking) and a level made by setup_empty_stage.py.

Safe to run again (rebuilds what it owns). Run headless with the editor closed:
  UnrealEditor-Cmd.exe Matte_Zoom.uproject -run=pythonscript -script="<this file>"
or inside the editor: Output Log > Python > py "<this file>"

Scene units are real centimeters. The camera is the Fujinon UA107x8.4 at full wide
on a 2/3" 16:9 sensor (8.4 mm, 59.4 deg). Plates are children of the camera, tagged
"ZoomPlate", and sized to fill the frame; BP_ZoomCamera re-fits them when zooming.
"""
import math
import os
import sys
import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib  # noqa: E402
import zoom_video  # noqa: E402
importlib.reload(zoom_video)   # the editor keeps modules between runs: always use the file as it is now
from zoom_video import build_pillar_material, build_video_material, neutral_post_process  # noqa: E402

CORE, TEST = "/Game/Zoom/Core", "/Game/Zoom/Test"
MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
SENSOR_W, SENSOR_H, WIDE_MM = 9.59, 9.59 * 9 / 16, 8.4
PLATES = [  # label, material, distance cm, tags (PersonPlate: BP_ZoomCamera moves it to the person distance)
    ("Plate_BG", "M_Zoom_BG", 10000.0, ["ZoomPlate"]),
    ("Plate_Person", "M_Zoom_Person", 1000.0, ["ZoomPlate", "PersonPlate"]),
]
# Walk-through test object between the person and the background: forward cm, right cm, diameter cm.
# 540 cm sits between where the ODD EYE CIRCLE trio stands (~5.8 m) and where they stop (~5.0 m).
PILLAR = (540.0, -31.0, 50.0)
PASS_BAND = 150.0         # cm behind an object over which it dissolves where the person is (walk-through)
MARKERS_IN_GAME = False   # zoom check cubes (Test folder): editor only unless True

assets = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def get_or_create(name, folder, cls, factory):
    path = f"{folder}/{name}"
    if assets.does_asset_exist(path):
        return assets.load_asset(path)
    return tools.create_asset(name, folder, cls, factory)


# ---------- render targets (RGBA8: RGBA16f makes the Spout copy fail silently) ----------
def make_rt(name):
    rt = get_or_create(name, CORE, unreal.TextureRenderTarget2D, unreal.TextureRenderTargetFactoryNew())
    rt.set_editor_property("render_target_format", unreal.TextureRenderTargetFormat.RTF_RGBA8)
    rt.set_editor_property("size_x", 1920)
    rt.set_editor_property("size_y", 1080)
    rt.set_editor_property("clear_color", unreal.LinearColor(0, 0, 0, 0))
    assets.save_loaded_asset(rt)
    return rt


rt_out, rt_bg = make_rt("RT_RVM_OUTPUT"), make_rt("RT_RVM_BG")


# ---------- materials ----------
def new_material(name, folder):
    m = get_or_create(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mel.delete_all_material_expressions(m)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    return m


def video_material(name, rt, cutout):
    """Unlit video plate (exact sRGB, sampled at screen pixels): see zoom_video.py."""
    return build_video_material(get_or_create(name, CORE, unreal.Material, unreal.MaterialFactoryNew()), rt, cutout)


mat_bg = video_material("M_Zoom_BG", rt_bg, False)
mat_person = video_material("M_Zoom_Person", rt_out, True)

marker = new_material("M_Zoom_Marker", TEST)
col = mel.create_material_expression(marker, unreal.MaterialExpressionVectorParameter, -300, 0)
col.set_editor_property("parameter_name", "Color")
col.set_editor_property("default_value", unreal.LinearColor(1.0, 0.25, 0.0, 1.0))
mel.connect_material_property(col, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
mel.recompile_material(marker)
assets.save_loaded_asset(marker)
marker_mis = {}
for mi_name, c in (("MI_Zoom_Marker_Orange", (1.0, 0.25, 0.0)), ("MI_Zoom_Marker_Cyan", (0.0, 0.8, 1.0))):
    mi = get_or_create(mi_name, TEST, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mi.set_editor_property("parent", marker)
    mel.set_material_instance_vector_parameter_value(mi, "Color", unreal.LinearColor(*c, 1.0))
    assets.save_loaded_asset(mi)
    marker_mis[mi_name] = mi


# ---------- level: clear what this script owns ----------
les.load_level(MAP_PATH)
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith(("Plate_", "Marker_", "SpoutInputs", "Pillar")):
        eas.destroy_actor(a)
unreal.SystemLibrary.collect_garbage()

# ---------- Spout inputs: one actor, two receivers ----------
bp_path = f"{CORE}/BP_SpoutInputs"
if assets.does_asset_exist(bp_path):
    assets.delete_asset(bp_path)
f = unreal.BlueprintFactory()
f.set_editor_property("parent_class", unreal.Actor)
bp = tools.create_asset("BP_SpoutInputs", CORE, unreal.Blueprint, f)
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
root = sds.k2_gather_subobject_data_for_blueprint(bp)[0]
for comp_name, rt, sender in (("Spout_RVM_OUTPUT", rt_out, "RVM_OUTPUT"), ("Spout_RVM_BG", rt_bg, "RVM_BG")):
    handle, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(
        parent_handle=root, new_class=unreal.SpoutReceiverComponent, blueprint_context=bp))
    sds.rename_subobject(handle, comp_name)
    comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
        unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle))
    comp.set_editor_property("auto_start", True)
    comp.set_editor_property("output_render_target", rt)
    comp.set_editor_property("spout_sender_name", sender)
    comp.set_editor_property("target_fps", 60)
    comp.set_editor_property("startup_policy", unreal.SpoutWorldBootstrapPolicy.EDITOR_AND_GAME)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
assets.save_loaded_asset(bp)


# ---------- MPC: person plate depth for object materials (set by BP_ZoomCamera every tick) ----------
mpc = get_or_create("MPC_Zoom", CORE, unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())
def mpc_scalar(name, value):
    sp = unreal.CollectionScalarParameter()
    sp.set_editor_property("parameter_name", name)
    sp.set_editor_property("default_value", value)
    return sp


mpc.set_editor_property("scalar_parameters", [mpc_scalar("PersonDepth", 1000.0), mpc_scalar("PassBand", PASS_BAND)])
assets.save_loaded_asset(mpc)

# ---------- BP_ZoomCamera (C++ AZoomCameraActor: reads the code, sets focal, fits plates) ----------
cam_path = f"{CORE}/BP_ZoomCamera"
if assets.does_asset_exist(cam_path):
    bp_cam = assets.load_asset(cam_path)
else:
    f = unreal.BlueprintFactory()
    f.set_editor_property("parent_class", unreal.ZoomCameraActor)
    bp_cam = tools.create_asset("BP_ZoomCamera", CORE, unreal.Blueprint, f)
cam_cdo = unreal.get_default_object(bp_cam.generated_class())
cam_cdo.set_editor_property("code_texture", rt_out)
cam_cdo.set_editor_property("wide_focal_length", WIDE_MM)
cam_cdo.set_editor_property("depth_parameters", mpc)
cam_cdo.set_editor_property("pass_band", PASS_BAND)
unreal.BlueprintEditorLibrary.compile_blueprint(bp_cam)
assets.save_loaded_asset(bp_cam)

# Swap the plain level camera for BP_ZoomCamera, keeping its look settings.
cam = next(a for a in eas.get_all_level_actors() if a.get_actor_label() == "ZoomCamera")
if cam.get_class() != bp_cam.generated_class():
    old = cam
    cam = eas.spawn_actor_from_class(bp_cam.generated_class(), unreal.Vector(0, 0, 0))
    cam.get_cine_camera_component().set_editor_property(
        "post_process_settings", old.get_cine_camera_component().get_editor_property("post_process_settings"))
    eas.destroy_actor(old)
    cam.set_actor_label("ZoomCamera")
    cam.set_folder_path("Core")
cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
cc = cam.get_cine_camera_component()
fs = cc.get_editor_property("focus_settings")
fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
cc.set_editor_property("focus_settings", fs)
fb = cc.get_editor_property("filmback")
fb.set_editor_property("sensor_width", SENSOR_W)
fb.set_editor_property("sensor_height", SENSOR_H)
cc.set_editor_property("filmback", fb)
ls = cc.get_editor_property("lens_settings")
ls.set_editor_property("min_focal_length", 4.0)
ls.set_editor_property("max_focal_length", 2000.0)    # 900 mm x 2 extender
ls.set_editor_property("min_f_stop", 1.7)
cc.set_editor_property("lens_settings", ls)
cc.set_editor_property("current_focal_length", WIDE_MM)
# Video must pass unchanged (also no motion blur: plates are re-sized every frame while zooming).
cc.set_editor_property("post_process_settings", neutral_post_process(cc.get_editor_property("post_process_settings")))
cam.set_actor_location(unreal.Vector(0, 0, 0), False, False)
cam.set_actor_rotation(unreal.Rotator(0, 0, 0), False)

hfov = 2 * math.atan(SENSOR_W / (2 * WIDE_MM))
# Engine plane: local X -> U, local Y -> V, normal +Z. Map U to screen right (+Y), V to screen down (-Z),
# normal toward the camera (-X).
plate_rot = unreal.MathLibrary.make_rot_from_xy(unreal.Vector(0, 1, 0), unreal.Vector(0, 0, -1))
plane = unreal.load_asset("/Engine/BasicShapes/Plane")
for label, mat_name, dist, tags in PLATES:
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
    a.set_actor_label(label)
    a.set_folder_path("Core")
    a.tags = tags
    smc = a.static_mesh_component
    smc.set_mobility(unreal.ComponentMobility.MOVABLE)
    smc.set_static_mesh(plane)
    smc.set_material(0, assets.load_asset(f"{CORE}/{mat_name}"))
    smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    smc.set_editor_property("cast_shadow", False)
    a.attach_to_actor(cam, "", unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE,
                      unreal.AttachmentRule.KEEP_RELATIVE, False)
    width = 2 * dist * math.tan(hfov / 2)
    smc.set_relative_location(unreal.Vector(dist, 0, 0), False, False)
    smc.set_relative_rotation(plate_rot, False, False)
    smc.set_relative_scale3d(unreal.Vector(width / 100.0, width * 9 / 16 / 100.0, 1.0))

spout = eas.spawn_actor_from_class(bp.generated_class(), unreal.Vector(0, 0, -200))
spout.set_actor_label("SpoutInputs")
spout.set_folder_path("Core")

# Zoom check markers (unlit cubes): a tight cross at 30 m that stays in frame up to ~x20,
# and a wide ring that is only visible near full wide.
cube = unreal.load_asset("/Engine/BasicShapes/Cube")
markers = [("Marker_C", 3000, 0, 0, 15, "Orange")]
markers += [(f"Marker_N{i}", 3000, y, z, 8, "Cyan") for i, (y, z) in enumerate([(60, 0), (-60, 0), (0, 35), (0, -35)])]
markers += [(f"Marker_W{i}", 3000, y, z, 60, "Orange") for i, (y, z) in enumerate([(1200, 600), (-1200, 600), (1200, -600), (-1200, -600)])]
for label, x, y, z, size, color in markers:
    m = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, z))
    m.set_actor_label(label)
    m.set_folder_path("Test")
    smc = m.static_mesh_component
    smc.set_static_mesh(cube)
    smc.set_material(0, marker_mis[f"MI_Zoom_Marker_{color}"])
    smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    smc.set_editor_property("cast_shadow", False)
    m.set_actor_scale3d(unreal.Vector(size / 100.0, size / 100.0, size / 100.0))
    m.set_actor_hidden_in_game(not MARKERS_IN_GAME)

# Pillar: unlit with a fixed fake light (no scene lights needed, video plates stay untouched).
# Walk-through: where the person is less than PassBand behind the pillar, the pillar fades
# (translucent) so the person seeps through instead of popping out. See zoom_video.py.
pm = build_pillar_material(get_or_create("M_Zoom_Pillar", TEST, unreal.Material, unreal.MaterialFactoryNew()), rt_out, mpc)

px, py, pd = PILLAR
pillar = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(px, py, 0))
pillar.set_actor_label("Pillar")
pillar.set_folder_path("Objects")
smc = pillar.static_mesh_component
smc.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cylinder"))
smc.set_material(0, pm)
smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
smc.set_editor_property("cast_shadow", False)
pillar.set_actor_scale3d(unreal.Vector(pd / 100.0, pd / 100.0, 20.0))   # 20 m tall, crosses the frame

les.save_current_level()
unreal.log_warning(f"ZOOM_SETUP ok: camera hfov={math.degrees(hfov):.2f} deg, plates={len(PLATES)}, "
                   f"markers={len(markers)}, pillar at {PILLAR[0]:.0f} cm")
