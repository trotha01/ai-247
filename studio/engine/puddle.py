"""Puddle Park scene builder for Blender (run headless).

The producer writes a short SCENE SCRIPT (JSON). This file is the fixed template library
that turns it into a rendered clip: felt puppets, the Puddle Park set, props, numerals and
letters, plus a small action vocabulary. The LLM directs; it never writes Blender code.

  blender -b --python puddle.py -- scene.json out_dir/

Scene script:
{
  "seconds": 15, "fps": 30, "resolution": [1280, 720], "samples": 16,
  "cast": {"pip": {"template": "puppet", "color": "orange", "size": 1.0, "at": [-1.6, 0]}},
  "timeline": [
    {"t": 0.0, "do": "shot", "shot": "wide"},
    {"t": 0.5, "do": "say", "who": "pip", "dur": 2.0, "text": "Let's count apples!"},
    {"t": 3.0, "do": "spawn", "prop": "apple", "at": [0.2, -0.3, 0.95], "name": "a1"},
    {"t": 3.0, "do": "numeral", "text": "1", "at": [0, 0.6, 2.6], "dur": 1.4},
    {"t": 5.0, "do": "hop", "who": "pip"},
    {"t": 6.0, "do": "move", "who": "pip", "to": [0, 0], "dur": 1.0},
    {"t": 7.0, "do": "wave", "who": "pip", "dur": 1.5},
    {"t": 8.0, "do": "look", "who": "pip", "at": [1, -3, 1.5]}
  ]
}
Actions: shot (wide|medium|close:<who>), say, hop, move, wave, look, spawn, numeral (any short
text: digits, letters, shapes are separate props), bounce (a spawned prop).
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

COLORS = {
    "orange": (0.95, 0.42, 0.08), "green": (0.20, 0.62, 0.22), "purple": (0.50, 0.25, 0.75),
    "yellow": (0.98, 0.80, 0.18), "blue": (0.15, 0.45, 0.90), "red": (0.85, 0.12, 0.10),
    "pink": (0.95, 0.45, 0.65), "brown": (0.45, 0.28, 0.14), "white": (0.95, 0.95, 0.92),
    "black": (0.02, 0.02, 0.02), "sky": (0.55, 0.78, 0.98), "grass": (0.35, 0.72, 0.30),
}

# ---------------------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------------------
_mats = {}


def _set(bsdf, names, value):
    for n in names:
        if n in bsdf.inputs:
            bsdf.inputs[n].default_value = value
            return


def felt(color_name, rough=0.95, bump=0.35):
    """Felt/fleece look: rough, sheen, a little subsurface and a fine noise bump."""
    key = ("felt", color_name, rough, bump)
    if key in _mats:
        return _mats[key]
    rgb = COLORS.get(color_name, COLORS["white"]) if isinstance(color_name, str) else color_name
    m = bpy.data.materials.new(f"felt_{color_name}")
    m.diffuse_color = (*rgb, 1)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    _set(bsdf, ["Base Color"], (*rgb, 1))
    _set(bsdf, ["Roughness"], rough)
    _set(bsdf, ["Sheen Weight", "Sheen"], LOOK.get("sheen", 0.8))
    _set(bsdf, ["Sheen Roughness"], 0.6)
    _set(bsdf, ["Subsurface Weight", "Subsurface"], 0.05)
    if bump:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 180.0
        noise.inputs["Detail"].default_value = 8.0
        b = nt.nodes.new("ShaderNodeBump")
        b.inputs["Strength"].default_value = bump
        nt.links.new(noise.outputs["Fac"], b.inputs["Height"])
        nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
    _mats[key] = m
    return m


def glossy(color_name):
    key = ("gloss", color_name)
    if key in _mats:
        return _mats[key]
    m = bpy.data.materials.new(f"gloss_{color_name}")
    m.diffuse_color = (*COLORS[color_name], 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    _set(bsdf, ["Base Color"], (*COLORS[color_name], 1))
    _set(bsdf, ["Roughness"], 0.25)
    _mats[key] = m
    return m


def paint(rgb_top, rgb_bottom):
    """Painted backdrop: vertical gradient."""
    m = bpy.data.materials.new("painted_sky")
    m.diffuse_color = (*rgb_top, 1)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*rgb_bottom, 1)
    ramp.color_ramp.elements[1].color = (*rgb_top, 1)
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    _set(bsdf, ["Roughness"], 1.0)
    return m


# ---------------------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------------------
def sphere(name, loc, scale, mat, parent=None, seg=48):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    bpy.ops.object.shade_smooth()
    o.data.materials.append(mat)
    if parent:
        o.parent = parent
        o.matrix_parent_inverse = parent.matrix_world.inverted()
    return o


def cylinder(name, loc, r, depth, mat, rot=(0, 0, 0), verts=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    bpy.ops.object.shade_smooth()
    o.data.materials.append(mat)
    return o


def box(name, loc, size, mat, bevel=0.06):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        mod = o.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 4
    bpy.ops.object.shade_smooth()
    o.data.materials.append(mat)
    return o


def empty(name, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    return o


# ---------------------------------------------------------------------------------------
# templates: puppet, set, props
# ---------------------------------------------------------------------------------------
def _attach(obj, parent):
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    return obj


def _front(cy, r, dx, dz):
    """y of an ellipsoid's front surface (the side facing the camera, -y) at offsets dx, dz from its center."""
    k = 1 - (dx / r[0]) ** 2 - (dz / r[2]) ** 2
    return cy - r[1] * math.sqrt(max(k, 0.05))


