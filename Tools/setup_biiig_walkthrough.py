"""Give the BIIG text the walk-through material, so the person seeps through it on F / G
instead of popping: it fades where the person is less than PassBand behind it (zoom_video.PASS_OPACITY).

- M_Biiig: lit translucent (the level's lights, forward shaded per pixel), Color / Roughness
  parameters, opacity = walk-through only. No shadows (translucent).
- Nanite off on the BIIG meshes (translucent materials do not render on Nanite).
- ZoomCamera: CueMoveTime / PassBand set below (both also editable in its Details panel).

Headless, editor closed:
  UnrealEditor-Cmd.exe Matte_Zoom_3.uproject -run=pythonscript -script="<this file>"
"""
import os
import sys
import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zoom_video  # noqa: E402

MAP_PATH = "/Game/Zoom/Maps/Zoom_Stage"
MATCH = "biiig"
COLOR = unreal.LinearColor(0.25, 0.25, 0.25, 1.0)   # base color (about the engine grid material): the level's lights shape it
ROUGHNESS = 0.4
CUE_MOVE_TIME = 3.0   # s for every F / G / A change (was 1.5)
PASS_BAND = 300.0     # cm behind an object over which it fades (was 150): wider = softer, longer seep

assets = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(MAP_PATH)

m_path = "/Game/Stage/M_Biiig"
m = unreal.load_asset(m_path) if assets.does_asset_exist(m_path) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
    "M_Biiig", "/Game/Stage", unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(m)
m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
m.set_editor_property("blend_mode", getattr(unreal.BlendMode, os.environ.get("BIIG_BLEND", "BLEND_TRANSLUCENT")))
# lit by the level's own lights per pixel, like an opaque surface (the default volume lighting is blurry)
m.set_editor_property("translucency_lighting_mode",
                      getattr(unreal.TranslucencyLightingMode, os.environ.get("BIIG_TLM", "TLM_SURFACE_PER_PIXEL_LIGHTING")))
col = mel.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -400, 0)
col.set_editor_property("parameter_name", "Color")
col.set_editor_property("default_value", COLOR)
mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)
rough = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -400, 200)
rough.set_editor_property("parameter_name", "Roughness")
rough.set_editor_property("default_value", ROUGHNESS)
mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
# walk-through opacity, same nodes as zoom_video.build_pillar_material
scr = mel.create_material_expression(m, unreal.MaterialExpressionScreenPosition, -1300, 600)
mat_a = mel.create_material_expression(m, unreal.MaterialExpressionTextureSample, -1100, 600)
mat_a.set_editor_property("texture", unreal.load_asset("/Game/Zoom/Core/RT_RVM_OUTPUT"))
mat_a.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
mel.connect_material_expressions(scr, "ViewportUV", mat_a, "UVs")
mpc = unreal.load_asset("/Game/Zoom/Core/MPC_Zoom")
pdepth = mel.create_material_expression(m, unreal.MaterialExpressionCollectionParameter, -1300, 800)
pdepth.set_editor_property("collection", mpc)
pdepth.set_editor_property("parameter_name", "PersonDepth")
band = mel.create_material_expression(m, unreal.MaterialExpressionCollectionParameter, -1300, 900)
band.set_editor_property("collection", mpc)
band.set_editor_property("parameter_name", "PassBand")
pix = mel.create_material_expression(m, unreal.MaterialExpressionPixelDepth, -1300, 1000)
op = mel.create_material_expression(m, unreal.MaterialExpressionCustom, -800, 800)
op.set_editor_property("code", zoom_video.PASS_OPACITY)
op.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT1)
op.set_editor_property("description", "walk-through opacity")
ins = []
for n in ("a", "pd", "px", "band"):
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", n)
    ins.append(ci)
op.set_editor_property("inputs", ins)
mel.connect_material_expressions(mat_a, "A", op, "a")
mel.connect_material_expressions(pdepth, "", op, "pd")
mel.connect_material_expressions(pix, "", op, "px")
mel.connect_material_expressions(band, "", op, "band")
mel.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
mel.recompile_material(m)
assets.save_loaded_asset(m)
mi = m

actors = eas.get_all_level_actors()
done = []
for a in actors:
    if MATCH not in a.get_actor_label().lower():
        continue
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        mesh = c.static_mesh
        ns = mesh.get_editor_property("nanite_settings")
        if ns.enabled:
            ns.enabled = False
            mesh.set_editor_property("nanite_settings", ns)
            assets.save_loaded_asset(mesh)
        for i in range(c.get_num_materials()):
            c.set_material(i, mi)
        c.set_editor_property("cast_shadow", False)
        done.append(f"{a.get_actor_label()}({mesh.get_name()}, {c.get_num_materials()} slots)")

cam = next(a for a in actors if a.get_actor_label() == "ZoomCamera")
cam.set_editor_property("cue_move_time", CUE_MOVE_TIME)
cam.set_editor_property("pass_band", PASS_BAND)
les.save_current_level()
unreal.log_warning(f"BIIG_WALK ok: {done} cue_move_time={CUE_MOVE_TIME} pass_band={PASS_BAND} "
                   f"front={cam.get_editor_property('cue_front_depth'):.0f} back={cam.get_editor_property('cue_back_depth'):.0f}")
