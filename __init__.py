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

import bpy

from . import addon_updater_ops

def ensure_site_packages(packages: typing.List[typing.Tuple[str, str]]):
    """ `packages`: list of tuples (<import name>, <pip name>) """
    
    if not packages:
        return

    import site
    import importlib
    import importlib.util

    user_site_packages = site.getusersitepackages()
    sys.path.append(user_site_packages)

    modules_to_install = [module[1] for module in packages if not importlib.util.find_spec(module[0])]
    if not modules_to_install:
        return

    if bpy.app.version < (2,91,0):
        python_binary = bpy.app.binary_path_python
    else:
        python_binary = sys.executable
        
    import subprocess
    subprocess.run([python_binary, '-m', 'ensurepip'], check=True)
    subprocess.run([python_binary, '-m', 'pip', 'install', *modules_to_install, "--user"], check=True)
    
    importlib.invalidate_caches()
    
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
    ("cached_property", "cached-property"),
    ("inflection", "inflection")
])

ADDON_FILES_POSTFIXES = ('_operator.py', '_ui.py', 'data.py')
ADDON_UTILS_POSTFIXES = ('utils.py', 'asset_parser.py', 'type_definer.py')

import importlib
modules = []
utils_names = set()
for file in os.scandir(os.path.dirname(__file__)):
    if not file.is_file():
        continue
    
    stem = os.path.splitext(file.name)[0]
    
    if file.name.endswith(ADDON_FILES_POSTFIXES):
        modules.append(importlib.import_module('.' + stem, package = __package__))
    elif file.name.endswith(ADDON_UTILS_POSTFIXES):
        utils_names.add(stem)

from . import utils
config = utils.read_local_file("config.json") # type: dict
if config and config.get("dev_mode"):
    modules.append(importlib.import_module('.dev_tools', package = __package__))

class ATOOL_OT_reload_addon(bpy.types.Operator):
    bl_idname = "atool.reload_addon"
    bl_label = "Reload Atool Addon"
    bl_description = "Reload the Atool addon."

    def execute(self, context):
        
        utils_to_reload = set()
        for module in modules:
            for key, value in module.__dict__.items():
                if key in utils_names:
                    utils_to_reload.add(value)
                    
        for util in utils_to_reload:
            importlib.reload(util)

        for module in modules:
            module.register.unregister()
            importlib.reload(module)
            module.register.register()
            
        wm = context.window_manager
        wm["at_asset_previews"] = 0
        wm["at_current_page"] = 1
        
        threading.Thread(target=wm.at_asset_data.update, args=(bpy.context,), daemon=True).start()
        # threading.Thread(target=utils.init_find, daemon=True).start()
        
        print('Atool has been reloaded.')
        
        return {'FINISHED'}

def register():
    start = timer()

    addon_updater_ops.register(bl_info)
    bpy.utils.register_class(ATOOL_OT_reload_addon)

    for module in modules:
        module.register.register()

    wm = bpy.context.window_manager
    wm["at_asset_previews"] = 0
    wm["at_current_page"] = 1

    threading.Thread(target=wm.at_asset_data.update, args=(bpy.context,), daemon=True).start()
    threading.Thread(target=utils.EVERYTHING.set_es_exe, daemon=True).start()

    register_time = timer() - start
    log.info(f"register time:\t {register_time:.2f} sec")
    log.info(f"all time:\t\t {register_time + init_time:.2f} sec")


def unregister():
    addon_updater_ops.unregister()
    bpy.utils.unregister_class(ATOOL_OT_reload_addon)

    for module in modules:
        module.register.unregister()
        

init_time = timer() - start
log.info(f"__init__ time:\t {init_time:.2f} sec")