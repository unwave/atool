import json
import math
import os
import random
import re
import shutil
import string
import time
import typing
import threading
import operator
from timeit import default_timer as timer

import bpy
from PIL import Image as pillow_image
from cached_property import cached_property

import _bpy # type: ignore
utils_previews = _bpy._utils_previews
del _bpy

try: 
    from . import asset_parser
    from . import type_definer
    from . import utils
    from . import bl_utils
    from . import image_utils
    from . import view_3d_ui
    from . import shader_editor_operator
except: # for external testing
    import asset_parser
    import utils
    import bl_utils
    import image_utils
    import type_definer

    # till i find a better way
    # import view_3d_ui
    # import shader_editor_operator

EMPTY_ITEM_LIST = [('/', "Empty :(", '＾-＾', 'GHOST_DISABLED', 0)]

current_browser_items = EMPTY_ITEM_LIST
current_search_query = None
reading_time = 0

PROHIBITED_TRAILING_SYMBOLS = " *-~:"

META_FILES = {"__icon__.png", "__info__.json", "__gallery__", "__extra__", "__archive__"}
SEARCH_SET_INFO = {"name", "url", "author", "tags", "system_tags"}


def get_browser_items(self, context):
    return current_browser_items

def update_search(wm, context):
    search_query = wm.at_search
    search_query.strip()

    if current_search_query != search_query:
        asset_data = wm.at_asset_data # type: AssetData
        try: 
            current_asset = asset_data.get(wm.at_asset_previews)
        except: 
            return # if data is not loaded yet
        
        wm["at_asset_previews"] = 0
        wm["at_current_page"] = 1

        asset_data.search(search_query)
        if current_asset in asset_data.search_result:
            asset_data.go_to_page(asset_data.get_asset_page(current_asset))
            wm["at_current_page"] = asset_data.current_page
            wm.at_asset_previews = current_asset.id


def update_page(wm, context):
    asset_data = wm.at_asset_data # type: AssetData
    asset_data.go_to_page(wm["at_current_page"])
    wm["at_current_page"] = asset_data.current_page
    wm["at_asset_previews"] = min(wm["at_asset_previews"], len(get_browser_items(None, None)) - 1)

def update_assets_per_page(wm, context):
    wm["at_current_page"] = 1
    wm["at_asset_previews"] = 0
    wm.at_asset_data.set_assets_per_page(wm["at_assets_per_page"])


def update_string_info(property_name, id, info, context):
    try:
        asset_to_update = context.window_manager.at_asset_data[id] # type: Asset
    except:
        info[property_name] = ""
        return
    info[property_name] = info[property_name].strip(PROHIBITED_TRAILING_SYMBOLS)
    if asset_to_update.info.get(property_name) != info[property_name]:
        asset_to_update.info[property_name] = info[property_name]
        asset_to_update.update_info()
        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def update_list_info(property_name, id, info, context):
    try:
        asset_to_update = context.window_manager.at_asset_data[id] # type: Asset
    except:
        info[property_name] = ""
        return
    tag_list = utils.deduplicate(filter(None, [tag.strip(PROHIBITED_TRAILING_SYMBOLS).lower() for tag in info[property_name].split()]))
    info[property_name] = ' '.join(tag_list)
    if set(asset_to_update.info[property_name]) != set(tag_list):
        asset_to_update.info[property_name] = tag_list
        asset_to_update.update_info()
        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def update_id(info, context):

    try:
        wm = context.window_manager
        current_id = wm.at_asset_previews
        asset_data: AssetData
        asset_data = wm.at_asset_data # type: AssetData
        asset_data[current_id]
    except:
        info["id"] = ""
        return

    info["id"] = utils.get_slug(info["id"])
    if current_id != info["id"]:
        global current_search_query
        current_search_query = None
        new_id = asset_data.reload_asset(current_id, context, new_id = info["id"])
        if asset_data[new_id] in asset_data.search_result:
            asset_data.go_to_page(asset_data.get_asset_page(asset_data[new_id]))
            wm["at_current_page"] = asset_data.current_page
            wm.at_asset_previews = new_id

def update_dimension(property_name, id, info, context):
    try:
        asset_to_update = context.window_manager.at_asset_data[id] # type: Asset
    except:
        return

    current_value = -1
    dimensions = asset_to_update.info.get('dimensions')
    if dimensions is not None:
        try:
            current_value = dimensions[property_name]
        except:
            pass
    else:
        asset_to_update.info['dimensions'] = {}

    if current_value != info[property_name]:

        asset_to_update.info['dimensions'][property_name] = info[property_name]
        asset_to_update.update_info()

        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def get_updater(property_name, function):
    def updater(info, context):
        function(property_name, context.window_manager.at_asset_previews, info, context)
    return updater