# body shapes per kind: center height and radii (before size); face: eye height, eye spacing, eye radius, mouth drop
KINDS = {
    "blob": {"body": (0.85, (0.75, 0.68, 0.82)), "face": (1.18, 0.27, 0.20, 0.40)},
    "small": {"body": (0.62, (0.66, 0.60, 0.60)), "face": (0.80, 0.22, 0.19, 0.30)},
    "tall": {"body": (1.20, (0.56, 0.52, 1.16)), "face": (1.80, 0.20, 0.17, 0.42)},
    "bird": {"body": (0.98, (0.58, 0.54, 0.66)), "face": (1.20, 0.20, 0.17, 0.30)},
    "puppy": {"body": (0.60, (0.60, 0.55, 0.52)), "face": None},  # face sits on a separate head
}
DEFAULT_KIND = {"pip": "small", "bramble": "tall", "wren": "bird", "biscuit": "puppy"}


class Puppet:
    """Felt puppets with a silhouette per kind, so each reads without color:
    blob (round), small (squat, sprout on top), tall (egg shape, long hanging ears, shaggy top, round nose),
    bird (wings, beak, crest, tail feathers, thin legs), puppy (head on a body, snout and nose, floppy ears, tail).
    Every kind has the same animated parts: root (at floor level), body (squash), mouth, pupils, arm pivots."""

    def __init__(self, name, color="orange", size=1.0, at=(0, 0), ears=False, beak=False, kind=None):
        kind = kind or DEFAULT_KIND.get(name, "blob")
        s = size
        x, y = at
        self.name, self.size, self.kind = name, s, kind
        self.root = empty(f"{name}_root", (x, y, 0))
        fm = felt(color)
        bz, r = KINDS[kind]["body"]
        R = tuple(v * s for v in r)
        self.body = sphere(f"{name}_body", (x, y, bz * s), R, fm, self.root)
        self.body_base_scale = tuple(self.body.scale)
        white, black = glossy("white"), glossy("black")

        # face carrier: the body itself, or (puppy) a head on top of it
        if kind == "puppy":
            hz, hr = 1.30, (0.48, 0.44, 0.42)
            HR = tuple(v * s for v in hr)
            sphere(f"{name}_head", (x, y - 0.06 * s, hz * s), HR, fm, self.body)
            cy, cz, CR, ez, sp, er, mdrop = y - 0.06 * s, hz * s, HR, (hz + 0.11) * s, 0.16 * s, 0.14 * s, 0.36 * s
        else:
            fz, spc, err, md = KINDS[kind]["face"]
            cy, cz, CR, ez, sp, er, mdrop = y, bz * s, R, fz * s, spc * s, err * s, md * s

        self.pupils = []
        for side in (-1, 1):
            ey = _front(cy, CR, sp, ez - cz)
            sphere(f"{name}_eye{side}", (x + side * sp, ey, ez), (er,) * 3, white, self.body)
            pp = sphere(f"{name}_pupil{side}", (x + side * sp, ey - 0.85 * er, ez - 0.15 * er), (0.43 * er,) * 3, black, self.body)
            self.pupils.append((pp, Vector(pp.location)))
        mz = ez - mdrop
        my = _front(cy, CR, 0, mz - cz) + 0.02 * s
        self.mouth = sphere(f"{name}_mouth", (x, my, mz), (0.2 * s, 0.06 * s, 0.035 * s), felt((0.25, 0.03, 0.05), bump=0), self.body)
        self.mouth_closed = tuple(self.mouth.scale)
        self.mouth_off = Vector((0, my - y, mz))
        self.head_z = ez

        # arms (wings for the bird): an ellipsoid hanging from a shoulder pivot that wave/point rotate
        arm_len = {"tall": 0.42, "bird": 0.40, "small": 0.26, "puppy": 0.26}.get(kind, 0.32) * s
        sh_z = {"tall": bz + 0.30, "bird": bz + 0.15, "small": bz + 0.05, "puppy": bz + 0.15}.get(kind, 0.95) * s
        self.arms = []
        for side in (-1, 1):
            sx = x + side * (R[0] - 0.1 * s)
            pivot = empty(f"{name}_shoulder{side}", (sx, y - 0.05 * s, sh_z))
            _attach(pivot, self.body)
            if kind == "bird":
                arm = sphere(f"{name}_wing{side}", (sx + side * 0.12 * s, y + 0.05 * s, sh_z - arm_len * 0.55),
                             (0.07 * s, 0.30 * s, arm_len), fm, pivot)
                arm.rotation_euler = (0.25, side * -0.45, 0)
            else:
                arm = sphere(f"{name}_arm{side}", (sx + side * 0.2 * s, y - 0.05 * s, sh_z - arm_len * 0.7),
                             (0.13 * s, 0.13 * s, arm_len), fm, pivot)
                arm.rotation_euler = (0, side * -0.35, 0)
            self.arms.append((side, pivot))

        # feet (thin legs for the bird)
        bottom = (bz - r[2]) * s
        for side in (-1, 1):
            fx = x + side * 0.28 * R[0] / s * s
            if kind == "bird":
                leg = cylinder(f"{name}_leg{side}", (fx, y, bottom / 2 + 0.03), 0.035 * s, bottom, felt("orange", bump=0))
                _attach(leg, self.body)
                sphere(f"{name}_foot{side}", (fx, y - 0.1 * s, 0.04), (0.12 * s, 0.17 * s, 0.04 * s), felt("orange", bump=0), self.body)
            else:
                sphere(f"{name}_foot{side}", (fx, y - R[1] * 0.55, max(0.06 * s, bottom + 0.05 * s)),
                       (0.17 * s, 0.24 * s, 0.08 * s), felt("brown" if kind == "puppy" else color), self.body)

        top = (bz + r[2]) * s
        if kind == "small":  # a sprout: stem and two leaves
            stem = cylinder(f"{name}_stem", (x, y, top + 0.1 * s), 0.03 * s, 0.24 * s, felt("green", bump=0.1))
            _attach(stem, self.body)
            for side in (-1, 1):
                lf = sphere(f"{name}_leaf{side}", (x + side * 0.12 * s, y, top + 0.24 * s), (0.13 * s, 0.05 * s, 0.06 * s),
                            felt("green", bump=0.1), self.body)
                lf.rotation_euler = (0, side * -0.4, 0)
        elif kind == "tall":  # shaggy top, long hanging ears, round nose
            for i, (dx, dz) in enumerate([(-0.18, -0.05), (0, 0.02), (0.18, -0.05), (-0.09, -0.02), (0.09, -0.02)]):
                sphere(f"{name}_shag{i}", (x + dx * s, y, top + dz * s), (0.14 * s, 0.14 * s, 0.17 * s), fm, self.body)
            for side in (-1, 1):
                e = sphere(f"{name}_ear{side}", (x + side * (R[0] + 0.02 * s), y + 0.05 * s, top - 0.75 * s),
                           (0.13 * s, 0.07 * s, 0.55 * s), fm, self.body)
                e.rotation_euler = (0, side * 0.18, 0)
            sphere(f"{name}_nose", (x, _front(cy, CR, 0, (ez - 0.2 * s) - cz) - 0.04 * s, ez - 0.2 * s),
                   (0.13 * s, 0.11 * s, 0.10 * s), felt("brown"), self.body)
        elif kind == "bird":  # beak, crest, tail feathers
            b = sphere(f"{name}_beak", (x, _front(cy, CR, 0, (ez - 0.14 * s) - cz) - 0.12 * s, ez - 0.14 * s),
                       (0.10 * s, 0.22 * s, 0.07 * s), felt("yellow"), self.body)
            b.rotation_euler = (0.25, 0, 0)
            for i, ang in enumerate((-0.35, 0, 0.35)):
                c = sphere(f"{name}_crest{i}", (x + ang * 0.25 * s, y, top + 0.1 * s), (0.04 * s, 0.04 * s, 0.17 * s), fm, self.body)
                c.rotation_euler = (0, ang, 0)
            for i, ang in enumerate((-0.4, 0, 0.4)):
                tf = sphere(f"{name}_tail{i}", (x + ang * 0.3 * s, y + R[1] + 0.15 * s, bz * s + 0.1 * s),
                            (0.08 * s, 0.30 * s, 0.05 * s), fm, self.body)
                tf.rotation_euler = (-0.7, 0, ang)
        elif kind == "puppy":  # snout and nose, floppy brown ears, tail
            snz = ez - 0.2 * s
            sny = _front(cy, CR, 0, snz - cz) - 0.06 * s
            sphere(f"{name}_snout", (x, sny, snz), (0.21 * s, 0.17 * s, 0.14 * s), felt((0.98, 0.88, 0.66), bump=0.2), self.body)
            sphere(f"{name}_nose", (x, sny - 0.15 * s, snz + 0.06 * s), (0.07 * s, 0.05 * s, 0.05 * s), black, self.body)
            for side in (-1, 1):
                e = sphere(f"{name}_ear{side}", (x + side * (CR[0] + 0.03 * s), cy + 0.02 * s, cz - 0.05 * s),
                           (0.14 * s, 0.06 * s, 0.32 * s), felt("brown"), self.body)
                e.rotation_euler = (0, side * 0.22, 0)
            t = sphere(f"{name}_tail", (x, y + R[1] + 0.05 * s, bz * s + 0.25 * s), (0.07 * s, 0.07 * s, 0.24 * s), fm, self.body)
            t.rotation_euler = (-0.6, 0, 0)
        else:  # blob keeps its old optional parts
            sphere(f"{name}_tuft", (x, y - 0.05 * s, top + 0.0 * s), (0.12 * s, 0.12 * s, 0.22 * s), fm, self.body)
            if ears:
                for side in (-1, 1):
                    e = sphere(f"{name}_ear{side}", (x + side * 0.55 * s, y, 1.45 * s), (0.12 * s, 0.08 * s, 0.38 * s), fm, self.body)
                    e.rotation_euler = (0, side * 0.5, 0)
            if beak:
                b = sphere(f"{name}_beak", (x, y - 0.75 * s, 0.95 * s), (0.12 * s, 0.22 * s, 0.07 * s), felt("yellow"), self.body)
                b.rotation_euler = (0.3, 0, 0)

    def head_world(self):
        return Vector((self.root.location.x, self.root.location.y, self.head_z))

    def mouth_world(self):
        return Vector((self.root.location.x, self.root.location.y, 0)) + self.mouth_off


