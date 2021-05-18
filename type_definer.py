from __future__ import annotations
import itertools
import json
import logging
import os
import re
from difflib import SequenceMatcher
import typing

log = logging.getLogger("atool")

try:
    from . import image_utils
except:
    import image_utils

# import inspect
# def possible_variants_debug_print(possible_variants):
#     for variant in possible_variants:
#         variant = [i for i in inspect.getmembers(variant) if not i[0].startswith('_') and not inspect.isroutine(i[1])]
#         print(*variant, sep='\n')
#         print()

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


def get_type(string, config = {}):

    string = string.lower()

    if not CONVENTIONS:
        raise Exception("Cannot read file bitmap_type_name_conventions.json.")

    patterns = CONVENTIONS["bitmap"]["type"]

    for customized_type, custom_names in config.get("custom", {}).items():
        for type, names in patterns.items():
            patterns[type] = [name for name in names if name not in custom_names]
            patterns[customized_type].extend(custom_names)
        
    reverse_dictionary = {name: type for type, names in patterns.items() for name in names}
    patterns = {type: re.compile('|'.join(sorted(names, reverse=True, key=len))) for type, names in patterns.items()}

    string_length = len(string)

    def match_length(match):
        start, end = match.span()
        return end - start

    def get_submatch(starting_index, types_to_avoid):
        submatches = []
        for type, pattern in patterns.items():
            if type in types_to_avoid:
                continue
            submatch = pattern.match(string, pos=starting_index)
            if submatch != None:
                submatches.append(submatch)
        
        return max(submatches, key=match_length) if submatches else None

    class Match:
        def __init__(self, string):
            self.submatches = []
            self.string = string
            self.string_length = len(string)
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
            self.bitmap_types = []

            if not self.submatches:
                return

            self.bitmap_types = [self.submatch_to_bitmap_type(submatch) for submatch in self.submatches]

            if self.bitmap_types[0] in TRIPLE_CHANNEL_MAPS:
                self.is_RGB_bitmap = True

            if len(self.submatches) == 1:
                self.are_submatches_separated = True
            else:
                self.are_submatches_separated = True
                for i in range(len(self.submatches) - 1):
                    if not self.submatches[i].span()[1] < self.submatches[i + 1].span()[0]:
                        self.are_submatches_separated = False

            first_char_index = self.submatches[0].span()[0]
            if first_char_index != 0:
                if SEPARATOR_PATTERN.match(self.string, pos=first_char_index - 1):
                    self.is_pre_separated = True
            elif first_char_index == 0:
                self.is_pre_separated = True

            last_char_index = self.submatches[-1].span()[1]
            if last_char_index != self.string_length:
                if SEPARATOR_PATTERN.match(self.string, pos=last_char_index):
                    self.is_post_separated = True
            elif last_char_index == self.string_length:
                self.is_post_separated = True
                
            if self.is_pre_separated and self.is_post_separated:
                self.is_separated = True

        def submatch_to_bitmap_type(self, match):
            start, end = match.span()
            return  reverse_dictionary[self.string[start:end]]

        def get_submatch_list(self):
            return [self.string[submatch.span()[0]:submatch.span()[1]] for submatch in self.submatches]

        def get_length(self):
            return self.submatches[-1].span()[1] - self.submatches[0].span()[0]


    def define_bitmap_type(starting_index):

        match = Match(string)

        for i in range(4):

            if match.is_RGB_bitmap:
                to_avoid = match.bitmap_types + TRIPLE_CHANNEL_MAPS
            else:
                to_avoid = match.bitmap_types

            separator = SEPARATOR_PATTERN.match(string, pos=starting_index)
            if separator:
                starting_index = separator.span()[1]

            submatch = get_submatch(starting_index, to_avoid)
            if submatch == None:
                break
            match.append(submatch)
            starting_index = submatch.span()[1]

            if not match.is_separated and match.are_submatches_separated:
                match.remove(-1)
                break
            if i == 1 and match.is_RGB_bitmap:
                break
            elif starting_index == string_length:
                break

        return match if match.submatches else None

    possible_variants = []
    point = 0
    while point <= string_length:
        results = define_bitmap_type(point)
        if results == None:
            point += 1
        else:
            point = results.submatches[-1].span()[1]
            possible_variants += [results]

    if not possible_variants:
        return None

    def submatch_to_string(submatch):
        return  string[submatch.span()[0]:submatch.span()[1]]

    def get_match_length(match):
        return match.get_length()

    # def is_one_letter_match_list(match):
    #     flag = False

    #     if len(''.join(match)) >= 3:
    #         flag = True
    #     else:
    #         for submatch in match:
    #             if len(submatch) > 1:
    #                 flag = True
    #     return flag
        
    def is_one_letter_match(match):
        flag = True

        if match.get_length() >= 3:
            flag = False
        else:
            for submatch in match.submatches:
                if len(submatch_to_string(submatch)) > 1:
                    flag = False
        return flag

    if not config.get("is_rgb_plus_alpha"):
        for variant in possible_variants:
            if len(variant.submatches) == 2:
                variant.remove(0)
        
    separated_matches_only = [match for match in possible_variants if match.is_separated]
    if separated_matches_only != []:
        result = separated_matches_only[-1].get_submatch_list()
        result = [reverse_dictionary[i] for i in result]
    else:
        not_one_letter_matches = [match for match in possible_variants if not is_one_letter_match(match)]
        if not_one_letter_matches != []:
            result = not_one_letter_matches[-1].get_submatch_list()
            result = [reverse_dictionary[i] for i in result]
        else:
            possible_variants.reverse()
            result = max(possible_variants, key=get_match_length)
            result = result.get_submatch_list()
            result = [reverse_dictionary[i] for i in result]
    return result


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
        images = [image_utils.Image(path.lower()) for path in paths]


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


        material_name = ""
        if len(images) == 1:
            material_name = images[0].name.rstrip("_-")
        else:
            first = images[0].name
            second = images[1].name
            match = SequenceMatcher(None, first, second).find_longest_match(0, len(first), 0, len(second))
            if match:
                material_name = first[match.a:match.a + match.size].rstrip("_-")
        result["material_name"] = material_name


        result["ok"] = True
        if queue:
            queue.put([result])
        return result
