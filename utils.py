import os
import json
import threading
import typing
import zipfile
import io
import shutil
import functools
import pathlib
import re
import operator
import tempfile
import subprocess
import sys
from datetime import datetime
from timeit import default_timer

IMAGE_EXTENSIONS = { ".bmp", ".jpeg", ".jpg", ".jp2", ".j2c", ".tga", ".cin", ".dpx", ".exr", ".hdr", ".sgi", ".rgb", ".bw", ".png", ".tiff", ".tif", ".psd", ".dds"}
GEOMETRY_EXTENSIONS = {".obj", ".fbx"}
URL_EXTENSIONS = (".url", ".desktop", ".webloc")
META_FOLDERS = {'__gallery__', '__extra__', '__archive__'}
META_TYPES = {"__info__", "__icon__"} | META_FOLDERS

DIR_PATH = os.path.dirname(os.path.realpath(__file__))
PLATFORM = sys.platform

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
    name = self.name

    if not self.is_file():
        if name in META_FOLDERS:
            return name
        return None
    
    if name == "__info__.json":
        return "__info__"
    elif name == "__icon__.png":
        return "__icon__"
    elif name == "BLENDSWAP_LICENSE.txt":
        return "blendswap_info"
    elif name.lower().endswith("license.html"):
        with self.open(encoding="utf-8") as info_file:
            if re.search(r"blendswap.com\/blends\/view\/\d+", info_file.read()):
                return "blendswap_info"

    suffix = self.suffix
    if suffix == ".sbsar":
        return "sbsar"
    elif suffix == ".zip":
        return "zip"
    elif suffix == ".json":
        with self.open(encoding="utf-8") as json_file:
            json_data = json.load(json_file)
            if type(json_data.get("id")) == str and type(json_data.get("meta")) == list and type(json_data.get("points")) == int:
                return "megascan_info"
    elif suffix in IMAGE_EXTENSIONS:
        return "image"
    elif suffix in GEOMETRY_EXTENSIONS:
        return "geometry"
    elif suffix in URL_EXTENSIONS:
        return "url"

    return None

pathlib.Path.type = file_type
pathlib.Path.is_meta = is_meta
pathlib.Path.data = data

class File_Filter(typing.Dict[str, pathlib.Path] , dict):
    def __init__(self):
        self.ignore = set()
        self.path = None

    @classmethod
    def from_dir(cls, path: os.DirEntry, ignore: typing.Union[str, typing.Iterable[str]] = None):
        filter = cls()
        if ignore:
            filter.ignore = ignore = {ignore} if isinstance(ignore, str) else set(ignore)

        filter.path = path.path
        for item in os.scandir(path.path):
            if item.name not in ignore:
                filter[item.name] = pathlib.Path(item.path)
        
        return filter

    @classmethod
    def from_files(cls, files: typing.Iterable[str]):
        filter = cls()
        for file in files:
            name = os.path.basename(file)
            filter[name] = pathlib.Path(file)
        return filter

    def update(self):
        if not self.path:
            return

        for name in list(self.keys()):
            if not self[name].exists():
                del self[name]

        ignore = self.ignore | set(self.keys())
        for file in os.scandir(self.path):
            if file.name not in ignore:
                self[file.name] = pathlib.Path(file.path)

    def __iter__(self):
        return iter(self.get_files())
    
    def get_files(self):
        return [item for item in self.values() if item.is_file()]
        
    def get_folders(self):
        return [item for item in self.values() if item.is_dir()]
        
    def get_by_type(self, type: typing.Union[str, typing.Iterable[str]]):
        type = {type} if isinstance(type, str) else set(type)
        return [item for item in self.values() if item.type in type]
               
    def get_by_name(self, name: typing.Union[str, typing.Iterable[str]]):
        name = {name} if isinstance(name, str) else set(name)
        return [item for item in self.values() if item.name in name]
            
    def get_by_extension(self, extension: typing.Union[str, typing.Iterable[str]]):
        extension = {extension} if isinstance(extension, str) else set(extension)
        return [item for item in self.values() if item.suffix in extension]