def image_wall(path, width=26.0, aspect=3.5, z0=-0.4, y=7.0):
    """A MOSS-painted backdrop: an emissive image plane behind the stage (lit by itself, so the painting keeps its colors).
    Backdrops are made panoramic (3.5:1) because the floor hides the bottom of the wall and the wide shot sees a strip."""
    h = width / aspect
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0.5, y, z0 + h / 2), rotation=(math.pi / 2, 0, 0))
    o = bpy.context.active_object
    o.name = "image_wall"
    o.scale = (width, h, 1)
    m = bpy.data.materials.new("image_wall")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(path))
    tex.extension = "EXTEND"
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = float(LOOK.get("backdrop_strength", 1.15))
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    o.data.materials.append(m)
    return o


def build_set(backdrop=None):
    """Puddle Park: felt grass floor, painted sky backdrop, cardboard rainbow, felt houses, paper pond, table.
    With a backdrop image (from the MOSS library) the painted sky, rainbow, houses and pond give way to the image."""
    box("floor", (0, 2, -0.05), (30, 16, 0.1), felt("grass", bump=0.5), bevel=0)
    if backdrop:
        image_wall(backdrop)
        build_table()
        return
    back = box("backdrop", (0, 7, 4), (30, 0.2, 10), paint((0.45, 0.70, 0.98), (0.85, 0.93, 1.0)), bevel=0)
    back.rotation_euler = (0, 0, 0)
    # cardboard rainbow (half tori)
    for i, c in enumerate(["red", "orange", "yellow", "green", "blue", "purple"]):
        bpy.ops.mesh.primitive_torus_add(major_radius=3.2 - i * 0.28, minor_radius=0.13, location=(1.5, 6.5, 0.3),
                                         rotation=(math.pi / 2, 0, 0), major_segments=96, minor_segments=16)
        t = bpy.context.active_object
        t.name = f"rainbow{i}"
        t.data.materials.append(felt(c, bump=0.15))
    # felt houses
    for i, (x, col) in enumerate([(-6.0, "pink"), (-3.6, "yellow"), (5.6, "blue")]):
        box(f"house{i}", (x, 5.2, 1.0), (1.8, 1.6, 2.0), felt(col))
        bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=1.45, depth=1.1, location=(x, 5.2, 2.55), rotation=(0, 0, math.pi / 4))
        bpy.context.active_object.data.materials.append(felt("red"))
        box(f"door{i}", (x, 4.38, 0.5), (0.45, 0.06, 0.8), felt("brown"), bevel=0.03)
    # paper pond
    cylinder("pond", (4.2, 1.8, 0.01), 1.4, 0.02, glossy("blue"))
    build_table()


