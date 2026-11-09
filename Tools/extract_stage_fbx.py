"""Pull the stage groups out of the full SketchUp FBX export into a small FBX for Unreal.

The SketchUp export is ASCII FBX (Blender cannot import it), Y-up, and its numbers are millimeters
although the header says centimeters. This reads it as text, keeps only the top-level groups in
KEEP, and writes a binary FBX through Blender in meters, rotated so the stage reads in Unreal as:
  Unreal X = SketchUp -Y (toward the back of the stage), Unreal Y = SketchUp -X, Z up,
  pivot = SketchUp origin (stage center, arena floor). One mesh per group.

  blender -b --factory-startup --python extract_stage_fbx.py -- <in.fbx> <out.fbx>
With LIST_GROUPS=1 it only prints every top-level group (vertex count, bounds) to find KEEP names.
"""
import math
import os
import re
import sys

import bpy
import numpy as np

KEEP = {  # top-level SketchUp groups (Outliner names) -> mesh name in Unreal
    # Group numbers change on every export: match a new export against the previous one with
    # LIST_GROUPS=1 (same bounds = same part). This is the 261027_1655 export.
    # Gone since the 261014_1305 cam12 export: the raised LED lift, the telescopic tower, the arena floor.
    "Group822": "SM_Stage_Main",           # main stage decks, stairs, ramps (was Group1404; one end 27 -> 24.3 m)
    "Group3924": "SM_Stage_Lifts",         # 2.5 m lifts in the middle (was Group4619)
    "Group4000": "SM_Stage_LiftBack",      # 13 x 5 m lift/LED floor at the back (was Group823; moved 1.8 m)
    "Group818": "SM_Stage_LEDFront",       # 10.76 x 2.5 m LED floor at the front (was Group947)
    "Group750": "SM_Stage_FrontDeck",      # (was Group819)
    "Main_SFX_Deck1": "SM_Stage_SFXDeck",
    "Group4069": "SM_Stage_SideDeck",      # new: 12 x 11 m deck next to the LED floor (SketchUp Y 18.9..30.3)
    "Group4569": "SM_Stage_Extra",         # new: low structures up to 3.4 m around the stage (SketchUp Y -25.6..66.9)
    "Man_1_1": "SM_Ref_Person",            # 1.8 m figure at the stage center
}

src, out = sys.argv[sys.argv.index("--") + 1:][:2]
rm = re.compile(r'^\s*Model: (\d+), "Model::(.*)", "(\w*)"')
rg = re.compile(r'^\s*Geometry: (\d+), "Geometry::(.*)", "(\w*)"')
rc = re.compile(r'^\s*C: "OO",(\d+),(\d+)')
rp = re.compile(r'^\s*P: "(Lcl Translation|Lcl Rotation|Lcl Scaling|GeometricTranslation|GeometricRotation|'
                r'GeometricScaling|PreRotation)", [^,]*, [^,]*, "[^"]*",([-\d.e+]+),([-\d.e+]+),([-\d.e+]+)')
models, geoms, conns = {}, {}, []
cur_m = cur_g = None
array_key, buf = None, []
with open(src, encoding="utf-8", errors="replace") as f:
    for line in f:
        if array_key:
            buf.append(line)
            if "}" in line:
                s = "".join(buf)
                s = s[s.index("a:") + 2:s.index("}")]
                geoms[cur_g][array_key] = s
                array_key, buf = None, []
            continue
        m = rm.match(line)
        if m:
            cur_m, cur_g = m[1], None
            models[cur_m] = {"name": m[2], "P": {}}
            continue
        m = rg.match(line)
        if m:
            cur_g, cur_m = m[1], None
            geoms[cur_g] = {}
            continue
        if cur_g:
            key = line.lstrip().split(":")[0]
            if key in ("Vertices", "PolygonVertexIndex") and "*" in line:
                array_key, buf = key, [line]
                if "}" in line:
                    geoms[cur_g][key] = line[line.index("a:") + 2:line.index("}")]
                    array_key, buf = None, []
                continue
        if cur_m:
            m = rp.match(line)
            if m:
                models[cur_m]["P"][m[1]] = tuple(float(m[i]) for i in (2, 3, 4))
        m = rc.match(line)
        if m:
            conns.append((m[1], m[2]))

