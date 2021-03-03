import bpy
from bpy_extras.io_utils import ImportHelper

import sys
import subprocess
import os
import json
import sqlite3
from dataclasses import dataclass, field
from collections import Counter
import itertools

from . view_3d_operator import get_current_browser_asset
from . import type_definer
from . imohashxx import hashfile
from PIL import Image as pillow_image

# from timeit import default_timer as timer

class Shader_Editor_Poll:
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'NODE_EDITOR' and context.space_data.tree_type == 'ShaderNodeTree'

def backward_compatibility_get(object, attribute: str, old_attribute: str): # matapp backward compatibility
    value = object.get(attribute) 
    if value != None:
        return value
    value = object.get(old_attribute)
    if value == None:
        return None
    object[attribute] = value
    del object[old_attribute]
    return value

def is_atool_material(group):
    if group.bl_idname == "ShaderNodeGroup":
        node_tree = group.node_tree
    elif group.bl_idname == "ShaderNodeTree":
        node_tree = group
    else:
        return False
    if not node_tree:
        return False
    else:
        nodes = node_tree.nodes
        material_output = nodes.get("Group Output")
        if material_output and (material_output.label == "__atool_material__" or material_output.label.startswith("matapptemp")): # matapp backward compatibility
            return True
        else:
            return False

def get_all_lt_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            operator.report({'INFO'}, "Nothing is selected. Select a AT material node group.")
            return []

        atool_node_groups = [node for node in selected_nodes if is_atool_material(node)]

        if not atool_node_groups:
            operator.report({'INFO'}, "No AT materials found in the selection. Select a AT material node group.")
            return []

        return atool_node_groups

def get_all_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            operator.report({'INFO'}, "Nothing is selected. Select a node group.")
            return []

        node_groups = [node for node in selected_nodes if node.type == 'GROUP']

        if not node_groups:
            operator.report({'INFO'}, "No node groups found in the selection. Select a node group.")
            return []

        return node_groups

def get_all_image_data_blocks(group):

        image_data_blocks = [node.image for node in group.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
        if not image_data_blocks:
            return None
        image_data_blocks = list(dict.fromkeys(image_data_blocks))

        return image_data_blocks

def find_image_block_by_type(blocks , type):
    for block in blocks:
        lt_type = backward_compatibility_get(block, "at_type", "ma_type")
        if type in lt_type:
            type_index = lt_type.index(type)
            if len(lt_type) <= 2:
                channel_names = {0: 'RGB', 1: 'A'}
                return (block, channel_names[type_index])
            else:
                channel_names = {0: 'R', 1: 'G', 2: 'B', 3: 'A'}
                return (block, channel_names[type_index])
    return None

def get_image_absolute_path(image):
    return os.path.realpath(bpy.path.abspath(image.filepath, library=image.library))

def get_node_tree_by_name(name):
    
    if name not in [i.name for i in bpy.data.node_groups]:
        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        templates_file_path = os.path.join(script_file_directory, "data.blend", "NodeTree")
        bpy.ops.wm.append(directory = templates_file_path, filename = name, set_fake = True)
        node_tree =  bpy.data.node_groups[name]
    else:
        node_tree =  bpy.data.node_groups[name]
    
    return node_tree

def add_lt_blending_node(operator, context, two_nodes, blend_node_tree):

    links = context.space_data.edit_tree.links
    nodes = context.space_data.edit_tree.nodes

    blend_node = nodes.new( type = 'ShaderNodeGroup' )
    blend_node.node_tree = blend_node_tree

    first_node, second_node = two_nodes

    first_node_location_x = first_node.location.x
    second_node_location_x = second_node.location.x

    if second_node_location_x >= first_node_location_x:
        blend_node_location_x = second_node_location_x
    else:
        blend_node_location_x = first_node_location_x

    blend_node_location_y = (first_node.location.y + second_node.location.y)/2 + 200
    blend_node.location = (blend_node_location_x + 400, blend_node_location_y)

    blend_node.width = 200
    blend_node.show_options = False

    blend_node_input_names = [i.name for i in blend_node.outputs if i.name != "Mask"]
    first_node_output_names = {i.name for i in first_node.outputs}
    second_node_output_names = {i.name for i in second_node.outputs}

    def add_geometry_normal_input(input_number):
        geometry_normal_node = nodes.new(type="ShaderNodeNewGeometry")
        geometry_normal_node.location = (blend_node.location.x - 175, blend_node.location.y - 300 - 100 * (input_number - 1))
        links.new(geometry_normal_node.outputs["Normal"], blend_node.inputs["Normal " + str(input_number)])
        for output in geometry_normal_node.outputs:
            if output.name != "Normal":
                output.hide = True

    for input_name in blend_node_input_names:

        is_name_used_by_first_input = False
        is_name_used_by_second_input = False
        if input_name in first_node_output_names and not first_node.outputs[input_name].hide:
            links.new(first_node.outputs[input_name], blend_node.inputs[input_name + " 1"])
            is_name_used_by_first_input = True
        if input_name in second_node_output_names and not second_node.outputs[input_name].hide:
            links.new(second_node.outputs[input_name], blend_node.inputs[input_name + " 2"])
            is_name_used_by_second_input = True

        if is_name_used_by_first_input and is_name_used_by_second_input:
            pass
        elif not is_name_used_by_first_input and not is_name_used_by_second_input:
            blend_node.outputs[input_name].hide = True
            blend_node.inputs[input_name + " 1"].hide = True
            blend_node.inputs[input_name + " 2"].hide = True
        elif input_name == "Normal":
            if not is_name_used_by_first_input and is_name_used_by_second_input:
                add_geometry_normal_input(1)
            elif is_name_used_by_first_input and not is_name_used_by_second_input:
                add_geometry_normal_input(2)

    return {'FINISHED'}

class ATOOL_OT_height_blend(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.add_height_blend"
    bl_label = "Add Height Blend"
    bl_description = "Add height blend for selected nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select two nodes")
            return {'CANCELLED'}

        return add_lt_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), get_node_tree_by_name("Height Blend AT"))


class ATOOL_OT_detail_blend(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.add_detail_blend"
    bl_label = "Add Detail Blend"
    bl_description = "Add detail blend for selected nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select two nodes")
            return {'CANCELLED'}

        return add_lt_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), get_node_tree_by_name("Detail Blend AT"))