def build_table():
    """The counting table every scene uses."""
    box("tabletop", (0.6, 0.0, 0.85), (2.6, 1.2, 0.12), felt("brown", bump=0.2))
    for dx in (-1.1, 1.1):
        for dy in (-0.45, 0.45):
            cylinder(f"leg{dx}{dy}", (0.6 + dx, dy, 0.42), 0.07, 0.84, felt("brown", bump=0.1))


def prop(kind, name, loc):
    if kind == "apple":
        o = sphere(name, loc, (0.22, 0.22, 0.2), glossy("red"))
        stem = cylinder(f"{name}_stem", (loc[0], loc[1], loc[2] + 0.22), 0.02, 0.1, felt("brown", bump=0))
        stem.parent = o
        stem.matrix_parent_inverse = o.matrix_world.inverted()
        leaf = sphere(f"{name}_leaf", (loc[0] + 0.07, loc[1], loc[2] + 0.25), (0.08, 0.03, 0.04), felt("green", bump=0), o)
        return o
    if kind == "ball":
        return sphere(name, loc, (0.25,) * 3, glossy("blue"))
    if kind == "star":
        bpy.ops.mesh.primitive_circle_add(vertices=10, radius=0.3, fill_type="NGON", location=loc, rotation=(math.pi / 2, 0, 0))
        o = bpy.context.active_object
        for i, v in enumerate(o.data.vertices):
            if i % 2:
                v.co *= 0.45
        o.modifiers.new("solid", "SOLIDIFY").thickness = 0.12
        o.name = name
        o.data.materials.append(felt("yellow"))
        return o
    return sphere(name, loc, (0.2,) * 3, felt("pink"))