class ATOOL_PROP_browser_asset_info(bpy.types.PropertyGroup):
    is_shown: bpy.props.BoolProperty(name='Show Info', default=True)
    is_id_shown: bpy.props.BoolProperty(name='Show ID Info', default=False)
    id: bpy.props.StringProperty(name='ID', update=update_id)
    name: bpy.props.StringProperty(name='Name', update=get_updater("name", update_string_info))
    url: bpy.props.StringProperty(name='URL', update=get_updater("url", update_string_info))
    author: bpy.props.StringProperty(name='Author', update=get_updater("author", update_string_info))
    author_url: bpy.props.StringProperty(name='Author URL', update=get_updater("author_url", update_string_info))
    licence: bpy.props.StringProperty(name='Licence', update=get_updater("licence", update_string_info))
    licence_url: bpy.props.StringProperty(name='Licence URL', update=get_updater("licence_url", update_string_info))
    description: bpy.props.StringProperty(name='Description', update=get_updater("description", update_string_info))
    tags: bpy.props.StringProperty(name='Tags', update=get_updater("tags", update_list_info))

    x: bpy.props.FloatProperty(name='X', update=get_updater("x", update_dimension), min = 0, default = 1)
    y: bpy.props.FloatProperty(name='Y', update=get_updater("y", update_dimension), min = 0, default = 1)
    z: bpy.props.FloatProperty(name='Z', update=get_updater("z", update_dimension), min = 0, default = 0.1)


def get_string_corrector(property_name):
    def updater(info, context):
        info[property_name] = info[property_name].strip(PROHIBITED_TRAILING_SYMBOLS)
    return updater

def correct_tags(info, context):
    info["tags"] = ' '.join(utils.deduplicate(filter(None, [tag.strip(PROHIBITED_TRAILING_SYMBOLS) for tag in info["tags"].split()])))