def move_to_folder(file: typing.Union[str, os.DirEntry, PseudoDirEntry, pathlib.PurePath], folder: str, create = True, exists_rename = True):
    
    if isinstance(file, str):
        old_path = file
        new_path = os.path.join(folder, os.path.basename(file))
    elif isinstance(file, pathlib.PurePath):
        old_path = str(file)
        new_path = os.path.join(folder, file.name)
    elif isinstance(file, (os.DirEntry, PseudoDirEntry)):
        old_path = file.path
        new_path = os.path.join(folder, file.name)
    else:
        raise TypeError(f"The function move_to_folder does not support {str(file)} of type {type(file)}.")

    if old_path != new_path:

        if create:
            os.makedirs(folder, exist_ok = True)

        if exists_rename:
            name, suffix = os.path.splitext(os.path.basename(new_path))
            index = 2
            while os.path.exists(new_path):
                new_path = os.path.join(folder, name + f'_{index}' + suffix)
                index += 1

        shutil.move(old_path, new_path)

    return new_path


def read_local_file(name, auto=True) -> typing.Union[str, dict]:
    path = os.path.join(DIR_PATH, name)
    
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r', encoding="utf-8") as file:
            if auto:
                if path.lower().endswith(".json"):
                    return(json.load(file))
            return file.read()
    except:
        import traceback
        traceback.print_exc()
        return None

def get_script(name, read = False):
    path = os.path.join(DIR_PATH, 'scripts', name)

    if not read:
        return path

    with open(path, 'r', encoding="utf-8") as file:
        return file.read()

def get_files(path, get_folders = False, recursively = True):
    list = []
    for item in os.scandir(path):
        if item.is_file():
            list.append(item)
        else:
            if get_folders:
                list.append(item)
            if recursively:
                list.extend(get_files(item.path, get_folders, recursively))
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
        path = os.path.splitext(file)[0]
    to_path = path.replace("/", os.sep)
    if extract:
        os.makedirs(to_path, exist_ok=True)
    with zipfile.ZipFile(file) as zip_file:
        for name in zip_file.namelist():
            if name.endswith(".zip") and recursively:
                inner_path =  '/'.join((path, name[:-4]))
                extracted_files.extend(extract_zip(io.BytesIO(zip_file.read(name)), inner_path, extract, recursively))
            else:
                if extract:
                    extracted_files.append(zip_file.extract(name, to_path))
                else:
                    extracted_files.append(os.path.join(to_path, name.replace("/", os.sep)))
    return extracted_files

def get_last_file(path: str, type: typing.Union[str, typing.Tuple[str]], recursively = True) -> str:
    files = [file for file in get_files(path, recursively) if file.name.lower().endswith(type)]
    if not files:
        return None
    return max(files, key=lambda x: (os.path.getmtime(x), os.path.getctime(x), x)).path

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
        

