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
import subprocess

import bpy
from PIL import Image as pillow_image
from cached_property import cached_property

import _bpy # type: ignore
utils_previews = _bpy._utils_previews
del _bpy

if __package__:
    from . import asset_parser
    from . import utils
    from . import bl_utils
    from . import image_utils
else: # for external testing
    import asset_parser
    import utils
    import bl_utils
    import image_utils
    
    # till i find a better way
    # import shader_editor_operator

register = bl_utils.Register(globals())

ID_CHARS = ''.join((string.ascii_lowercase, string.digits))
PROHIBITED_TRAILING_SYMBOLS = ' *-~:'
META_FILES = {'__icon__.png', '__info__.json', '__gallery__', '__extra__', '__archive__'}

EMPTY_ITEM_LIST = [('/', "Empty :(", '＾-＾', 'GHOST_DISABLED', 0)]
current_browser_items = EMPTY_ITEM_LIST
def get_browser_items(self, context):
    return current_browser_items

register.property(
    'at_asset_previews',
    bpy.props.EnumProperty(items=get_browser_items)
)


def update_search(wm, context):

    asset_data = wm.at_asset_data # type: AssetData
    try: 
        current_asset = asset_data.get(wm.at_asset_previews)
    except: 
        return # if data is not loaded yet
    
    wm["at_asset_previews"] = 0
    wm["at_current_page"] = 1

    asset_data.search(wm.at_search)
    if current_asset in asset_data.search_result:
        asset_data.go_to_page(asset_data.get_asset_page(current_asset))
        wm["at_current_page"] = asset_data.current_page
        wm.at_asset_previews = current_asset.id

register.property(
    'at_search', 
    bpy.props.StringProperty(
            name="", 
            description= \
            ':no_icon - with no preview \n'\
            ':more_tags - less than 4 tags\n'\
            ':no_url - with no url\n'\
            ':i - intersection mode, default - subset\n'\
            '-<tag> to exclude the tag\n'\
            'id:<asset id> - find by id\n'\
            '\n'\
            'Auto added tags: blend, image, zip, sbsar, no_type',
            update=update_search, 
            default='',
            options={'TEXTEDIT_UPDATE'}
        )
    )

def update_page(wm, context):
    asset_data = wm.at_asset_data # type: AssetData
    asset_data.go_to_page(wm["at_current_page"])
    wm["at_current_page"] = asset_data.current_page
    wm["at_asset_previews"] = min(wm["at_asset_previews"], len(get_browser_items(None, None)) - 1)

register.property(
    'at_current_page',
    bpy.props.IntProperty(name="Page", description="Page", update=update_page, min=1, default=1)
)

def update_assets_per_page(wm, context):
    wm["at_current_page"] = 1
    wm["at_asset_previews"] = 0
    wm.at_asset_data.set_assets_per_page(wm["at_assets_per_page"])

register.property(
    'at_assets_per_page',
    bpy.props.IntProperty(name="Assets Per Page", update=update_assets_per_page, min=1, default=24, soft_max=104)
)


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
        # context.window_manager.at_current_search_query = ''
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
        # context.window_manager.at_current_search_query = ''
        update_search(context.window_manager, None)

def update_id(info, context):

    try:
        wm = context.window_manager
        current_id = wm.at_asset_previews
        asset_data = wm.at_asset_data # type: AssetData
        asset_data[current_id]
    except:
        info["id"] = ""
        return

    new_id = info["id"] = info["id"].strip()
    if new_id == current_id:
        return
    
    slug = utils.get_slug(new_id)
    info["id"] = slug
    if slug == current_id:
        return
    
    # context.window_manager.at_current_search_query = ''
    new_id = asset_data.reload_asset(current_id, context, new_id = slug)
    
    if asset_data[new_id] in asset_data.search_result: # focus
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

        # context.window_manager.at_current_search_query = ''
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

register.property(
    'at_browser_asset_info',
    bpy.props.PointerProperty(type=ATOOL_PROP_browser_asset_info)
)

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
    do_move_sub_assets: bpy.props.BoolProperty(name="Move Sub Assets", default = False, description="Move used sub assets to the asset")

register.property(
    'at_template_info',
    bpy.props.PointerProperty(type=ATOOL_PROP_template_info)
)

