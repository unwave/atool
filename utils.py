import os
import json
import typing
import zipfile
import io
import shutil
import functools
import pathlib
import re
import operator

IMAGE_EXTENSIONS = { ".bmp", ".jpeg", ".jpg", ".jp2", ".j2c", ".tga", ".cin", ".dpx", ".exr", ".hdr", ".sgi", ".rgb", ".bw", ".png", ".tiff", ".tif", ".psd", ".dds"}
GEOMETRY_EXTENSIONS = {}
URL_EXTENSIONS = (".url", ".desktop", ".webloc")
META_TYPES = {"__info__", "__icon__", "__gallery__", "__extra__", "__archive__"}

class PseudoDirEntry:
    def __init__(self, path):
        self.path = os.path.realpath(path)
        self.name = os.path.basename(self.path)
    
    def is_file(self):
        return os.path.isfile(self.path)
    
    def is_dir(self):
        return os.path.isdir(self.path)

def color_to_gray(color):
    return 0.2126*color[0] + 0.7152*color[1] + 0.0722*color[2]

@property
@functools.lru_cache()
def data(self):
    if self.type == "megascan_info":
        with self.open(encoding="utf-8") as json_file:
            return json.load(json_file)
    elif self.type == "url":
        if self.suffix == ".webloc":
            from xml.dom.minidom import parse as xml_parse
            tag = xml_parse(str(self)).getElementsByTagName("string")[0]
            return tag.firstChild.nodeValue
        else:
            import configparser
            config = configparser.ConfigParser(interpolation=None)
            config.read(str(self))
            return config[config.sections()[0]].get("URL")
    elif self.type == "blendswap_info":
        with self.open(encoding="utf-8") as info_file:
            match = re.search(r"blendswap.com\/blends\/view\/\d+", info_file.read())
            if match:
                return match.group(0)
    elif self.type == "__info__":
        with self.open(encoding="utf-8") as json_file:
            return json.load(json_file)
    return None


@property
@functools.lru_cache()
def is_meta(self):
    return self.type in META_TYPES

@property
@functools.lru_cache()
def file_type(self):
    if self.is_file():
        if self.name == "__info__.json":
            return "__info__"
        elif self.name == "__icon__.png":
            return "__icon__"
        elif self.name == "BLENDSWAP_LICENSE.txt":
            return "blendswap_info"
        elif self.name.lower().endswith("license.html"):
            with self.open(encoding="utf-8") as info_file:
                if re.search(r"blendswap.com\/blends\/view\/\d+", info_file.read()):
                    return "blendswap_info"
        elif self.suffix == ".sbsar":
            return "sbsar"
        elif self.suffix == ".zip":
            return "zip"
        elif self.suffix == ".json":
            with self.open(encoding="utf-8") as json_file:
                json_data = json.load(json_file)
                if type(json_data.get("id")) == str and type(json_data.get("meta")) == list and type(json_data.get("points")) == int:
                    return "megascan_info"
        elif self.suffix in IMAGE_EXTENSIONS:
            return "image"
        elif self.suffix in GEOMETRY_EXTENSIONS:
            return "geometry"
        elif self.suffix in URL_EXTENSIONS:
            return "url"
    else:
        if self.name == "__gallery__":
            return "__gallery__"
        elif self.name == "__extra__":
            return "__extra__"
        elif self.name == "__archive__":
            return "__archive__"  

    return None

pathlib.Path.type = file_type
pathlib.Path.is_meta = is_meta
pathlib.Path.data = data


class File_Filter:
    def __init__(self, path: os.DirEntry, ignore: typing.Union[str, typing.Iterable[str]]):
        self.path = path.path
        ignore = {ignore} if isinstance(ignore, str) else set(ignore)
        self.ignore = ignore
        self.data = {item.name: pathlib.Path(item.path) for item in os.scandir(path.path) if item.name not in ignore}

    def update(self):

        for name in list(self.data.keys()):
            if not self.data[name].exists():
                del self.data[name]

        ignore = self.ignore | set(self.data.keys())
        for file in os.scandir(self.path):
            if file.name not in ignore:
                self.data[file.name] = pathlib.Path(file.path)

    def __iter__(self):
        return iter(self.get_files())
    
    def get_files(self):
        return [item for item in self.data.values() if item.is_file()]
        
    def get_folders(self):
        return [item for item in self.data.values() if item.is_dir()]
        
    def get_by_type(self, type: typing.Union[str, typing.Iterable[str]]):
        type = {type} if isinstance(type, str) else set(type)
        return [item for item in self.data.values() if item.type in type]
               
    def get_by_name(self, name: typing.Union[str, typing.Iterable[str]]):
        name = {name} if isinstance(name, str) else set(name)
        return [item for item in self.data.values() if item.name in name]
            
    def get_by_extension(self, extension: typing.Union[str, typing.Iterable[str]]):
        extension = {extension} if isinstance(extension, str) else set(extension)
        return [item for item in self.data.values() if item.suffix in extension]



