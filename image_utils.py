from __future__ import annotations

import json
import logging
import os
import sqlite3
import typing


import numpy as np
from cached_property import cached_property
from PIL import Image as pillow_image
from PIL import ImageGrab

log = logging.getLogger("atool")

OPENCV_IO_ENABLE_OPENEXR = False

def set_OPENCV_IO_ENABLE_OPENEXR():
    config = utils.read_local_file("config.json") # type: dict
    if config and config.get("OPENCV_IO_ENABLE_OPENEXR"):
        global OPENCV_IO_ENABLE_OPENEXR
        OPENCV_IO_ENABLE_OPENEXR = True
        os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

if __package__:
    import bpy
    from . import utils
    set_OPENCV_IO_ENABLE_OPENEXR()
    from . import type_definer
    from . imohashxx import hashfile
else:
    import utils
    set_OPENCV_IO_ENABLE_OPENEXR()
    import type_definer
    from imohashxx import hashfile

import cv2 as cv

FILE_PATH = os.path.dirname(os.path.realpath(__file__))
CASHE_PATH = os.path.join(FILE_PATH, "__cache__.db")

class Image_Cache_Database:
    def __enter__(self):
        self.connection = sqlite3.connect(CASHE_PATH)
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS cache (hash TEXT PRIMARY KEY, data TEXT)")
        return self
        
    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.commit()
        self.cursor.close()
        self.connection.close()
        
    def get(self, hashs):
        self.cursor.execute(f"SELECT * FROM cache WHERE hash in ({', '.join(['?']*len(hashs))})", hashs)
        datas = [json.loads(data[1]) for data in self.cursor.fetchall()]
        return datas
        
    def set(self, hash, data):
        data = json.dumps(data, ensure_ascii=False)
        self.cursor.execute("INSERT OR REPLACE INTO cache (hash, data) VALUES(?,?)", (hash, data))


CHANNEL_TO_INDEX = {'R': 0, 'G': 1, 'B': 2, 'A': 3}
INDEX_TO_CHANNEL = ('R', 'G', 'B', 'A')
DUMPABLE = ("x", "y", "channels", "min_max", "hash", "shape", "dtype", "aspect_ratio", "dominant_color")
ONLY_DUMPABLE = ('basename', 'type')