SEARCH_SET_INFO = {'name', 'url', 'author', 'tags', 'system_tags'}
SEARCH_SET_INFO_INFLECTABLE = {'name', 'tags', 'url', 'system_tags'}

BASIC_TYPE_ATTRS = {'name', 'url', 'author', 'path', 'id', 'ctime', 'mtime'}
STRING_TYPE_ATTRS = {'name', 'url', 'author', 'path', 'id'}

class Asset:
    name: str
    url: str
    author: str
    tags: typing.List[str]
    system_tags: typing.List[str]
    system_tags_mtime: float
    ctime: float
    
    def __init__(self, path: os.DirEntry):
        self.info: dict
        self.path: str
        self.preview = None
        self.path = path.path
        self.id: str
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
    
    def __getattr__(self, key):
        return self.info[key] if key in self.info else super().__getattribute__(key)
    
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
        
        global json_reading_time
        start = timer()

        try:
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
        except:
            if os.path.exists(asset.json_path):
                os.rename(asset.json_path, utils.ensure_unique_path(asset.json_path + "@error_" + utils.get_time_stamp()))
            asset.info = asset.get_empty_info()
            with open(asset.json_path, 'w', encoding='utf-8') as json_file:
                json.dump(asset.info, json_file, indent=4, ensure_ascii=False)
                
            import traceback
            traceback.print_exc()
            
        json_reading_time += timer() - start
        

        asset.standardize_info()

        if not asset.update_system_tags():
            asset.update_search_set()

        return asset

    @classmethod
    def remote(cls, path: str): # type: (str) -> Asset
        asset = cls(path)
        
        try:
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
        except:
            return None

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


        # if SketchFab asset --> use folder structure and try to utilize info about the scene

        if not preview:
            if not files.get_by_type("__icon__"):
                possible_icons = [file for file in files.get_by_extension(('.png', '.jpg', '.jpeg')) if not file.is_meta]
                if not possible_icons:
                    # render asset's preview
                    pass
                if len(possible_icons) == 1:
                    preview = possible_icons[0]
        
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

    @utils.synchronized
    def move_to_folder(self, path_or_paths: typing.Union[str, typing.Iterable[str]], subfolder = None):
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

    @utils.synchronized
    def update_system_tags(self, do_force_update=False):

        mtime = os.path.getmtime(self.path)
        if not (mtime > self.info.get("system_tags_mtime", 0) or do_force_update):
            return False

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

    @utils.synchronized
    def update_search_set(self):
        
        self.search_name = ''
        search_set = []
        for key, value in self.info.items():
            
            if not value or key not in SEARCH_SET_INFO:
                continue
            
            if type(value) == str:
                self.search_name += value
            elif type(value) == list:
                self.search_name += ' '.join(value)
            
            if type(value) != list:
                value = utils.split(value)
                
            if key in SEARCH_SET_INFO_INFLECTABLE:
                search_set.extend(utils.singularize(subvalue.lower()) for subvalue in value)
                search_set.extend(utils.pluralize(subvalue.lower()) for subvalue in value)

            search_set.extend(subvalue.lower() for subvalue in value)
                
        self.search_set = set(search_set)
        self.ctime = self.get('ctime', os.path.getctime(self.json_path))

    @utils.synchronized
    def generate_icon_from_gallery(self):
        for file in [item for item in os.scandir(self.gallery) if item.is_file() and item.name.lower().endswith(tuple(utils.IMAGE_EXTENSIONS))]:
            with pillow_image.open(file.path) as image:
                icon_path = image_utils.save_as_icon(image, self.path)
                self.icon = icon_path
                return icon_path
        return None

    @utils.synchronized
    def update_info(self, info = None, update = True):
        """ if `info` is `None` when only the json updates"""
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
            data = json.load(json_file)
            if update:
                data.update(self.info)
            else:
                data = self.info
            json_file.seek(0)
            json.dump(data, json_file, indent=4, ensure_ascii=False)
            json_file.truncate()

        self.update_search_set()

    @utils.synchronized
    def extract_zips(self):
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

    def get_images(self, path = None, recursive = False, as_string = True):
        files = self.get_files(path = path, recursive = recursive)
        image_extensions = tuple(utils.IMAGE_EXTENSIONS)
        if as_string:
            return [file.path for file in files if file.name.lower().endswith(image_extensions)]
        else:
            return [file for file in files if file.name.lower().endswith(image_extensions)]

    @property
    def blend(self):
        return utils.get_last_file(self.path, ".blend", recursively = False)

    @property
    def is_blend(self):
        for file in os.scandir(self.path):
            if file.is_file() and file.name.lower().endswith('.blend'):
                return True
        return False

    @utils.synchronized
    def get_web_info(self, context):
        url = self.info.get("url")
        if not url:
            return "No url."

        is_ok, result = asset_parser.get_web(url)

        if is_ok:
            self.update_info(result)
            context.window_manager.current_browser_asset_id = ''
            update_search(context.window_manager ,context)
            print("The info has been updated.")
            return "The info has been updated."
        else:
            print(result)
            return result
    
    @property
    def mtime(self):
        return max(os.path.getmtime(self.json_path), os.path.getmtime(self.path))

