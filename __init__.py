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


# https://docs.python.org/3/howto/logging.html
# https://docs.python.org/3/library/logging.html
import logging
log = logging.getLogger("atool")
log.setLevel(logging.DEBUG)

log_handler = logging.StreamHandler()
log_handler.setLevel(logging.DEBUG)
log_formatter = logging.Formatter("Atool %(levelname)s: %(message)s")
log_handler.setFormatter(log_formatter)
log.addHandler(log_handler)

import typing
import sys
import os
import threading
import time

import bpy
from bpy.app.handlers import persistent

from . import addon_updater_ops


def ensure_site_packages(packages: typing.List[typing.Tuple[str, str]]):
    """ `packages`: list of tuples (<import name>, <pip name>) """
    
    if not packages:
        return

    import site
    import importlib.util

    user_site_packages = site.getusersitepackages()
    os.makedirs(user_site_packages, exist_ok = True)
    sys.path.append(user_site_packages)

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
    ("validators", "validators"),
    ("pyperclip", "pyperclip"),
    # ("pathos", "pathos"),
    ("cv2", "opencv-contrib-python-headless"),
    ("cached_property", "cached-property")
])

from . addon_preferences_ui import *
from . view_3d_operator import *
from . view_3d_ui import *
from . shader_editor_operator import *
from . shader_editor_ui import *
from . data import *
from . import utils

config = utils.read_local_file("config.json") # type: dict
if config and config.get("dev_mode"):
    from . dev_tools import *

classes = [module for name, module in locals().items() if name.startswith("ATOOL")]

def register():
    start = timer()

    addon_updater_ops.register(bl_info)

    for c in classes:
        bpy.utils.register_class(c)

    addon_preferences = bpy.context.preferences.addons[__package__].preferences
    wm = bpy.types.WindowManager
    wm.at_asset_data = AssetData(addon_preferences.library_path, addon_preferences.auto_path)
    wm.at_asset_previews = bpy.props.EnumProperty(items=get_browser_items)
    wm.at_browser_asset_info = bpy.props.PointerProperty(type=ATOOL_PROP_browser_asset_info)
    wm.at_template_info = bpy.props.PointerProperty(type=ATOOL_PROP_template_info)
    wm.at_import_config = bpy.props.PointerProperty(type=ATOOL_PROP_import_config)
    wm.at_search = bpy.props.StringProperty(name="", 
        description= \
        ':no_icon - with no preview \n'\
        ':more_tags - less than 4 tags\n'\
        ':no_url - with no url\n'\
        ':i - intersection mode, default - subset\n'\
        '-<tag> to exclude the tag\n'\
        'id:<asset id> - find by id'
        ,update=update_search, default='')
    wm.at_current_page = bpy.props.IntProperty(name="Page", description="Page", update=update_page, min=1, default=1)
    wm.at_assets_per_page = bpy.props.IntProperty(name="Assets Per Page", update=update_assets_per_page, min=1, default=24, soft_max=104)

    bpy.types.Object.at_uv_multiplier = bpy.props.FloatProperty(default = 1)

    wm = bpy.context.window_manager
    wm["at_asset_previews"] = 0
    wm["at_current_page"] = 1

    threading.Thread(target=wm.at_asset_data.update, args=(bpy.context,), daemon=True).start()
    threading.Thread(target=utils.init_find, daemon=True).start()

    register_time = timer() - start
    log.info(f"register time:\t {register_time:.2f} sec")
    log.info(f"all time:\t\t {register_time + init_time:.2f} sec")


def unregister():

    addon_updater_ops.unregister()

    for c in classes:
        bpy.utils.unregister_class(c)

    wm = bpy.types.WindowManager
    del wm.at_asset_data
    del wm.at_asset_previews
    del wm.at_browser_asset_info
    del wm.at_template_info
    del wm.at_search
    del wm.at_current_page
    del wm.at_assets_per_page

    del bpy.types.Object.at_uv_multiplier

init_time = timer() - start
log.info(f"__init__ time:\t {init_time:.2f} sec")