class Everything:
    def __init__(self):
        self.exe = None
        self.es_exe = None
        self.error_text = ""
        self.is_initialized = False
        self.lock = threading.RLock()

    @property
    def is_available(self):

        if self.is_initialized:
            return bool(self.es_exe)
        else:
            self.set_es_exe()
            if not self.es_exe:
                print(self.error_text)
            return bool(self.es_exe)

    def set_es_exe(self):

        with self.lock:

            if self.is_initialized:
                return

            print('atool: checking es.exe')

            if not os.name == 'nt':
                self.error_text = "Current OS is not supported."
                self.is_initialized = True
                return

            es_exe = os.path.join(os.path.dirname(__file__), 'es.exe')
            if os.path.exists(es_exe):
                self.es_exe = es_exe
                self.is_initialized = True
                return 

            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Everything.FileList\DefaultIcon") as key:
                    self.exe = winreg.QueryValueEx(key, "")[0].split(",")[0]
            except:
                self.error_text = "Everything.exe is not found."
                self.is_initialized = True
                return
        
            with tempfile.TemporaryDirectory() as temp_dir:

                if __package__:
                    from . import asset_parser
                else:
                    import asset_parser

                is_success, zip = asset_parser.get_web_file(r"https://www.voidtools.com/ES-1.1.0.18.zip", content_folder = temp_dir)
                if not is_success:
                    self.error_text = "Cannot download es.exe"
                    self.is_initialized = True
                    return

                for file in extract_zip(zip):
                    if os.path.basename(file) == 'es.exe':
                        move_to_folder(file, os.path.dirname(__file__), create = False)
                
                if not os.path.exists(es_exe):
                    self.error_text = "Cannot find es.exe in downloads."
                    self.is_initialized = True
                    return None

                self.es_exe = es_exe
                self.is_initialized = True

    def find(self, names):

        if not self.is_available:
            raise BaseException(self.error_text)

        query = '|'.join(["*\\" + '"' + name + '"' for name in names])
            
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = os.path.join(temp_dir, "temp.txt")
            command = ' '.join(['"' + self.es_exe + '"', query, '-export-txt', '"' + temp_file + '"'])
            subprocess.run(command)
            with open(temp_file, encoding='utf-8') as text:
                paths = text.read().split("\n")[:-1]

        return paths

    def get_everything(self, query):
        
        if not self.is_available:
            raise BaseException(self.error_text)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = os.path.join(temp_dir, "temp.txt")
            subprocess.run([self.es_exe, query, '-export-txt', temp_file])
            with open(temp_file, encoding='utf-8') as text:
                return text.read().split("\n")[:-1]

EVERYTHING = Everything()


def get_closest_path(lost_path, string_paths):

    lost_path = lost_path.lower().split(os.sep)[:-1]
    paths = [path.lower().split(os.sep)[:-1] for path in string_paths]
    
    if os.name == 'nt':
        lost_path.insert(0, 'root')
        for path in paths:
            path.insert(0, 'root')

    lost_reversed = list(reversed(lost_path))
    def locate_fragment(item):
        for index, fragment in enumerate(lost_reversed):
            if fragment == item:
                return index
                
    routs = []
    for path_index, path in enumerate(paths):
        for length, item in enumerate(reversed(path), start = 1):
            index = locate_fragment(item)
            if index is not None:
                length += index + 1
                routs.append((length, path_index))
                break
    
    return string_paths[min(routs)[1]]


def os_open(operator, path):

    if PLATFORM == 'win32':
        os.startfile(path)
    elif PLATFORM == 'darwin':
        subprocess.Popen(['open', path])
    else:
        try:
            subprocess.Popen(['xdg-open', path])
        except OSError:
            operator.report({'INFO'}, "Current OS is not supported.")
            import traceback
            traceback.print_exc()

def os_show(operator, files: typing.Iterable[str]):

    if PLATFORM != 'win32':
        for directory in deduplicate([os.path.dirname(file) for file in files]):
            os_open(operator, directory)
        return

    files = [file.lower() for file in files]
    directories = list_by_key(files, os.path.dirname)

    import ctypes
    import ctypes.wintypes

    prototype = ctypes.WINFUNCTYPE(ctypes.POINTER(ctypes.c_int), ctypes.wintypes.LPCWSTR)
    paramflags = (1, "pszPath"),
    ILCreateFromPathW = prototype(("ILCreateFromPathW", ctypes.windll.shell32), paramflags)

    ctypes.windll.ole32.CoInitialize(None)

    for directory, files in directories.items():
    
        directory_pidl = ILCreateFromPathW(directory)
        
        file_pidls = (ctypes.POINTER(ctypes.c_int) * len(files))()
        for index, file in enumerate(files):
            file_pidls[index] = ILCreateFromPathW(file)

        ctypes.windll.shell32.SHOpenFolderAndSelectItems(directory_pidl, len(file_pidls), file_pidls, 0)
        
        ctypes.windll.shell32.ILFree(directory_pidl)
        for file_pidl in file_pidls:
            ctypes.windll.shell32.ILFree(file_pidl)
            
    ctypes.windll.ole32.CoUninitialize()