def numeral(text, loc, color="yellow"):
    """Exact on-screen text (digits/letters) as chunky felt 3D type, facing the camera."""
    cu = bpy.data.curves.new(f"num_{text}", type="FONT")
    cu.body = text
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.extrude = 0.12
    cu.bevel_depth = 0.03
    cu.size = 1.8
    o = bpy.data.objects.new(f"num_{text}", cu)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (math.pi / 2, 0, 0)
    o.data.materials.append(felt(color, bump=0.2))
    return o


# ---------------------------------------------------------------------------------------
# keyframe helpers and actions
# ---------------------------------------------------------------------------------------
FPS = 30
ON_TWOS = False
STEP = 1
ENGINE = "eevee"
LOOK = {}
FRAME_FORMAT = "PNG"


def F(t):
    return int(round(t * FPS)) + 1


def key(obj, path, frame, value=None, index=-1):
    if value is not None:
        setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=frame, index=index)


def act_say(p, t, dur, env=None, **_):
    """Puppet-style lip sync: the mouth opens with the voice's loudness (env, one value per
    video frame, from voice.py); the body leans into loud syllables. Without env: generic flaps."""
    closed = p.mouth_closed
    base = p.body_base_scale
    if env:
        step = STEP
        f0 = F(t)
        key(p.mouth, "scale", f0 - 1, closed)
        for i in range(0, len(env), step):
            o = env[i]
            key(p.mouth, "scale", f0 + i, (closed[0] * (1 + 0.25 * o), closed[1], closed[2] * (1 + 5.0 * o)))
            key(p.body, "scale", f0 + i, (base[0] * (1 + 0.025 * o), base[1] * (1 + 0.025 * o), base[2] * (1 - 0.02 * o)))
        key(p.mouth, "scale", f0 + len(env) + 1, closed)
        key(p.body, "scale", f0 + len(env) + 1, base)
        return
    n = max(1, int(dur * 5))
    for i in range(n):
        f0 = F(t + i / 5)
        key(p.mouth, "scale", f0, closed)
        key(p.mouth, "scale", f0 + 3, (closed[0], closed[1], closed[2] * 4.0))
    key(p.mouth, "scale", F(t + dur), closed)
    base = p.body_base_scale
    for i in range(int(dur * 2)):
        f0 = F(t + i / 2)
        key(p.body, "scale", f0, base)
        key(p.body, "scale", f0 + 7, (base[0] * 1.02, base[1] * 1.02, base[2] * 0.97))
    key(p.body, "scale", F(t + dur), base)


