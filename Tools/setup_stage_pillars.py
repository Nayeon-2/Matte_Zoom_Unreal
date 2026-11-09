"""Matte_Zoom_3: the MAMA stage model seen from one SketchUp camera, and pillars standing on the stage.

Run after setup_zoom_stage.py (this project is a copy of Matte_Zoom, where it already ran) and
extract_stage_fbx.py (Tools/stage_src/<stage fbx>).
Safe to run again (rebuilds what it owns, and replaces the stage meshes). Headless, editor closed:
  UnrealEditor-Cmd.exe Matte_Zoom_3.uproject -run=pythonscript -script="<this file>"
or inside the editor: Output Log > Python > py "<this file>"

Scene units are real centimeters with the camera at the origin looking down +X (fixed shot, no
zoom). The stage model hangs off StageRoot, which is moved and turned so that the chosen camera
(CAMERAS[CAMERA]: eye and target in SketchUp meters, horizontal FOV) lands on the origin.
Pillars are given in SketchUp stage coordinates per camera and stand on the stage top.
"""
import importlib
import math
import os
import sys
import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zoom_video  # noqa: E402
importlib.reload(zoom_video)   # the editor keeps modules between runs

CORE, STAGE = "/Game/Zoom/Core", "/Game/Stage"
MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
SENSOR_W = 9.59
TOOLS = os.path.dirname(os.path.abspath(__file__))
STAGE_FBX = os.path.join(TOOLS, "stage_src", "MAMA_stage_1655.fbx")   # 261027_1655 drawing
CAMERA = os.environ.get("STAGE_CAMERA", "CAM12")
def vfov_to_hfov(vfov, aspect=16.0 / 9.0):
    """SketchUp scene cameras give the vertical FOV (fov_is_height); Unreal wants the horizontal one."""
    return math.degrees(2.0 * math.atan(math.tan(math.radians(vfov) / 2.0) * aspect))


# Scene cameras read from the SketchUp model with the Ruby console:
#   Sketchup.active_model.pages.each{|p| c=p.camera; puts p.name, c.eye.to_a.map(&:to_m), c.target.to_a.map(&:to_m), c.fov}
CAMERAS = {  # eye / target: SketchUp meters (X, Y, Z; Z = height above the arena floor); hfov deg
    "CAM2": dict(eye=(0.01, 44.33, 2.89), target=(0.02, 23.82, 3.73), hfov=vfov_to_hfov(10.0), ref="CAM2_ref.png",
                 pillars=[  # label, SketchUp X m, SketchUp Y m, diameter cm, height cm
                     ("StagePillar_FL", 4.0, 3.0, 100.0, 420.0), ("StagePillar_FR", -4.0, 3.0, 100.0, 420.0),
                     ("StagePillar_BL", 6.0, -4.0, 120.0, 600.0), ("StagePillar_BR", -6.0, -4.0, 120.0, 600.0)]),
    "CAM12": dict(eye=(40.46, -0.02, 3.18), target=(-72.14, 0.07, 6.85), hfov=vfov_to_hfov(15.0), ref=None,
                  pillars=[
                      ("StagePillar_FL", 3.0, -4.0, 100.0, 420.0), ("StagePillar_FR", 3.0, 4.0, 100.0, 420.0),
                      ("StagePillar_BL", -4.0, -6.0, 120.0, 600.0), ("StagePillar_BR", -4.0, 6.0, 120.0, 600.0)]),
}
CAM = CAMERAS[CAMERA]
REF_IMAGE = os.path.join(TOOLS, "ref", CAM["ref"]) if CAM["ref"] else None
USE_REF_BG = REF_IMAGE is not None   # background plate shows the camera's reference image instead of RVM_BG
STAGE_IN_GAME = os.environ.get("STAGE_IN_GAME", "0") == "1"   # stage model is an editor-only guide
OLD_PILLARS_IN_GAME = False   # Matte_Zoom's Pillar/2/3 sit a few meters from the lens and fill the frame
REF_HFOV = CAM["hfov"]
STAGE_TOP = 213.0          # cm, main stage deck above the arena floor

# SketchUp (m) -> imported stage mesh frame (cm): (-Y, -X, Z) (see extract_stage_fbx.py), then the
# camera eye to the origin and its view direction to +X.
_eye = unreal.Vector(-CAM["eye"][1] * 100, -CAM["eye"][0] * 100, CAM["eye"][2] * 100)
_tgt = unreal.Vector(-CAM["target"][1] * 100, -CAM["target"][0] * 100, CAM["target"][2] * 100)
_dir = _tgt - _eye
CAM_YAW = math.degrees(math.atan2(_dir.y, _dir.x))                       # of the view in the mesh frame
CAM_PITCH = math.degrees(math.atan2(_dir.z, math.hypot(_dir.x, _dir.y)))  # negative = looking down


