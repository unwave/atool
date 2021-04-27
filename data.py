import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import tempfile
import time
import typing  # heavy
import threading
from datetime import datetime
from timeit import default_timer as timer

import bpy
import bpy.utils.previews
from PIL import Image as pillow_image

try: 
    from . import asset_parser
    from . utils import *
    from . view_3d_ui import update_ui
except: # for external testing
    import asset_parser
    from utils import *

current_browser_items = [('/', "Empty :(", '＾-＾', 'GHOST_DISABLED', 0)]
current_search_query = None
reading_time = 0

PROHIBITED_TRAILING_SYMBOLS = " *-~:"

META_FILES = {"__icon__.png", "__info__.json", "__gallery__", "__extra__", "__archive__"}
SEARCH_SET_INFO = {"name", "url", "author", "tags", "system_tags"}

EVERYTHING_EXE = None
ES_EXE = None


def get_browser_items(self, context):
    return current_browser_items

def update_search(wm, context):
    search_query = wm.at_search
    search_query.strip()

    if current_search_query != search_query:
        asset_data = wm.at_asset_data
        try: current_asset = asset_data.data.get(wm.at_asset_previews)
        except: return # if data is not loaded yet
        
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

def update_string_info(property_name, id, info, context):
    try:
        asset_to_update = context.window_manager.at_asset_data.data[id]
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


def update_name(info, context):
    update_string_info("name", context.window_manager.at_asset_previews, info, context)

def update_url(info, context):
    update_string_info("url", context.window_manager.at_asset_previews, info, context)

def update_author(info, context):
    update_string_info("author", context.window_manager.at_asset_previews, info, context)

def update_author_url(info, context):
    update_string_info("author_url", context.window_manager.at_asset_previews, info, context)

def update_licence(info, context):
    update_string_info("licence", context.window_manager.at_asset_previews, info, context)

def update_licence_url(info, context):
    update_string_info("licence_url", context.window_manager.at_asset_previews, info, context)

def update_description(info, context):
    update_string_info("description", context.window_manager.at_asset_previews, info, context)


def update_list_info(property_name, id, info, context):
    try:
        asset_to_update = context.window_manager.at_asset_data.data[id]
    except:
        info[property_name] = ""
        return
    tag_list = deduplicate(filter(None, [tag.strip(PROHIBITED_TRAILING_SYMBOLS).lower() for tag in info[property_name].split()]))
    info[property_name] = ' '.join(tag_list)
    if set(asset_to_update.info[property_name]) != set(tag_list):
        asset_to_update.info[property_name] = tag_list
        asset_to_update.update_info()
        global current_search_query
        current_search_query = None
        update_search(context.window_manager, None)

def update_tags(info, context):
    update_list_info("tags", context.window_manager.at_asset_previews, info, context)

def get_slug(string):
    return re.sub("[\\\\\/:*?\"<>|]", "", string).strip(" ")

def update_id(info, context):
    try:
        wm = context.window_manager
        current_id = wm.at_asset_previews
        asset_data = wm.at_asset_data
        # asset_to_update = asset_data.data[current_id]
    except:
        info["id"] = ""
        return

    info["id"] = get_slug(info["id"])
    if current_id != info["id"]:
        global current_search_query
        current_search_query = None
        new_id = asset_data.reload_asset(current_id, context, new_id = info["id"])
        asset_data.go_to_page(asset_data.get_asset_page(asset_data.data[new_id]))
        wm["at_current_page"] = asset_data.current_page
        wm.at_asset_previews = new_id