parent, geo_of = {}, {}
for c, p in conns:
    if c in models and (p in models or p == "0"):
        parent[c] = p
    if c in geoms and p in models:
        geo_of.setdefault(p, []).append(c)


def rot(r):
    x, y, z = (math.radians(a) for a in r)
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx          # FBX eEulerXYZ


def local(p):
    m = np.eye(4)
    r = rot(p.get("Lcl Rotation", (0, 0, 0)))
    if "PreRotation" in p:
        r = rot(p["PreRotation"]) @ r
    m[:3, :3] = r @ np.diag(p.get("Lcl Scaling", (1, 1, 1)))
    m[:3, 3] = p.get("Lcl Translation", (0, 0, 0))
    return m


world_cache = {}


def world(mid):
    if mid not in world_cache:
        p = parent.get(mid, "0")
        world_cache[mid] = (world(p) if p in models else np.eye(4)) @ local(models[mid]["P"])
    return world_cache[mid]


def top_group(mid):
    chain = []
    while mid in models:
        chain.append(models[mid]["name"])
        mid = parent.get(mid, "0")
    return chain[-2] if len(chain) >= 2 else None   # chain[-1] is the SketchUp "Model" root


# FBX (Y-up, mm) -> SketchUp (Z-up, m) -> export frame (x = -Y_su, y = X_su, z = Z_su).
# Blender's FBX export + Unreal's import mirror y, giving Unreal (x, y, z) = (-Y_su, -X_su, Z_su).
to_su = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]) / 1000.0
to_out = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) @ to_su

if os.environ.get("LIST_GROUPS"):
    # Every top-level group with its size and bounds (SketchUp m): group numbers change on every
    # export, so the new KEEP names are found by matching these against the previous export.
    stats = {}
    for mid, gids in geo_of.items():
        grp = top_group(mid)
        if grp is None:
            continue
        m = world(mid)
        for gid in gids:
            if "Vertices" not in geoms[gid]:
                continue
            v = np.array(geoms[gid]["Vertices"].replace("\n", "").split(","), dtype=np.float64).reshape(-1, 3)
            v = (v @ m[:3, :3].T + m[:3, 3]) @ to_su.T
            n, lo, hi = stats.get(grp, (0, np.full(3, np.inf), np.full(3, -np.inf)))
            stats[grp] = (n + len(v), np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0)))
    for grp, (n, lo, hi) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
        print(f"STAGE_GROUP {grp}\t{n}\tmin {lo.round(2).tolist()}\tmax {hi.round(2).tolist()}")
    sys.exit(0)

parts = {name: ([], []) for name in KEEP.values()}
for mid, gids in geo_of.items():
    grp = top_group(mid)
    if grp not in KEEP:
        continue
    p = models[mid]["P"]
    g = np.eye(4)
    g[:3, :3] = rot(p.get("GeometricRotation", (0, 0, 0))) @ np.diag(p.get("GeometricScaling", (1, 1, 1)))
    g[:3, 3] = p.get("GeometricTranslation", (0, 0, 0))
    m = world(mid) @ g
    verts_out, faces_out = parts[KEEP[grp]]
    for gid in gids:
        gd = geoms[gid]
        if "Vertices" not in gd or "PolygonVertexIndex" not in gd:
            continue
        v = np.array(gd["Vertices"].replace("\n", "").split(","), dtype=np.float64).reshape(-1, 3)
        v = (v @ m[:3, :3].T + m[:3, 3]) @ to_out.T
        base = sum(len(x) for x in verts_out)
        verts_out.append(v)
        poly = []
        for i in map(int, gd["PolygonVertexIndex"].replace("\n", "").split(",")):
            if i < 0:
                poly.append(~i + base)
                faces_out.append(poly)
                poly = []
            else:
                poly.append(i + base)

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, (vl, fl) in parts.items():
    if not vl:
        print("STAGE_EXTRACT missing", name)
        continue
    verts = np.concatenate(vl)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], fl)
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    lo, hi = verts.min(0), verts.max(0)
    print(f"STAGE_EXTRACT {name}: {len(verts)} verts {len(fl)} faces  min {lo.round(2)} max {hi.round(2)} m")
bpy.ops.export_scene.fbx(filepath=out, use_selection=False, object_types={"MESH"}, mesh_smooth_type="FACE",
                         add_leaf_bones=False, bake_anim=False)
print("STAGE_EXTRACT wrote", out)