def move_to_folder(file: typing.Union[str, os.DirEntry], folder:str, create=True):
    if create:
        os.makedirs(folder, exist_ok=True)
    if isinstance(file, str):
        new_path = os.path.join(folder, os.path.basename(file))
        shutil.move(file, new_path)
        return new_path
    elif isinstance(file, pathlib.PurePath):
        new_path = os.path.join(folder, file.name)
        shutil.move(str(file), new_path)
        return new_path
    elif isinstance(file, (os.DirEntry, PseudoDirEntry)):
        new_path = os.path.join(folder, file.name)
        shutil.move(file.path, new_path)
        return new_path
    raise TypeError(f"The function move_to_folder does not support {str(file)} of type {type(file)}.")

def read_local_file(name, auto=True):
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), name)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding="utf-8") as file:
        if not auto:
            return(file.read())
        elif path.lower().endswith(".json"):
            return(json.load(file))

def get_files(path, get_folders = False, recursivly = True):
    list = []
    for item in os.scandir(path):
        if item.is_file():
            list.append(item)
        else:
            if get_folders:
                list.append(item)
            if recursivly:
                list.extend(get_files(item.path, get_folders, recursivly))
    return list

def deduplicate(list_to_deduplicate: list):
        return list(dict.fromkeys(list_to_deduplicate))

def remove_empty(iterable):
    if isinstance(iterable, dict):
        for key in list(iterable.keys()):
            if not iterable[key]:
                iterable.pop(key)
    elif isinstance(iterable, list):
        index = len(iterable) - 1
        for item in reversed(iterable):
            if not item:
                iterable.pop(index)
            index -= 1
    else:
        raise TypeError(f"The argument type should be \"dict\" or \"list\" not {type(iterable)}")

def extract_zip(file: typing.Union[str, typing.IO[bytes]], path = None, extract = True, recursively = True):
    """
    `file`: a path to a zip file \n
    `path`: a target root folder, if `None` the zip's folder is used \n
    `extract`: if `False` the function only returns the list of files without an extraction \n
    `recursively`: extract zips recursively
    """
    extracted_files = []
    if path is None:
        path = file
    path = os.path.splitext(path)[0]
    to_path = path.replace("/", os.sep)
    if extract:
        os.makedirs(to_path, exist_ok=True)
    with zipfile.ZipFile(file) as zip_file:
        for name in zip_file.namelist():
            if name.endswith(".zip") and recursively:
                extracted_files.extend(extract_zip(io.BytesIO(zip_file.read(name)), '/'.join((path, name)), extract, recursively))
            else:
                if extract:
                    extracted_files.append(zip_file.extract(name, to_path))
                else:
                    extracted_files.append(os.path.join(to_path, name.replace("/", os.sep)))
    return extracted_files

class Item_Location:
    def __init__(self, path, iter):
        self.path = path
        self.iter = iter
    
    @property
    def string(self):
        return "".join(("".join(("[", fragment.__repr__(),"]")) for fragment in self.path))
    
    @property
    def data(self):
        data = self.iter
        for fragment in self.path:
            data = data[fragment]
        return data
        
    @property
    def parent(self):
        parent = self.iter
        for fragment in self.path[:-1]:
            parent = parent[fragment]
        return parent
        
    def get_parent(self, level = 1):
        parent = self.iter
        for fragment in self.path[:-level]:
            parent = parent[fragment]
        return parent


def locate_item(iter, item, is_dict_key = False, return_as = None, mode = 'eq'):
    """
    `type`: 'any' can be a key, a value
    `mode`: operator's 'eq', 'contains', etc.
    """
    
    def contains(a, b):
        if type(a) == str and type(b) == str:
            return operator.contains(b.lower(), a.lower())
        else:
            return operator.eq(a, b)
    
    if mode == 'eq':
        comparison = operator.eq
    elif mode == 'contains':
        comparison = contains
    else:
        comparison = getattr(operator, mode)
    

    def locate_value(iter, item, path = []):
        if isinstance(iter, (list, tuple)):
            for index, value in enumerate(iter):
                if isinstance(value, (list, dict, tuple)):
                    yield from locate_value(value, item, path + [index])
                elif comparison(item, value):
                    yield path + [index]
        elif isinstance(iter, dict):
            for name, value in iter.items():
                if isinstance(value, (list, dict, tuple)):
                    yield from locate_value(value, item, path + [name])
                elif comparison(item, value):
                    yield path + [name]
                

    def locate_key(iter, item, path = []):
        if isinstance(iter, (list, tuple)):
            for index, value in enumerate(iter):
                yield from locate_key(value, item, path + [index])
        elif isinstance(iter, dict):
            for key, value in iter.items():
                if isinstance(value, (list, dict, tuple)):
                    yield from locate_key(value, item, path + [key])
                elif comparison(item, key):
                    yield path + [key]
                
    
    def locate_key_and_value(iter, item, path = []):
        if isinstance(iter, (list, tuple)):
            for index, value in enumerate(iter):
                yield from locate_key_and_value(value, item, path + [index])
        elif isinstance(iter, dict):
            for key, value in iter.items():
                if isinstance(value, (list, dict, tuple)):
                    yield from locate_key_and_value(value, item, path + [key])
                elif  comparison(item[0], key) and  comparison(item[1], value):
                    yield path + [key]
                
    
    if isinstance(item, tuple):
        locate = locate_key_and_value
    else:
        locate = locate_key if is_dict_key else locate_value
        
    if return_as:
        return [getattr(Item_Location(path, iter), return_as) for path in locate(iter, item)]
    else:
        return [Item_Location(path, iter) for path in locate(iter, item)]
        