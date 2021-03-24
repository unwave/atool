import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import time
import typing # heavy
from datetime import datetime
from timeit import default_timer as timer


import bpy
# import validators
# import imagesize
from PIL import Image as pillow_image

from . import asset_parser
from . utils import *
from . view_3d_ui import update_ui

current_browser_items = [('/', "Empty :(", '＾-＾', 'GHOST_DISABLED', 0)]
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
        asset_data = wm.at_asset_data
        current_asset = asset_data.data.get(wm.at_asset_previews)
        
        wm["at_asset_previews"] = 0
        wm["at_current_page"] = 1

        asset_data.search(search_query)
        if current_asset in asset_data.search_result:
            asset_data.go_to_page(asset_data.get_asset_page(current_asset))
            wm["at_current_page"] = asset_data.current_page
            wm.at_asset_previews = current_asset.id


def update_page(wm, context):
    asset_data = wm.at_asset_data
    asset_data.go_to_page(wm["at_current_page"])
    wm["at_current_page"] = asset_data.current_page
    wm["at_asset_previews"] = min(wm["at_asset_previews"], len(get_browser_items(None, None)) - 1)

def update_assets_per_page(wm, context):
    wm["at_current_page"] = 1
    wm["at_asset_previews"] = 0
    wm.at_asset_data.set_assets_per_page(wm["at_assets_per_page"])

def update_string_info(info, property_name, id, context):
    try:
        asset_to_update = context.window_manager.at_asset_data.data[id]
    except:
        info[property_name] = ""
        return
    info[property_name] = info[property_name].strip(PROHIBITED_TRAILING_SYMBOLS)
    if asset_to_update.info[property_name] != info[property_name]:
        asset_to_update.info[property_name] = info[property_name]
        asset_to_update.update_info()
        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def update_object_name(info, context):
    update_string_info(info, "name", context.object.get("atool_id"), context)

def update_object_url(info, context):
    update_string_info(info, "url", context.object.get("atool_id"), context)

def update_object_author(info, context):
    update_string_info(info, "author", context.object.get("atool_id"), context)

def update_object_licence(info, context):
    update_string_info(info, "licence", context.object.get("atool_id"), context)

def update_browser_name(info, context):
    update_string_info(info, "name", context.window_manager.at_asset_previews, context)

def update_browser_url(info, context):
    update_string_info(info, "url", context.window_manager.at_asset_previews, context)

def update_browser_author(info, context):
    update_string_info(info, "author", context.window_manager.at_asset_previews, context)

def update_browser_licence(info, context):
    update_string_info(info, "licence", context.window_manager.at_asset_previews, context)


def update_list_info(info, property_name, id, context):
    try:
        asset_to_update = context.window_manager.at_asset_data.data[id]
    except:
        info[property_name] = ""
        return
    tag_list = deduplicate(filter(None, [tag.strip(PROHIBITED_TRAILING_SYMBOLS) for tag in info[property_name].split()]))
    info[property_name] = ' '.join(tag_list)
    if set(asset_to_update.info[property_name]) != set(tag_list):
        asset_to_update.info[property_name] = tag_list
        asset_to_update.update_info()
        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def update_object_tags(info, context):
    update_list_info(info, "tags", context.object.get("atool_id"), context)

def update_browser_tags(info, context):
    update_list_info(info, "tags", context.window_manager.at_asset_previews, context)

