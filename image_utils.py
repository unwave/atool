from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Dict, List, Tuple, Type

import cv2 as cv
import numpy as np
from cached_property import cached_property
from PIL import Image as pillow_image
# import imagesize

log = logging.getLogger("atool")


try:
    from . import type_definer
    from . imohashxx import hashfile
except:
    import type_definer
    from imohashxx import hashfile

try:
    import bpy
except:
    pass


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

class Image:
    def __init__(self, path: str):
        self.path = path
        self.name, self.extension = os.path.splitext(os.path.basename(path))
        self.extension = self.extension.lower()

        self.data_block: object # bpy.types.Image
        self.type: List[str] # what if type definer retruns all possible types in order of more probable?
        self.min_max: Dict[str, Tuple[float, float]]
        self.min_max = {}
        self.dominant_color = {}
        self.image: np.ndarray
        self.dtype: str
        self.hash: str
        self.x: int
        self.y: int
        self.channels: int
        

    @classmethod
    def from_block(cls, block, define_type = True):
        image = cls(os.path.realpath(bpy.path.abspath(block.filepath, library=block.library)))
        image.data_block = block

        type = block.get("at_type")
        if not type:
            if define_type:
                type = type_definer.get_type(image.name)
            else:
                type = ['None']
        image.type = type

        return image
        
    def __repr__(self):
        return "<Image " + self.path + ">"
        
    @cached_property
    def hash(self):
        return hashfile(self.path, hexdigest=True)

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

            if self.extension in (".exr"): # bad
                for channel in reversed(cv.split(image)): # what if all channels?
                    if channel.any():
                        image = channel
        
        assert image is not None, f"The image {self.path} wasn't loaded!"
        log.debug(f"Image loaded: {self.path}")

        return image
    
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
        
    def process(self,  file_info: dict = None, db: Image_Cache_Database = None, no_height = False):
        assert not(file_info == None and db == None)

        hash = self.hash

        if file_info is not None:
            info = file_info.get(hash)
            if info:
                self.load(info)
                log.debug(f"Info for {self.path} has been read from the asset info.")
        else:
            if db:
                info = db.get((hash,))
                if info:
                    self.load(info[0])
                    log.debug(f"Info for {self.path} has been read from the database cache.")


        self.aspect_ratio

        for channel, subtype in self.iter_type():

            if subtype in {"diffuse", "albedo", "roughness", "gloss", "metallic"}:
                if not self.dominant_color.get(channel):
                    self.dominant_color[channel] = self.get_dominant_color(channel)

            # normalize if: height, roughness, gloss, specular
            if subtype in {"displacement", "roughness", "gloss", "specular"}:
                if not self.min_max.get(channel):
                    self.min_max[channel] = self.get_min_max(channel)

            # delight?
            # valid color range for PBR
            # normalize if out of range
            # if no height use color and normalize it
            if subtype in {"diffuse", "albedo"}:
                if no_height and not self.min_max.get(channel):
                    self.min_max[channel] = self.get_min_max(channel)

            # check if normal map is correct
            # auto-detect normals Y channel style, DirectX/OpenGL
            # invert x, y
            # sRGB/Linear
            # auto detect normal map?
            if subtype == "normal":
                pass

        
        if file_info is not None:
            if not file_info.get(hash):
                file_info[hash] = {}
            file_info[hash].update(self.dump())
        else:
            if db:
                db.set(self.hash, self.dump())


    def iter_type(self):
        assert self.type, "Image type is not defined."
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
        log.debug(f"Getting dominant color for channel: {channel}")

        image = self.get_channel(channel, self.resized(256))
        channels = self.get_shape(image)[2]
        image = image.reshape((-1,channels))
        image = np.float32(image)
        criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        result = cv.kmeans(image, 1, None, criteria, 10, cv.KMEANS_RANDOM_CENTERS)
        center = result[2][0].astype(float)
        if channels > 1:
            return list(self.to_float(center[::-1]))
        else:
            return list(self.to_float(center.repeat(3)))


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


    def get_min_max(self, channel: str):
        log.debug(f"Getting min max for channel: {channel}")

        image = self.get_channel(channel)
        channels = self.get_shape(image)[2]
        if channels > 1:
            image = self.get_grayscaled(image)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(image)
        return self.to_float(min_val), self.to_float(max_val)
        

    # https://numpy.org/doc/stable/user/basics.types.html
    # https://numpy.org/doc/stable/reference/generated/numpy.finfo.html
    # https://numpy.org/doc/stable/reference/generated/numpy.iinfo.html
    def to_float(self, array):
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
        data = {key: getattr(self, key) for key in DUMPABLE}
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