def su_to_scene(x, y, z):
    """SketchUp meters -> this scene (cm, camera at the origin looking down +X)."""
    sx, sy, sz = -y * 100 - _eye.x, -x * 100 - _eye.y, z * 100 - _eye.z
    c, s = math.cos(math.radians(CAM_YAW)), math.sin(math.radians(CAM_YAW))
    return unreal.Vector(c * sx + s * sy, -s * sx + c * sy, sz)


STAGE_ORIGIN = su_to_scene(0.0, 0.0, 0.0)   # SketchUp origin (stage center, arena floor) in this scene
FLOOR_Z = STAGE_ORIGIN.z + STAGE_TOP
PERSON_DEPTH = math.hypot(STAGE_ORIGIN.x, STAGE_ORIGIN.y)   # person plate depth until a distance arrives
CUE_FRONT, CUE_BACK = PERSON_DEPTH - 500.0, PERSON_DEPTH + 700.0   # F / G: in front of / behind all pillars
PILLARS = CAM["pillars"]

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


# ---------- camera reference image (raw bytes like the Spout RT: sRGB off, M_Zoom_BG applies the gamma) ----------
ref_mi = None
if USE_REF_BG:
    tex_name = "T_" + os.path.splitext(CAM["ref"])[0]
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", REF_IMAGE)
    task.set_editor_property("destination_path", f"{STAGE}/Ref")
    task.set_editor_property("destination_name", tex_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    tools.import_asset_tasks([task])
    tex = assets.load_asset(f"{STAGE}/Ref/{tex_name}")
    tex.set_editor_property("srgb", False)
    tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
    tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    assets.save_loaded_asset(tex)

    ref_mi = get_or_create("MI_Stage_RefBG", f"{STAGE}/Ref", unreal.MaterialInstanceConstant,
                           unreal.MaterialInstanceConstantFactoryNew())
    ref_mi.set_editor_property("parent", assets.load_asset(f"{CORE}/M_Zoom_BG"))
    mel.set_material_instance_texture_parameter_value(ref_mi, "Video", tex)
    assets.save_loaded_asset(ref_mi)

# ---------- MAMA stage model (reference geometry: translucent, no collision) ----------
# Replace, not merge: meshes from an earlier export must not linger.
if assets.does_directory_exist(f"{STAGE}/MAMA"):
    assets.delete_directory(f"{STAGE}/MAMA")
task = unreal.AssetImportTask()
task.set_editor_property("filename", STAGE_FBX)
task.set_editor_property("destination_path", f"{STAGE}/MAMA")
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", True)
tools.import_asset_tasks([task])
stage_meshes = [m for m in (assets.load_asset(p) for p in assets.list_assets(f"{STAGE}/MAMA", recursive=True))
                if isinstance(m, unreal.StaticMesh)]
# The import turns Nanite on, but the guide material is translucent, which Nanite cannot draw
# (map check: "missing Used with Nanite"). The meshes are small, so plain static meshes.
for m in stage_meshes:
    ns = m.get_editor_property("nanite_settings")
    if ns.get_editor_property("enabled"):
        ns.set_editor_property("enabled", False)
        m.set_editor_property("nanite_settings", ns)   # notifies the change: the mesh is rebuilt
        assets.save_loaded_asset(m)

sm_ref = get_or_create("M_Stage_Ref", STAGE, unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(sm_ref)
sm_ref.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
sm_ref.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
sm_ref.set_editor_property("two_sided", True)
ref_col = mel.create_material_expression(sm_ref, unreal.MaterialExpressionVectorParameter, -300, 0)
ref_col.set_editor_property("parameter_name", "Color")
ref_col.set_editor_property("default_value", unreal.LinearColor(0.0, 0.9, 1.0, 1.0))
ref_op = mel.create_material_expression(sm_ref, unreal.MaterialExpressionScalarParameter, -300, 150)
ref_op.set_editor_property("parameter_name", "Opacity")
ref_op.set_editor_property("default_value", 0.25)
mel.connect_material_property(ref_col, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
mel.connect_material_property(ref_op, "", unreal.MaterialProperty.MP_OPACITY)
mel.recompile_material(sm_ref)
assets.save_loaded_asset(sm_ref)

# ---------- MPC: floor height ----------
mpc = get_or_create("MPC_Stage", STAGE, unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())


def mpc_scalar(name, value):
    sp = unreal.CollectionScalarParameter()
    sp.set_editor_property("parameter_name", name)
    sp.set_editor_property("default_value", value)
    return sp


mpc.set_editor_property("scalar_parameters", [mpc_scalar("FloorZ", FLOOR_Z)])
assets.save_loaded_asset(mpc)
mpc_zoom = assets.load_asset(f"{CORE}/MPC_Zoom")
rt_out = assets.load_asset(f"{CORE}/RT_RVM_OUTPUT")

# ---------- M_Stage_Pillar ----------
# Same look and translucent walk-through as M_Zoom_Pillar (zoom_video.py), plus:
#   floor: everything below FloorZ is cut away, so nothing shows under the (video) floor
#   contact: the bottom 80 cm is darkened a little so it sits on the floor
pm = get_or_create("M_Stage_Pillar", STAGE, unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(pm)
pm.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
pm.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)


def node(cls, x, y, **props):
    n = mel.create_material_expression(pm, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def const(v, x, y):
    return node(unreal.MaterialExpressionConstant, x, y, r=v)


def mpc_param(collection, name, x, y):
    return node(unreal.MaterialExpressionCollectionParameter, x, y, collection=collection, parameter_name=name)


def link(a, b, pin="", out=""):
    mel.connect_material_expressions(a, out, b, pin)


# world Z (includes the offset) and height above the floor
wpos = node(unreal.MaterialExpressionWorldPosition, -1700, 1300)
wz = node(unreal.MaterialExpressionComponentMask, -1500, 1300, r=False, g=False, b=True, a=False)
link(wpos, wz)
floor = mpc_param(mpc, "FloorZ", -1500, 1400)
above = node(unreal.MaterialExpressionSubtract, -1300, 1300)
link(wz, above, "A")
link(floor, above, "B")

# shading: fake key light x contact darkening
pcol = node(unreal.MaterialExpressionVectorParameter, -700, -100, parameter_name="Color",
            default_value=unreal.LinearColor(0.78, 0.76, 0.72, 1.0))
nrm = node(unreal.MaterialExpressionVertexNormalWS, -1100, 100)
ldir = node(unreal.MaterialExpressionConstant3Vector, -1100, 250, constant=unreal.LinearColor(-0.6, -0.5, 0.62, 0))
dot = node(unreal.MaterialExpressionDotProduct, -900, 150)
link(nrm, dot, "A")
link(ldir, dot, "B")
sat = node(unreal.MaterialExpressionSaturate, -750, 150)
link(dot, sat)
amb = node(unreal.MaterialExpressionScalarParameter, -900, 300, parameter_name="Ambient", default_value=0.3)
light = node(unreal.MaterialExpressionLinearInterpolate, -550, 200)
link(amb, light, "A")
link(const(1.0, -750, 400), light, "B")
link(sat, light, "Alpha")
contact_k = node(unreal.MaterialExpressionDivide, -1100, 1150)
link(above, contact_k, "A")
link(const(80.0, -1300, 1200), contact_k, "B")
contact_s = node(unreal.MaterialExpressionSaturate, -950, 1150)
link(contact_k, contact_s)
contact = node(unreal.MaterialExpressionLinearInterpolate, -750, 1100)
link(const(0.35, -950, 1050), contact, "A")
link(const(1.0, -950, 1100), contact, "B")
link(contact_s, contact, "Alpha")
lit = node(unreal.MaterialExpressionMultiply, -350, 100)
link(light, lit, "A")
link(contact, lit, "B")
shade = node(unreal.MaterialExpressionMultiply, -200, 0)
link(pcol, shade, "A")
link(lit, shade, "B")
mel.connect_material_property(shade, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

# walk-through (zoom_video.PASS_OPACITY): fades only where the person stands within PassBand behind
scr = node(unreal.MaterialExpressionScreenPosition, -1500, 600)
mat_a = node(unreal.MaterialExpressionTextureSample, -1300, 600, texture=rt_out,
             sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
link(scr, mat_a, "UVs", "ViewportUV")
pdepth = mpc_param(mpc_zoom, "PersonDepth", -1500, 800)
band = mpc_param(mpc_zoom, "PassBand", -1500, 900)
pix = node(unreal.MaterialExpressionPixelDepth, -1500, 1000)
pass_op = node(unreal.MaterialExpressionCustom, -1000, 800, code=zoom_video.PASS_OPACITY,
               output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT1, description="walk-through opacity")
ins = []
for n in ("a", "pd", "px", "band"):
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", n)
    ins.append(ci)
pass_op.set_editor_property("inputs", ins)
mel.connect_material_expressions(mat_a, "A", pass_op, "a")
link(pdepth, pass_op, "pd")
link(pix, pass_op, "px")
link(band, pass_op, "band")

# floor cut: 0 below FloorZ, 1 above (1 mm ramp)
cut_k = node(unreal.MaterialExpressionMultiply, -1100, 1300)
link(above, cut_k, "A")
link(const(10.0, -1300, 1400), cut_k, "B")
cut = node(unreal.MaterialExpressionSaturate, -950, 1300)
link(cut_k, cut)
opacity = node(unreal.MaterialExpressionMultiply, -300, 900)
link(pass_op, opacity, "A")
link(cut, opacity, "B")
mel.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
mel.recompile_material(pm)
assets.save_loaded_asset(pm)

# ---------- level ----------
les.load_level(MAP_PATH)
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith(("StagePillar_", "StageRoot", "MAMA_")):
        eas.destroy_actor(a)
    elif a.get_actor_label().startswith("Pillar"):
        a.set_actor_hidden_in_game(not OLD_PILLARS_IN_GAME)
unreal.SystemLibrary.collect_garbage()

# Move/turn StageRoot to re-align the whole stage (a mesh-less StaticMeshActor: a plain Actor has no transform)
stage_rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=-CAM_YAW)
root = eas.spawn_actor_from_class(unreal.StaticMeshActor, STAGE_ORIGIN, stage_rot)
root.set_actor_label("StageRoot")
root.set_folder_path("Stage")
for mesh in stage_meshes:
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, STAGE_ORIGIN, stage_rot)
    a.set_actor_label("MAMA_" + mesh.get_name().removeprefix("SM_"))
    a.set_folder_path("Stage/MAMA")
    smc = a.static_mesh_component
    smc.set_static_mesh(mesh)
    for i in range(smc.get_num_materials()):
        smc.set_material(i, sm_ref)
    smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    smc.set_editor_property("cast_shadow", False)
    a.set_actor_hidden_in_game(not STAGE_IN_GAME)
    a.attach_to_actor(root, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                      unreal.AttachmentRule.KEEP_WORLD, False)

cam = next(a for a in eas.get_all_level_actors() if a.get_actor_label() == "ZoomCamera")
cam.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=CAM_PITCH, yaw=0.0), False)
cam.set_editor_property("wide_focal_length", (SENSOR_W / 2) / math.tan(math.radians(REF_HFOV) / 2))
cam.set_editor_property("default_person_depth", PERSON_DEPTH)
cam.set_editor_property("cue_front_depth", CUE_FRONT)
cam.set_editor_property("cue_back_depth", CUE_BACK)
cam.set_editor_property("max_person_depth", 20000.0)
cam.apply_scale(1.0)          # focal = wide focal, plates re-fitted to the new field of view
cam.apply_person_depth(PERSON_DEPTH)

bg = next(a for a in eas.get_all_level_actors() if a.get_actor_label() == "Plate_BG")
bg.static_mesh_component.set_material(0, ref_mi or assets.load_asset(f"{CORE}/M_Zoom_BG"))

cyl = unreal.load_asset("/Engine/BasicShapes/Cylinder")   # 100 cm tall, pivot at the center
for label, su_x, su_y, dia, h in PILLARS:
    loc = su_to_scene(su_x, su_y, 0.0)
    loc.z = FLOOR_Z + h / 2
    p = eas.spawn_actor_from_class(unreal.StaticMeshActor, loc)
    p.set_actor_label(label)
    p.set_folder_path("Stage")
    smc = p.static_mesh_component
    smc.set_static_mesh(cyl)
    smc.set_material(0, pm)
    smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    smc.set_editor_property("cast_shadow", False)
    p.set_actor_scale3d(unreal.Vector(dia / 100.0, dia / 100.0, h / 100.0))

les.save_current_level()
if assets.does_directory_exist(f"{STAGE}/Pillars"):   # per-pillar rise instances from an earlier version
    assets.delete_directory(f"{STAGE}/Pillars")
unreal.log_warning(f"STAGE_SETUP ok: camera={CAMERA} yaw={CAM_YAW:.1f} pitch={CAM_PITCH:.1f} "
                   f"stage origin={STAGE_ORIGIN} hfov={cam.get_horizontal_fov():.2f} deg, floor={FLOOR_Z:.0f} cm, "
                   f"pillars={len(PILLARS)}, stage meshes={len(stage_meshes)} "
                   f"{[m.get_name() for m in stage_meshes]}, ref_bg={USE_REF_BG}")
for m in stage_meshes:
    unreal.log_warning(f"STAGE_MESH {m.get_name()} nanite={m.get_editor_property('nanite_settings').enabled}")
