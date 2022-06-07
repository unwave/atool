from __future__ import annotations
import itertools
import json
import logging
import os
import re
import operator
import typing

import inflection

log = logging.getLogger("atool")

if __package__:
    from . import image_utils
    from . import utils
else:
    import image_utils
    import utils

SINGLE_CHANNEL_MAPS = ["metallic", "roughness", "displacement", "ambient_occlusion", "bump", "opacity", "gloss", "specular"]
TRIPLE_CHANNEL_MAPS = ["normal", "diffuse", "albedo", "emissive"]
SEPARATOR_PATTERN = re.compile(r"[^a-zA-Z0-9]+|$")

try:
    name_conventions_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bitmap_type_name_conventions.json")
    with open(name_conventions_path, "r", encoding='utf-8') as f:
        CONVENTIONS: dict = json.load(f)
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
        self._type_list = None # type: typing.List[str]
        
    def copy(self):
        match = Match(self.string, self.reverse_dictionary)
        match.submatches = self.submatches.copy()
        if self._type_list:
            match._type_list = self._type_list.copy()
        return match
        
    def __repr__(self):
        return f"<type_definer.Match object; {self.submatch_list}>"

    def append(self, submatch):
        self.submatches.append(submatch)

    def remove(self, index):
        del self.submatches[index]
        
    @property
    def is_separated(self):
        if not self.submatches:
            return False
        
        if self.is_pre_separated and self.is_post_separated:
            return True
        
        return False
    
    @property
    def is_pre_separated(self):
        if not self.submatches:
            return False
        
        first_char_index = self.submatches[0].start()
        if first_char_index != 0:
            if SEPARATOR_PATTERN.match(self.string, pos=first_char_index - 1):
                return True
        elif first_char_index == 0:
            return True
        
        return False

    @property
    def is_post_separated(self):
        if not self.submatches:
            return False
        
        last_char_index = self.submatches[-1].end()
        if last_char_index != self.string_length:
            if SEPARATOR_PATTERN.match(self.string, pos=last_char_index):
                return True
        elif last_char_index == self.string_length:
            return True
            
        return False
    
    @property
    def is_RGB_bitmap(self):
        if not self.submatches:
            return False
        
        if self.type_list[0] in TRIPLE_CHANNEL_MAPS:
            return True
        
        return False
    
    @property
    def are_submatches_separated(self):
        if len(self.submatches) <= 1:
            return False
        
        for i in range(len(self.submatches) - 1):
            if not self.submatches[i].end() < self.submatches[i + 1].start():
                return False
                
        return True
    
    @property
    def are_any_submatches_separated(self):
        if len(self.submatches) <= 1:
            return False
        
        for i in range(len(self.submatches) - 1):
            if self.submatches[i].end() < self.submatches[i + 1].start():
                return True
            
        return False

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
        return False if self.length > len(self.submatches) else True

class Filter_Config:
    def __init__(self):
        self.ignore_type: typing.List[str]  = []
        self.ignore_format: typing.List[typing.Tuple[str, typing.List[str]]]  = []
        self.prefer_type: typing.List[typing.Tuple[str, str]]  = []
        self.prefer_format: typing.List[typing.Tuple[str, str, typing.List[str]]]  = []
        
        self.custom: typing.Dict[str, typing.List[str]] = {}
        self.is_rgb_plus_alpha: bool = True   
        
        self.is_strict: bool = True
        
        self.common_prefix: str = None
        self.common_prefix_len: int
        
        if not image_utils.OPENCV_IO_ENABLE_OPENEXR:
            self.ignore_format.append('.exr')
        
    def set_common_prefix_from_paths(self, paths: typing.Iterable[str]):
        self.set_common_prefix((os.path.splitext(os.path.basename(path))[0] for path in paths))
        
    def set_common_prefix(self, names: typing.Iterable[str]):
        names = list(names)
        if len(names) <= 1:
            return
        
        common_prefix = utils.get_longest_substring(names, from_beginning = True)
        if not common_prefix:
            return
            
        self.common_prefix = common_prefix
        self.common_prefix_len = len(self.common_prefix)
    
    @property
    def dict(self):
        return {key: value for key, value in self.__dict__.items() if not key.startswith('__')}