def act_hop(p, t, height=0.6, **_):
    loc = p.root.location.copy()
    base = p.body_base_scale
    key(p.root, "location", F(t), loc)
    key(p.body, "scale", F(t), base)
    key(p.body, "scale", F(t + 0.12), (base[0] * 1.12, base[1] * 1.12, base[2] * 0.82))  # squash
    key(p.root, "location", F(t + 0.4), loc + Vector((0, 0, height)))
    key(p.body, "scale", F(t + 0.3), (base[0] * 0.92, base[1] * 0.92, base[2] * 1.12))  # stretch
    key(p.root, "location", F(t + 0.75), loc)
    key(p.body, "scale", F(t + 0.82), (base[0] * 1.1, base[1] * 1.1, base[2] * 0.86))
    key(p.body, "scale", F(t + 1.0), base)


def act_move(p, t, to, dur=1.0, **_):
    start = p.root.location.copy()
    end = Vector((to[0], to[1], 0))
    key(p.root, "location", F(t), start)
    steps = max(2, int(dur * 4))
    for i in range(1, steps + 1):
        u = i / steps
        pos = start.lerp(end, u)
        pos.z = abs(math.sin(u * math.pi * steps / 2)) * 0.12  # bouncy walk
        key(p.root, "location", F(t + dur * u), pos)
    p.root.location = end
    key(p.root, "location", F(t + dur), end)


def act_wave(p, t, dur=1.5, **_):
    side, pivot = p.arms[1]
    key(pivot, "rotation_euler", F(t), (0, 0, 0))
    for i in range(int(dur * 3)):
        key(pivot, "rotation_euler", F(t + 0.15 + i / 3), (0, -2.3, 0.0))
        key(pivot, "rotation_euler", F(t + 0.32 + i / 3), (0, -1.8, 0.0))
    key(pivot, "rotation_euler", F(t + dur + 0.2), (0, 0, 0))


def act_point(p, t, dur=1.2, **_):
    side, pivot = p.arms[0]
    key(pivot, "rotation_euler", F(t), (0, 0, 0))
    key(pivot, "rotation_euler", F(t + 0.25), (-0.9, 1.4, 0))
    key(pivot, "rotation_euler", F(t + dur), (-0.9, 1.4, 0))
    key(pivot, "rotation_euler", F(t + dur + 0.3), (0, 0, 0))


def act_look(p, t, at, **_):
    target = Vector(at)
    for pupil, home in p.pupils:
        d = (target - p.head_world())
        d.normalize()
        off = Vector((d.x * 0.06 * p.size, 0, d.z * 0.05 * p.size))
        key(pupil, "location", F(t), pupil.location.copy())
        pupil.location = home + off
        key(pupil, "location", F(t + 0.15), pupil.location.copy())


def pop_in(obj, t, final_scale=None):
    final = Vector(final_scale or obj.scale)
    key(obj, "scale", F(t) - 1, (0.001,) * 3)
    key(obj, "scale", F(t + 0.18), final * 1.25)
    key(obj, "scale", F(t + 0.32), final * 0.92)
    key(obj, "scale", F(t + 0.45), final)


def pop_out(obj, t):
    s = obj.scale.copy()
    key(obj, "scale", F(t), s)
    key(obj, "scale", F(t + 0.25), (0.001,) * 3)


def act_eat(p, t, obj, **_):
    """The puppet eats a prop: it hops up to the puppet's mouth (0.5 s), three chomps (0.4 s each) with the
    body bouncing, and the prop shrinks a third per bite until it is gone."""
    start = obj.location.copy()
    # in front of the face, not at the mouth itself: a snout or beak would hide it
    mouth = p.mouth_world() + Vector((0, -(0.42 if p.kind in ("puppy", "bird") else 0.25) * p.size, 0.06 * p.size))
    key(obj, "location", F(t), start)
    key(obj, "location", F(t + 0.25), (start + mouth) / 2 + Vector((0, 0, 0.45)))
    key(obj, "location", F(t + 0.5), mouth)
    s0 = obj.scale.copy()
    key(obj, "scale", F(t + 0.5), s0)
    closed, base = p.mouth_closed, p.body_base_scale
    for i in range(3):
        tb = t + 0.5 + i * 0.4
        key(p.mouth, "scale", F(tb), (closed[0] * 1.25, closed[1], closed[2] * 6.0))
        key(p.mouth, "scale", F(tb + 0.2), closed)
        key(p.body, "scale", F(tb + 0.2), (base[0] * 1.05, base[1] * 1.05, base[2] * 0.95))
        key(p.body, "scale", F(tb + 0.38), base)
        key(obj, "scale", F(tb + 0.2), s0 * (1 - (i + 1) / 3) if i < 2 else Vector((0.001,) * 3))


