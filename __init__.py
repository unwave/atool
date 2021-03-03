bl_info = {
    "name" : "ATool",
    "author" : "unwave",
    "description" : "",
    "blender" : (2, 83, 0),
    "version" : (0, 0, 1),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}

from timeit import default_timer as timer
start = timer()

import typing
import bpy
import sys
from . import addon_updater_ops

def ensure_site_packages(packages: typing.List[typing.Tuple[str, str]]):
    """ `packages`: list of tuples (<import name>, <pip name>) """
    
    if not packages:
        return

    import site
    import importlib

    sys.path.append(site.getusersitepackages())

    modules_to_install = [module[1] for module in packages if not importlib.util.find_spec(module[0])]   

    if modules_to_install:
        import subprocess

        if bpy.app.version < (2,91,0):
            python_binary = bpy.app.binary_path_python
        else:
            python_binary = sys.executable

        subprocess.run([python_binary, '-m', 'ensurepip'], check=True)
        subprocess.run([python_binary, '-m', 'pip', 'install', *modules_to_install, "--user"], check=True)

ensure_site_packages([
    ("PIL", "Pillow"),
    # ("imagesize", "imagesize"),
    ("xxhash","xxhash"),
    # ("lxml", "lxml"),
    ("bs4","beautifulsoup4"),
    # ("tldextract", "tldextract"),
    ("validators", "validators")
])

from . addon_preferences_ui import *
from . view_3d_operator import *
from . view_3d_ui import *
from . shader_editor_operator import *
from . shader_editor_ui import *
from . data import *

classes = [module for name, module in locals().items() if name.startswith("ATOOL_")]

def register():
    start = timer()

    addon_updater_ops.register(bl_info)

    for c in classes:
        bpy.utils.register_class(c)

    addon_preferences = bpy.context.preferences.addons[__package__].preferences
    wm = bpy.types.WindowManager
    wm.at_asset_data = AssetData(addon_preferences.library_path, addon_preferences.auto_path)
    wm.at_asset_previews = bpy.props.EnumProperty(items=get_browser_items)
    wm.at_asset_info = bpy.props.PointerProperty(type=ATOOL_PROP_asset_info)
    wm.at_browser_asset_info = bpy.props.PointerProperty(type=ATOOL_PROP_browser_asset_info)
    wm.at_template_info = bpy.props.PointerProperty(type=ATOOL_PROP_template_info)
    wm.at_search = bpy.props.StringProperty(name="", description="Search", update=update_search)
    wm.at_current_page = bpy.props.IntProperty(name="Page", description="Page", update=update_page, min=1, default=1)
    wm.at_assets_per_page = bpy.props.IntProperty(name="Assets Per Page", update=update_assets_per_page, min=1, default=24, soft_max=104)

    register_time = timer() - start
    print("AT register time:\t", register_time)
    print("AT all time:\t\t", register_time + init_time)


def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)

    wm = bpy.types.WindowManager
    del wm.at_asset_data
    del wm.at_asset_previews
    del wm.at_asset_info
    del wm.at_browser_asset_info
    del wm.at_template_info
    del wm.at_search
    del wm.at_current_page
    del wm.at_assets_per_page

init_time = timer() - start
print("AT __init__ time:\t", init_time)