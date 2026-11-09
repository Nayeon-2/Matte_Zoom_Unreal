"""Shared by setup_zoom_stage.py and apply_video_quality.py: how the Spout video is shown.

Video plates: the render target holds sRGB bytes (Spout copy, RGBA8, read with a linear
sampler). They are decoded with the exact sRGB curve (not pow 2.2) and sampled at the exact
screen pixel (ScreenPosition.ViewportUV): every plate is fitted to fill the frame, so screen
UV = video UV and no resampling of the plane's UV can soften the picture.

Camera: everything that would change the video is neutral (manual exposure 0, tone curve 0,
no bloom/vignette/grain/flare/fringe, local exposure contrast 1, no motion blur).
"""
import unreal

mel = unreal.MaterialEditingLibrary
assets = unreal.EditorAssetLibrary

SRGB_DECODE = ("float3 x = max(c, 0.0);\n"
               "return lerp(pow((x + 0.055) / 1.055, 2.4), x / 12.92, step(x, 0.04045));")

CAMERA_NEUTRAL = [
    ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL), ("auto_exposure_bias", 0.0),
    ("auto_exposure_apply_physical_camera_exposure", False), ("tone_curve_amount", 0.0),
    ("expand_gamut", 0.0), ("blue_correction", 0.0), ("vignette_intensity", 0.0),
    ("bloom_intensity", 0.0), ("film_grain_intensity", 0.0), ("motion_blur_amount", 0.0),
    ("scene_fringe_intensity", 0.0), ("lens_flare_intensity", 0.0),
    ("local_exposure_highlight_contrast_scale", 1.0), ("local_exposure_shadow_contrast_scale", 1.0),
    ("local_exposure_detail_strength", 1.0),
]