class ATOOL_PROP_browser_asset_info(bpy.types.PropertyGroup):
    is_shown: bpy.props.BoolProperty(name='Show Info', default=True)
    is_id_shown: bpy.props.BoolProperty(name='Show ID Info', default=False)
    id: bpy.props.StringProperty(name='ID', update=update_id)
    name: bpy.props.StringProperty(name='Name', update=update_name)
    url: bpy.props.StringProperty(name='URL', update=update_url)
    author: bpy.props.StringProperty(name='Author', update=update_author)
    author_url: bpy.props.StringProperty(name='Author URL', update=update_author_url)
    licence: bpy.props.StringProperty(name='Licence', update=update_licence)
    licence_url: bpy.props.StringProperty(name='Licence URL', update=update_licence_url)
    description: bpy.props.StringProperty(name='Description', update=update_description)
    tags: bpy.props.StringProperty(name='Tags', update=update_tags)


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
        self.lock = threading.RLock()

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
    def remout(cls, path: str):
        asset = cls(path)
        try:
            with open(asset.json_path, "r", encoding='utf-8') as json_file:
                asset.info = json.load(json_file)
        except:
            if os.path.exists(asset.json_path):
                os.rename(asset.json_path, asset.json_path + "@error_" + datetime.now().strftime('%y%m%d_%H%M%S'))
            asset.info = asset.get_empty_info()
            with open(asset.json_path, 'w', encoding='utf-8') as json_file:
                json.dump(asset.info, json_file, indent=4, ensure_ascii=False)

        if not asset.update_system_tags():
            asset.update_search_set()

    @classmethod
    def auto(cls, path: os.DirEntry, asset_data_path, ignore_info = False):

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
            id_path = PseudoDirEntry(id_path)
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
                extract_zip(str(zip), path=id_path.path)
                move_to_folder(zip, archive_folder)
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
            move_to_folder(preview, gallery_folder)

        asset = cls.new(id_path, exist_ok = True)
        if ignore_info and old_info:
            asset.update_info(old_info)
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
                
                if not extensions.isdisjoint(IMAGE_EXTENSIONS):
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
                    search_set.append(value.lower())
            self.search_set = set(search_set)
            self.ctime = os.path.getctime(self.json_path)

    def generate_icon_from_gallery(self):
        with self.lock:
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

    def get_web_info(self, context):
        with self.lock:
            url = self.info.get("url")
            if not url:
                return "No url."

            is_ok, result = asset_parser.get_web(url)

            if is_ok:
                self.update_info(result)
                update_ui()
                update_search(context.window_manager ,context)
                print("The info has been updated.")
                return "The info has been updated."
            else:
                print(result)
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

        config = read_local_file("config.json")
        self.config = config
        if config:
            json_library = config.get("library")
            if json_library and os.path.exists(json_library) and os.path.isdir(json_library):
                self.library = json_library
            json_auto = config.get("auto")
            if json_auto and os.path.exists(json_auto) and os.path.isdir(json_auto):
                self.auto = json_auto

        self.id_chars = "".join((string.ascii_lowercase, string.digits))
        self.search_result = []
        self.number_of_pages = 1
        self.current_page = 1
        self.assets_per_page = 24

        self.preview_collection = bpy.utils.previews.new() 
        self.re_compile()

        
    def update(self):

        if not self.library:
            self.data = {}
            return

        start = timer()

        self.data = {folder.name: Asset.default(folder) for folder in os.scandir(self.library) if folder.is_dir()}
        self.update_auto()
        # self.update_remout()

        print("JSON reading time:\t", reading_time)
        print("Asset import time:\t", timer() - start)

    def update_auto(self):
        if self.auto:
            for file in os.scandir(self.auto):
                if not file.name.lower().endswith(URL_EXTENSIONS):
                    id, asset = Asset.auto(file, self.library)
                    self.data[id] = asset

    def update_remout(self):
        if not os.name == 'nt':
            return

        global ES_EXE
        global EVERYTHING_EXE
        
        es_exe = os.path.join(os.path.dirname(__file__), 'es.exe')
        if not os.path.exists(es_exe):
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Everything.FileList\DefaultIcon") as key:
                    EVERYTHING_EXE = winreg.QueryValueEx(key, "")[0].split(",")[0]
            except:
                print("Everything.exe is not found.")
                return

            with tempfile.TemporaryDirectory() as temp_dir:
                is_success ,zip = asset_parser.get_web_file(r"https://www.voidtools.com/ES-1.1.0.18.zip", content_folder = temp_dir)

                if not is_success:
                    print("Cannot download es.exe")
                    return

                for file in extract_zip(zip):
                    if os.path.basename(file) == 'es.exe':
                        ES_EXE = move_to_folder(file, os.path.dirname(__file__), create = False)
                
                if not ES_EXE:
                    print("Cannot find es.exe in downloads.")
                    return
        else:
            ES_EXE = es_exe

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = os.path.join(temp_dir, "temp.txt")
            subprocess.run([ES_EXE, "*__info__.json", '-export-txt', temp_file])
            with open(temp_file, encoding='utf-8') as text:
                paths = text.read().split("\n")[:-1]

        paths = [path for path in paths if os.path.dirname(path) != self.library]

        for path in paths:
            self.data[path] = Asset.remout(path)
            
    
    def re_compile(self):
        self.re_any = re.compile(r"\S")
        self.re_id = re.compile(r"(?:(?<=^id:)|(?<=\sid:))[^\\\\\/:*?\"<>|]+", flags=re.IGNORECASE)
        self.re_no_icon = re.compile(r"(\s|^):no_icon(\s|$)", flags=re.IGNORECASE)
        self.re_more_tags = re.compile(r"(\s|^):more_tags(\s|$)", flags=re.IGNORECASE)
        self.re_no_url = re.compile(r"(\s|^):no_url(\s|$)", flags=re.IGNORECASE)
        self.re_is_intersection = re.compile(r"(\s|^):i(\s|$)", flags=re.IGNORECASE)

    def get_result(self, query):
        """
        `:no_icon` - with no preview \n
        `:more_tags` - less than 4 tags\n
        `:no_url` - with no url\n
        `:i` - intersection mode, default - subset\n
        `id:<asset id>` - find by id
        """
        
        assets = list(self.data.values())
        if not assets:
            return []

        assets.sort(key=operator.attrgetter('ctime'), reverse=True)
        # assets.sort(key=operator.attrgetter('id'))

        if not self.re_any.search(query):
            return assets

        ids = deduplicate(self.re_id.findall(query))
        if ids:
            return [self.data[id] for id in ids]

        if self.re_no_icon.match(query):
            return [asset for asset in assets if not os.path.exists(asset.icon)]

        if self.re_more_tags.match(query):
            return [asset for asset in assets if len(asset.info["tags"]) < 4]

        if self.re_no_url.match(query):
            return [asset for asset in assets if not asset.info["url"]]

        if self.re_is_intersection.search(query):
            query = self.re_is_intersection.sub(" ", query)

            query = set(query.lower().split())
            result = [asset for asset in assets if not asset.search_set.isdisjoint(query)]
            result.sort(key=lambda asset: len(asset.search_set.intersection(query)), reverse = True)
        else:
            query = set(query.lower().split())
            result = [asset for asset in assets if query.issubset(asset.search_set)]
            
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
                icon = asset.icon
                if os.path.exists(icon):
                    icon = self.preview_collection.load(icon, icon, 'IMAGE').icon_id
                else:
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

    def reload_asset(self, id, context, do_reimport=False, new_id = None):
        asset = self.data[id]
        asset_folder = asset.path
        # del self.preview_collection[asset.icon]
        del self.data[id]

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
                id, asset = Asset.auto(PseudoDirEntry(asset_folder), self.library, ignore_info = True)
                self.data[id] = asset
            else:
                asset = Asset.default(PseudoDirEntry(asset_folder))
                id = asset.id
                self.data[id] = asset

        update_ui()
        update_search(context.window_manager ,context)

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

        self.data[id] = asset

        update_search(context.window_manager, context)
        update_ui()

        return True, id
    
    def __del__(self):
        bpy.utils.previews.remove(self.preview_collection)