def web_open(string , is_url = False):

    starts_with_http = string.startswith("https://") or string.startswith("http://")

    if is_url:
        if not starts_with_http:
            url = "https://" + string
        else:
            url = string
    else:
        if starts_with_http:
            url = string
        else:
            url = fr"https://www.google.com/search?q={string}"
    
    import webbrowser
    webbrowser.open(url, new=2, autoraise=True)


def list_by_key(items, key_func):
    dict = {}
    for item in items:
        key = key_func(item)
        list = dict.get(key)
        if list:
            list.append(item)
        else:
            dict[key] = [item]
    return dict

def map_to_list(mapping: dict, key, value: typing.Union[list, dict, typing.Any]):

    if not value:
        return

    if type(value) == dict:
        for key, value in value.items():
            map_to_list(mapping, key, value)
        return

    if mapping.get(key):
        if type(value) == list:
            mapping[key].extend(value)
        else:
            mapping[key].append(value)
    else:
        if type(value) == list:
            mapping[key] = value.copy()
        else:
            mapping[key] = [value]

def get_time_stamp():
    return datetime.now().strftime('%y%m%d_%H%M%S')


def get_longest_substring(strings: typing.Iterable[str], from_beginning = False):

    if len(strings) == 1:
        return  list(strings)[0]

    sets = []
    if from_beginning:
        for string in strings:
            string_set = []
            string_len = len(string)
            for i in range(string_len):
                string_set.append(string[:i + 1])
            sets.append(set(string_set))
    else:
        for string in strings:
            string_set = []
            string_len = len(string)
            for i in range(string_len):
                for j in range(i + 1, string_len + 1):
                    string_set.append(string[i:j])
            sets.append(set(string_set))

    mega_set = set().union(*sets)

    for string_set in sets:
        mega_set.intersection_update(string_set)

    if not mega_set:
        return ""

    return max(mega_set, key=len)


def get_slug(string):
    string = re.sub("[\\\\\/:*?\"<>|]", "", string)
    string = string.strip(" ")
    string = re.sub(" +", "_", string)
    return string
    

def get_desktop():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return winreg.QueryValueEx(key, "Desktop")[0]
    except:
        return os.path.expanduser("~/Desktop")

def ensure_unique_path(path):

    if not os.path.exists(path):
        return path

    dir = os.path.dirname(path)
    stem, ext = os.path.splitext(os.path.basename((path)))
    number = 2

    new_path = os.path.join(dir, stem + f"_{number}" + ext)
    while os.path.exists(new_path):
        number += 1
        new_path = os.path.join(dir, stem + f"_{number}" + ext)
    
    return new_path

def get_path_list(path: str):
    fragmented_path = path.split(os.sep)
    path_list = []
    for i in range(len(fragmented_path)):
        path_list.append(os.sep.join(fragmented_path[:i + 1]))
    path_list.sort(key = len)
    return path_list

def get_path_set(path: str):
    fragmented_path = path.split(os.sep)
    path_set = set()
    for i in range(len(fragmented_path)):
        path_set.add(os.sep.join(fragmented_path[:i + 1]))
    return path_set

def synchronized(func):
    def wrapper(*args, **kw):
        with args[0].lock: # self.lock
            return func(*args, **kw)
    return wrapper

import binascii
import xxhash   

SAMPLE_THRESHOLD = 256 * 1024
SAMPLE_SIZE = 32 * 1024

def encode_leb128(n):
    """ https://en.wikipedia.org/wiki/LEB128 """
    result = []
    while n >= 128:
        result.append(n & 127 | 128)
        n >>= 7
    result.append(n)
    return bytes(result)