# ---------------------------------------------------------------------------------------
# camera, lights, render
# ---------------------------------------------------------------------------------------
SHOTS = {"wide": ((0.5, -10.5, 2.3), (0.5, 0.5, 0.95), 30), "medium": ((0.5, -8.2, 1.9), (0.5, 0.0, 1.45), 35)}


def setup_camera():
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    target = empty("cam_target")
    c = cam.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = target
    cam_data.dof.aperture_fstop = 4.0
    return cam, target


def act_shot(cam_target, t, shot, cast, smooth=0.0):
    cam, target = cam_target
    if shot.startswith("close:"):
        p = cast[shot.split(":", 1)[1]]
        h = p.head_world()
        pos, look, lens = (h.x + 0.4, h.y - 5.2, h.z + 0.3), (h.x + 0.4, h.y, h.z), 40
    else:
        pos, look, lens = SHOTS.get(shot, SHOTS["wide"])
    f = F(t)
    if smooth and f > 1:
        key(cam, "location", f, None)
        key(target, "location", f, None)
        key(cam.data, "lens", f, None)
        f = F(t + smooth)
    cam.location, target.location, cam.data.lens = pos, look, lens
    key(cam, "location", f)
    key(target, "location", f)
    key(cam.data, "lens", f)


def setup_lights_world():
    w = bpy.context.scene.world or bpy.data.worlds.new("world")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.75, 0.85, 1.0, 1)
    bg.inputs["Strength"].default_value = LOOK.get("world", 0.3)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-25))
    sun.data.energy = 2.2
    sun.data.angle = math.radians(8)
    key_l = bpy.data.objects.new("key", bpy.data.lights.new("key", "AREA"))
    bpy.context.scene.collection.objects.link(key_l)
    key_l.location = (-3.5, -6, 5)
    key_l.rotation_euler = (math.radians(55), 0, math.radians(-30))
    key_l.data.energy = LOOK.get("key", 350)
    key_l.data.size = 5


