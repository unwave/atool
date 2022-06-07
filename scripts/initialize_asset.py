import bpy
import os
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-atool_path')
parser.add_argument('-atool_library_path')
parser.add_argument('-move_textures', action='store_true')
parser.add_argument('-move_sub_assets', action='store_true')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)


FILE_PATH = bpy.data.filepath
DIR_PATH = os.path.dirname(FILE_PATH)
TEXTURES_PATH = os.path.join(DIR_PATH, 'textures')

for object in bpy.data.objects:
    bpy.context.collection.objects.link(object)

def move_textures():

    textures = [texture for texture in bpy.data.images if texture.source == 'FILE' and os.path.exists(texture.filepath)]
    if not textures:
        return

    import site
    sys.path.insert(0, site.getusersitepackages())
    sys.path.insert(0, args.atool_path)
    import data
    import utils
    import bl_utils
    assets = data.AssetData(library=args.atool_library_path)
    assets.update_library()

    os.makedirs(TEXTURES_PATH, exist_ok = True)

    for texture in textures:
        filepath = bl_utils.get_block_abspath(texture)

        if not args.move_sub_assets and assets.is_sub_asset(filepath):
            texture.filepath = bpy.path.relpath(filepath)
            continue
        
        new_path = utils.move_to_folder(filepath, TEXTURES_PATH)

        texture.filepath = bpy.path.relpath(new_path)

if args.move_textures:
    move_textures()

bpy.ops.object.select_all(action='DESELECT')
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=FILE_PATH)
bpy.ops.wm.quit_blender()