import sys
import argparse
import json
import os
import time

import bpy
import mathutils

parser = argparse.ArgumentParser()
parser.add_argument('-job')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

JOB = json.loads(args.job)

def get_desktop():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return winreg.QueryValueEx(key, "Desktop")[0]
    except:
        return os.path.expanduser("~/Desktop")

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
    scene.render.resolution_x = JOB['resolution']
    scene.render.resolution_y = JOB['resolution']
    scene.render.film_transparent = JOB['use_film_transparent']

    scene.render.use_crop_to_border = False
    scene.render.use_border = False

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = JOB['samples']
    scene.cycles.use_square_samples = False
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        scene.cycles.denoising_input_passes = 'RGB_ALBEDO_NORMAL'
        scene.cycles.denoising_prefilter = 'ACCURATE'
    except:
        pass
    scene.use_nodes = False

    if JOB['use_default_world']:
        scene.view_settings.exposure = -3.7
        scene.view_settings.view_transform = 'Filmic'

        scene.world = get_world()
    
bpy.ops.wm.open_mainfile(filepath=JOB['filepath'], load_ui=False, use_scripts=False, display_file_selector=False)

context = bpy.context
set_render_settings(context.scene)

for object in bpy.data.objects:

    for modifier in object.modifiers:
        modifier.show_render = modifier.show_viewport

    object.hide_render = not object.visible_get()

    if JOB['is_local_view']:
        object.hide_render = not object.name in JOB['local_view_objects']

    if JOB['use_default_world']:
        if object.type == 'LIGHT' and object.data.type == 'SUN':
            object.hide_render = True

camera_data = bpy.data.cameras.new("Camera")

camera = bpy.data.objects.new("Camera", camera_data)
context.collection.objects.link(camera)
context.scene.camera = camera

camera.matrix_world = mathutils.Matrix(JOB['view_matrix'])
camera_data.lens = JOB['lens']
camera_data.clip_start = JOB['clip_start']
camera_data.clip_end = JOB['clip_end']

if 0: # debug
    filepath = os.path.join(get_desktop(), f"preview_render_test_{time.strftime('%y%m%d_%H%M%S')}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=filepath)

bpy.ops.render.render()

image = bpy.data.images['Render Result']
render_path = os.path.join(get_desktop(), time.strftime('%y%m%d_%H%M%S') + '.png')
image.save_render(render_path)