class ATOOL_PROP_template_info(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name', update=get_string_corrector("name"))
    tags: bpy.props.StringProperty(name='Tags', update=correct_tags)
    url: bpy.props.StringProperty(name='Url', update=get_string_corrector("url"))
    description: bpy.props.StringProperty(name='Description')
    author: bpy.props.StringProperty(name='Author', update=get_string_corrector("author"))
    author_url: bpy.props.StringProperty(name='Author URL') # need url checker
    licence: bpy.props.StringProperty(name='Licence', update=get_string_corrector("licence"))
    licence_url: bpy.props.StringProperty(name='Licence URL') # need url checker
    

    do_move_images: bpy.props.BoolProperty(name="Move Images", default = True, description="Move used images to the asset")
    # do_move_sub_asset: bpy.props.BoolProperty(name="Move Sub Assets", default = False, description="Move used sub assets to the asset")


class Asset:
    def __init__(self, path: os.DirEntry):
        self.info: dict
        self.path: str
        self.preview = None
        self.path = path.path
        self.id = path.name.lower()
        self.json_path = os.path.join(self.path, "__info__.json")
        self.gallery = os.path.join(self.path, "__gallery__")
        self.icon = os.path.join(self.path, "__icon__.png")
        self.lock = threading.RLock()

        if os.path.exists(self.icon) and not bpy.app.background:
            self.pre_load_icon()

    @cached_property
    def icon_id(self):
        if os.path.exists(self.icon):
            self.preview = utils_previews.load(self.icon, self.icon, 'IMAGE', False)
            return self.preview.icon_id
        else:
            return 'SEQ_PREVIEW'

    def pre_load_icon(self):
        self.icon_id
        len(self.preview.image_pixels_float)
        self.preview.icon_pixels_float = []

    def reload_preview(self, context):
        if not self.preview:
            if self.__dict__.get('icon_id'):
                del self.__dict__['icon_id']
            self.icon_id
            update_search(context.window_manager, context)
        self.preview.reload()
        len(self.preview.image_pixels_float)
        self.preview.icon_pixels_float = []
    
    def __getitem__(self, key):
        return self.info[key]

    def get(self, key, default = None):
        return self.info.get(key, default)

    def __setitem__(self, key, value):
        self.info[key] = value
    
    def standardize_info(self):

        dimensions = self.get('dimensions')
        if dimensions is None:
            self['dimensions'] = dimensions = {}

        if isinstance(dimensions, list):
            self['dimensions'] = {name: value for name, value in zip('xyz', dimensions)}


    @classmethod
    def default(cls, path: os.DirEntry): # type: (os.DirEntry) -> Asset
        asset = cls(path)
        try:
            global reading_time
            start = timer()
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
            reading_time += timer() - start
        except:
            if os.path.exists(asset.json_path):
                os.rename(asset.json_path, asset.json_path + "@error_" + utils.get_time_stamp())
            asset.info = asset.get_empty_info()
            with open(asset.json_path, 'w', encoding='utf-8') as json_file:
                json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

        asset.standardize_info()

        if not asset.update_system_tags():
            asset.update_search_set()

        return asset

    @classmethod
    def remout(cls, path: str): # type: (str) -> Asset
        asset = cls(path)
        try:
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
        except:
            if os.path.exists(asset.json_path):
                os.rename(asset.json_path, asset.json_path + "@error_" + utils.get_time_stamp())
            asset.info = asset.get_empty_info()
            with open(asset.json_path, 'w', encoding='utf-8') as json_file:
                json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

        asset.standardize_info()

        if not asset.update_system_tags():
            asset.update_search_set()

    @classmethod
    def auto(cls, path: os.DirEntry, asset_data_path, ignore_info = False): # type: (os.DirEntry, str, bool) -> typing.Tuple[str, Asset]
        info = {}
        preview = None

        id = os.path.splitext(path.name)[0]
        if os.path.dirname(path.path) != asset_data_path:
            if id:
                number = 2
                id_path = os.path.join(asset_data_path, id)
                while True:
                    if os.path.exists(id_path):
                        id_path = os.path.join(asset_data_path, id + f"_{number}")
                        number += 1
                    else:
                        break                 
            else:
                id_chars = "".join((string.ascii_lowercase, string.digits))
                while True:
                    id = ''.join(random.choice(id_chars) for _ in range(11))
                    id_path = os.path.join(asset_data_path, id)
                    if not os.path.exists(id_path):
                        break
            id_path = utils.PseudoDirEntry(id_path)
        else:
            id_path = path
        
        extra_folder = os.path.join(id_path.path, "__extra__")
        archive_folder = os.path.join(id_path.path, "__archive__")
        gallery_folder = os.path.join(id_path.path, "__gallery__")

        def get_info():
            is_ok, result = asset_parser.get_web(url, id_path.path)
            if is_ok:
                preview = result.pop("preview_path", None)
                return result, preview
            return None, None

        if path.is_file():
            file = utils.pathlib.Path(path)

            url = None
            auto_folder = file.parent
            url_files = [utils.pathlib.Path(auto_folder, file.stem + extension) for extension in utils.URL_EXTENSIONS]
            url_files = [url for url in url_files if url.exists() and url.type == "url"]
            for url_file in url_files:
                url = url_file.data
                utils.move_to_folder(url_file, extra_folder)

            if url:
                info, preview = get_info()

            if file.type == "zip":
                utils.extract_zip(file, id_path.path)
                utils.move_to_folder(file, archive_folder)
            else:
                utils.move_to_folder(file, id_path.path)
        else:
            id_path = utils.PseudoDirEntry(utils.move_to_folder(path.path, asset_data_path))

        files = utils.File_Filter.from_dir(id_path, ignore = ("__extra__", "__archive__"))

        old_info = None
        for existing_info in files.get_by_type("__info__"):
            if ignore_info:
                old_info = existing_info.data
                break
            else:
                return id, cls.default(id_path)

        zips = files.get_by_type("zip")
        if zips:
            for zip in zips:
                utils.extract_zip(str(zip), path=id_path.path)
                utils.move_to_folder(zip, archive_folder)
            files.update()

        if not info:
            for url_file in files.get_by_type("url"):
                url = url_file.data
                info, preview = get_info()
                if info:
                    break
        
        if not info:
            for megascan_info in files.get_by_type("megascan_info"):
                megascan_id = megascan_info.data.get('id')
                if not megascan_id:
                    continue
                url = f"https://quixel.com/megascans/home?assetId={megascan_id}"
                info, preview = get_info()
                if info:
                    previews = [str(file) for file in files.get_files() if file.name.lower().endswith("_preview.png")]
                    if previews:
                        preview = previews[0]
                    break

        if not info:
            for blendswap_info in files.get_by_type("blendswap_info"):
                url = blendswap_info.data
                info, preview = get_info()
                if info:
                    break
        
        if not info and asset_parser.seven_z:
            for sbsar in files.get_by_type("sbsar"):
                is_ok, result = asset_parser.get_info_from_sbsar(str(sbsar))
                if is_ok:
                    info = result
                    xml_attrs = info.pop("xml_attrs")

                    if info.get("author") in ("Allegorithmic", "Adobe") or all(map(xml_attrs.get, ("pkgurl", "label", "keywords", "category", "author", "authorurl"))):
                        sbsar_info = info

                        label = info["name"] # if is Adobe name == label
                        info_by_label = asset_parser.get_web_substance_source_info_by_label(label)
                        if info_by_label:
                            info = info_by_label
                            description = sbsar_info.get("description")
                            if description:
                                info["description"] = description


        # if sketchfab asset --> use folder structure and try to utilize info about the scene

        if not preview:
            if not files.get_by_type("__icon__"):
                posible_icons = [file for file in files.get_by_extension(('.png', '.jpg', '.jpeg')) if not file.is_meta]
                if not posible_icons:
                    # render asset's preview
                    pass
                if len(posible_icons) == 1:
                    preview = posible_icons[0]
        
        if preview:
            utils.move_to_folder(preview, gallery_folder)

        asset = cls.new(id_path, exist_ok = True)
        if ignore_info and old_info:
            asset.update_info(old_info)
        asset.update_info(info)
        asset.standardize_info()
        
        id = id.lower()
        return id, asset

    @classmethod
    def new(cls, path: typing.Union[str, os.DirEntry, utils.PseudoDirEntry], exist_ok = False): # type: (typing.Union[str, os.DirEntry, utils.PseudoDirEntry], bool) -> Asset
        """
        `path`: an asset path \n
        `info`: an info to update at creation
        """
        if not isinstance(path, (os.DirEntry, utils.PseudoDirEntry)):
            path = utils.PseudoDirEntry(path)
        os.makedirs(path.path, exist_ok = exist_ok)
        asset = cls(path)

        asset.info = asset.get_empty_info()
            
        with open(asset.json_path, 'w', encoding='utf-8') as json_file:
            json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

        asset.standardize_info()
        asset.update_system_tags()

        return asset

    @staticmethod
    def get_empty_info():
        info = {
            "name": "",
            "url": "",
            "author": "",
            "licence": "",
            "tags": [],
            "system_tags": [],
            "system_tags_mtime": 0,
            "ctime": time.time()
        }
        return info

    def move_to_folder(self, path_or_paths: typing.Union[str, typing.Iterable[str]], subfolder = None):
        with self.lock:
            if subfolder:
                os.makedirs(os.path.join(self.path, subfolder), exist_ok = True)

            if isinstance(path_or_paths, str):
                if subfolder:
                    new_path = os.path.join(self.path, subfolder, os.path.basename(path_or_paths))
                else:
                    new_path = os.path.join(self.path, os.path.basename(path_or_paths))
                shutil.move(path_or_paths, new_path)
            else:
                for path in path_or_paths:
                    if subfolder:
                        new_path = os.path.join(self.path, subfolder, os.path.basename(path))
                    else:
                        new_path = os.path.join(self.path, os.path.basename(path))
                    shutil.move(path, new_path)

            self.update_system_tags()

    def update_system_tags(self, do_force_update=False):
        with self.lock:
            mtime = os.path.getmtime(self.path)
            if mtime > self.info.get("system_tags_mtime", 0) or do_force_update:

                # ???
                os.makedirs(self.gallery, exist_ok=True)

                if not os.path.exists(self.icon):
                    self.generate_icon_from_gallery()

                extensions = {os.path.splitext(file.name)[1].lower() for file in os.scandir(self.path) if file.name not in META_FILES}

                system_tags = []

                if ".blend" in extensions:
                    system_tags.append("blend")
                
                if not extensions.isdisjoint(utils.IMAGE_EXTENSIONS):
                    system_tags.append("image")

                if ".zip" in extensions:
                    system_tags.append("zip")

                if ".sbsar" in extensions:
                    system_tags.append("sbsar")

                if not self.info["system_tags"]:
                    system_tags.append("no_type")

                self.info["system_tags"] = system_tags
                self.update_info({"system_tags_mtime": mtime})

                return True
            return False

    def update_search_set(self):
        with self.lock:
            search_set = []
            for key, value in self.info.items():
                if not value or key not in SEARCH_SET_INFO:
                    continue
                if isinstance(value, list):
                    search_set.extend([subvalue.lower() for subvalue in value])
                else:
                    search_set.extend(value.lower().split())
            self.search_set = set(search_set)
            self.ctime = os.path.getctime(self.json_path)

    def generate_icon_from_gallery(self):
        with self.lock:
            for file in [item for item in os.scandir(self.gallery) if item.is_file() and item.name.lower().endswith(tuple(utils.IMAGE_EXTENSIONS))]:
                with pillow_image.open(file.path) as image:
                    icon_path = image_utils.save_as_icon(image, self.path)
                    self.icon = icon_path
                    return icon_path
            return None

    def update_info(self, info = None):
        """ if `info` is `None` when only the json updates"""
        with self.lock:
            if info:
                for key, value in info.items():
                    current_value = self.info.get(key)
                    if current_value:
                        if isinstance(current_value, list):
                            for subvalue in value:
                                if subvalue not in current_value:
                                    current_value.append(subvalue)
                        elif isinstance(current_value, dict):
                            current_value.update(value)
                        else:
                            self.info[key] = value
                    else:
                        self.info[key] = value

            with open(self.json_path, 'r+', encoding='utf-8') as json_file:
                old_json = json.load(json_file)
                old_json.update(self.info)
                json_file.seek(0)
                json.dump(old_json, json_file, indent=4, ensure_ascii=False)
                json_file.truncate()

            self.update_search_set()

    def extract_zips(self):
        with self.lock:
            zip_paths = [file for file in os.scandir(self.path) if os.path.splitext(file.name)[1] == ".zip"]

            if not zip_paths:
                return []

            self.extra = os.path.join(self.path, "__extra__")
            os.makedirs(self.extra, exist_ok=True)

            extracted_files = []
            for zip_path in zip_paths:
                extracted_files.extend(utils.extract_zip(zip_path))
                os.rename(zip_path, os.path.join(self.extra, os.path.basename(zip_path)))

            self.info["system_tags"].remove("zip")
            self.update_search_set()

            return extracted_files

    def get_files(self, path = None, recursive = False) -> typing.List[os.DirEntry]:
        if not path:
            path = self.path
        files = []
        for file in os.scandir(path):
            if file.is_file():
                if file.name not in META_FILES:
                    files.append(file)
            else:
                if recursive:
                    files.extend(self.get_files(path = file.path, recursive = recursive))
        return files

    def get_imags(self, path = None, recursive = False, as_string = True):
        files = self.get_files(path = path, recursive = recursive)
        image_extensions = tuple(utils.IMAGE_EXTENSIONS)
        if as_string:
            return [file.path for file in files if file.name.lower().endswith(image_extensions)]
        else:
            return [file for file in files if file.name.lower().endswith(image_extensions)]

    @property
    def blend(self):
        blends = [file.path for file in os.scandir(self.path) if file.path.endswith(".blend")]
        return blends[0] if blends else None

    def get_web_info(self, context):
        with self.lock:
            url = self.info.get("url")
            if not url:
                return "No url."

            is_ok, result = asset_parser.get_web(url)

            if is_ok:
                self.update_info(result)
                view_3d_ui.update_ui()
                update_search(context.window_manager ,context)
                print("The info has been updated.")
                return "The info has been updated."
            else:
                print(result)
                return result


class AssetData(typing.Dict[str, Asset], dict):

    def __init__(self, library: str = None, auto: str = None, background = False):

        if background:
            self.background_init(library)
        else:
            self.default_init(library, auto)

        self.id_chars = "".join((string.ascii_lowercase, string.digits))
        self.re_compile()

    def default_init(self, library, auto):

        if library:
            if not os.path.exists(library):
                print("The specified library path does not exist.")
                library = None
        self.library = library

        if auto:
            if not os.path.exists(auto):
                print("The specified auto-folder path does not exist.")
                auto = None
        self.auto = auto

        config = utils.read_local_file("config.json")
        if config:
            for attr in ('library', 'auto'):
                value = config.get(attr)
                if value and os.path.exists(value) and os.path.isdir(value):
                    setattr(self, attr, value)

        self.search_result = []
        self.number_of_pages = 1
        self.current_page = 1
        self.assets_per_page = 24

    def background_init(self, library):
        self.library = library
        self.update_library()

    def __setitem__(self, key: str, value: Asset):
        dict.__setitem__(self, key.lower(), value)

    def __getitem__(self, key: str) -> Asset:
        return dict.__getitem__(self, key.lower())

    def update(self, context):

        if not self.library:
            return

        start = timer()

        self.update_library(context)

        if self.auto:
            self.update_auto(context)

        # self.update_remout()

        print(f"JSON reading time:\t {reading_time:.2f} sec")
        print(f"Asset import time:\t {timer() - start:.2f} sec")

    def update_library(self, context = None):
        self.clear()
        for folder in bl_utils.iter_with_progress(list(os.scandir(self.library)), prefix='Loading Assets'):
            if folder.is_dir():
                self[folder.name] = Asset.default(folder)

        if not bpy.app.background or not context:
            wm = context.window_manager
            wm.at_search = wm.at_search

    def update_auto(self, context = None):
        for file in bl_utils.iter_with_progress(list(os.scandir(self.auto)), prefix='Auto Importing Assets'):
            if not file.name.lower().endswith(utils.URL_EXTENSIONS):
                id, asset = Asset.auto(file, self.library)
                self[id] = asset

        if not bpy.app.background or not context:
            wm = context.window_manager
            wm.at_search = wm.at_search

    def update_remout(self):
        pass
    
    def re_compile(self):
        self.re_id = re.compile(r"id:([^\\\\\/:*?\"<>|]+)$", flags=re.IGNORECASE)

        self.re_no_icon = re.compile(r":no_icon", flags=re.IGNORECASE)
        self.re_more_tags = re.compile(r":more_tags", flags=re.IGNORECASE)
        self.re_no_url = re.compile(r":no_url", flags=re.IGNORECASE)
        self.re_is_intersection = re.compile(r":i", flags=re.IGNORECASE)

        self.re_exclude = re.compile(r"-([a-z0-9_-]+$)", flags=re.IGNORECASE)
        self.re_include = re.compile(r"[a-z0-9_-]+$", flags=re.IGNORECASE)

        self.re_bad_id = re.compile(r":bad_id", flags=re.IGNORECASE)
        self.re_bad_id_string = re.compile(r"^[a-zA-Z0-9]+$" , flags=re.IGNORECASE)

    def get_result(self, query):
        """
        `:no_icon` - with no preview \n
        `:more_tags` - less than 4 tags\n
        `:no_url` - with no url\n
        `:i` - intersection mode, default - subset\n
        `id:<asset id>` - find by id
        """
        
        assets = list(self.values())
        if not assets:
            return []

        assets.sort(key=operator.attrgetter('ctime'), reverse=True)
        # assets.sort(key=operator.attrgetter('id'))

        if not query:
            return assets

        query = query.lower().strip().split()
        exclude = []
        include = []
        only_certain_ids = False
        is_intersection = False

        for fragment in query:

            match = self.re_id.match(fragment)
            if match:
                id = match.group(1)
                asset = self.get(id)
                if not only_certain_ids:
                    assets = []
                if asset and asset not in assets:
                    assets.append(asset)
                only_certain_ids = True
                continue

            if self.re_no_icon.match(fragment):
                assets = [asset for asset in assets if not os.path.exists(asset.icon)]
                continue

            if self.re_more_tags.match(fragment):
                assets = [asset for asset in assets if len(asset.info["tags"]) < 4]
                continue

            if self.re_no_url.match(fragment):
                assets = [asset for asset in assets if not asset.info["url"]]
                continue

            if self.re_bad_id.match(fragment):
                assets = [asset for asset in assets if len(asset.id) == 11 and self.re_bad_id_string.match(asset.id)]
                continue

            if self.re_is_intersection.match(fragment):
                is_intersection = True
                continue

            match = self.re_exclude.match(fragment)
            if match:
                exclude.append(match.group(1))
                continue

            match = self.re_include.match(fragment)
            if match:
                include.append(match.group(0))
                continue
        
        exclude = set(exclude)
        include = set(include)

        if is_intersection:
            assets = [asset for asset in assets if (not include.isdisjoint(asset.search_set) or not include) and exclude.isdisjoint(asset.search_set)]
            assets.sort(key=lambda asset: len(include.intersection(asset.search_set)), reverse = True)
        else:
            assets = [asset for asset in assets if include.issubset(asset.search_set) and exclude.isdisjoint(asset.search_set)]
            
        return assets


    def search(self, search_query):
        self.current_page = 1
        self.search_result = self.get_result(search_query)
        self.number_of_pages = math.ceil(len(self.search_result)/self.assets_per_page)
        self.update_preview_items()

    def set_assets_per_page(self, assets_per_page):
        self.current_page = 1
        self.assets_per_page = assets_per_page
        self.number_of_pages = math.ceil(len(self.search_result)/self.assets_per_page)
        self.update_preview_items()

    def go_to_next_page(self):
        if not self.search_result:
            return
        if self.current_page == self.number_of_pages:
            self.current_page = 1
        else:
            self.current_page = self.current_page + 1
        self.update_preview_items()

    def go_to_prev_page(self):
        if not self.search_result:
            return
        if self.current_page - 1 == 0:
            self.current_page = self.number_of_pages
        else:
            self.current_page = self.current_page - 1
        self.update_preview_items()

    def go_to_page(self, page: int):
        if not self.search_result:
            return
        self.current_page = max(0, min(page , self.number_of_pages))
        self.update_preview_items()

    def get_asset_page(self, asset):
        asset_index = self.search_result.index(asset)
        for page_number in range(1, self.number_of_pages + 1):
            start = (page_number - 1) * self.assets_per_page
            end = start + self.assets_per_page
            if asset_index >= start and asset_index < end:
                return page_number

    def get_current_page_assets(self):
        if not self.search_result:
            return []
        start = (self.current_page - 1) * self.assets_per_page
        end = start + min(self.assets_per_page, len(self.search_result))
        return self.search_result[start:end]

    def update_preview_items(self):
        global current_browser_items

        assets = self.get_current_page_assets()
        if not assets:
            current_browser_items = EMPTY_ITEM_LIST
            return

        preview_items = []
        for i, asset in enumerate(assets):
            icon_id = asset.icon_id
            text = ' '.join(asset.info.get('tags', ''))
            preview_items.append((asset.id, asset.info["name"], text, icon_id, i))

        current_browser_items = preview_items

    def get_new_id(self):

        ids = {f.name for f in os.scandir(self.library)} | set(self.keys())

        while True:
            id = ''.join(random.choice(self.id_chars) for _ in range(11))
            if not id in ids:
                return id

    def ensure_unique_id(self, id):
        ids = {f.name for f in os.scandir(self.library)} | set(self.keys())

        index = 2
        initial_id = id
        while True:
            if not id in ids:
                return id
            id = initial_id + f"_{index}"
            index += 1

    def make_screen_shot(self, context, asset):
        space_data = context.space_data
        
        initial_show_overlays = space_data.overlay.show_overlays
        # not to use it if panels are not transparent
        initial_show_region_toolbar = space_data.show_region_toolbar
        initial_show_region_ui = space_data.show_region_ui
        
        space_data.overlay.show_overlays = False
        space_data.show_region_toolbar = False
        space_data.show_region_ui = False

        # bad
        bpy.ops.wm.redraw_timer(type='DRAW_WIN', iterations=1)

        time_stamp = utils.get_time_stamp()
        file_basename = "".join(("screen_shot_", time_stamp, ".png"))
        screen_shot_path = os.path.join(asset.gallery, file_basename)
        bpy.ops.screen.screenshot(filepath=screen_shot_path, full=False)
        
        space_data.overlay.show_overlays = initial_show_overlays
        space_data.show_region_toolbar = initial_show_region_toolbar
        space_data.show_region_ui = initial_show_region_ui

    def add_to_library(self, context, objects: typing.List[bpy.types.Object], info: dict):

        id = utils.get_slug(info.get("name", "")).strip('-_')
        if not id:
            id = utils.get_slug(utils.get_longest_substring([object.name for object in objects])).strip('-_')
        if not id:
            id = "untitled_" + utils.get_time_stamp()
        id = self.ensure_unique_id(id)

        asset_folder = os.path.join(self.library, id)

        if not info.get("name"):
            info["name"] = id.replace('_', ' ')

        do_move_images = info.pop('do_move_images')

        asset = Asset.new(asset_folder)
        asset.update_info(info)

        blend_file_path = os.path.join(asset_folder, id + ".blend")
        bpy.data.libraries.write(blend_file_path, set(objects), fake_user=True, path_remap = 'ABSOLUTE', compress = True)

        initialize_asset = utils.get_script('initialize_asset.py')
        argv = []
        if do_move_images:
            argv.append('-move_textures')
        bl_utils.run_blender(blend_file_path, initialize_asset, argv, use_atool=True, library_path=self.library)

        self[id] = asset

        threading.Thread(target=self.render_icon, args=(id, context)).start()

        update_search(context.window_manager, context)

        return id, blend_file_path

    def add_files_to_library(self, context, files, info: dict):
        
        id = utils.get_slug(info.get("name", "")).strip('-_')
        if not id:
            files = utils.File_Filter.from_files(files)
            
            blends = files.get_by_extension('.blend')
            if blends:
                blend = max(blends, key=os.path.getmtime)
                id = blend.stem

            if not id:
                images = files.get_by_type("image")
                if images:
                    image_names = [image.stem for image in images]
                    id = utils.get_slug(utils.get_longest_substring(image_names)).strip('-_')

            if not id:
                id = "untitled_" + utils.get_time_stamp()

        id = self.ensure_unique_id(id)
        asset_folder = os.path.join(self.library, id)

        if not info.get("name"):
            info["name"] = id.replace('_', ' ')

        asset = Asset.new(asset_folder)
        asset.update_info(info)

        asset.move_to_folder(files)

        self[id] = asset

        threading.Thread(target=self.render_icon, args=(id, context)).start()

        update_search(context.window_manager, context)

        return id

    def reload_asset(self, id, context, do_reimport=False, new_id = None):
        asset_folder = self[id].path
        del self[id]

        if new_id:
            number = 2
            new_path = os.path.join(self.library, new_id)
            while True:
                if os.path.exists(new_path):
                    new_path = os.path.join(self.library, new_id + f"_{number}")
                    number += 1
                else:
                    break
            os.rename(asset_folder, new_path)
            asset_folder = new_path

        if os.path.exists(asset_folder):
            if do_reimport:
                id, asset = Asset.auto(utils.PseudoDirEntry(asset_folder), self.library, ignore_info = True)
                self[id] = asset
            else:
                asset = Asset.default(utils.PseudoDirEntry(asset_folder))
                id = asset.id
                self[id] = asset
 
        asset.reload_preview(context)
        view_3d_ui.update_ui()
        update_search(context.window_manager, context)

        return id

    def web_get_asset(self, url, context):

        id = self.get_new_id()
        asset_folder = os.path.join(self.library, id)
        os.makedirs(asset_folder)

        is_ok, result = asset_parser.get_web(url, asset_folder, True)
        if not is_ok:
            os.rmdir(asset_folder)
            return False, result

        id = result.get("id")
        if id:
            new_asset_path = os.path.join(self.library, id)
            os.rename(asset_folder, new_asset_path)
            asset_folder = new_asset_path
        preview_path = result.pop("preview_path", None)

        asset = Asset.new(asset_folder, exist_ok=True)
        asset.update_info(result)

        if preview_path:
            preview_path = os.path.join(asset_folder, os.path.basename(preview_path))
            asset.move_to_folder(preview_path, "__gallery__")
            asset.generate_icon_from_gallery()

        self[id] = asset

        update_search(context.window_manager, context)
        view_3d_ui.update_ui()

        return True, id

    def icon_from_clipboard(self, id, context): 
        result = image_utils.save_as_icon_from_clipboard(self[id].path)
        if result:
            self[id].reload_preview(context)

    def render_icon(self, id, context):

        jobs = {}

        asset = self[id]
        result_path = asset.icon

        blends = [file.path for file in os.scandir(asset.path) if file.path.endswith(".blend")]
        if blends:
            blend = max(blends, key=os.path.getmtime)
            job = {
                'result_path': result_path,
                'filepath': blend
            }
            jobs['objects'] = [job]
        else:
            images = asset.get_imags()
            if images:

                invert_normal_y = False
                material_settings = asset.get('material_settings') # type: dict
                if material_settings:
                    invert_normal_y = bool(material_settings.get("Y- Normal Map"))

                invert_normal_y_dict = {image: invert_normal_y for image in images}

                # terrable
                disp_min_max_mult = 1
                for image in images:
                    type = type_definer.get_type(image)
                    if 'displacement' in type:
                        image = image_utils.Image(image)
                        image.type = type
                        file_info = asset.get("file_info")
                        if not file_info:
                            asset["file_info"] = file_info = {}
                        image.process(file_info = file_info)
                        for channel, subtype in image.iter_type():
                            if subtype == 'displacement':
                                min_max = image.min_max.get(channel)
                                disp_min_max_mult = 1/abs(min_max[1] - min_max[0])
                        asset.update_info()
                        

                displacement_scale = 0.1
                dimensions = asset.get('dimensions')
                if dimensions:
                    x = dimensions.get('x', 1)
                    y = dimensions.get('y', 1)
                    z = dimensions.get('z', 0.1)
                    if z:
                        z /= min((x, y))
                        displacement_scale = z
                displacement_scale *= 1.9213 # sphere uv_multiplier 
                displacement_scale *= disp_min_max_mult

                job = {
                    'result_path': result_path,
                    'files': images,
                    'invert_normal_y': invert_normal_y_dict,
                    'displacement_scale': displacement_scale
                }
                jobs['type_definer_config'] = shader_editor_operator.get_definer_config(context)
                jobs['materials'] = [job]

        if not jobs:
            return

        jobs_path = os.path.join(bpy.app.tempdir, 'atool_icon_render_jobs.json')

        with open(jobs_path, 'w', encoding='utf-8') as jobs_file:
            json.dump(jobs, jobs_file, indent = 4, ensure_ascii = False)

        initialize_asset = utils.get_script('render_icon.py')
        argv = ['-jobs_path', f'"{jobs_path}"' if " " in jobs_path else jobs_path]
        bl_utils.run_blender(script = initialize_asset, argv = argv, use_atool=True, library_path=self.library)

        print(f"An icon for the asset '{asset.id}' has been updated.")
        asset.reload_preview(context)

    def is_sub_asset(self, path):
        if os.path.commonpath((path, self.library)) == self.library:
            return True
        # remout = [asset.path for asset in self.values() if asset.is_remout]
        return False

    def move_asset_to_desktop(self, id, context):

        asset_folder = self[id].path
        utils.move_to_folder(asset_folder, utils.get_desktop())
        
        del self[id]

        update_search(context.window_manager, context)
        view_3d_ui.update_ui()