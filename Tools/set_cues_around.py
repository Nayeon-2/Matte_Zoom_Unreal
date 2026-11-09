"""Set the F / G cue depths around an object (default: the BIIG text), so that F puts the person
plate in front of all of it and G behind all of it. Depths are measured along the ZoomCamera view.

Headless, editor closed (the level is saved):
  UnrealEditor-Cmd.exe Matte_Zoom_3.uproject -run=pythonscript -script="<this file>"
or in the editor (not while playing): py "<this file>". Actor labels / mesh names matched by
CUE_MATCH (comma separated, case-insensitive), default "biiig".
Run again after moving the object; setup_stage_pillars.py resets the cues to the pillars.
"""
import itertools
import os
import unreal

MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
MATCH = [m.strip().lower() for m in os.environ.get("CUE_MATCH", "biiig").split(",") if m.strip()]
MARGIN = 150.0   # cm clear of the object, at least the camera's PassBand (the walk-through fade never touches it)

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not unreal.EditorLevelLibrary.get_editor_world().get_path_name().startswith(MAP_PATH):
    les.load_level(MAP_PATH)
actors = eas.get_all_level_actors()
cam = next(a for a in actors if a.get_actor_label() == "ZoomCamera")


def names(a):
    out = [a.get_actor_label()]
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        if c.static_mesh:
            out.append(c.static_mesh.get_name())
    return " ".join(out).lower()


objs = [a for a in actors if a != cam and any(m in names(a) for m in MATCH)]
if not objs:
    raise RuntimeError(f"CUE no actor matches {MATCH}")
to_cam = cam.get_actor_transform()
near, far = float("inf"), float("-inf")
for a in objs:
    origin, ext = a.get_actor_bounds(False)
    d = [unreal.MathLibrary.inverse_transform_location(
            to_cam, unreal.Vector(origin.x + sx * ext.x, origin.y + sy * ext.y, origin.z + sz * ext.z)).x
         for sx, sy, sz in itertools.product((-1, 1), repeat=3)]
    unreal.log_warning(f"CUE_OBJ {a.get_actor_label()}: depth {min(d):.0f} .. {max(d):.0f} cm, "
                       f"hidden_in_game={a.is_hidden_ed() or a.get_editor_property('hidden')}")
    near, far = min(near, min(d)), max(far, max(d))

MARGIN = max(MARGIN, cam.get_editor_property("pass_band"))   # G must sit outside the fade band
front, back = max(near - MARGIN, 100.0), far + MARGIN
cam.set_editor_property("cue_front_depth", front)
cam.set_editor_property("cue_back_depth", back)
cam.set_editor_property("max_person_depth", max(cam.get_editor_property("max_person_depth"), back + 100.0))
les.save_current_level()
unreal.log_warning(f"CUE_SET front(F)={front:.0f} cm back(G)={back:.0f} cm "
                   f"(objects {near:.0f} .. {far:.0f} cm, {len(objs)} actors)")