class AssetData(typing.Dict[str, Asset], dict):

    def __init__(self, library: str = None, auto: str = None, background = bpy.app.background):

        self.library: str = None
        self.auto: str = None
        if library:
            self.check_path(library, 'library')
        if auto:
            self.check_path(auto, 'auto')

        self.re_compile()
        self.search_result = []
        self.number_of_pages = 1
        self.current_page = 1
        self.assets_per_page = 24

        self.asset_paths = set()
        self.asset_by_path = {}

        self.lock = threading.RLock()

    def check_path(self, path: str, type: str):

        if path and os.path.exists(path):
            setattr(self, type, path)
            return

        config = utils.read_local_file("config.json")
        if config:
            value = config.get(type)
            if value and os.path.isdir(value) and os.path.exists(value):
                setattr(self, type, value)
                print(f"Fallback to config for {type} path.")
                return

        print(f"No valid {type} path is specified.")

    def __setitem__(self, key: str, value: Asset):
        dict.__setitem__(self, key.lower(), value)
        self.asset_paths.add(value.path)
        self.asset_by_path[value.path] = value

    def __delitem__(self, key: str):
        path = self[key].path
        dict.__delitem__(self, key.lower())
        self.asset_paths.remove(path)
        self.asset_by_path.pop(path)

    def __getitem__(self, key: str) -> Asset:
        return dict.__getitem__(self, key.lower())

    @utils.synchronized
    def update(self, context):

        addon_preferences = context.preferences.addons[__package__].preferences
        self.check_path(addon_preferences.library_path, 'library')
        self.check_path(addon_preferences.auto_path, 'auto')

        if not self.library:
            return

        start = timer()

        self.update_library(context)
        self.update_auto(context)
        # self.update_remote()

        print(f"Asset import time:\t {timer() - start:.2f} sec")

    @utils.synchronized
    def update_library(self, context = None):
        if not self.library:
            return
        
        self.clear()
        
        global json_reading_time
        json_reading_time = 0
        
        for folder in bl_utils.iter_with_progress(list(os.scandir(self.library)), prefix='Loading Assets'):
            if folder.is_dir():
                self[folder.name] = Asset.default(folder)
                
        print(f"JSON reading time:\t {json_reading_time:.2f} sec")

        if not bpy.app.background and context:
            wm = context.window_manager
            if hasattr(wm, 'at_search'):
                wm.at_search = wm.at_search

    @utils.synchronized
    def update_auto(self, context = None):
        if not self.auto:
            return

        for file in bl_utils.iter_with_progress(list(os.scandir(self.auto)), prefix='Auto Importing Assets'):
            if not file.name.lower().endswith(utils.URL_EXTENSIONS):
                id, asset = Asset.auto(file, self.library)
                self[id] = asset

        if not bpy.app.background and context:
            wm = context.window_manager
            if hasattr(wm, 'at_search'):
                wm.at_search = wm.at_search

    def update_remote(self):
        pass
    
    def re_compile(self):
        self.re_id = re.compile(r'id:"(.+)"$|id:(.+)$', flags=re.IGNORECASE)
        self.re_sort = re.compile(r"(?:sort|s):([a-z_]+)(:rev)?", flags=re.IGNORECASE)
        self.re_bad_id_string = re.compile(r"^[a-zA-Z0-9]+$" , flags=re.IGNORECASE)
        self.re_query_fragment = re.compile(r'\S+".+?"|\S+', flags=re.IGNORECASE)

    def get_result(self, query):
        """ See the `at_search: bpy.props.StringProperty` definition"""
        
        assets = list(self.values())
        if not assets:
            return []

        assets.sort(key=operator.attrgetter('ctime'), reverse=True)

        if not query:
            return assets

        query = self.re_query_fragment.findall(query.lower().strip()) # type: typing.List[str]
        exclude = []
        include = []
        sort_stack = []
        only_certain_ids = False
        is_intersection = False
        is_partial = True

        for fragment in query:

            match = self.re_id.match(fragment)
            if match:
                id = match.group(1)
                if not id:
                    id = match.group(2)
                    
                asset = self.get(id)
                if not only_certain_ids:
                    assets = []
                if asset and asset not in assets:
                    assets.append(asset)
                only_certain_ids = True
                continue

            if fragment == ':no_icon':
                assets = [asset for asset in assets if not os.path.exists(asset.icon)]
                continue

            if fragment == ':more_tags':
                assets = [asset for asset in assets if len(asset.info["tags"]) < 4]
                assets.sort(key = lambda asset: len(asset.info["tags"]), reverse = True)
                continue

            if fragment == ':no_url':
                assets = [asset for asset in assets if not asset.info["url"]]
                continue

            if fragment == ':bad_id':
                assets = [asset for asset in assets if len(asset.id) == 11 and self.re_bad_id_string.match(asset.id)]
                continue

            if fragment == ':i':
                is_intersection = True
                continue
            
            if fragment == ':w':
                is_partial = False
                continue
            
            match = self.re_sort.match(fragment)
            if match:
                
                sort_by = match.group(1)
                if not sort_by in BASIC_TYPE_ATTRS:
                    continue
                
                do_reverse = not bool(match.group(2))
                sort_stack.append((sort_by, do_reverse))
                continue
            
            if fragment.startswith('-'):
                exclude.append(fragment[1:])
                continue
            
            include.append(fragment)
            
        def sort_assets(assets: list):
            for sort_by, do_reverse in sort_stack:
                
                if sort_by in STRING_TYPE_ATTRS:
                    assets.sort(key = lambda x: getattr(x, sort_by).lower(), reverse = not do_reverse)
                    continue
                
                assets.sort(key=operator.attrgetter(sort_by), reverse = do_reverse)
        
        exclude = set(exclude)
        include = set(include)

        if is_partial:
            if is_intersection:
                assets = [asset for asset in assets if any(fragment in asset.search_name for fragment in include) and exclude.isdisjoint(asset.search_set)]
            else:
                assets = [asset for asset in assets if all(fragment in asset.search_name for fragment in include) and exclude.isdisjoint(asset.search_set)]
        
            assets.sort(key=lambda asset: sum(fragment in asset.search_name for fragment in include), reverse = True)
        else:
            if is_intersection:
                assets = [asset for asset in assets if (not include.isdisjoint(asset.search_set) or not include) and exclude.isdisjoint(asset.search_set)]
            else:
                assets = [asset for asset in assets if include.issubset(asset.search_set) and exclude.isdisjoint(asset.search_set)]
                
            assets.sort(key=lambda asset: len(include.intersection(asset.search_set)), reverse = True)
            
        sort_assets(assets)

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
            id = ''.join(random.choice(ID_CHARS) for _ in range(11))
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

    @utils.synchronized
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
        do_move_sub_assets = info.pop('do_move_sub_assets')

        asset = Asset.new(asset_folder)
        asset.update_info(info)

        blend_file_path = os.path.join(asset_folder, id + ".blend")
        bpy.data.libraries.write(blend_file_path, set(objects), fake_user=True, path_remap = 'ABSOLUTE', compress = True)

        initialize_asset = utils.get_script('initialize_asset.py')
        argv = []
        if do_move_images:
            argv.append('-move_textures')
        if do_move_sub_assets:
            argv.append('-move_sub_assets')
        bl_utils.run_blender(blend_file_path, initialize_asset, argv, use_atool=True, library_path=self.library)

        self[id] = asset

        threading.Thread(target=self.render_icon, args=(id, context)).start()

        update_search(context.window_manager, context)

        return id, blend_file_path

    @utils.synchronized
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

    @utils.synchronized
    def reload_asset(self, id: str, context: bpy.types.Context = None, do_reimport = False, new_id = None) -> str:
        asset_folder = self[id].path
        del self[id]

        if new_id:
            new_path = os.path.join(self.library, new_id)
            new_path = utils.ensure_unique_path(new_path)
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

        if context:
            asset.reload_preview(context)
            context.window_manager.current_browser_asset_id = ''
            update_search(context.window_manager, context)

        return id

    @utils.synchronized
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
            new_asset_path = utils.ensure_unique_path(new_asset_path)
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
        context.window_manager.current_browser_asset_id = ''

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
            images = asset.get_images()
            if images:
                
                from . import shader_editor_operator
                type_definer_config = shader_editor_operator.get_definer_config(context)
                type_definer_config.set_common_prefix_from_paths(images)

                invert_normal_y = False
                material_settings = asset.get('material_settings') # type: dict
                if material_settings:
                    invert_normal_y = bool(material_settings.get("Y- Normal Map"))

                invert_normal_y_dict = {image: invert_normal_y for image in images}

                multiplier = 1
                for image in images:
                    image = image_utils.Image.from_asset_info(image, asset.info, type_definer_config = type_definer_config)
                    if 'displacement' in image.type:
                        for channel, subtype in image.iter_type():
                            if subtype == 'displacement':
                                min_max = image.get_min_max(channel)
                                multiplier = 1/abs(min_max[1] - min_max[0])
                        image.update_source()
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
                displacement_scale *= multiplier

                job = {
                    'result_path': result_path,
                    'files': images,
                    'invert_normal_y': invert_normal_y_dict,
                    'displacement_scale': displacement_scale
                }
                
                jobs['type_definer_config'] = type_definer_config.dict
                jobs['materials'] = [job]

        if not jobs:
            return

        jobs_path = utils.ensure_unique_path(os.path.join(bpy.app.tempdir, 'atool_icon_render_jobs.json'))
        with open(jobs_path, 'w', encoding='utf-8') as jobs_file:
            json.dump(jobs, jobs_file, indent = 4, ensure_ascii = False)

        render_icon = utils.get_script('render_icon.py')
        argv = ['-jobs_path', f'"{jobs_path}"' if " " in jobs_path else jobs_path]
        bl_utils.run_blender(script = render_icon, argv = argv, use_atool=True, library_path=self.library, stdout = subprocess.DEVNULL)

        print(f"An icon for the asset '{asset.id}' has been updated.")
        asset.reload_preview(context)

    def is_sub_asset(self, path):
        path = bl_utils.abspath(path)

        if os.path.isfile(path):
            path = os.path.dirname(path)

        if utils.get_path_set(path).isdisjoint(self.asset_paths):
            return False
        
        return True

    def get_asset_by_path(self, path) -> Asset:
        path = bl_utils.abspath(path)

        if os.path.isfile(path):
            path = os.path.dirname(path)

        intersection = utils.get_path_set(path).intersection(self.asset_paths)
        if not intersection:
            return None

        return self.asset_by_path[max(intersection, key = len)]

    @utils.synchronized
    def move_asset_to_desktop(self, id, context):

        asset_folder = self[id].path
        utils.move_to_folder(asset_folder, utils.get_desktop())
        
        del self[id]

        update_search(context.window_manager, context)
        context.window_manager.current_browser_asset_id = ''

    def get_assets_from_objects(self, objects) -> typing.Dict[bpy.types.Object, typing.List[Asset]]:
        
        def get_asset_by_path(path, assets = {}) -> Asset:

            asset = assets.get(path)
            if asset:
                return asset

            assets[path] = asset = self.get_asset_by_path(path)
            return asset
        
        dependencies = bl_utils.Dependency_Getter()

        result = {} # type: typing.Dict[bpy.types.Object, typing.List[Asset]]
        for object in objects:

            assets = []
            for dependency in dependencies.get_object_dependencies_by_type(object):
                asset = get_asset_by_path(bl_utils.get_block_abspath(dependency))
                if asset:
                    assets.append(asset)

            if assets:
                result[object] = utils.deduplicate(assets)
                
        return result
        

register.property(
    'at_asset_data',
    AssetData()
)