def build_video_material(m, rt, cutout):
    """Unlit video: exact sRGB -> linear x VideoGain at screen pixels.

    cutout (person plate): Masked on the matte alpha. The plate then writes depth where the
    person is, so objects in front/behind it are sorted per pixel (F / G / walk-through), and the
    rest of the plate (the matte RGB carries the whole source picture) is discarded. Translucent
    would draw the whole source picture over anything behind the plate."""
    mel.delete_all_material_expressions(m)
    m.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED if cutout else unreal.BlendMode.BLEND_OPAQUE)
    m.set_editor_property("two_sided", True)
    scr = mel.create_material_expression(m, unreal.MaterialExpressionScreenPosition, -1000, 0)
    tex = mel.create_material_expression(m, unreal.MaterialExpressionTextureSampleParameter2D, -800, 0)
    tex.set_editor_property("parameter_name", "Video")
    tex.set_editor_property("texture", rt)
    tex.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    mel.connect_material_expressions(scr, "ViewportUV", tex, "UVs")
    dec = mel.create_material_expression(m, unreal.MaterialExpressionCustom, -500, 0)
    dec.set_editor_property("code", SRGB_DECODE)
    dec.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    dec.set_editor_property("description", "sRGB decode")
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", "c")
    dec.set_editor_property("inputs", [ci])
    mel.connect_material_expressions(tex, "RGB", dec, "c")
    gain = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -500, 150)
    gain.set_editor_property("parameter_name", "VideoGain")
    gain.set_editor_property("default_value", 1.0)
    mul = mel.create_material_expression(m, unreal.MaterialExpressionMultiply, -250, 0)
    mel.connect_material_expressions(dec, "", mul, "A")
    mel.connect_material_expressions(gain, "", mul, "B")
    mel.connect_material_property(mul, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    if cutout:
        m.set_editor_property("opacity_mask_clip_value", 0.3333)
        mel.connect_material_property(tex, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
    mel.recompile_material(m)
    assets.save_loaded_asset(m)
    return m


# Walk-through: the object fades only where the person (matte alpha at this screen pixel) stands
# behind it within PassBand, fully at the object's depth, not at all PassBand behind. When the
# person is in front, nothing is hidden: the person plate (masked, writes depth) covers the object.
PASS_OPACITY = ("float b = pd - px;\n"
                "float n = b > 0 ? 1 - smoothstep(0, band, b) : 0;\n"
                "return 1 - a * n;")


def build_pillar_material(pm, rt, mpc):
    """Unlit object with a fixed fake light, translucent walk-through (no dither: needs no TSR)."""
    mel.delete_all_material_expressions(pm)
    pm.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    pm.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    pcol = mel.create_material_expression(pm, unreal.MaterialExpressionVectorParameter, -700, -100)
    pcol.set_editor_property("parameter_name", "Color")
    pcol.set_editor_property("default_value", unreal.LinearColor(0.75, 0.72, 0.68, 1.0))
    nrm = mel.create_material_expression(pm, unreal.MaterialExpressionVertexNormalWS, -900, 100)
    ldir = mel.create_material_expression(pm, unreal.MaterialExpressionConstant3Vector, -900, 250)
    ldir.set_editor_property("constant", unreal.LinearColor(-0.6, -0.5, 0.62, 0))   # from camera-left, above
    dot = mel.create_material_expression(pm, unreal.MaterialExpressionDotProduct, -700, 150)
    sat = mel.create_material_expression(pm, unreal.MaterialExpressionSaturate, -550, 150)
    amb = mel.create_material_expression(pm, unreal.MaterialExpressionScalarParameter, -700, 300)
    amb.set_editor_property("parameter_name", "Ambient")
    amb.set_editor_property("default_value", 0.25)
    one = mel.create_material_expression(pm, unreal.MaterialExpressionConstant, -700, 400)
    one.set_editor_property("r", 1.0)
    lerp = mel.create_material_expression(pm, unreal.MaterialExpressionLinearInterpolate, -400, 200)
    shade = mel.create_material_expression(pm, unreal.MaterialExpressionMultiply, -200, 0)
    mel.connect_material_expressions(nrm, "", dot, "A")
    mel.connect_material_expressions(ldir, "", dot, "B")
    mel.connect_material_expressions(dot, "", sat, "")
    mel.connect_material_expressions(amb, "", lerp, "A")
    mel.connect_material_expressions(one, "", lerp, "B")
    mel.connect_material_expressions(sat, "", lerp, "Alpha")
    mel.connect_material_expressions(pcol, "", shade, "A")
    mel.connect_material_expressions(lerp, "", shade, "B")
    mel.connect_material_property(shade, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    scr = mel.create_material_expression(pm, unreal.MaterialExpressionScreenPosition, -1300, 600)
    mat_a = mel.create_material_expression(pm, unreal.MaterialExpressionTextureSample, -1100, 600)
    mat_a.set_editor_property("texture", rt)
    mat_a.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    mel.connect_material_expressions(scr, "ViewportUV", mat_a, "UVs")
    pdepth = mel.create_material_expression(pm, unreal.MaterialExpressionCollectionParameter, -1300, 800)
    pdepth.set_editor_property("collection", mpc)
    pdepth.set_editor_property("parameter_name", "PersonDepth")
    band = mel.create_material_expression(pm, unreal.MaterialExpressionCollectionParameter, -1300, 900)
    band.set_editor_property("collection", mpc)
    band.set_editor_property("parameter_name", "PassBand")
    pix = mel.create_material_expression(pm, unreal.MaterialExpressionPixelDepth, -1300, 1000)
    op = mel.create_material_expression(pm, unreal.MaterialExpressionCustom, -800, 800)
    op.set_editor_property("code", PASS_OPACITY)
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
    mel.recompile_material(pm)
    assets.save_loaded_asset(pm)
    return pm


def neutral_post_process(pp):
    for prop, val in CAMERA_NEUTRAL:
        pp.set_editor_property("override_" + prop, True)
        pp.set_editor_property(prop, val)
    return pp