class Image:
    def __init__(self, path: str):
        self.path = path
        self.basename = os.path.basename(path)
        self.name, self.extension = os.path.splitext(self.basename)
        self.extension = self.extension.lower()

        self.db: Image_Cache_Database = None
        self.asset_info: dict = None
        self.data_block: object = None # type: bpy.types.Image
        self.type_definer_config: type_definer.Filter_Config = None

        self.type: typing.List[str] # what if type definer retruns all possible types in order of more probable?
        
        self.hash: str # property, saved, key, called every time
        
        self.x: int # property, saved
        self.y: int # property, saved
        self.channels: int # property, saved
        self.dtype: str # property, saved
        
        self.min_max: typing.Dict[str, typing.Tuple[float, float]] = {} # dict, saved
        self.dominant_color = {} # dict, saved
        
        self.image: np.ndarray # property, not saved

    @classmethod
    def from_db(cls, path: str, db: Image_Cache_Database = None, type_definer_config: type_definer.Filter_Config = None) -> Image:
        image = cls(path)
        
        if type_definer_config:
            image.type_definer_config = type_definer_config

        if db:
            image.db = db
            image.load_from_db(db)
        else:
            with Image_Cache_Database() as db:
                image.load_from_db(db)

        return image
    
    def load_from_db(self, db: Image_Cache_Database):
            info = db.get((self.hash,))
            if info:
                self.load(info[0])

    @classmethod
    def from_asset_info(cls, path: str, info: dict, type_definer_config: type_definer.Filter_Config = None) -> Image:
        image = cls(path)
        
        if type_definer_config:
            image.type_definer_config = type_definer_config
        
        image.load_from_asset_info(info)
        return image
    
    def load_from_asset_info(self, info: dict):
        self.asset_info = info
        file_info = info.get('file_info') # type: dict
        if file_info:
            image_info = file_info.get(self.hash)
            if image_info:
                self.load(image_info)

    def update_source(self):
        try:
            if self.db:
                self.db.set(self.hash, self.dump())
        except:
            print(f'The Image_Cache_Database for image {self.path} was not updated.')

        if self.asset_info:
            file_info = self.asset_info.get('file_info') # type: dict
            if not file_info:
                self.asset_info['file_info'] = {}
            self.asset_info['file_info'][self.hash] = self.dump()     

        if self.data_block:
            self.data_block['at_type'] = self.type

    @classmethod
    def from_block(cls, block, define_type = True, type_definer_config: type_definer.Filter_Config = None) -> Image:
        image = cls(os.path.realpath(bpy.path.abspath(block.filepath, library=block.library)))
        image.data_block = block
        
        if type_definer_config:
            image.type_definer_config = type_definer_config

        type = block.get("at_type")
        if type:
            image.type = type

        return image
    
    def __repr__(self):
        return f"<atool.image_utils.Image object; <{self.path}>"

    @cached_property
    def type(self):
        return type_definer.get_type(self.name, self.type_definer_config)
        
    @cached_property
    def hash(self):
        return utils.get_file_hash(self.path)

    @cached_property
    def image(self):
        if self.extension in (".tga",):
            with pillow_image.open(self.path) as pil_image:
                bands = len(pil_image.getbands())
                image = np.array(pil_image)
                if bands == 3:
                    image = cv.cvtColor(image, cv.COLOR_RGB2BGR)
                elif bands == 4:
                    image = cv.cvtColor(image, cv.COLOR_RGBA2BGRA)
        else:
            image = cv.imread(self.path, cv.IMREAD_UNCHANGED | cv.IMREAD_ANYCOLOR | cv.IMREAD_ANYDEPTH)
        
        if self.extension == '.exr': # what if zeros are what i need?
            image = cv.merge([channel for channel in cv.split(image) if channel.any()])
    
        assert image is not None, f"The image {self.path} wasn't loaded!"
        log.debug(f"Image loaded: {self.path}")

        return image
    
    def trim_type(self):
        if self.channels > 3:
            return
        
        if len(self.type) == 4 or (len(self.type) == 2 and self.type[0] in type_definer.TRIPLE_CHANNEL_MAPS):
            init_type = self.type.copy()
            self.type.pop(0)
            print(f'The image {self.path} had a wrong type and was trimmed from {init_type} to {self.type}.')
    
    @cached_property
    def shape(self):
        shape = self.image.shape
        if len(shape) == 2:
            y, x = shape
            channels = 1
        else:
            y, x, channels = shape
        return x, y, channels

    def get_shape(self, image = None):
        if image is None:
            image = self.image
        shape = image.shape
        if len(shape) == 2:
            y, x = shape
            channels = 1
        else:
            y, x, channels = shape
        return x, y, channels

    @cached_property
    def dtype(self):
        return str(self.image.dtype)

    @cached_property
    def x(self):
        return self.shape[0]

    @cached_property
    def y(self):
        return self.shape[1]

    @cached_property
    def channels(self):
        return self.shape[2]

    @cached_property
    def aspect_ratio(self):
        return self.shape[0]/self.shape[1]
        
    def pre_process(self, no_height = False):

        self.aspect_ratio
        self.trim_type()

        for channel, subtype in self.iter_type():

            if subtype in {"diffuse", "albedo", "roughness", "gloss", "metallic"}:
                self.get_dominant_color(channel)

            # normalize if: height, roughness, gloss, specular
            if subtype in {"displacement", "roughness", "gloss", "specular"}:
                self.get_min_max(channel)

            # delight?
            # valid color range for PBR
            # normalize if out of range
            # if no height use color and normalize it
            if subtype in {"diffuse", "albedo"}:
                if no_height:
                    self.get_min_max(channel)

            # check if normal map is correct
            # auto-detect normals Y channel style, DirectX/OpenGL
            # invert x, y
            # sRGB/Linear
            # auto detect normal map?
            if subtype == "normal":
                pass

    def iter_type(self):
        # assert self.type, "Image type is not defined."
        type_len = len(self.type)
        for index, subtype in enumerate(self.type):
            if type_len == 1: # RGB
                channel = 'RGB'
            elif type_len == 2: # RGB + A
                if index == 0:
                    channel = 'RGB'
                else:
                    channel = 'A'
            else: # R + G + B, R + G + B + A
                channel = INDEX_TO_CHANNEL[index]
            yield channel, subtype


    def get_channel(self, channel: str, image = None):
        log.debug(f"Getting channel: {channel}")

        if image is None:
            image = self.image
        if channel in {'R', 'G', 'B'}:
            if self.channels > 1:
                image = list(reversed(cv.split(image)))
                if self.channels == 4:
                    image = image[1:]
                image = image[CHANNEL_TO_INDEX[channel]]
            else:
                pass # does one channel image has R, G or B?
        elif channel == 'A':
            assert self.channels == 4, f"Image {self.path} does not have an alpha channel."
            image = cv.split(image)[-1]
        elif channel == 'RGB': # first three channels in BGR order
            if self.channels > 1:
                if self.channels == 4:
                    image = cv.cvtColor(image, cv.COLOR_BGRA2BGR)
            else:
                pass # is one channel image is RGB?
        else:
            raise KeyError(f"No such channel: '{channel}'.")
        return image


    def get_dominant_color(self, channel: str):  
        dominant_color = self.dominant_color.get(channel)
        if dominant_color:
            return dominant_color
        
        log.debug(f"Computing dominant color for channel: {channel}")
            
        image = self.get_channel(channel, self.resized(256))
        channels = self.get_shape(image)[2]
        image = image.reshape((-1,channels))
        image = np.float32(image)
        criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        result = cv.kmeans(image, 1, None, criteria, 10, cv.KMEANS_RANDOM_CENTERS)
        center = result[2][0].astype(float)
        
        if channels > 1:
            dominant_color = list(self.to_float(center[::-1]))
        else:
            dominant_color = list(self.to_float(center.repeat(3)))
            
        self.dominant_color[channel] = dominant_color
        return dominant_color


    def get_grayscaled(self, image = None) -> np.ndarray:
        log.debug(f"Getting grayscaled.")

        if image is None:
            image = self.image
            channels = self.channels
        else:
            channels = self.get_shape(image)[2]
        if channels > 1:
            if channels == 4:
                image = cv.cvtColor(image, cv.COLOR_BGRA2BGR)
            image = cv.transform(image, np.array([0.0722, 0.7152, 0.2126]).reshape((1,3)))
        return image


    def get_min_max(self, channel: str) -> typing.Tuple[float, float]:
        min_max = self.min_max.get(channel)
        if min_max:
            return min_max
        
        log.debug(f"Computing min max for channel: {channel}")

        image = self.get_channel(channel)
        channels = self.get_shape(image)[2]
        if channels > 1:
            image = self.get_grayscaled(image)
        
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(image)
        
        min_max = self.to_float(min_val), self.to_float(max_val)
        self.min_max[channel] = min_max
        return min_max
        

    # https://numpy.org/doc/stable/user/basics.types.html
    # https://numpy.org/doc/stable/reference/generated/numpy.finfo.html
    # https://numpy.org/doc/stable/reference/generated/numpy.iinfo.html
    def to_float(self, array: typing.Union[np.ndarray, float]) -> typing.Union[np.ndarray, float]:
        if self.dtype.startswith('float'):
            result = array
        elif self.dtype == 'uint8':
            result = array/255
        elif self.dtype == 'uint16':
            result = array/65535
        elif self.dtype == 'unit32':
            result = array/4294967295
        else:
            raise TypeError(f"Type {self.dtype} is not defined for the convertion to float.")

        try: not_bad = all(0 <= x <= 1 for x in result)
        except: not_bad = 0 <= result <= 1
        assert not_bad, f"Bad convertion to float 0-1 for {result}." # Move to report!

        return result

    def load(self, data):
        for key, value in data.items():
            if key in DUMPABLE:
                setattr(self, key, value)

    def dump(self):
        data = {key: getattr(self, key) for key in DUMPABLE + ONLY_DUMPABLE}
        return data

            
    def resized(self, target) -> np.ndarray:
        x = self.x
        y = self.y

        if x == y:
            x = y = target
        elif x > y:
            y = int(y/x * target)
            x = target
        else:
            x = int(x/y * target)
            y = target

        return cv.resize(self.image, (x, y))

    def set_bl_props(self, image_block):
        image_block["at_hash"] = self.hash
        image_block["at_type"] = self.type
        image_block["at_size"] = self.shape[:2]

    def to_uint8(self):
        image = self.image
        dtype = self.dtype
        if dtype == 'uint8':
            result = image
        elif dtype == 'uint16':
            result = image / 65535 * 255
        elif dtype == 'unit32':
            result = image / 4294967295 * 255
        elif dtype.startswith('float'):
            print("BAD!")
            result = cv.normalize(image, None, alpha=0, beta=255, norm_type=cv.NORM_MINMAX, dtype=cv.cv_8u)
        else:
            raise TypeError(f"Type {dtype} is not defined for the convertion to uint8.")
        return result

    def save(self, path):
        new_image_path = os.path.join(path, self.name, ".jpg")
        if not os.path.exists(new_image_path):
            image = self.to_uint8()
            cv.imwrite(new_image_path, image)