class ATOOL_OT_make_links(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.make_material_links"
    bl_label = "Make Links"
    bl_description = "Make links between matching socket names from active to selected"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select at least two nodes.")
            return {'CANCELLED'}

        links = context.space_data.edit_tree.links

        active = selected_nodes[0]
        selected = selected_nodes[1:]

        active_output_names = {socket.name for socket in active.outputs if not socket.hide}
        selected_inputs = list(itertools.chain.from_iterable([node.inputs for node in selected]))

        for input in selected_inputs:
            if not input.hide:
                socket_name = input.name
                if socket_name in active_output_names:
                    links.new(active.outputs[socket_name], input)

        return {'FINISHED'}


def ensure_adaptive_subdivision(operator, context, new_material = False):

    active_object = context.object
    if not active_object:
        operator.report({'INFO'}, "Select an object.")
        return {'CANCELLED'}

    active_material = active_object.active_material
    if not active_material:
        operator.report({'INFO'}, "Select a material.")
        return {'CANCELLED'}

    if new_material:
        nodes = active_material.node_tree.nodes
        links = active_material.node_tree.links
        active_node = None
    else:
        nodes = context.space_data.edit_tree.nodes
        links = context.space_data.edit_tree.links
        selected_nodes = context.selected_nodes
        if selected_nodes:
            active_node = selected_nodes[0]
        else:
            active_node = None

    context.scene.cycles.feature_set = 'EXPERIMENTAL'

    context.scene.cycles.preview_dicing_rate = operator.preview_dicing_rate
    context.scene.cycles.offscreen_dicing_scale = operator.offscreen_dicing_scale

    active_material.cycles.displacement_method = 'DISPLACEMENT'
    active_object.cycles.use_adaptive_subdivision = True

    if active_object.modifiers:
        if active_object.modifiers[-1].type != 'SUBSURF':
            subdivision_modifier = active_object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
            subdivision_modifier.subdivision_type = 'SIMPLE'
    else:
        subdivision_modifier = active_object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
        subdivision_modifier.subdivision_type = 'SIMPLE'


    material_output_nodes = [node for node in nodes if node.type == 'OUTPUT_MATERIAL']

    if material_output_nodes == []:
        operator.report({'INFO'}, "No material output node found.")
        return {'CANCELLED'}

    material_output = None
    for material_output_node in material_output_nodes:
        if material_output_node.is_active_output:
            material_output = material_output_node
            break
    if not material_output:
        operator.report({'INFO'}, "No active material output found.")
        return {'CANCELLED'}

    def add_displacement_node():
        displacement_node = nodes.new( type = "ShaderNodeDisplacement" )

        (x, y) = material_output.location
        displacement_node.location = (x, y - 150)

        links.new(displacement_node.outputs[0], material_output.inputs[2])

        displacement_node.inputs[3].hide = True

        return displacement_node
    
    material_output_displacement_links = material_output.inputs[2].links
    if not material_output_displacement_links:
        displacement_node = add_displacement_node()
    else:
        node = material_output_displacement_links[0].from_node
        if node.type == 'DISPLACEMENT':
            displacement_node = node
            if displacement_node.inputs[0].links:
                return {'FINISHED'}
        else:
            displacement_node = add_displacement_node()


    if active_node:
        height_output = active_node.outputs.get("Height")
        if height_output:
            links.new(height_output, displacement_node.inputs[0])
            return {'FINISHED'}

    material_output_shader_links = material_output.inputs[0].links

    if material_output_shader_links:
        to_material_output = material_output_shader_links[0].from_node
        if to_material_output.type == 'BSDF_PRINCIPLED':
            # socket_names = []
            color_links = to_material_output.inputs[0].links
            if color_links:
                to_bsdf = color_links[0].from_node
                to_bsdf_height = to_bsdf.outputs.get("Height")
                if to_bsdf_height:
                    links.new(to_bsdf.outputs["Height"], displacement_node.inputs[0])
                    return {'FINISHED'}

    operator.report({'INFO'}, "Cannot find height. Select a node with a \"Height\" output socket.")
    return {'FINISHED'}

class ATOOL_OT_ensure_adaptive_subdivision(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.ensure_adaptive_subdivision"
    bl_label = "Ensure Adaptive Subdivision"
    bl_description = "Ensure adaptive subdivision setup for the active object"
    bl_options = {'REGISTER', 'UNDO'}

    preview_dicing_rate: bpy.props.IntProperty(
        name="Preview Dicing Rate",
        default = 1
        )

    offscreen_dicing_scale: bpy.props.IntProperty(
        name="Offscreen Dicing Scale",
        default = 16
        )

    def execute(self, context):
        return ensure_adaptive_subdivision(self, context)


def normalize_texture(operator, context, new_material = False, node_groups = []):

    def find_max_and_min(image, channel_name = 'R', all_channels = False):

        filepath = get_image_absolute_path(image)

        if filepath.lower().endswith(".exr"):
            operator.report({'INFO'}, f"Cannot normalize {image.filepath}, EXR is not supported")
            return

        with pillow_image.open(filepath) as image:
            image_bands = image.getbands()
            if len(image_bands) > 1:
                if all_channels:
                    relative_luminance = (0.2126, 0.7152, 0.0722, 0)
                    if len(image_bands) == 4:
                        image = image.convert("RGB")
                    bw_image = image.convert('L', relative_luminance)
                    (minimum, maximum) = bw_image.getextrema()
                else:
                    channel = image.getchannel(channel_name)
                    (minimum, maximum) = channel.getextrema()
            else:
                (minimum, maximum) = image.getextrema()

        average = (minimum + maximum)/2
        if average < 1:
            pass
        elif average >= 1 and average < 255:
            (minimum, maximum) = (minimum/255.0, maximum/255.0)
        elif average >= 255:
            (minimum, maximum) = (minimum/65535.0, maximum/65535.0)

        return (minimum, maximum)
    
    if new_material:
        groups = node_groups
        images = []
    else:
        groups = operator.groups
        images = operator.images

    nodes = context.space_data.edit_tree.nodes
    links = context.space_data.edit_tree.links

    for group in groups:

        image_data_blocks = get_all_image_data_blocks(group)
        if not image_data_blocks:
            operator.report({'INFO'}, f"No image found in the group: {group.name}")
            continue

        # group_flags = group.node_tree["at_flags"] # not yet used

        if operator.normalize_height:

            height_mix_in = group.node_tree.nodes.get("displacement_mix_in")
            if not height_mix_in:
                height_mix_in = group.node_tree.nodes.get("displacement_x_mix_in")

            if not height_mix_in:
                operator.report({'WARNING'}, f"Failed to find a hight map for the group: {group.name}")
                continue
        
            height_mix_in_input_link = height_mix_in.inputs[0].links[0]
            to_height_mix_in = height_mix_in_input_link.from_node

            if to_height_mix_in.type == 'TEX_IMAGE':
                image = to_height_mix_in.image
                if height_mix_in_input_link.from_socket.name == "Alpha":
                    result = find_max_and_min(image, 'A')
                else:
                    result = find_max_and_min(image)
            elif to_height_mix_in.type == 'GAMMA':
                image = to_height_mix_in.inputs[0].links[0].from_node.image
                result = find_max_and_min(image, all_channels = True)
            elif to_height_mix_in.type == 'SEPRGB':
                image = to_height_mix_in.inputs[0].links[0].from_node.image
                channel_name = height_mix_in_input_link.from_socket.name
                result = find_max_and_min(image, channel_name = channel_name)
            else:
                operator.report({'WARNING'}, "Cannot find height texture")
                continue

            if result:
                (minimum, maximum) = result
                group.inputs["From Min"].default_value = minimum
                group.inputs["From Max"].default_value = maximum
                group.node_tree.inputs["From Min"].default_value = minimum
                group.node_tree.inputs["From Max"].default_value = maximum

                operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the displacement bitmap in the group: {group.name}")

        if operator.normalize_roughness:
            roughness_output = group.outputs.get("Roughness")
            if roughness_output:
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "roughness")
                if not block_and_channel_name:
                    block_and_channel_name = find_image_block_by_type(image_data_blocks , "gloss")
                if block_and_channel_name:
                    (block, channel_name) = block_and_channel_name
                    if channel_name == 'RGB':
                        channel_name = 'R'
                    result = find_max_and_min(block, channel_name)

                    (minimum, maximum) = result
                    
                    socket_links = roughness_output.links
                    to_sockets = [link.to_socket for link in socket_links]
                    
                    map_range = nodes.new(type = 'ShaderNodeMapRange')

                    (x, y) = group.location
                    map_range.location = (x + 350, y - 150)
                    map_range.inputs[1].default_value = minimum
                    map_range.inputs[2].default_value = maximum
                    map_range.name = f"Roughness Normalized {group.name}"
                    map_range.label = f"Roughness Normalized"
                    
                    for to_socket in to_sockets:
                        links.new(map_range.outputs[0], to_socket)
        
                    links.new(roughness_output, map_range.inputs[0])

                    operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the roughness bitmap in the group: {group.name}")

            else:
                operator.report({'INFO'}, f"No roughness in the group: {group.name}")
        
        if operator.normalize_specular:
            specular_output = group.outputs.get("Specular")
            if specular_output:
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "specular")
                if block_and_channel_name:
                    (block, channel_name) = block_and_channel_name
                    if channel_name == 'RGB':
                        channel_name = 'R'
                    result = find_max_and_min(block, channel_name)

                    (minimum, maximum) = result
                    
                    socket_links = specular_output.links
                    to_sockets = [link.to_socket for link in socket_links]
                    
                    map_range = nodes.new(type = 'ShaderNodeMapRange')

                    (x, y) = group.location
                    map_range.location = (x + 350, y - 50)
                    map_range.inputs[1].default_value = minimum
                    map_range.inputs[2].default_value = maximum
                    map_range.name = f"Specular Normalized {group.name}"
                    map_range.label = f"Specular Normalized"

                    
                    for to_socket in to_sockets:
                        links.new(map_range.outputs[0], to_socket)
        
                    links.new(specular_output, map_range.inputs[0])

                    operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the specular bitmap in the group: {group.name}")
            else:
                operator.report({'INFO'}, f"No specular in the group: {group.name}")

    for image in images:

        block = image.image
        image_output = image.outputs[0]
        # image_alpha_output = image.outputs[1] no alpha normalization yet

        if operator.normalize_separately:
            results = [find_max_and_min(block, channel_name) for channel_name in ['R', 'G', 'B']]

            (x, y) = image.location
            offset = 300

            to_separate_rgb = image

            if block.colorspace_settings.name == 'sRGB':

                gamma = nodes.new( type = 'ShaderNodeGamma' )
                gamma.location = (x + offset, y)
                offset += 200
                gamma.inputs[1].default_value = 1/2.2

                links.new(image_output, gamma.inputs[0])

                to_separate_rgb = gamma

            separate_rgb = nodes.new(type = 'ShaderNodeSeparateRGB')
            separate_rgb.location = (x + offset, y)
            offset += 200

            links.new(to_separate_rgb.outputs[0], separate_rgb.inputs[0])

            to_map_range = separate_rgb

            for index, result in enumerate(results):
                (minimum, maximum) = result
                
                map_range = nodes.new(type = 'ShaderNodeMapRange')

                map_range.location = (x + offset, y - (index * 80))
                map_range.inputs[1].default_value = minimum
                map_range.inputs[2].default_value = maximum
                map_range.label = f"Normalized"


                links.new(to_map_range.outputs[index], map_range.inputs[0])

                operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the {index} channell in the image: {block.name}")
        else:
            result = find_max_and_min(block, all_channels = True)

            (x, y) = image.location
            offset = 300

            to_map_range = image

            if block.colorspace_settings.name == 'sRGB':

                gamma = nodes.new( type = 'ShaderNodeGamma' )
                gamma.location = (x + offset, y)
                offset += 200
                gamma.inputs[1].default_value = 1/2.2

                links.new(image_output, gamma.inputs[0])
                
                to_map_range = gamma

            (minimum, maximum) = result
            
            map_range = nodes.new(type = 'ShaderNodeMapRange')

            map_range.location = (x + offset, y)
            map_range.inputs[1].default_value = minimum
            map_range.inputs[2].default_value = maximum
            map_range.label = f"Normalized"


            links.new(to_map_range.outputs[0], map_range.inputs[0])

            operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the image: {block.name}")
            

    return {'FINISHED'}

