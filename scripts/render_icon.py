from itertools import accumulate
import sys
import argparse
import json
import os

import bpy
import mathutils

parser = argparse.ArgumentParser()
parser.add_argument('-atool_path')
parser.add_argument('-atool_library_path')
parser.add_argument('-jobs_path')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

ATOOL_PATH = args.atool_path
ATOOL_LIBRARY = args.atool_library_path

with open(args.jobs_path, encoding='utf-8') as jobs_file:
    jobs = json.load(jobs_file) # type: dict

material_jobs = jobs.get('materials')
object_jobs = jobs.get('objects')


def get_world():
    world = bpy.data.worlds.new(name='world')
    world.use_nodes = True
    nodes = world.node_tree.nodes
    background = [node for node in nodes if node.type == 'BACKGROUND'][0]
    sky = nodes.new('ShaderNodeTexSky')
    sky.sun_rotation = 2
    sky.sun_elevation = 0.7854
    world.node_tree.links.new(sky.outputs[0], background.inputs[0])
    return world

def set_render_settings(scene: bpy.types.Scene):
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.film_transparent = True

    scene.render.use_crop_to_border = False
    scene.render.use_border = False

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 10
    scene.cycles.use_square_samples = False
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    except:
        pass
    scene.use_nodes = False

    scene.view_settings.exposure = -3.7
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'

    scene.world = get_world()


if material_jobs:

    import site
    sys.path.append(site.getusersitepackages())
    sys.path.append(ATOOL_PATH)

    import node_utils
    import type_definer

    filepath = os.path.join(ATOOL_PATH, 'scripts', 'render_icon.blend')
    bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=False, use_scripts=False, display_file_selector=False)

    mat_sphere = bpy.data.objects['material_sphere']

    type_definer_config = type_definer.Filter_Config()
    type_definer_config.__dict__.update(jobs['type_definer_config'])

    context = bpy.context
    set_render_settings(context.scene)

    for job in material_jobs:
        type_definer_config.set_common_prefix_from_paths(job['files'])
        material = node_utils.get_material(job['files'], use_displacement = True, displacement_scale = job['displacement_scale'], invert_normal_y = job['invert_normal_y'], type_definer_config = type_definer_config)
        mat_sphere.material_slots[0].material = material

        bpy.ops.render.render()

        image = bpy.data.images['Render Result']
        image.save_render(job['result_path'])

if object_jobs:
    
    for job in object_jobs:

        bpy.ops.wm.open_mainfile(filepath=job['filepath'], load_ui=False, use_scripts=False, display_file_selector=False)

        context = bpy.context
        set_render_settings(context.scene)

        coordinates = []
        for object in bpy.data.objects:

            if not object.visible_get():
                continue
            
            if object.hide_render:
                continue

            # blender 3.0
            if hasattr(object, 'is_shadow_catcher') and object.is_shadow_catcher:
                continue
            
            # blender <3.0
            if hasattr(object.cycles, 'is_shadow_catcher') and object.cycles.is_shadow_catcher:
                continue
            
            # blender 3.0
            if hasattr(object, 'visible_camera') and not object.visible_camera:
                continue
            
            # blender <3.0
            if hasattr(object, 'cycles_visibility') and not object.cycles_visibility.camera:
                continue

            if object.type == 'LIGHT' and object.data.type == 'SUN':
                object.hide_render = True
                continue

            if not object.type in {'MESH', 'CURVE'}:
                continue

            # context.collection.objects.link(object)
            # matrix_world = object.matrix_world @ mathutils.Matrix.Scale(1.1, 4)
            matrix_world = object.matrix_world
            for v in object.bound_box:
                coordinates.extend(matrix_world @ mathutils.Vector(v))

        camera_data = bpy.data.cameras.new("Camera")
        camera_data.lens = 120

        camera = bpy.data.objects.new("Camera", camera_data)
        context.collection.objects.link(camera)
        camera.rotation_mode = 'XYZ'
        camera.rotation_euler = (1.178097, 0, 0.3926991)

        context.scene.camera = camera

        depsgraph = context.evaluated_depsgraph_get()
        co_return, scale_return = camera.camera_fit_coords(depsgraph, coordinates)

        camera.location = co_return
        
        import math
        dist = math.sqrt(sum(x*x for x in co_return))
        camera_data.clip_start *= dist
        camera_data.clip_end = dist * 2
        
        if 0: # debug
            def get_desktop():
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                        return winreg.QueryValueEx(key, "Desktop")[0]
                except:
                    return os.path.expanduser("~/Desktop")
                
            filepath = os.path.join(get_desktop(), 'icon_test.blend')
            bpy.ops.wm.save_as_mainfile(filepath=filepath)

        bpy.ops.render.render()

        image = bpy.data.images['Render Result']
        image.save_render(job['result_path'])