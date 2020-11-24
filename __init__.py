bl_info = {
    "name" : "Material Applier",
    "author" : "unwave",
    "description" : "",
    "blender" : (2, 81, 0),
    "version" : (0, 0, 1),
    "location" : "",
    "warning" : "",
    "category" : "Material"
}

import bpy
import sys
import os

script_file_directory = os.path.dirname(os.path.realpath(__file__))
site_packages_path = os.path.join(script_file_directory, "site-packages")

if not os.path.exists(site_packages_path):
    os.makedirs(site_packages_path)

sys.path.append(site_packages_path)

try:
    import xxhash
    from PIL import Image as pillow_image
except:
    import subprocess
    python_binary =  bpy.app.binary_path_python
    # sys.executable ?
    try:
        subprocess.run([python_binary, '-m', 'ensurepip'], check=True)
        # subprocess.run([python_binary, '-m', 'ensurepip', '--upgrade'], check=True)
        # subprocess.run([python_binary, '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
        subprocess.run([python_binary, '-m', 'pip', 'install', 'xxhash', '-t', site_packages_path], check=True)
        subprocess.run([python_binary, '-m', 'pip', 'install', 'Pillow', '-t', site_packages_path], check=True)
    except subprocess.SubprocessError as error:
        print(error.output)


from . lib import *
from . ui import *

classes = (
    MATAPP_OT_apply_material, 
    MATAPP_properties, 
    MATAPP_OT_height_blend, 
    MATAPP_PT_tools, 
    MATAPP_OT_make_links, 
    MATAPP_OT_detail_blend, 
    MATAPP_OT_ensure_adaptive_subdivision, 
    MATAPP_OT_normalize_height, 
    MATAPP_OT_bake_defaults,
    MATAPP_OT_append_extra_nodes,
    MATAPP_OT_save_material_settings,
    MATAPP_OT_load_material_settings,
    MATAPP_OT_open_in_file_browser,
    MATAPP_OT_transfer_settings,
    MATAPP_OT_convert_materail,
    MATAPP_OT_restore_default_settings,
    MATAPP_OT_restore_factory_settings
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.matapp_properties = bpy.props.PointerProperty(type=MATAPP_properties)

def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.matapp_properties