class ATOOL_OT_normalize_height(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.normalize_height_range"
    bl_label = "Normalize:"
    bl_description = "Normalize a texture range of a AT material or an image node texture. Does not work for .EXR"
    bl_options = {'REGISTER', 'UNDO'}

    normalize_height: bpy.props.BoolProperty(
        name="Height",
        description="Normalize a MA matearil height range",
        default = True
        )
    normalize_roughness: bpy.props.BoolProperty(
        name="Roughness",
        description="Normalize a MA matearil roughness range for manual adjustment",
        default = False
        )
    normalize_specular: bpy.props.BoolProperty(
        name="Specular",
        description="Normalize a MA matearil specular range for manual adjustment",
        default = False
        )
    normalize_separately: bpy.props.BoolProperty(
        name="Separately",
        description="Normalize texture channels separately",
        default = False
        )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'
        layout.prop(self, "normalize_height")
        layout.prop(self, "normalize_roughness")
        layout.prop(self, "normalize_specular")
        layout.separator()
        layout.prop(self, "normalize_separately")

    def invoke(self, context, event):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            self.report({'INFO'}, "Select a AT material node group or an image node.")
            return {'CANCELLED'}

        self.groups = [node for node in selected_nodes if is_atool_material(node)]
        self.images = [node for node in selected_nodes if node.type == 'TEX_IMAGE' and node.image]

        if not self.groups and not self.images:
            self.report({'INFO'}, "No AT material or image was found in the selection.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width = 200)

    def execute(self, context):
        return normalize_texture(self, context)


class ATOOL_OT_append_extra_nodes(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.append_extra_nodes"
    bl_label = "Append Extra Nodes"
    bl_description = "Append extra Material Applier nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        templates_file_path = os.path.join(script_file_directory, "data.blend")

        def is_atool_extra_node(node_name):
            material_output = bpy.data.node_groups[node_name].nodes.get("Group Output")
            if material_output:
                label = bpy.data.node_groups[node_name].nodes["Group Output"].label
                if label == "__atool_extra__":
                    return True
            return False
        
        to_import_names = []
        to_import = []

        present_node_groups_names = {node_group.name for node_group in bpy.data.node_groups}

        with bpy.data.libraries.load(filepath = templates_file_path) as (data_from, data_to):
            for node_group in data_from.node_groups:
                node_name = node_group[2:]
                if node_group.startswith("++"):
                    new_node_name = node_name
                    if node_name in present_node_groups_names:
                        if is_atool_extra_node(node_name):
                            continue
                        new_node_name = node_name + " AT"
                    elif node_name + " AT" in present_node_groups_names:
                        if is_atool_extra_node(node_name + " AT"):
                            continue
                        new_node_name = node_name + " ATOOL"
                    to_import_names.append(new_node_name)
                    to_import.append(node_group)
                    
            data_to.node_groups = to_import

        for node_group, to_import_name in zip(data_to.node_groups, to_import_names):
            node_group.use_fake_user = True
            node_group.name = to_import_name

        return {'FINISHED'}



def set_default_settings(operator, context):

    node_groups = get_all_groups_from_selection(operator, context)

    for group in node_groups:

        if is_atool_material(group):
            settings = {}
            for input_index in range(len(group.inputs)):
                if group.inputs[input_index].type != 'STRING':
                    value = group.inputs[input_index].default_value
                    group.node_tree.inputs[input_index].default_value = value
                    settings[group.inputs[input_index].name] = value

            default_settings = backward_compatibility_get(group.node_tree, "at_default_settings", "ma_default_settings")

            if default_settings:
                default_settings.update(settings)
            else:
                group.node_tree["at_default_settings"] = settings
                
        else:
            for input_index in range(len(group.inputs)):
                try:
                    value = group.inputs[input_index].default_value
                    group.node_tree.inputs[input_index].default_value = value
                except:
                    pass
        
        operator.report({'INFO'}, f"The settings have been baked for the group: {group.name}")
    
    return {'FINISHED'}

class ATOOL_OT_bake_defaults(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.bake_node_group_defaults"
    bl_label = "Bake Node Group Defaults"
    bl_description = "Set current settings as default ones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return set_default_settings(self, context)


class ATOOL_OT_restore_default_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.restore_default_settings"
    bl_label = "Restore Defaults"
    bl_description = "Restore default settings of a node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        node_groups = get_all_groups_from_selection(self, context)

        for group in node_groups:

            for input_index in range(len(group.inputs)):
                try:
                    group.inputs[input_index].default_value = group.node_tree.inputs[input_index].default_value
                except:
                    pass         
        
            self.report({'INFO'}, f"The settings have been reset for the group: {group.name}.")

        return {'FINISHED'}


class ATOOL_OT_restore_factory_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.restore_factory_settings"
    bl_label = "Restore Factory Settings"
    bl_description = "Restore factory settings of a AT material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        atool_node_groups = get_all_lt_groups_from_selection(self, context)

        for group in atool_node_groups:

            settings = backward_compatibility_get(group.node_tree, "at_factory_settings", "ma_factory_settings")

            if not settings:
                self.report({'INFO'}, f"No factory settings for the group: {group.name}")
                continue

            for key in settings.keys():
                input = group.inputs.get(key)
                if input:
                    input.default_value = settings[key]

            for input_index in range(len(group.inputs)):
                group.node_tree.inputs[input_index].default_value = group.inputs[input_index].default_value
        
            self.report({'INFO'}, f"The factory settings have been restored for the group: {group.name}")

        return {'FINISHED'}


class ATOOL_OT_save_material_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.save_material_settings"
    bl_label = "Save Material Settings"
    bl_description = "Save material settings of the selected AT material node group"
    bl_options = {'REGISTER', 'UNDO'}

    save_to_database: bpy.props.BoolProperty(
        name="Save To Database",
        description="Save the settings to the local sqlite database even if the material is a library asset",
        default = True
        )

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        settings_database_path = os.path.join(script_file_directory, "material_settings.db")

        try:
            connection = sqlite3.connect(settings_database_path)
        except sqlite3.Error as e:
            self.report({'ERROR'}, "Cannot connect to a material settings database.")
            self.report({'ERROR'}, e)
            return {'CANCELLED'}

        atool_node_groups = get_all_lt_groups_from_selection(self, context)
        
        for group in atool_node_groups:

            inputs = group.node_tree.inputs
            nodes = group.node_tree.nodes

            for input_index in range(len(group.inputs)):
                if group.node_tree.inputs[input_index].type != 'STRING':
                    group.node_tree.inputs[input_index].default_value = group.inputs[input_index].default_value

            material_settings = {input.name: round(input.default_value, 6) for input in inputs if input.type != 'STRING'}

            atool_id = group.node_tree.get("atool_id")
            if atool_id:
                library = context.window_manager.at_asset_data.data
                library[atool_id].save_material_settings(material_settings)
                self.report({'INFO'}, f"The settings have been saved for the library group: {group.name}. ID: {atool_id}")
                if not self.save_to_database:
                    continue

            image_paths = [os.path.realpath(bpy.path.abspath(node.image.filepath, library=node.image.library)) for node in nodes if node.type == 'TEX_IMAGE' and node.image]
            if image_paths == []:
                self.report({'INFO'}, f"No images found in the group: {group.name}")
                continue
            
            image_paths = list(dict.fromkeys(image_paths))
            image_hashes = [hashfile(image_path, hexdigest=True) for image_path in image_paths]
            image_path_by_id = dict(zip(image_hashes, image_paths))
        
            cursor = connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id TEXT PRIMARY KEY,
                    hash_name TEXT,
                    last_path TEXT,
                    data TEXT
                    )
            """)

            updated_setting_ids = []
            cursor.execute('SELECT * FROM settings WHERE id in ({0})'.format(
                ', '.join('?' for image_hash in image_hashes)), image_hashes)
            existing_image_settings = cursor.fetchall()
            for image_setting in existing_image_settings:
                id = image_setting[0]
                string = image_setting[3]
                old_setting = json.loads(image_setting[3])
                old_setting.update(material_settings)
                new_setting = json.dumps(old_setting, ensure_ascii=False)
                cursor.execute("""
                UPDATE settings
                SET last_path = ?,
                    data = ?
                WHERE
                    id = ? 
                """, (image_path_by_id[id], new_setting, id))
                updated_setting_ids.append(id)

            material_settings_json = json.dumps(material_settings, ensure_ascii=False)
            for image_hash, image_path in image_path_by_id.items():
                if image_hash not in updated_setting_ids:
                    cursor.execute(
                    "INSERT INTO settings (id, hash_name, last_path, data) VALUES(?,?,?,?)", 
                    (image_hash, "imohashxx", image_path, material_settings_json))

            connection.commit()

            if not atool_id:
                self.report({'INFO'}, f"The settings have been saved to the database for the group: {group.name}")

        connection.close()

        return {'FINISHED'}


def load_material_settings(operator, context, new_material = False, node_groups = []):

    script_file_directory = os.path.dirname(os.path.realpath(__file__))
    settings_database_path = os.path.join(script_file_directory, "material_settings.db")

    if not os.path.exists(settings_database_path):
        operator.report({'INFO'}, f"No settings have been saved yet.")
        return {'CANCELLED'}

    try:
        connection = sqlite3.connect(settings_database_path)
        cursor = connection.cursor()
    except sqlite3.Error as e:
        operator.report({'ERROR'}, "Cannot connect to a material settings database.")
        operator.report({'ERROR'}, e)
        return {'CANCELLED'}

    if new_material:
        atool_node_groups = node_groups
    else:
        atool_node_groups = get_all_lt_groups_from_selection(operator, context)
        
    for group in atool_node_groups:

        material_settings = None

        atool_id = group.node_tree.get("atool_id")
        if atool_id:
            library = context.window_manager.at_asset_data.data
            material_settings = library[atool_id].load_material_settings()
            if material_settings:
                operator.report({'INFO'}, f"Settings were loaded for the library group: {group.name}. ID: {atool_id}")
        
        if not atool_id or not material_settings:
            nodes = group.node_tree.nodes

            image_paths = [os.path.realpath(bpy.path.abspath(node.image.filepath, library=node.image.library)) for node in nodes if node.type == 'TEX_IMAGE' and node.image]
            if not image_paths:
                operator.report({'INFO'}, f"No image was found in the group: {group.name}")
                continue
            image_paths = list(dict.fromkeys(image_paths))

            image_hashes = [hashfile(image_path, hexdigest=True) for image_path in image_paths]

            cursor.execute('SELECT * FROM settings WHERE id in ({0})'.format(
                ', '.join('?' for image_hash in image_hashes)), image_hashes)
            all_image_settings = cursor.fetchall()

            if not all_image_settings:
                operator.report({'INFO'}, f"No settings were found for the group: {group.name}")
                continue

            material_settings = {}
            for image_settings in all_image_settings:
                settings = json.loads(image_settings[3])
                for name, value in settings.items():
                    if name not in material_settings.keys():
                        material_settings[name] = []
                        material_settings[name].append(value)
                    else:     
                        material_settings[name].append(value)

            for key in material_settings.keys():
                material_settings[key] = Counter(material_settings[key]).most_common(1)[0][0]

            operator.report({'INFO'}, f"Settings were loaded from the database for the group: {group.name}")

        for key in material_settings.keys():
            node_input = group.inputs.get(key)
            if node_input:
                node_input.default_value = material_settings[key]

        for input_index in range(len(group.inputs)):
            group.node_tree.inputs[input_index].default_value = group.inputs[input_index].default_value


        default_settings = backward_compatibility_get(group.node_tree, "at_default_settings", "ma_default_settings")

        if default_settings:
            default_settings.update(material_settings)
        else:
            group.node_tree["at_default_settings"] = material_settings

    connection.close()

    return {'FINISHED'}

class ATOOL_OT_load_material_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.load_material_settings"
    bl_label = "Load Material Settings"
    bl_description = "Load material settings for the selected AT material node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return load_material_settings(self, context)


class ATOOL_OT_open_in_file_browser(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.open_in_file_browser"
    bl_label = "Open File Browser"
    bl_description = "Open the selected AT material or the selected image in a file browser"
	
    def execute(self, context):

        platform = sys.platform

        def open_in_file_browser(directory):
            if platform=='win32':
                os.startfile(directory)
            elif platform=='darwin':
                subprocess.Popen(['open', directory])
            else:
                try:
                    subprocess.Popen(['xdg-open', directory])
                except OSError:
                    self.report({'INFO'}, "Current OS is not supported.")

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            self.report({'INFO'}, "Nothing is selected.")
            return {'CANCELLED'}

        something_relevant = False

        for node in selected_nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                path = get_image_absolute_path(node.image)
                if os.path.exists(path):
                    open_in_file_browser(os.path.dirname(path))
                    something_relevant = True
                else:
                    self.report({'INFO'}, f'No image exists in the path "{path}" for the node "{node.name}".')
            elif node.type == 'GROUP':
                nodes = node.node_tree.nodes
                image_paths = [get_image_absolute_path(node.image) for node in nodes if node.type == 'TEX_IMAGE' and node.image]
                if not image_paths:
                    self.report({'INFO'}, f'No image found in a group: {node.name}.')
                    continue
                image_paths = [path for path in image_paths if os.path.exists(path)]
                if not image_paths:
                    self.report({'INFO'}, f'No images exist in the paths: {image_paths}.')
                    continue
                image_paths = list(dict.fromkeys(image_paths))
                image_directories = [os.path.dirname(image_path) for image_path in image_paths]
                directory = Counter(image_directories).most_common(1)[0][0]
                open_in_file_browser(directory)
                something_relevant = True

        if not something_relevant:
            self.report({'INFO'}, "The selected nodes do not include any images.")
            return {'CANCELLED'}

        return {'FINISHED'}


class ATOOL_OT_transfer_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.transfer_settings"
    bl_label = "Transfer Properties"
    bl_description = "Transfer node settings from active to selected. It does not set them as default"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select at least two nodes.")
            return {'CANCELLED'}

        active = selected_nodes[0]
        selected = selected_nodes[1:]

        active_inputs_names = {socket.name for socket in active.inputs}
        selected_inputs = list(itertools.chain.from_iterable([node.inputs for node in selected]))

        for input in selected_inputs:
            socket_name = input.name
            if socket_name in active_inputs_names:
                try:
                    input.default_value = active.inputs[socket_name].default_value
                except:
                    pass

        return {'FINISHED'}

# def get_dominant_color(image_path):
#     image = pillow_image.open(image_path)
#     image.thumbnail((256, 256), pillow_image.HAMMING)
#     image = image.convert('RGB').quantize(colors=1, method=pillow_image.MEDIANCUT)
#     return image.getpalette()[:3]

# def get_average(image_path):
#     im = pillow_image.open(image_path)
#     average = pillow_image.Stat(im).mean[0]
#     if average < 1:
#         pass
#     elif average >= 1 and average < 255:
#         average = average/255.0
#     elif average >= 255:
#         average = average/65535.0
#     return average

def setup_material(operator, context):

    nodes = operator.atool_node_tree.nodes
    links = operator.atool_node_tree.links
    inputs = operator.atool_node_tree.inputs
    outputs = operator.atool_node_tree.outputs

    flags = {
        "albedo": False,
        "diffuse": False,
        "ambient_occlusion": False,
        "metallic": False,
        "specular": False,
        "roughness": False,
        "gloss": False,
        "displacement": False,
        "bump": False,
        "opacity": False,
        "emissive": False,
        "normal": False
    }

    postfixes = {
        1: ("",),
        2: ("", "_seams"),
        3: ("_x", "_y", "_z"),
        4: ("_seams_x", "_seams_y", "_seams_z", "_x", "_y", "_z")
    }

    def add_separate_rgb(name):
            separate_rgb = operator.atool_node_tree.nodes.new( type = 'ShaderNodeSeparateRGB' )
            (x, y) = nodes[name].location
            separate_rgb.location = (x + 400, y)

            links.new(nodes[name].outputs[0], separate_rgb.inputs[0])
            return separate_rgb

    def add_gamma_0_4545(name, index):
        gamma = operator.atool_node_tree.nodes.new( type = 'ShaderNodeGamma' )
        (x, y) = nodes[name].location
        gamma.location = (x + 250, y)
        gamma.inputs[1].default_value = 1/2.2

        links.new(nodes[name].outputs[index], gamma.inputs[0])
        return gamma

    def add_gamma_0_4545_and_plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[operator.material_type]:
            gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
            links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[operator.material_type]:
            links.new(nodes[name + postfix].outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def add_gamma_2_2(node, index):
            gamma = operator.atool_node_tree.nodes.new( type = 'ShaderNodeGamma' )
            (x, y) = node.location
            gamma.location = (x + 250, y)
            gamma.inputs[1].default_value = 2.2

            links.new(node.outputs[index], gamma.inputs[0])
            return gamma

    def set_bitmap_to_node(name):
        for postfix in postfixes[operator.material_type]:
            nodes[name + postfix].image = current_image

    def add_separate_rgb_and_plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[operator.material_type]:
            separate_rgb = add_separate_rgb(name + postfix)
            links.new(separate_rgb.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def handle_bitmap():

        def separate_rgb_and_plug_output_to_post_in():
            separate_rgb = add_separate_rgb(bitmap_type[0] + "_mix_out")
            for i in range(3):
                if bitmap_type[i] == "ambient_occlusion":
                    gamma_2_2 = add_gamma_2_2(separate_rgb, i)
                    links.new(gamma_2_2.outputs[0], nodes[bitmap_type[i] + "_post_in"].inputs[0])
                elif bitmap_type[i] == "displacement":
                    add_separate_rgb_and_plug_output_to_mix_in(bitmap_type[0], "displacement", i)
                else:
                    links.new(separate_rgb.outputs[i], nodes[bitmap_type[i] + "_post_in"].inputs[0])
                flags[bitmap_type[i]] = True

        # RGB
        if packed_bitmap_type == 1:
            if bitmap_type[0] in {"normal", "diffuse", "albedo", "emissive", "ambient_occlusion"}:
                if bitmap_type[0] == "normal":
                    current_image.colorspace_settings.name = 'Non-Color'
                    if operator.bl_idname == "atool.apply_material" and operator.is_y_minus_normal_map:
                        inputs["Y- Normal Map"].default_value = 1
                else:
                    current_image.colorspace_settings.name = 'sRGB'
            else:
                current_image.colorspace_settings.name = 'Non-Color'

            set_bitmap_to_node(bitmap_type[0])
            flags[bitmap_type[0]] = True
            return

        # RGB + A
        if packed_bitmap_type == 2:
            if bitmap_type[0] in {"normal", "diffuse", "albedo", "emissive", "ambient_occlusion"}:
                if bitmap_type[0] == "normal":
                    current_image.colorspace_settings.name = 'Non-Color'
                    if operator.bl_idname == "atool.apply_material" and operator.is_y_minus_normal_map:
                        inputs["Y- Normal Map"].default_value = 1
                else:
                    current_image.colorspace_settings.name = 'sRGB'
            else:
                current_image.colorspace_settings.name = 'Non-Color'

            current_image.alpha_mode = 'CHANNEL_PACKED'

            set_bitmap_to_node(bitmap_type[0])
            plug_output_to_mix_in(bitmap_type[0], bitmap_type[1], 1)
            flags[bitmap_type[0]] = True
            flags[bitmap_type[1]] = True
            return
        
        # R + G + B
        if packed_bitmap_type == 3:
            current_image.colorspace_settings.name = 'Non-Color'
            set_bitmap_to_node(bitmap_type[0])
            separate_rgb_and_plug_output_to_post_in()
            return

        # R + G + B + A
        if packed_bitmap_type == 4:
            current_image.colorspace_settings.name = 'Non-Color'
            current_image.alpha_mode = 'CHANNEL_PACKED'

            set_bitmap_to_node(bitmap_type[0])
            separate_rgb_and_plug_output_to_post_in()
            plug_output_to_mix_in(bitmap_type[0], bitmap_type[3], 1)
            flags[bitmap_type[3]] = True
            return

    bitmap_resolutions = []
    for index, current_image in enumerate(operator.image_data_blocks):

        filepath = get_image_absolute_path(current_image)
        hash = hashfile(filepath, hexdigest=True)
        at_pixel_sizes = current_image.get("at_pixel_sizes")
        if at_pixel_sizes:
            size = at_pixel_sizes.get(hash)
            if not size:
                try:
                    with pillow_image.open(filepath) as image:
                        size = image.size
                except:
                    size = tuple(current_image.size)
                at_pixel_sizes[hash] = size
        else:
            current_image["at_pixel_sizes"] = {}
            at_pixel_sizes = current_image["at_pixel_sizes"]
            try:
                with pillow_image.open(filepath) as image:
                    size = image.size
            except:
                size = tuple(current_image.size)
            at_pixel_sizes[hash] = size  
        bitmap_resolutions.append(size)

        bitmap_type = backward_compatibility_get(current_image, "at_type", "ma_type")
        packed_bitmap_type = len(bitmap_type)
        current_image["at_order"] = index # not yet used
        handle_bitmap()
        operator.report({'INFO'}, "The bitmap " + str(os.path.basename(current_image.filepath)) + " was set as: " + str(bitmap_type))

    group_output_node = nodes["Group Output"]

    bitmap_aspect_ratios = [res[0]/res[1] for res in bitmap_resolutions]

    if all(aspect_ratio == bitmap_aspect_ratios[0] for aspect_ratio in bitmap_aspect_ratios):
        final_aspect_ratio = bitmap_aspect_ratios[0]
    else:
        final_aspect_ratio = Counter(bitmap_aspect_ratios).most_common(1)[0][0]
        operator.report({'WARNING'}, f"Imported bitmaps have diffrent aspect ratios, the ratio set to {final_aspect_ratio}")


    if final_aspect_ratio == 1:
        pass
    elif final_aspect_ratio > 1:
        inputs["Y Scale"].default_value = final_aspect_ratio
    elif final_aspect_ratio < 1:
        inputs["X Scale"].default_value = final_aspect_ratio

    if flags["albedo"]:
        if flags["ambient_occlusion"]:
            links.new(nodes["albedo_and_ao_post_out"].outputs[0], group_output_node.inputs["Base Color"])
        else:
            links.new(nodes["albedo_post_in"].outputs[0], group_output_node.inputs["Base Color"])

    if flags["diffuse"] and not flags["ambient_occlusion"]:
        links.new(nodes["diffuse_post_in"].outputs[0], group_output_node.inputs["Base Color"])

    
    if not flags["albedo"] and not flags["diffuse"]:
        if flags["ambient_occlusion"]:
            links.new(nodes["ambient_occlusion_post_out"].outputs[0], group_output_node.inputs["Base Color"])
        else:
            outputs.remove(outputs["Base Color"])

    if not flags["ambient_occlusion"]:
        inputs.remove(inputs["AO"])

    if not flags["metallic"]:
        outputs.remove(outputs["Metallic"])

    if not flags["specular"]:
        outputs.remove(outputs["Specular"])

    if not flags["roughness"] and not flags["gloss"]:
        outputs.remove(outputs["Roughness"])

    if not flags["roughness"] and flags["gloss"]:
        links.new(nodes["gloss_post_out"].outputs[0], group_output_node.inputs["Roughness"])

    if not flags["displacement"]:
        
        if flags["diffuse"]:
            add_gamma_0_4545_and_plug_output_to_mix_in("diffuse", "displacement", 0)
            operator.report({'INFO'}, "No displacement bitmap found, diffuse used instead")
        elif flags["albedo"]:
            add_gamma_0_4545_and_plug_output_to_mix_in("albedo", "displacement", 0)
            operator.report({'INFO'}, "No displacement bitmap found, albedo used instead")
        elif flags["ambient_occlusion"]:
            # only works for a separate ao map
            add_gamma_0_4545_and_plug_output_to_mix_in("ambient_occlusion", "displacement", 0)
            operator.report({'INFO'}, "No displacement bitmap found, ambient occlusion used instead")
        else:
            outputs.remove(outputs["Height"])
            inputs_to_remove = []
            for input_to_remove in inputs_to_remove:
                inputs.remove(inputs[input_to_remove])
            operator.report({'INFO'}, "No displacement bitmap found.")
                

    if not flags["opacity"]:
        outputs.remove(outputs["Alpha"])
    
    if not flags["emissive"]:
        outputs.remove(outputs["Emission"])

    if not flags["normal"]:
        if flags["bump"]:
            links.new(nodes["bump_post_out"].outputs[0], group_output_node.inputs["Normal"])
        else:
            outputs.remove(outputs["Normal"])
        for input_to_remove in ("Y- Normal Map", "X Rotation′", "Y Rotation′"):
            try:
                inputs.remove(inputs[input_to_remove])
            except:
                pass


    settings = {}
    for input in inputs:
        if input.type != 'STRING':
            settings[input.name] = input.default_value

    operator.atool_node_tree["at_factory_settings"] = settings
    operator.atool_node_tree["at_default_settings"] = settings
    operator.atool_node_tree["at_type"] = operator.material_type

    operator.atool_node_tree["at_flags"] = flags # not yet used


class ATOOL_OT_apply_material(bpy.types.Operator, ImportHelper):
    bl_idname = "atool.apply_material"
    bl_label = "Apply Material"
    bl_description = "Apply material to active object"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    is_y_minus_normal_map: bpy.props.BoolProperty(
        name="Y- Normal Map",
        description="Invert the green channel for DirectX style normal maps",
        default = False
        )
    use_triplanar: bpy.props.BoolProperty(
        name="Triplanar",
        description="Use triplanar mapping",
        default = False
        )
    use_untiling: bpy.props.BoolProperty(
        name="Untiling",
        description="Use untiling to break textures repetition",
        default = True
        )
    ensure_adaptive_subdivision: bpy.props.BoolProperty(
        name="Ensure Adaptive Subdivision",
        description="Ensure adaptive subdivision setup for the active object",
        default = False
        )
    preview_dicing_rate: bpy.props.FloatProperty(
        name="Preview Dicing Rate",
        default = 1,
        soft_min=0.5,
        max=1000
        )
    offscreen_dicing_scale: bpy.props.FloatProperty(
        name="Offscreen Dicing Scale",
        default = 16,
        min=1
        )
    load_settings: bpy.props.BoolProperty(
        name="Load Settings",
        description="Load the imported material's settings",
        default = True
        )
    a_for_ambient_occlusion: bpy.props.BoolProperty(
        name="A For Ambient Occlusion",
        description="Solve the ambiguity. The default is A for albedo",
        default = False
        )
    not_rgb_plus_alpha: bpy.props.BoolProperty(
        name="Not RGB + Alpha",
        description="An debug cases which excludes RGB+A type combinations. An example to solve: \"Wall_A_\" plus a single channel map name",
        default = True
        )

    ignore_by_type: bpy.props.StringProperty(
        name="Ignore Type",
        description="Ignore bitmap by type",
        default = "bump ambient_occlusion"
        )
    use_ignore_by_type: bpy.props.BoolProperty(
        name="Ignore Type",
        description="Ignore bitmap by type",
        default = True
        )

    ignore_by_format: bpy.props.StringProperty(
        name="Ignore Format",
        description="Ignore bitmap by file format",
        default = ".exr"
        )
    use_ignore_by_format: bpy.props.BoolProperty(
        name="Ignore Format",
        description="Ignore bitmap by file format",
        default = True
        )

    prefer_over: bpy.props.StringProperty(
        name="Prefer Type",
        description="Prefer one type over another and ignore the latter",
        default = "roughness-gloss albedo-diffuse"
        )
    use_prefer_over: bpy.props.BoolProperty(
        name="Prefer Type",
        description="Prefer one type over another and ignore the latter",
        default = True
        )


    from_asset_browser: bpy.props.BoolProperty(
        options={'HIDDEN'}
    )

    def draw(self, context):

        layout = self.layout
        # layout.use_property_split = True
        layout.alignment = 'LEFT'

        layout.prop(self, "is_y_minus_normal_map")
        layout.prop(self, "use_untiling")
        layout.prop(self, "use_triplanar")

        layout.separator()

        layout.prop(self, "load_settings")

        layout.separator()

        layout.prop(self, "ensure_adaptive_subdivision")
        if self.ensure_adaptive_subdivision:
            layout.prop(self, "preview_dicing_rate")
            layout.prop(self, "offscreen_dicing_scale")

        layout.separator()

        layout.prop(self, "a_for_ambient_occlusion")
        layout.prop(self, "not_rgb_plus_alpha")

        layout.prop(self, "use_ignore_by_type")
        if self.use_ignore_by_type:
            layout.prop(self, "ignore_by_type", text='')

        layout.prop(self, "use_ignore_by_format")
        if self.use_ignore_by_format:
            layout.prop(self, "ignore_by_format", text='')

        layout.prop(self, "use_prefer_over")
        if self.use_prefer_over:
            layout.prop(self, "prefer_over", text='')

    def invoke(self, context, event):
        if self.from_asset_browser:
            return context.window_manager.invoke_props_dialog(self, width = 300)
        else:
            return super().invoke(context, event)

    def execute(self, context):

        height_scale = None
        asset_name = None

        if self.from_asset_browser:
            current_asset = get_current_browser_asset(self, context)
            if not current_asset:
                return {'CANCELLED'}
            self.file_paths = current_asset.get_imags()
            if not self.file_paths:
                self.report({'INFO'}, "No image files.")
                return {'CANCELLED'}
            atool_id = current_asset.id

            dimensions = current_asset.info.get("dimensions")
            if dimensions:
                x, y, z = dimensions
                height_scale = z * min(x, y)

            asset_name = current_asset.info.get("name")

        else:
            if self.files[0].name == "":
                self.report({'INFO'}, "No files selected.")
                return {'CANCELLED'}
            self.file_paths = [os.path.join(self.directory, file.name) for file in self.files]
            atool_id = None

        bitmap_paths_and_types, material_name = type_definer.define(self.file_paths, not self.not_rgb_plus_alpha, self.a_for_ambient_occlusion)

        if not bitmap_paths_and_types:
            self.report({'INFO'}, "No valid bitmaps found.")
            return {'CANCELLED'}

        if self.use_ignore_by_type:
            ignored_types = set(self.ignore_by_type.split(" "))
            bitmap_paths_and_types = [(path, type) for path, type in bitmap_paths_and_types if not (len(type) == 1 and type[0] in ignored_types)]
        
        if bitmap_paths_and_types and self.use_ignore_by_format:
            ignored_formats = tuple(self.ignore_by_format.split(" "))
            bitmap_paths_and_types = [(path, type) for path, type in bitmap_paths_and_types if not path.endswith(ignored_formats)]

        if bitmap_paths_and_types and self.use_prefer_over:
            for preferred, ignored in [tuple(pare.split("-")) for pare in self.prefer_over.split(" ")]:
                for path_type_tuple in bitmap_paths_and_types.copy():
                    type = path_type_tuple[1]
                    if not len(type) == 1:
                        continue
                    if type[0] == ignored and preferred in (type[0] for path, type in bitmap_paths_and_types if len(type) == 1):
                        bitmap_paths_and_types.remove(path_type_tuple)

        if not bitmap_paths_and_types:
            self.report({'INFO'}, "No valid bitmaps found. All valid ones were excluded.")
            return {'CANCELLED'}
        
        self.image_data_blocks = []
        for bitmap_path, bitmap_type in bitmap_paths_and_types:
            image_data_block = bpy.data.images.load(filepath = bitmap_path, check_existing=True)
            image_data_block["at_type"] = bitmap_type
            self.image_data_blocks.append(image_data_block)

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        self.templates_file_path = os.path.join(script_file_directory, "data.blend", "NodeTree")

        material_type = "_at_temp_"
        if self.use_triplanar:
            material_type += "tri_"
        if self.use_untiling:
            material_type += "unt_"

        bpy.ops.wm.append(directory = self.templates_file_path, filename = material_type, set_fake = True)
        self.atool_node_tree = bpy.data.node_groups[material_type]

        if material_type == "_at_temp_":
            self.material_type = 1
        elif material_type == "_at_temp_unt_":
            self.material_type = 2
        elif material_type == "_at_temp_tri_":
            self.material_type = 3
        elif material_type == "_at_temp_tri_unt_":
            self.material_type = 4

        if asset_name:
            self.atool_node_tree.name = asset_name
        else:
            self.atool_node_tree.name = "M_" + material_name

        if height_scale != None:
            self.atool_node_tree.inputs["Scale′"].default_value = height_scale
        setup_material(self ,context)

        active_object = context.object
        if not active_object:
            self.report({'INFO'}, "No active object. The material was added as a node group.")
            return {'FINISHED'}

        active_material = active_object.active_material
        if active_material:

            node_group = active_material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
            node_group.node_tree = self.atool_node_tree
            node_group.name = node_group.node_tree.name

            node_group.width = 300
            node_group.show_options = False

            principled_node = active_object.active_material.node_tree.nodes.get("Principled BSDF")
            if principled_node:
                (x, y) = principled_node.location
            else:
                (x, y) = (0, 0)

            node_group.location = (x - 400, y)
        else:
            new_material = bpy.data.materials.new(name="New Material")
            new_material.use_nodes = True
            active_object.data.materials.append(new_material)

            # active_object.active_material_index = len(context.object.material_slots) - 1

            node_group = new_material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
            node_group.node_tree = self.atool_node_tree
            node_group.name = node_group.node_tree.name
            node_group.width = 300
            node_group.show_options = False
            
            links = new_material.node_tree.links

            principled_node = new_material.node_tree.nodes["Principled BSDF"]
            (x, y) = principled_node.location
            node_group.location = (x - 400, y)

            names_to_ignore = {"Height", "Seam"}
            for output in node_group.outputs:
                if output.name not in names_to_ignore:
                    links.new(node_group.outputs[output.name], principled_node.inputs[output.name])

        if atool_id:
            self.atool_node_tree["atool_id"] = atool_id

        if self.load_settings:
            load_material_settings(self, context, new_material = True, node_groups = [node_group])

        if self.ensure_adaptive_subdivision:
            ensure_adaptive_subdivision(self, context, new_material = True)

        return {'FINISHED'}

class ATOOL_OT_convert_material(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.convert_material"
    bl_label = "Convert To"
    bl_description = "Convert the selected AT material"
    bl_options = {'REGISTER', 'UNDO'}

    convert_to_untiling: bpy.props.BoolProperty(
        name="Untiling",
        description="Use untiling to break textures repetition",
        default = False
        )
    convert_to_triplanar: bpy.props.BoolProperty(
        name="Triplanar",
        description="Use triplanar mapping",
        default = False
        )
    convert_and_replace_all_users: bpy.props.BoolProperty(
        name="Replace All",
        description="Replace all users of the initial material with the converted one",
        default = False
        )
    convert_and_delete: bpy.props.BoolProperty(
        name="Delete",
        description="Delete the initial material if it has zero users",
        default = False
        )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'
        layout.prop(self, "convert_to_untiling")
        layout.prop(self, "convert_to_triplanar")
        layout.separator()
        layout.prop(self, "convert_and_replace_all_users")
        layout.prop(self, "convert_and_delete")

    def invoke(self, context, event):

        atool_materials = get_all_lt_groups_from_selection(self, context)
        if not atool_materials:
            return {'CANCELLED'}

        @dataclass
        class Converting_Node_Group:
            node_tree: object
            node_groups: list = field(default_factory=list)

        node_trees = [group.node_tree for group in atool_materials]
        node_trees = list(dict.fromkeys(node_trees))

        self.converting_node_groups = []
        for node_tree in node_trees:
            converting_node_group = Converting_Node_Group(node_tree)
            for group in atool_materials:
                if group.node_tree == node_tree:
                    converting_node_group.node_groups.append(group)
            self.converting_node_groups.append(converting_node_group)
            
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        self.templates_file_path = os.path.join(script_file_directory, "data.blend", "NodeTree")
        
        for converting_node_group in self.converting_node_groups:

            image_data_blocks = [node.image for node in converting_node_group.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
            if not image_data_blocks:
                self.report({'INFO'}, f"No image found in the group: {converting_node_group.node_tree.name}")
                continue
            self.image_data_blocks = list(dict.fromkeys(image_data_blocks))

            group_type = "_at_temp_"
            if self.convert_to_triplanar:
                group_type += "tri_"
            if self.convert_to_untiling:
                group_type += "unt_"

            bpy.ops.wm.append(directory = self.templates_file_path, filename = group_type, set_fake = True)
            self.atool_node_tree =  bpy.data.node_groups[group_type]

            if group_type == "_at_temp_":
                self.material_type = 1
            elif group_type == "_at_temp_unt_":
                self.material_type = 2
            elif group_type == "_at_temp_tri_":
                self.material_type = 3
            elif group_type == "_at_temp_tri_unt_":
                self.material_type = 4

            initial_node_tree_name = converting_node_group.node_tree.name
            initial_node_tree = converting_node_group.node_tree

            setup_material(self, context)

            default_settings = backward_compatibility_get(converting_node_group.node_tree, "at_default_settings", "ma_default_settings")
            self.atool_node_tree["at_default_settings"] = default_settings.to_dict()
            
            atool_id = converting_node_group.node_tree.get("atool_id")
            if atool_id:
                self.atool_node_tree["atool_id"] = atool_id

            for name, value in default_settings.items():
                try:
                    self.atool_node_tree.inputs[name].default_value = value
                except:
                    pass

            if self.convert_and_replace_all_users:
                initial_node_tree.user_remap(self.atool_node_tree)
            else:
                for node_group in converting_node_group.node_groups:
                    node_group.node_tree = self.atool_node_tree

            if self.convert_and_delete:
                if not initial_node_tree.users or (initial_node_tree.users == 1 and initial_node_tree.use_fake_user):
                    bpy.data.node_groups.remove(initial_node_tree)

            self.atool_node_tree.name = initial_node_tree_name

            self.report({'INFO'}, f"Converted node tree: {initial_node_tree_name} --> {self.atool_node_tree.name}")

        return {'FINISHED'}

# replace material
# full material output