class ATOOL_PROP_asset_info(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name', update=update_object_name)
    url: bpy.props.StringProperty(name='Url', update=update_object_url)
    author: bpy.props.StringProperty(name='Author', update=update_object_author)
    licence: bpy.props.StringProperty(name='Licence', update=update_object_licence)
    tags: bpy.props.StringProperty(name='Tags', update=update_object_tags)

class ATOOL_PROP_browser_asset_info(bpy.types.PropertyGroup):
    is_shown: bpy.props.BoolProperty(name='Info', default=True)
    name: bpy.props.StringProperty(name='Name', update=update_browser_name)
    url: bpy.props.StringProperty(name='Url', update=update_browser_url)
    author: bpy.props.StringProperty(name='Author', update=update_browser_author)
    licence: bpy.props.StringProperty(name='Licence', update=update_browser_licence)
    tags: bpy.props.StringProperty(name='Tags', update=update_browser_tags)


def correct_name(info, context):
    info["name"] = info["name"].strip(PROHIBITED_TRAILING_SYMBOLS)

def correct_url(info, context):
    info["url"] = info["url"].strip(PROHIBITED_TRAILING_SYMBOLS)

def correct_author(info, context):
    info["author"] = info["author"].strip(PROHIBITED_TRAILING_SYMBOLS)

def correct_licence(info, context):
    info["licence"] = info["licence"].strip(PROHIBITED_TRAILING_SYMBOLS)

def correct_tags(info, context):
    info["tags"] = ' '.join(deduplicate(filter(None, [tag.strip(PROHIBITED_TRAILING_SYMBOLS) for tag in info["tags"].split()])))

class ATOOL_PROP_template_info(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name', update=correct_name)
    url: bpy.props.StringProperty(name='Url', update=correct_url)
    author: bpy.props.StringProperty(name='Author', update=correct_author)
    licence: bpy.props.StringProperty(name='Licence', update=correct_licence)
    tags: bpy.props.StringProperty(name='Tags', update=correct_tags)


class Asset():
    def __init__(self, path: os.DirEntry):
        self.path = path.path
        self.id = path.name
        self.json_path = os.path.join(self.path, "__info__.json")
        self.gallery = os.path.join(self.path, "__gallery__")
        self.icon = os.path.join(self.path, "__icon__.png")

    @classmethod
    def default(cls, path: os.DirEntry):
        asset = cls(path)
        try:
            global reading_time
            start = timer()
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
            reading_time += timer() - start
        except:
            if os.path.exists(asset.json_path):
                os.rename(asset.json_path, asset.json_path + "@error_" + datetime.now().strftime('%y%m%d_%H%M%S'))
            asset.info = asset.get_empty_info()
            with open(asset.json_path, 'w', encoding='utf-8') as json_file:
                json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

        if not asset.update_system_tags():
            asset.update_search_set()

        return asset

    @classmethod
    def auto(cls, path: os.DirEntry, asset_data_path):

        info = {}
        preview = None

        id = os.path.splitext(path.name)[0]
        if id:
            number = 2
            while True:
                id_path = os.path.join(asset_data_path, id)
                if not os.path.exists(id_path):
                    break
                else:
                    id_path = os.path.join(asset_data_path, id + f"_{number}")
        else:
            id_chars = "".join((string.ascii_lowercase, string.digits))
            while True:
                id = ''.join(random.choice(id_chars) for _ in range(11))
                id_path = os.path.join(asset_data_path, id)
                if not os.path.exists(id_path):
                    break
        id_path = PseudoDirEntry(id_path)
        extra_folder = os.path.join(id_path.path, "__extra__")
        archive_folder = os.path.join(id_path.path, "__archive__")
        gallery_folder = os.path.join(id_path.path, "__gallery__")

        def get_info():
            is_success, result = asset_parser.get_web_info(url, id_path.path)
            if is_success:
                preview = result.pop("preview_path", None)
                return result, preview
            return None, None

        if path.is_file():
            file = pathlib.Path(path)

            url = None
            auto_folder = file.parent
            url_files = [pathlib.Path(auto_folder, file.stem + extension) for extension in URL_EXTENSIONS]
            url_files = [url for url in url_files if url.exists() and url.type == "url"]
            for url_file in url_files:
                url = url_file.data
                move_to_folder(url_file, extra_folder)

            if url:
                info, preview = get_info()

            if file.type == "zip":
                extract_zip(file, id_path.path)
                move_to_folder(file, archive_folder)
            else:
                move_to_folder(file, id_path.path)
        else:
            id_path = PseudoDirEntry(move_to_folder(path.path, asset_data_path))

        files = File_Filter(id_path, ignore = ("__extra__", "__archive__"))

        if files.get_by_type("__info__"):
            return id, cls.default(id_path)

        for zip in files.get_by_type("zip"):
            extract_zip(str(zip))
            move_to_folder(zip, archive_folder)

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
        
        if not info:
            for sbsar in files.get_by_type("sbsar"):
                # get info from the sbsar's xml or from the site
                pass

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
            move_to_folder(preview, gallery_folder)

        asset = cls.new(id_path, exist_ok = True)
        asset.update_info(info)

        return id, asset

    @classmethod
    def new(cls, path: typing.Union[str, os.DirEntry, PseudoDirEntry], exist_ok = False):
        """
        `path`: an asset path \n
        `info`: an info to update at creation
        """
        if not isinstance(path, (os.DirEntry, PseudoDirEntry)):
            path = PseudoDirEntry(path)
        os.makedirs(path.path, exist_ok = exist_ok)
        asset = cls(path)

        asset.info = asset.get_empty_info()
            
        with open(asset.json_path, 'w', encoding='utf-8') as json_file:
            json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

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

    def update_system_tags(self):

        mtime = os.path.getmtime(self.path)
        if mtime > self.info.get("system_tags_mtime", 0):

            # ???
            os.makedirs(self.gallery, exist_ok=True)

            if not os.path.exists(self.icon):
                self.generate_icon_from_gallery()

            extensions = {os.path.splitext(file.name)[1].lower() for file in os.scandir(self.path) if file.name not in META_FILES}

            system_tags = []

            if ".blend" in extensions:
                system_tags.append("blend")
            
            if not extensions.isdisjoint(IMAGE_EXTENSIONS):
                system_tags.append("image")

            if ".zip" in extensions:
                system_tags.append("zip")

            if ".sbsar" in extensions:
                system_tags.append("sbsar")

            if not self.info["system_tags"]:
                system_tags.append("no_type")

            self.update_info({"system_tags": system_tags, "system_tags_mtime": mtime})

            return True
        return False

    def update_search_set(self):
        search_set = []
        for key, value in self.info.items():
            if not value or key not in SEARCH_SET_INFO:
                continue
            if isinstance(value, list):
                search_set.extend([subvalue.lower() for subvalue in value])
            else:
                search_set.append(value.lower())
        self.search_set = set(search_set)

    def generate_icon_from_gallery(self):
        for file in [item for item in os.scandir(self.gallery) if item.is_file() and item.name.lower().endswith(tuple(IMAGE_EXTENSIONS))]:
            with pillow_image.open(file.path) as image:
                x, y = image.size
                if x > y:
                    box = ((x-y)/2, 0, (x+y)/2, y)
                elif x < y:
                    box = (0, (y-x)/2, x, (y+x)/2)
                else:
                    box = None
                image = image.resize((128, 128), resample = pillow_image.LANCZOS, box = box)
                icon_path = os.path.join(self.path, "__icon__.png")
                image.save(icon_path , "PNG", optimize=True)
                self.icon = icon_path
                return icon_path
        return None

    def update_info(self, info = None):
        """ if `info` is `None` when only the json updates"""

        if info:
            for key, value in info.items():
                current_value = self.info.get(key)
                if current_value:
                    if isinstance(current_value, list):
                        for subvalue in value:
                            if subvalue not in current_value:
                                current_value.append(subvalue)
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

    def save_material_settings(self, settings):
        material_settings = self.info.get("material_settings")
        if material_settings:
            material_settings.update(settings)
        else:
            self.info["material_settings"] = settings
        self.update_info()

    def load_material_settings(self):
        return self.info.get("material_settings")

    def extract_zips(self):

        zip_paths = [file for file in os.scandir(self.path) if os.path.splitext(file.name)[1] == ".zip"]

        if not zip_paths:
            return []

        self.extra = os.path.join(self.path, "__extra__")
        os.makedirs(self.extra, exist_ok=True)

        extracted_files = []
        for zip_path in zip_paths:
            extracted_files.extend(extract_zip(zip_path))
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
        image_extensions = tuple(IMAGE_EXTENSIONS)
        if as_string:
            return [file.path for file in files if file.name.lower().endswith(image_extensions)]
        else:
            return [file for file in files if file.name.lower().endswith(image_extensions)]

    def get_info_from_url(self):
        is_success, result = asset_parser.get_web_info(self.info["url"])

        if is_success:
            self.update_info(result)
            update_ui()
            return "The info has been updated."
        else:
            return result

        
class AssetData():
    def __init__(self, library, auto):

        if os.path.exists(library):
            self.library = library
        else:
            if library:
                print("The specified library path does not exist.")
            self.library = None

        if os.path.exists(auto):
            self.auto = auto
        else:
            if auto:
                print("The specified auto-folder path does not exist.")
            self.auto = None

        paths_json = read_local_file("config.json")
        if paths_json:
            json_library = paths_json.get("library")
            if json_library and os.path.exists(json_library) and os.path.isdir(json_library):
                self.library = json_library
            json_auto = paths_json.get("auto")
            if json_auto and os.path.exists(json_auto) and os.path.isdir(json_auto):
                self.auto = json_auto

        self.id_chars = "".join((string.ascii_lowercase, string.digits))
        self.search_result = []
        self.number_of_pages = 1
        self.current_page = 1
        self.assets_per_page = 24

        self.preview_collection = bpy.utils.previews.new() 

        self.update()

        
    def update(self):
        if self.library:
            start = timer()

            self.data = {folder.name: Asset.default(folder) for folder in os.scandir(self.library) if folder.is_dir()}
            
            self.update_auto()

            print("JSON reading time:\t", reading_time)
            print("Asset import time:\t", timer() - start)
        else:
            self.data = {}

    def update_auto(self):
        if self.auto:
            for file in os.scandir(self.auto):
                if not file.name.lower().endswith(URL_EXTENSIONS):
                    id, asset = Asset.auto(file, self.library)
                    self.data[id] = asset
    
    def get_result(self, search_query):
        """
        :all
        :no_icon
        :more_tags
        :no_url
        :new

        """

        if re.match(r"(\s|^):al*(\s|$)", search_query, flags=re.IGNORECASE):
            return list(self.data.values())

        ids = deduplicate(re.findall(r"(?:(?<=^id:)|(?<=\sid:))[^\\\\\/:*?\"<>|]+", search_query, flags=re.IGNORECASE))
        if ids:
            return [self.data[id] for id in ids]

        assets = self.data.values()

        if re.match(r"(\s|^):no_icon(\s|$)", search_query, flags=re.IGNORECASE):
            return [asset for asset in assets if not os.path.exists(asset.icon)]

        if re.match(r"(\s|^):more_tags(\s|$)", search_query, flags=re.IGNORECASE):
            return [asset for asset in assets if len(asset.info["tags"]) < 4]

        if re.match(r"(\s|^):no_url(\s|$)", search_query, flags=re.IGNORECASE):
            return [asset for asset in assets if not asset.info["url"]]

        if re.match(r"(\s|^):new(\s|$)", search_query, flags=re.IGNORECASE):
            return sorted(list(self.data.values()), key=lambda a: os.path.getmtime(a.json_path), reverse=True)

        search_query = set(search_query.lower().split())

        # start = timer()
        # result = []
        # lengths = []
        # for asset in assets:
        #     intersection = asset.search_set.intersection(search_query)
        #     length = len(intersection)
        #     if not length:
        #         continue
        #     result.append(asset)
        #     lengths.append(length)
        # result = [asset for asset, _ in sorted(zip(result,lengths), reverse = True, key=lambda x: x[1])]
        # print("Search time 2:\t", timer() - start)


        # start = timer()
        result = [asset for asset in assets if not asset.search_set.isdisjoint(search_query)]
        result.sort(reverse = True, key=lambda asset: len(asset.search_set.intersection(search_query)))
        # print("Search time 1:\t", timer() - start)

        return result

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
            current_browser_items = [('/', "Empty :(",'', 'GHOST_DISABLED', 0)]
            return

        preview_items = []
        for i, asset in enumerate(assets):       
            preview = self.preview_collection.get(asset.icon)
            if preview:
                icon = preview.icon_id
            else:
                try:
                    icon = self.preview_collection.load(asset.icon, asset.icon, 'IMAGE').icon_id
                except:
                    icon = 'SEQ_PREVIEW'
            preview_items.append((asset.id, asset.info["name"], "", icon, i))
        current_browser_items = preview_items

    def get_new_id(self):

        ids = {f.name for f in os.scandir(self.library)} | set(self.data.keys())

        while True:
            id = ''.join(random.choice(self.id_chars) for _ in range(11))
            if not id in ids:
                return id

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

        time_stamp = datetime.now().strftime('%y%m%d_%H%M%S')
        file_basename = "".join(("screen_shot_", time_stamp, ".png"))
        screen_shot_path = os.path.join(asset.gallery, file_basename)
        bpy.ops.screen.screenshot(filepath=screen_shot_path, full=False)
        
        space_data.overlay.show_overlays = initial_show_overlays
        space_data.show_region_toolbar = initial_show_region_toolbar
        space_data.show_region_ui = initial_show_region_ui

    def add_to_library(self, context, objects, info):

        id = self.get_new_id()
        asset_folder = os.path.join(self.library, id)

        asset = Asset.new(asset_folder)
        asset.update_info(info)
        self.make_screen_shot(context, asset)
        asset.generate_icon_from_gallery()

        blend_file_name = re.sub("[\\\\\/:*?\"<>|]", "", asset.info["name"]).strip(" ")
        if not blend_file_name:
            blend_file_name = "untitled"

        blend_file_path = os.path.join(asset_folder, blend_file_name + ".blend")

        for object in objects:
            object["atool_id"] = id

        bpy.data.libraries.write(blend_file_path, set(objects), fake_user=True)

        # https://docs.blender.org/api/current/bpy.types.CollectionObjects.html
        # bpy.context.collection.objects.link(object)
        # bpy.data.collections["Collection Name"].objects.link(object)

        script = "\n".join([
            "import bpy",
            "*map(bpy.context.collection.objects.link, bpy.data.objects),",
            "bpy.ops.object.select_all(action='DESELECT')",
            "bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)",
            "bpy.ops.wm.quit_blender()"
        ])
        subprocess.Popen([bpy.app.binary_path, "-b", blend_file_path,  "--python-expr", script])

        self.data[id] = asset

        update_search(context.window_manager ,context)

        return id, blend_file_path

    def reload_asset(self, id, context):
        asset = self.data[id]
        asset_folder = asset.path
        self.preview_collection
        del self.preview_collection[asset.icon]
        del asset

        asset = Asset.default(PseudoDirEntry(asset_folder))
        self.data[asset.id] = asset

        update_ui()
        update_search(context.window_manager ,context)

    def __del__(self):
        bpy.utils.previews.remove(self.preview_collection)