def setup_render(res, fps, seconds, samples, out_dir):
    sc = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    for attr, val in (("taa_render_samples", samples), ("use_shadows", True), ("use_raytracing", False)):
        if hasattr(sc.eevee, attr):
            setattr(sc.eevee, attr, val)
    if ENGINE == "workbench":
        # what Blender's viewport "Solid" mode draws: material colors, studio light, shadows, cavity
        sc.render.engine = "BLENDER_WORKBENCH"
        sh = sc.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_shadows = True
        sh.shadow_intensity = 0.35
        sh.show_cavity = True
        sh.cavity_type = "BOTH"
        sc.display.render_aa = "8"
    if ENGINE == "cycles":
        # the video's tricks: GPU (OptiX), low samples + adaptive, few bounces, denoise, persistent data
        sc.render.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev_type in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = dev_type
                prefs.refresh_devices()
                for d in prefs.devices:
                    d.use = d.type == dev_type
                break
            except TypeError:
                continue
        sc.cycles.device = "GPU"
        sc.cycles.samples = samples
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.adaptive_threshold = 0.05
        sc.cycles.use_denoising = True
        for name in ("OPENIMAGEDENOISE", "OPTIX"):
            try:
                sc.cycles.denoiser = name
                break
            except TypeError:
                pass
        sc.cycles.max_bounces, sc.cycles.diffuse_bounces, sc.cycles.glossy_bounces = 4, 2, 2
        sc.cycles.transmission_bounces, sc.cycles.transparent_max_bounces = 2, 4
        sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
        sc.render.use_persistent_data = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 1, int(seconds * fps)
    sc.frame_step = STEP
    if FRAME_FORMAT == "JPEG":
        sc.render.image_settings.file_format = "JPEG"
        sc.render.image_settings.quality = 95
    else:
        sc.render.image_settings.file_format = "PNG"
        sc.render.image_settings.compression = 0
    sc.render.image_settings.color_mode = "RGB"
    sc.render.filepath = str(Path(out_dir) / "frames" / "f_")
    sc.view_settings.view_transform = "AgX" if "AgX" in [v.identifier for v in
        bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    sc.view_settings.exposure = LOOK.get("exposure", -0.3)
    if LOOK.get("view"):
        sc.view_settings.view_transform = LOOK["view"]
    for look in (() if LOOK.get("view") else ("AgX - Punchy", "AgX - Medium High Contrast", "Medium High Contrast")):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            pass



# ---------------------------------------------------------------------------------------
# plug-in actions: actions/<name>.py files written by the engineer agent and approved by the owners
# ---------------------------------------------------------------------------------------
class ActionAPI:
    """What a plug-in action gets: the scene (cast, spawned props) and the engine's building blocks."""

    def __init__(self, cast, spawned, cam_target):
        import types
        self.cast, self.spawned, self.cam_target = cast, spawned, cam_target
        self.F, self.key, self.Vector, self.math = F, key, Vector, math
        self.sphere, self.cylinder, self.box, self.empty = sphere, cylinder, box, empty
        self.felt, self.glossy, self.attach = felt, glossy, _attach
        self.pop_in, self.pop_out, self.new_prop = pop_in, pop_out, prop
        self.hop, self.move, self.wave, self.point, self.look, self.eat = act_hop, act_move, act_wave, act_point, act_look, act_eat
        self.fps, self.step = FPS, STEP

    def puppet(self, name):
        return self.cast[name]

    def prop(self, name):
        return self.spawned[name]


def load_plugins():
    """Plug-ins from the folders in $PUDDLE_ACTIONS (colon-separated); default: the approved (live) folder."""
    import importlib.util
    import os
    dirs = os.environ.get("PUDDLE_ACTIONS", "/hyperai/home/loop/puddle/actions/live").split(":")
    found = {}
    for d in dirs:
        for f in sorted(Path(d).glob("*.py")) if Path(d).is_dir() else []:
            try:
                spec = importlib.util.spec_from_file_location(f"action_{f.stem}", f)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                found[m.ACTION] = m
            except Exception as e:
                print(f"PLUGIN LOAD FAILED {f}: {e!r}")
    return found

# ---------------------------------------------------------------------------------------
def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    script = json.loads(Path(args[0]).read_text())
    out_dir = Path(args[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    global FPS, ON_TWOS
    FPS = int(script.get("fps", 30))
    ON_TWOS = bool(script.get("on_twos", False))
    global STEP
    STEP = int(script.get("step", 2 if ON_TWOS else 1))
    global LOOK
    LOOK = script.get("look", {})
    global ENGINE
    ENGINE = script.get("engine", "eevee")
    global FRAME_FORMAT
    FRAME_FORMAT = script.get("frame_format", "PNG")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_set(script.get("backdrop_path"))
    setup_lights_world()
    cast = {}
    for name, spec in script["cast"].items():
        cast[name] = Puppet(name, spec.get("color", "orange"), spec.get("size", 1.0), spec.get("at", (0, 0)),
                            ears=spec.get("ears", False), beak=spec.get("beak", False), kind=spec.get("kind"))
    cam_target = setup_camera()
    spawned = {}
    plugins = load_plugins()
    api = ActionAPI(cast, spawned, cam_target)
    for ev in sorted(script["timeline"], key=lambda e: e["t"]):
        t, do = ev["t"], ev["do"]
        if do == "shot":
            act_shot(cam_target, t, ev["shot"], cast, ev.get("smooth", 0.0))
        elif do in ("say", "hop", "move", "wave", "point", "look"):
            fn = {"say": act_say, "hop": act_hop, "move": act_move, "wave": act_wave,
                  "point": act_point, "look": act_look}[do]
            fn(cast[ev["who"]], t, **{k: v for k, v in ev.items() if k not in ("t", "do", "who", "text")})
        elif do == "spawn":
            o = prop(ev["prop"], ev.get("name", f"{ev['prop']}{len(spawned)}"), ev["at"])
            pop_in(o, t)
            spawned[o.name] = o
        elif do == "bounce":
            o = spawned[ev["name"]]
            z = o.location.z
            key(o, "location", F(t), None)
            o.location.z = z + 0.35
            key(o, "location", F(t + 0.2))
            o.location.z = z
            key(o, "location", F(t + 0.4))
        elif do == "eat":
            o = spawned.get(ev.get("name"))
            if o is not None:
                act_eat(cast[ev["who"]], t, o)
                spawned.pop(ev["name"])
        elif do == "numeral":
            o = numeral(ev["text"], ev["at"], ev.get("color", "yellow"))
            pop_in(o, t)
            if ev.get("dur"):
                pop_out(o, t + ev["dur"])
        elif do in plugins:
            try:
                plugins[do].run(api, ev)
            except Exception as e:
                print(f"PLUGIN FAILED {do} at {t}: {e!r}")
        else:
            raise ValueError(f"unknown action {do}")
    setup_render(script.get("resolution", (1280, 720)), FPS, script.get("seconds", 15),
                 script.get("samples", 16), out_dir)
    if len(args) > 2:  # optional: render only frames A..B (e.g. "1:30" for a quick test)
        a, b = (int(x) for x in args[2].split(":"))
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = a, b
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "scene.blend"))
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
