from __future__ import annotations
import itertools
import json
import logging
import os
import re
import operator
import typing

log = logging.getLogger("atool")

try:
    from . import image_utils
    from . import utils
except:
    import image_utils
    import utils

SINGLE_CHANNEL_MAPS = ["metallic", "roughness", "displacement", "ambient_occlusion", "bump", "opacity", "gloss", "specular"]
TRIPLE_CHANNEL_MAPS = ["normal", "diffuse", "albedo", "emissive"]
SEPARATOR_PATTERN = re.compile(r"[^a-zA-Z0-9]+|$")

try:
    name_conventions_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bitmap_type_name_conventions.json")
    with open(name_conventions_path, "r", encoding='utf-8') as f:
        CONVENTIONS = json.load(f)
except:
    import traceback
    traceback.print_exc()
    CONVENTIONS = None


class Match:
    def __init__(self, string, reverse_dictionary):
        self.string = string
        self.string_length = len(string)
        self.reverse_dictionary = reverse_dictionary
        self.submatches = [] # type: typing.List[re.Match]
        self._type_list = None
        self.update()

    def append(self, submatch):
        self.submatches.append(submatch)
        self.update()

    def remove(self, index):
        del self.submatches[index]
        self.update()

    def update(self):

        self.is_separated = False
        self.is_pre_separated = False
        self.is_post_separated = False
        self.is_RGB_bitmap = False
        self.are_submatches_separated = False

        if not self.submatches:
            return

        if self.type_list[0] in TRIPLE_CHANNEL_MAPS:
            self.is_RGB_bitmap = True

        if len(self.submatches) == 1:
            self.are_submatches_separated = True
        else:
            self.are_submatches_separated = True
            for i in range(len(self.submatches) - 1):
                if not self.submatches[i].end() < self.submatches[i + 1].start():
                    self.are_submatches_separated = False

        first_char_index = self.submatches[0].start()
        if first_char_index != 0:
            if SEPARATOR_PATTERN.match(self.string, pos=first_char_index - 1):
                self.is_pre_separated = True
        elif first_char_index == 0:
            self.is_pre_separated = True

        last_char_index = self.submatches[-1].end()
        if last_char_index != self.string_length:
            if SEPARATOR_PATTERN.match(self.string, pos=last_char_index):
                self.is_post_separated = True
        elif last_char_index == self.string_length:
            self.is_post_separated = True
            
        if self.is_pre_separated and self.is_post_separated:
            self.is_separated = True

    @property
    def type_list(self) -> typing.List[str]:
        if self._type_list != None:
            return  self._type_list
        return [self.reverse_dictionary[submatch_str] for submatch_str in self.submatch_list]

    @type_list.setter
    def type_list(self, value):
        self._type_list = value

    @property
    def submatch_list(self) -> typing.List[str]:
        return [submatch.group(0) for submatch in self.submatches]

    @property
    def match_string(self):
        return ''.join(self.submatch_list)

    @property
    def length(self):
        return self.submatches[-1].end() - self.submatches[0].start()

    @property
    def is_one_letter_match(self):
        flag = True

        if self.length >= 3:
            flag = False
        else:
            for submatch in self.submatches:
                if len(submatch.group(0)) > 1:
                    flag = False
        return flag


