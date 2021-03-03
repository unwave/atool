import re
import os
import json
from difflib import SequenceMatcher

# import inspect
# def possible_variants_debug_print(possible_variants):
#     for variant in possible_variants:
#         variant = [i for i in inspect.getmembers(variant) if not i[0].startswith('_') and not inspect.isroutine(i[1])]
#         print(*variant, sep='\n')
#         print()

SINGLE_CHANNEL_MAPS = ["metallic", "roughness", "displacement", "ambient_occlusion", "bump", "opacity", "gloss", "specular"]
TRIPLE_CHANNEL_MAPS = ["normal", "diffuse", "albedo", "emissive"]

separator_pattern = re.compile(r"[^a-zA-Z0-9]+|$")

def define(image_path_list, is_rgb_plus_alpha = False, a_for_ambient_occlusion = False):

        def define_type(string):
            string_length = len(string)

            def match_length(match):
                start, end = match.span()
                return end - start

            def get_submatch(starting_index, patterns_names_to_avoid):
                submatches = []
                for pattern_name in bitmap_patterns_names:
                    if pattern_name in patterns_names_to_avoid:
                        continue
                    submatch = bitmap_type_patterns[pattern_name].match(string, pos=starting_index)
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
                        if separator_pattern.match(self.string, pos=first_char_index - 1):
                            self.is_pre_separated = True
                    elif first_char_index == 0:
                        self.is_pre_separated = True

                    last_char_index = self.submatches[-1].span()[1]
                    if last_char_index != self.string_length:
                        if separator_pattern.match(self.string, pos=last_char_index):
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

                    separator = separator_pattern.match(string, pos=starting_index)
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

            if not is_rgb_plus_alpha:
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


        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        name_conventions_file_path = os.path.join(script_file_directory, "bitmap_type_name_conventions.json")
        try:
            with open(name_conventions_file_path, "r", encoding='utf-8') as f:
                name_conventions = json.load(f)
        except:
            import traceback
            traceback.print_exc()
            raise

        bitmap_type_patterns = {}
        for bitmap_type in name_conventions["bitmap"]["type"]:
            bitmap_type_names = name_conventions["bitmap"]["type"][bitmap_type]

            if a_for_ambient_occlusion == True:
                if bitmap_type == 'albedo':
                    try:
                        bitmap_type_names.remove("a")
                    except:
                        pass
                if bitmap_type == 'ambient_occlusion':
                    bitmap_type_names.append("a")
                    
            bitmap_type_names.sort(reverse=True, key=len)
            bitmap_type_patterns[bitmap_type] = re.compile('|'.join(bitmap_type_names))


        bitmap_patterns_names = list(bitmap_type_patterns)

        reverse_dictionary = {}
        for bitmap_type in name_conventions["bitmap"]["type"]:
            for name_variant in name_conventions["bitmap"]["type"][bitmap_type]:
                reverse_dictionary[name_variant] = bitmap_type

        bitmap_paths = []
        bitmap_names = []

        def if_any(string):
            for pattern_name in bitmap_patterns_names:
                if bitmap_type_patterns[pattern_name].search(string):
                    return True
            return False

        for file_path in image_path_list:
            basename = os.path.splitext(os.path.basename(file_path))
            name = basename[0].lower()
            extension = basename[1].lower()
            if extension in name_conventions["bitmap"]["extension"] and if_any(name):
                bitmap_paths.append(file_path)
                bitmap_names.append(name)

        number_of_bitmaps = len(bitmap_names)
        material_name = ""
        if number_of_bitmaps == 0:
            return None
        elif number_of_bitmaps == 1:
            material_name = bitmap_names[0].rstrip("_-")
        else:
            material_name_match = SequenceMatcher(None, bitmap_names[0], bitmap_names[1]).find_longest_match(0, len(bitmap_names[0]), 0, len(bitmap_names[1]))
            if material_name_match:
                material_name = bitmap_names[0][material_name_match.a:material_name_match.a + material_name_match.size].rstrip("_-")
            # also removes important things
            # matches = SequenceMatcher(None, bitmap_names[0], bitmap_names[1]).get_matching_blocks()
            # for match in matches:
            #     match_flag = True
            #     match_string = bitmap_names[0][match.a:match.a + match.size]
            #     for rest_index in range(number_of_bitmaps)[2:]:
            #         if not re.search(match_string, bitmap_names[rest_index]):
            #             match_flag = False
            #     if match_flag:
            #         for i in range(number_of_bitmaps):
            #             bitmap_names[i] = re.sub(match_string, "", bitmap_names[i], count=0, flags=0)

        final_bitmap_paths = []
        final_bitmap_types = []
        for bitmap_name, bitmap_path in zip(bitmap_names, bitmap_paths):
            bitmap_type = define_type(bitmap_name)
            if bitmap_type:
                final_bitmap_paths.append(bitmap_path)
                final_bitmap_types.append(bitmap_type)

        if final_bitmap_paths:
            return zip(final_bitmap_paths, final_bitmap_types), material_name
        else:
            return None