def save_as_icon(image: pillow_image.Image, path):
    x, y = image.size
    if x > y:
        box = ((x-y)/2, 0, (x+y)/2, y)
    elif x < y:
        box = (0, (y-x)/2, x, (y+x)/2)
    else:
        box = None
    image = image.resize((128, 128), resample = pillow_image.LANCZOS, box = box)
    icon_path = os.path.join(path, "__icon__.png")
    image.save(icon_path , "PNG", optimize=True)
    return icon_path

def save_as_icon_from_clipboard(path):
    grab = ImageGrab.grabclipboard()
    if not grab:
        print("No image in the clipboard.")
        return None
    return save_as_icon(grab, path)
        
def convert_unreal_image(path: str, format = 'png', bgr_to_rgb = False):
    new_name = os.path.splitext(os.path.basename(path))[0] + "." + format
    new_path = os.path.join(os.path.dirname(path), new_name)
    if not os.path.exists(new_path):
        with pillow_image.open(path) as tga:
            
            if bgr_to_rgb:
                getbands_len = len(tga.getbands())
                if getbands_len == 3:
                    r, g, b = tga.split()
                    tga = pillow_image.merge('RGB', (b, g, r))
                elif getbands_len == 4:
                    r, g, b, a = tga.split()
                    tga = pillow_image.merge('RGBA', (b, g, r, a))

            tga.save(new_path, format = format, compress_level=3)
            # ? optimize=True
    return new_path