def get_type(string: str, config = {}):

    if not CONVENTIONS:
        raise Exception("Cannot read file bitmap_type_name_conventions.json.")

    patterns = CONVENTIONS["bitmap"]["type"]

    for customized_type, custom_names in config.get("custom", {}).items():
        for type, names in patterns.items():
            patterns[type] = [name for name in names if name not in custom_names]
            patterns[customized_type].extend(custom_names)
        
    reverse_dictionary = {name: type for type, names in patterns.items() for name in names}
    patterns = {type: re.compile('|'.join(sorted(names, reverse=True, key=len))) for type, names in patterns.items()}


    string = string.lower()
    string_length = len(string)

    def match_length(match):
        start, end = match.span()
        return end - start

    def get_submatch(starting_index, types_to_avoid):
        submatches = [] # type: typing.List[re.Match]
        for type, pattern in patterns.items():
            if type in types_to_avoid:
                continue
            submatch = pattern.match(string, pos=starting_index)
            if submatch != None:
                submatches.append(submatch)
        
        return max(submatches, key=match_length) if submatches else None

    def define_bitmap_type(starting_index):

        match = Match(string, reverse_dictionary)

        for i in range(4):

            to_avoid = match.type_list
            if match.is_RGB_bitmap:
                to_avoid += TRIPLE_CHANNEL_MAPS

            separator = SEPARATOR_PATTERN.match(string, pos=starting_index)
            if separator:
                starting_index = separator.end()

            submatch = get_submatch(starting_index, to_avoid)
            if submatch == None:
                break
            match.append(submatch)
            starting_index = submatch.end()

            if not match.is_separated and match.are_submatches_separated:
                match.remove(-1)
                break
            if i == 1 and match.is_RGB_bitmap:
                break
            elif starting_index == string_length:
                break

        return match if match.submatches else None

    matches = [] # type: typing.List[Match]
    point = 0
    while point <= string_length:
        result = define_bitmap_type(point)
        if result == None:
            point += 1
        else:
            point = result.submatches[-1].end()
            matches.append(result)

    if not matches:
        return None

    for match in matches:
        type_list = match.type_list

        if len(type_list) == 1 and match.match_string == 'ddna':
            match.type_list = ['normal', 'gloss']
        
        if len(type_list) == 2 and type_list[0] in ('diffuse', 'albedo') and type_list[1] == 'metallic' and match.submatch_list[1].lower() == 'm':
            match.type_list = [type_list[0], 'opacity']

    if not config.get("is_rgb_plus_alpha"):
        for match in matches:
            if len(match.submatches) == 2:
                match.remove(0)

    variants = [match for match in matches if match.is_separated]
    if variants:
        return variants[-1].type_list

    variants = [match for match in matches if not match.is_one_letter_match]
    if variants:
        return variants[-1].type_list

    matches.reverse()
    match = max(matches, key=operator.attrgetter('length'))
    return match.type_list


def define(paths, config: dict):
        """
        `paths`: image file paths
        `config`: {
            "ignore_type": List[str],
            "ignore_format": List[Tuple[str, List[str]]],
            "prefer_type": List[Tuple[str, str]],
            "prefer_format": List[Tuple[str, str, List[str]]],
            "custom": Dict[str, List[str]],
            "file_info":  dict
        }
        """

        result = {}
        result["ok"] = False
        result["report"] = report = []
        queue = config.get("queue")
        images: typing.List[image_utils.Image]
        images = [image_utils.Image(path) for path in paths]


        extensions = set(CONVENTIONS["bitmap"]["extension"]).difference(set(config["ignore_format"]))

        for image in images.copy():
            if not image.extension in extensions:
                images.remove(image)
                report.append(({'INFO'},f"Image {image.name} was excluded by file format."))

        if not images:
            report.append(({'INFO'}, f"All images were excluded."))
            if queue:
                queue.put([result])
            return result


        ignore_type = set(config["ignore_type"])

        for image in images.copy():
            type = get_type(image.name, config)
            if not type:
                images.remove(image)
                report.append(({'INFO'}, f"Image {image.name} has not type."))
                continue
            if len(type) == 1 and type[0] in ignore_type:
                images.remove(image)
                report.append(({'INFO'}, f"Image {image.name} was excluded by type '{type[0]}'."))
                continue
            image.type = type
                
        if not images:
            report.append(({'INFO'}, f"All images were excluded."))
            if queue:
                queue.put([result])
            return result

        
        for preferred, ignored in config["prefer_type"]:
            for image in images.copy():
                if preferred in image.type:
                    for _image in images.copy():
                        type = [None if subtype == ignored else subtype for subtype in _image.type]
                        if not any(type):
                            images.remove(_image)
                            report.append(({'INFO'}, f"Image {image.name} was excluded by preferering type '{preferred}' over '{ignored}'."))
                        else:
                            _image.type = type
                            

        for preferred, ignored, types in config["prefer_format"]:
            for image in images.copy():
                if preferred == image.extension:
                    for _image in images.copy():
                        if _image.extension == ignored and len(_image.type) == 1 and _image.type[0] in types:
                            images.remove(_image)
                            report.append(({'INFO'}, f"Image {image.name} was excluded by preferering format '{preferred}' over '{ignored}'."))
                            
        
        result["images"] = images
        no_height = "displacement" not in set(itertools.chain.from_iterable([image.type for image in images]))


        asset = config.get("asset")
        if asset:
            file_info = asset.info.get("file_info")
            if not file_info:
                asset.info["file_info"] = file_info = {}
            for image in images:
                image.process(file_info = file_info, no_height = no_height)
                file_info[image.hash]["name"] = os.path.relpath(image.path, start = asset.path)
                file_info[image.hash]["type"] = image.type
                asset.update_info()
        else:
            with image_utils.Image_Cache_Database() as db:
                for image in images:
                    image.process(db = db, no_height = no_height)

        result["material_name"] = utils.get_longest_substring([image.name for image in images]).strip(" ").rstrip(" _-")

        result["ok"] = True
        if queue:
            queue.put([result])
        return result