def get_file_hash(path):
    with open(path, 'rb') as f:
        
        size = os.fstat(f.fileno()).st_size

        if size < SAMPLE_THRESHOLD:
            data = f.read()
        else:
            data = f.read(SAMPLE_SIZE)
            
            f.seek(size//2)
            data += f.read(SAMPLE_SIZE)
            
            f.seek(-SAMPLE_SIZE, os.SEEK_END)
            data += f.read(SAMPLE_SIZE)

        digest = xxhash.xxh3_128_digest(data)

        # left for backward compatibility with imohash from https://pypi.org/project/imohash/ by kalafut using xxhash
        digest = digest[7::-1] + digest[16:7:-1]
        
        leb128_encoded_size = encode_leb128(size)
        digest = leb128_encoded_size + digest[len(leb128_encoded_size):]
        
        return binascii.hexlify(digest).decode()


def print_json(object):
    print(json.dumps(object, indent=4, default=lambda x: x.__repr__()))
    
import inflection

PLURALS_SUB = [(re.compile(rule), replacement) for rule, replacement in inflection.PLURALS]
UNCOUNTABLES_PLURALIZE = inflection.UNCOUNTABLES

cache_pluralize = {}

def pluralize(word: str) -> str:
    result = cache_pluralize.get(word)
    if result:
        return result
    
    if word in UNCOUNTABLES_PLURALIZE:
        cache_pluralize[word] = word
        return word
        
    for rule, replacement in PLURALS_SUB:
        result = rule.sub(replacement, word)
        if word != result:
            cache_pluralize[word] = result
            return result
        
    cache_pluralize[word] = word
    return word

UNCOUNTABLES_SINGULARIZE = [re.compile(r'(?i)\b(%s)\Z' % inflection) for inflection in inflection.UNCOUNTABLES]
SINGULARS_SUB = [(re.compile(rule), replacement) for rule, replacement in inflection.SINGULARS]

cache_singularize = {}

def singularize(word: str) -> str:
    result = cache_singularize.get(word)
    if result:
        return result
    
    for inflection in UNCOUNTABLES_SINGULARIZE:
        if inflection.search(word):
            cache_singularize[word] = word
            return word

    for rule, replacement in SINGULARS_SUB:
        result = rule.sub(replacement, word)
        if word != result:
            cache_singularize[word] = result
            return result
        
    cache_singularize[word] = word
    return word

SUB_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
SUB_2 = re.compile(r"([a-z\d])([A-Z])")
TAGS = re.compile('[^\W_]+')

def split(word: str):
    word = SUB_1.sub(r'\1 \2', word)
    word = SUB_2.sub(r'\1 \2', word)
    return TAGS.findall(word)

def get_most_common(items: typing.Iterable):
    dictionary = {}
    for item in items:
        dictionary[item] = dictionary.get(item, 0) + 1
    return sorted(dictionary.items(), key = operator.itemgetter(1), reverse = True)[0][0]


def timeit(text = None, digits = 2, average = False, timeit_average_dict = {}):
    """To getting average text should true and be unique for a testing item."""

    def timeit_decorator(func):

        @functools.wraps(func)
        def timeit_func(*args, **kwargs):
        
            start = default_timer()
            return_value = func(*args, **kwargs)
            end = default_timer()

            nonlocal text

            time = end - start
            if average and text:
                result = timeit_average_dict.get(text)
                if result:
                    count, func_time = result
                    timeit_average_dict[text] = (count + 1, func_time + time)
                    time = (func_time + time)/(count + 1)
                else:
                    timeit_average_dict[text] = (1, time)

            if not text:
                text = func.__name__ + ' took'

            if time >= 1:
                time = round(time, digits)
            else:
                for index, digit in enumerate(format(time, 'f')[2:]):
                    if digit == '0':
                        continue
                    time = round(time, digits + index)
                    break

            print(f"{text}: {format(time, 'f').rstrip('.0')} s")

            return return_value

        return timeit_func

    return timeit_decorator
    