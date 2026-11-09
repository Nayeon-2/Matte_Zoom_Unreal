"""Matte_Zoom: build an empty stage level with one camera.

Run headless:
  UnrealEditor-Cmd.exe Matte_Zoom.uproject -run=pythonscript -script="<this file>"
"""
import unreal

MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
GM_DIR, GM_NAME = "/Game/Zoom/Core", "GM_Zoom"

assets = unreal.EditorAssetLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()

# Game mode with no pawn and no HUD: Play shows only the level camera.
gm_path = f"{GM_DIR}/{GM_NAME}"
if assets.does_asset_exist(gm_path):
    gm = assets.load_asset(gm_path)
else:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.GameModeBase)
    gm = tools.create_asset(GM_NAME, GM_DIR, unreal.Blueprint, factory)
cdo = unreal.get_default_object(gm.generated_class())
cdo.set_editor_property("default_pawn_class", None)
unreal.BlueprintEditorLibrary.compile_blueprint(gm)
assets.save_loaded_asset(gm)

# Empty, non-partitioned level.
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if assets.does_asset_exist(MAP_PATH):
    les.load_level(MAP_PATH)
else:
    les.new_level(MAP_PATH, False)

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "ZoomCamera":
        eas.destroy_actor(a)

cam = eas.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
cam.set_actor_label("ZoomCamera")
cam.set_folder_path("Core")
cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
cc = cam.get_cine_camera_component()
# 16:9 sensor; focal length is what zoom tracking will drive later.
fb = cc.get_editor_property("filmback")
fb.set_editor_property("sensor_width", 36.0)
fb.set_editor_property("sensor_height", 20.25)
cc.set_editor_property("filmback", fb)
cc.set_editor_property("current_focal_length", 20.0)
fs = cc.get_editor_property("focus_settings")
fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
cc.set_editor_property("focus_settings", fs)
# Video-faithful look: manual exposure 0 EV, no bloom/vignette/grain.
pp = cc.get_editor_property("post_process_settings")
for prop, val in [
    ("override_auto_exposure_method", True), ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL),
    ("override_auto_exposure_apply_physical_camera_exposure", True), ("auto_exposure_apply_physical_camera_exposure", False),
    ("override_auto_exposure_bias", True), ("auto_exposure_bias", 0.0),
    ("override_bloom_intensity", True), ("bloom_intensity", 0.0),
    ("override_vignette_intensity", True), ("vignette_intensity", 0.0),
    ("override_film_grain_intensity", True), ("film_grain_intensity", 0.0),
]:
    pp.set_editor_property(prop, val)
cc.set_editor_property("post_process_settings", pp)

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
ws = world.get_world_settings()
ws.set_editor_property("default_game_mode", gm.generated_class())

les.save_current_level()
unreal.log("Zoom_Stage ready")