def get_type(string: str, config: Filter_Config = None):
    
    if not CONVENTIONS:
        raise Exception("Cannot read file bitmap_type_name_conventions.json.")

    patterns = CONVENTIONS["bitmap"]["type"].copy() # type: dict   
    
    is_strict = config.is_strict if config else True
    
    ignores = patterns.pop('ignore') # type: dict
    if is_strict: # temporally only for external testing
        for ignore in ignores:
            ignore = patterns.pop(ignore)

    if config:
        for customized_type, custom_names in config.custom.items():
            for type, names in patterns.items():
                patterns[type] = [name for name in names if name not in custom_names]
            patterns[customized_type].extend(custom_names)
        
    reverse_dictionary = {name: type for type, names in patterns.items() for name in names}
    patterns = {type: re.compile('|'.join(sorted(names, reverse=True, key=len))) for type, names in patterns.items()}

    if config and config.common_prefix:
        if string.startswith(config.common_prefix): # protect if config is reused
            string = string[config.common_prefix_len:]

    string = inflection.underscore(string)
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
            if submatch:
                submatches.append(submatch)
        
        return max(submatches, key=match_length) if submatches else None

    def define_bitmap_type(starting_index):

        match = Match(string, reverse_dictionary)

        for i in range(4):

            to_avoid = match.type_list
            if match.is_RGB_bitmap or i > 0:
                to_avoid += TRIPLE_CHANNEL_MAPS

            separator = SEPARATOR_PATTERN.match(string, pos=starting_index)
            if separator:
                starting_index = separator.end()

            submatch = get_submatch(starting_index, to_avoid)
            if not submatch:
                break
            match.append(submatch)
            starting_index = submatch.end()

            if i == 1 and match.is_RGB_bitmap:
                break
            elif starting_index == string_length:
                break
            
        if not match.submatches:
            return None

        return match

    matches = [] # type: typing.List[Match]
    point = 0
    while point <= string_length:
        result = define_bitmap_type(point)
        if result:
            # point = result.submatches[-1].end()
            point += 1
            matches.append(result)
        else:
            point += 1

    if not matches:
        return None
    
    def filter_strict(matches: typing.List[Match]):
        matches = matches.copy()
        
        for match in matches.copy():
            while not match.is_separated:
                
                if not match.submatches:
                    matches.remove(match)
                    break

                match.remove(-1)
        
        for match in matches.copy():
            if not match.are_submatches_separated and match.are_any_submatches_separated:
                matches.remove(match)
                
        return matches
        
    if is_strict:
        matches = filter_strict(matches)
        if not matches:
            return None
    else:
        not_strict_maches = [match.copy() for match in matches]
        matches = filter_strict(matches)
        
        if not not_strict_maches:
            return None

        if not matches:
            matches = not_strict_maches
            
            for match in matches.copy():
                
                if match.are_submatches_separated and not match.is_separated:
                    matches.remove(match)
                    continue
                
                if match.is_one_letter_match:
                    matches.remove(match)
                    continue
                    
            if not matches:
                return None
                    
    for match in matches: # exceptions
        type_list = match.type_list

        if len(type_list) == 1:

            if match.match_string == 'ddna':
                match.type_list = ['normal', 'gloss']

            # elif match.match_string == 'arm':
            #     match.type_list = ['ambient_occlusion', 'roughness', 'metallic']

        elif len(type_list) == 2 and type_list[0] in ('diffuse', 'albedo') and type_list[1] == 'metallic' and match.submatch_list[1].lower() == 'm':
            match.type_list = [type_list[0], 'opacity']
        
    # if not is_strict:
    #     for match in matches:
    #         for index, type in enumerate(type_list):
    #             if type in ignores:
    #                 new_type_list = match.type_list
    #                 new_type_list[index] = None
    #                 match.type_list = new_type_list

    if config and not config.is_rgb_plus_alpha:
        for match in matches:
            if len(match.submatches) == 2:
                match.remove(0)
                
    # print(*matches, sep="\n")
    
    match = max(matches, key=operator.attrgetter('length'))
    return match.type_list

    # variants = [match for match in matches if match.is_separated]
    # if variants:
    #     return variants[-1].type_list

    # variants = [match for match in matches if not match.is_one_letter_match]
    # if variants:
    #     return variants[-1].type_list

    return matches[-1].type_list

    # matches.reverse()
    # match = max(matches, key=operator.attrgetter('length'))
    # return match.type_list
    

def filter_by_config(images: typing.List[image_utils.Image], config: Filter_Config):
    """
    return `paths`, `report`
    `images`: list of tuples, (<path>, <type>)
    `report`: `list`, in the Blender's `operator.report` style,
    """
    images = images.copy()
    report = []

    extensions = set(CONVENTIONS["bitmap"]["extension"]).difference(set(config.ignore_format))
    for image in images.copy():
        if not image.extension in extensions:
            images.remove(image)
            report.append(({'INFO'},f"Image {image.basename} was excluded by file format."))


    ignore_type = set(config.ignore_type)
    for image in images.copy():
        type = image.type
        if not type:
            images.remove(image)
            report.append(({'INFO'}, f"Image {image.basename} has no type detected."))
            continue
        if len(type) == 1 and type[0] in ignore_type:
            images.remove(image)
            report.append(({'INFO'}, f"Image {image.basename} was excluded by type '{type[0]}'."))
            continue
        
    
    for preferred, ignored in config.prefer_type:
        for image in images.copy():

            if not preferred in image.type:
                continue

            for _image in images.copy():

                type = [None if subtype == ignored else subtype for subtype in _image.type]
                
                if not any(type):
                    images.remove(_image)
                    report.append(({'INFO'}, f"Image {_image.basename} was excluded by preferring type '{preferred}' over '{ignored}'."))
                    continue

                _image.type = type
    
    
    for preferred, ignored, types in config.prefer_format:
        for image in images.copy():

            if preferred != image.extension:
                continue

            for _image in images.copy():
                if _image.extension == ignored and len(_image.type) == 1 and _image.type[0] in types:
                    images.remove(_image)
                    report.append(({'INFO'}, f"Image {_image.basename} was excluded by preferring format '{preferred}' over '{ignored}'."))
                    
    return images, report