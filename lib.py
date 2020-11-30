import bpy
from bpy_extras.io_utils import ImportHelper

import sys
import subprocess
import os
import json
import sqlite3
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from collections import Counter
import itertools

from . imohashxx import hashfile
from PIL import Image as pillow_image


class MATAPP_node_editor_poll:
    @classmethod
    def poll(cls, context):
        if context.space_data.type == 'NODE_EDITOR' and context.space_data.tree_type == 'ShaderNodeTree':
            return True
        else:
            return False

def is_matapp_material(group):
    if group.bl_idname == "ShaderNodeGroup":
        node_tree = group.node_tree
    elif group.bl_idname == "ShaderNodeTree":
        node_tree = group
    else:
        return False
    if node_tree == None:
        return False
    else:
        nodes = node_tree.nodes
        material_output = nodes.get("Group Output")
        if material_output and material_output.label.startswith("matapptemp"):
            return True
        else:
            return False

def get_all_ma_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) == 0:
            operator.report({'INFO'}, "Nothing is selected. Select a MA material node group.")
            return []

        matapp_node_groups = [node for node in selected_nodes if is_matapp_material(node)]

        if len(matapp_node_groups) == 0:
            operator.report({'INFO'}, "No MA materials found in the selection. Select a MA material node group.")
            return []

        return matapp_node_groups

def get_all_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) == 0:
            operator.report({'INFO'}, "Nothing is selected. Select a node group.")
            return []

        node_groups = [node for node in selected_nodes if node.type == 'GROUP']

        if len(node_groups) == 0:
            operator.report({'INFO'}, "No node groups found in the selection. Select a node group.")
            return []

        return node_groups

def get_all_image_data_blocks(group):

        image_data_blocks = [node.image for node in group.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image != None]
        if len(image_data_blocks) == 0:
            return None
        image_data_blocks = list(dict.fromkeys(image_data_blocks))

        return image_data_blocks

def find_image_block_by_type(blocks , type):
    for block in blocks:
        ma_type = block["ma_type"]
        if type in ma_type:
            type_index = ma_type.index(type)
            if len(ma_type) <= 2:
                channel_names = {0: 'RGB', 1: 'A'}
                return (block, channel_names[type_index])
            else:
                channel_names = {0: 'R', 1: 'G', 2: 'B', 3: 'A'}
                return (block, channel_names[type_index])
    return None

def get_node_tree_by_name(name):
    
    if name not in [i.name for i in bpy.data.node_groups]:
        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        templates_file_path = os.path.join(script_file_directory, "def_mats.blend", "NodeTree")
        bpy.ops.wm.append(directory = templates_file_path, filename = name, set_fake = True)
        node_tree =  bpy.data.node_groups[name]
    else:
        node_tree =  bpy.data.node_groups[name]
    
    return node_tree

def add_ma_blending_node(operator, context, two_nodes, blend_node_tree):

    links = context.space_data.edit_tree.links
    nodes = context.space_data.edit_tree.nodes

    blend_node = nodes.new( type = 'ShaderNodeGroup' )
    blend_node.node_tree = blend_node_tree

    first_node = two_nodes[1]
    second_node = two_nodes[0]

    # x = (first_node.location.x + second_node.location.x)/2
    # y = (first_node.location.y + second_node.location.y)/2
    # blend_node.location = (x + 400, y)

    first_node_location_x = first_node.location.x
    # first_node_location_y = first_node.location.y
    second_node_location_x = second_node.location.x
    # second_node_location_y = second_node.location.y

    if second_node_location_x >= first_node_location_x:
        blend_node_location_x = second_node_location_x
    else:
        blend_node_location_x = first_node_location_x

    blend_node_location_y = (first_node.location.y + second_node.location.y)/2
    blend_node.location = (blend_node_location_x + 400, blend_node_location_y)

    blend_node.width = 200
    blend_node.show_options = False

    blend_node_input_names = [i.name for i in blend_node.outputs[1:]]
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
        if input_name in first_node_output_names and first_node.outputs[input_name].hide == False:
            links.new(first_node.outputs[input_name], blend_node.inputs[input_name + " 1"])
            is_name_used_by_first_input = True
        if input_name in second_node_output_names and second_node.outputs[input_name].hide == False:
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

class MATAPP_OT_height_blend(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_add_height_blend"
    bl_label = "Add Height Blend"
    bl_description = "Add height blend for selected nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select two nodes")
            return {'CANCELLED'}

        return add_ma_blending_node(self, context, (selected_nodes[1], selected_nodes[0]), get_node_tree_by_name("Height Blend MA"))


class MATAPP_OT_detail_blend(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_add_detail_blend"
    bl_label = "Add Detail Blend"
    bl_description = "Add detail blend for selected nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) < 2:
            self.report({'INFO'}, "Select two nodes")
            return {'CANCELLED'}

        return add_ma_blending_node(self, context, (selected_nodes[1], selected_nodes[0]), get_node_tree_by_name("Detail Blend MA"))


class MATAPP_OT_make_links(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_make_material_links"
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

        active_output_names = {socket.name for socket in active.outputs if socket.hide == False}
        selected_inputs = list(itertools.chain.from_iterable([node.inputs for node in selected]))

        for input in selected_inputs:
            if input.hide == False:
                socket_name = input.name
                if socket_name in active_output_names:
                    links.new(active.outputs[socket_name], input)

        return {'FINISHED'}


def ensure_adaptive_subdivision(operator, context, new_material = False):

    active_object = context.object
    active_material = active_object.active_material

    if active_material == None:
        operator.report({'INFO'}, "Select a material.")
        return {'CANCELLED'}

    if new_material:
        nodes = active_material.node_tree.nodes
        links = active_material.node_tree.links
    else:
        nodes = context.space_data.edit_tree.nodes
        links = context.space_data.edit_tree.links

    selected_nodes = context.selected_nodes
    if len(selected_nodes) != 0:
        active_node = selected_nodes[0]
    else:
        active_node = None

    context.scene.cycles.feature_set = 'EXPERIMENTAL'

    if context.scene.cycles.preview_dicing_rate == 8:
        context.scene.cycles.preview_dicing_rate = 1
    
    if context.scene.cycles.offscreen_dicing_scale == 4:
        context.scene.cycles.offscreen_dicing_scale = 16

    active_material.cycles.displacement_method = 'DISPLACEMENT'
    active_object.cycles.use_adaptive_subdivision = True

    if len(active_object.modifiers) != 0:
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
    if material_output == None:
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
            if len(displacement_node.inputs[0].links) != 0:
                return {'FINISHED'}
        else:
            displacement_node = add_displacement_node()


    if active_node != None:
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
            if color_links != ():
                to_bsdf = color_links[0].from_node
                to_bsdf_height = to_bsdf.outputs.get("Height")
                if to_bsdf_height != None:
                    links.new(to_bsdf.outputs["Height"], displacement_node.inputs[0])
                    return {'FINISHED'}

    operator.report({'INFO'}, "Cannot find height. Select a node with a \"Height\" output socket.")
    return {'FINISHED'}

class MATAPP_OT_ensure_adaptive_subdivision(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_ensure_adaptive_subdivision"
    bl_label = "Ensure Adaptive Subdivision"
    bl_description = "Ensure adaptive subdivision setup for the active object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return ensure_adaptive_subdivision(self, context)


def normalize_texture(operator, context, new_material = False, node_groups = []):

    def find_max_and_min(image, channel_name = 'R', all_channels = False):

        filepath = os.path.realpath(bpy.path.abspath(image.filepath, library=image.library))

        if filepath.lower().endswith(".exr"):
            operator.report({'INFO'}, f"Cannot normalize {image.filepath}, EXR is not supported")
            return

        with pillow_image.open(filepath) as image:
            image_bands = image.getbands()
            if len(image_bands) > 1:
                if all_channels == True:
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
    
    if new_material == True:
        groups = node_groups
        images = []
    else:
        groups = operator.groups
        images = operator.images

    nodes = context.space_data.edit_tree.nodes
    links = context.space_data.edit_tree.links

    for group in groups:

        image_data_blocks = get_all_image_data_blocks(group)
        if image_data_blocks == None:
            operator.report({'INFO'}, f"No image found in the group: {group.name}")
            continue

        # group_flags = group.node_tree["ma_flags"]

        if context.scene.matapp_properties.normalize_height:

            height_mix_in = group.node_tree.nodes.get("displacement_mix_in")
            if height_mix_in == None:
                height_mix_in = group.node_tree.nodes.get("displacement_x_mix_in")

            if height_mix_in == None:
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

        if context.scene.matapp_properties.normalize_roughness:
            roughness_output = group.outputs.get("Roughness")
            if roughness_output != None:
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "roughness")
                if block_and_channel_name == None:
                    block_and_channel_name = find_image_block_by_type(image_data_blocks , "gloss")
                if block_and_channel_name != None:
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

                    map_range.show_options = False
                    for i in range(1,5):
                        map_range.inputs[i].hide = True
                    
                    for to_socket in to_sockets:
                        links.new(map_range.outputs[0], to_socket)
        
                    links.new(roughness_output, map_range.inputs[0])

                    operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the roughness bitmap in the group: {group.name}")

            else:
                operator.report({'INFO'}, f"No roughness in the group: {group.name}")
        
        if context.scene.matapp_properties.normalize_specular:
            specular_output = group.outputs.get("Specular")
            if specular_output != None:
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "specular")
                if block_and_channel_name != None:
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

                    map_range.show_options = False
                    for i in range(1,5):
                        map_range.inputs[i].hide = True
                    
                    for to_socket in to_sockets:
                        links.new(map_range.outputs[0], to_socket)
        
                    links.new(specular_output, map_range.inputs[0])

                    operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the specular bitmap in the group: {group.name}")
            else:
                operator.report({'INFO'}, f"No specular in the group: {group.name}")

    for image in images:

        block = image.image
        image_output = image.outputs[0]
        image_alpha_output = image.outputs[1]

        if context.scene.matapp_properties.normalize_separately:
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

                map_range.show_options = False
                for i in range(1,5):
                    map_range.inputs[i].hide = True

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

            map_range.show_options = False
            for i in range(1,5):
                map_range.inputs[i].hide = True

            links.new(to_map_range.outputs[0], map_range.inputs[0])

            operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the image: {block.name}")
            

    return {'FINISHED'}

class MATAPP_OT_normalize_height(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_normalize_height_range"
    bl_label = "Normalize:"
    bl_description = "Normalize a texture range of a MA material or an image node texture. Does not work for .EXR"
    bl_options = {'REGISTER', 'UNDO'}

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        layout.prop(context.scene.matapp_properties, "normalize_height")
        layout.prop(context.scene.matapp_properties, "normalize_roughness")
        layout.prop(context.scene.matapp_properties, "normalize_specular")
        layout.separator()
        layout.prop(context.scene.matapp_properties, "normalize_separately")

    def invoke(self, context, event):

        selected_nodes = context.selected_nodes

        if len(selected_nodes) == 0:
            self.report({'INFO'}, "Select a MA material node group or an image node.")
            return {'CANCELLED'}

        self.groups = [node for node in selected_nodes if is_matapp_material(node)]
        self.images = [node for node in selected_nodes if node.type == 'TEX_IMAGE' and node.image != None]

        if len(self.groups) + len(self.images) == 0:
            self.report({'INFO'}, "No MA material or image was found in the selection.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width = 200)

    def execute(self, context):
        return normalize_texture(self, context)


class MATAPP_OT_append_extra_nodes(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_append_extra_nodes"
    bl_label = "Append Extra Nodes"
    bl_description = "Append extra Material Applier nodes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        templates_file_path = os.path.join(script_file_directory, "def_mats.blend")
        
        node_names_list = [
            "Height Scale",
            "Range Mask",
            "Color Proximity",
            "Noise",
            "Noise 3D",
            #"Mix Noise",
            #"Mix Noise 3D",
            "Add Noise",
            "Add Noise 3D",
            "Add Vector Noise",
            "Add Vector Noise 3D",
            "Directional Noise",
            "Camera Distance Mask"
        ]

        to_import = []
        to_import_name = []

        present_node_groups_names = {node_group.name for node_group in bpy.data.node_groups}
        for node_name in node_names_list:
            new_node_name = node_name
            if node_name in present_node_groups_names:
                material_output = bpy.data.node_groups[node_name].nodes.get("Group Output")
                if material_output:
                    label = bpy.data.node_groups[node_name].nodes["Group Output"].label
                    if label == "matapp__" + node_name:
                        continue
                new_node_name = node_name + " MA"
            elif node_name + " MA" in present_node_groups_names:
                material_output = bpy.data.node_groups[node_name + " MA"].nodes.get("Group Output")
                if material_output:
                    label = bpy.data.node_groups[node_name + " MA"].nodes["Group Output"].label
                    if label == "matapp__" + node_name:
                        continue
                new_node_name = node_name + " MATAPP"
            to_import_name.append(new_node_name)
            to_import.append("__" + node_name)
        # bpy.ops.wm.append(directory = templates_file_path, filename = "__" + node_name, set_fake = True)
        with bpy.data.libraries.load(filepath = templates_file_path) as (data_from, data_to):
            data_to.node_groups = [name for name in data_from.node_groups if name in to_import]

        for node, name in zip(to_import, to_import_name):
            bpy.data.node_groups[node].use_fake_user = True
            bpy.data.node_groups[node].name = name

        return {'FINISHED'}


def set_default_settings(operator, context):

    node_groups = get_all_groups_from_selection(operator, context)

    for group in node_groups:

        if is_matapp_material(group):
            settings = {}
            for input_index in range(len(group.inputs)):
                if group.inputs[input_index].type != 'STRING':
                    value = group.inputs[input_index].default_value
                    group.node_tree.inputs[input_index].default_value = value
                    settings[group.inputs[input_index].name] = value
            if not group.node_tree.get("ma_default_settings"):
                group.node_tree["ma_default_settings"] = settings
            else:
                group.node_tree["ma_default_settings"].update(settings)
        else:
            for input_index in range(len(group.inputs)):
                try:
                    value = group.inputs[input_index].default_value
                    group.node_tree.inputs[input_index].default_value = value
                except:
                    pass
        
        operator.report({'INFO'}, f"The settings have been baked for the group: {group.name}")
    
    return {'FINISHED'}

class MATAPP_OT_bake_defaults(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_bake_node_group_defaults"
    bl_label = "Bake Node Group Defaults"
    bl_description = "Set current settings as default ones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return set_default_settings(self, context)


class MATAPP_OT_restore_default_settings(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_restore_default_settings"
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


class MATAPP_OT_restore_factory_settings(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_restore_factory_settings"
    bl_label = "Restore Factory Settings"
    bl_description = "Restore factory settings of a MA material"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        matapp_node_groups = get_all_ma_groups_from_selection(self, context)

        for group in matapp_node_groups:

            settings = group.node_tree.get("ma_factory_settings")
            if settings == None:
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


class MATAPP_OT_save_material_settings(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_save_material_settings"
    bl_label = "Save Material Settings"
    bl_description = "Save material settings of the selected MA materail node group to the local database"

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        settings_database_path = os.path.join(script_file_directory, "material_settings.db")

        try:
            connection = sqlite3.connect(settings_database_path)
        except sqlite3.Error as e:
            print(e)
            self.report({'ERROR'}, "Cannot connect to a material settings database.")
            self.report({'ERROR'}, e)
            return {'CANCELLED'}

        matapp_node_groups = get_all_ma_groups_from_selection(self, context)
        
        for group in matapp_node_groups:

            inputs = group.node_tree.inputs
            nodes = group.node_tree.nodes
                
            image_paths = [os.path.realpath(bpy.path.abspath(node.image.filepath, library=node.image.library)) for node in nodes if node.type == 'TEX_IMAGE' and node.image != None]
            if image_paths == []:
                self.report({'INFO'}, f"No image found in the group: {group.name}")
                continue
            image_paths = list(dict.fromkeys(image_paths))
            
            image_hashes = []
            for image_path in image_paths:
                image_hashes.append(hashfile(image_path, hexdigest=True))

            image_path_by_id = dict(zip(image_hashes, image_paths))

            for input_index in range(len(group.inputs)):
                if group.node_tree.inputs[input_index].type != 'STRING':
                    group.node_tree.inputs[input_index].default_value = group.inputs[input_index].default_value

            material_settings = {}
            for input in inputs:
                if input.type != 'STRING':
                    material_settings[input.name] = input.default_value

            material_settings_json = json.dumps(material_settings)
        
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
                new_setting = json.dumps(old_setting)
                cursor.execute("""
                UPDATE settings
                SET last_path = ?,
                    data = ?
                WHERE
                    id = ? 
                """, (image_path_by_id[id], new_setting, id))
                updated_setting_ids.append(id)

            for image_hash, image_path in image_path_by_id.items():
                if image_hash not in updated_setting_ids:
                    cursor.execute(
                    "INSERT INTO settings (id, hash_name, last_path, data) VALUES(?,?,?,?)", 
                    (image_hash, "imohashxx", image_path, material_settings_json))


            connection.commit()
            self.report({'INFO'}, f"The settings have been saved for the group: {group.name}")

        connection.close()

        return {'FINISHED'}


def load_material_settings(operator, context, new_material = False, node_groups = []):

    script_file_directory = os.path.dirname(os.path.realpath(__file__))
    settings_database_path = os.path.join(script_file_directory, "material_settings.db")

    try:
        connection = sqlite3.connect(settings_database_path)
        cursor = connection.cursor()
    except sqlite3.Error as e:
        print(e)
        operator.report({'ERROR'}, "Cannot connect to a material settings database.")
        operator.report({'ERROR'}, e)
        return {'CANCELLED'}

    if new_material == True:
        matapp_node_groups = node_groups
    else:
        matapp_node_groups = get_all_ma_groups_from_selection(operator, context)
        
    for group in matapp_node_groups:
        nodes = group.node_tree.nodes

        image_paths = [os.path.realpath(bpy.path.abspath(node.image.filepath, library=node.image.library)) for node in nodes if node.type == 'TEX_IMAGE' and node.image != None]
        if len(image_paths) == 0:
            operator.report({'INFO'}, f"No image was found in the group: {group.name}")
            continue
        image_paths = list(dict.fromkeys(image_paths))

        image_hashes = []
        for image_path in image_paths:
            image_hashes.append(hashfile(image_path, hexdigest=True))

        cursor.execute('SELECT * FROM settings WHERE id in ({0})'.format(
            ', '.join('?' for image_hash in image_hashes)), image_hashes)
        all_image_settings = cursor.fetchall()

        if len(all_image_settings) == 0:
            operator.report({'INFO'}, f"No settings were found for the group: {group.name}")
            continue

        all_settings = {}
        for image_settings in all_image_settings:
            settings = json.loads(image_settings[3])
            for name, value in settings.items():
                if name not in all_settings.keys():
                    all_settings[name] = []
                    all_settings[name].append(value)
                else:     
                    all_settings[name].append(value)

        for key in all_settings.keys():
            all_settings[key] = Counter(all_settings[key]).most_common(1)[0][0]

        for key in all_settings.keys():
            node_input = group.inputs.get(key)
            if node_input:
                node_input.default_value = all_settings[key]

        if not group.node_tree.get("ma_default_settings"):
            group.node_tree["ma_default_settings"] = all_settings
        else:
            group.node_tree["ma_default_settings"].update(all_settings)

        for input_index in range(len(group.inputs)):
            group.node_tree.inputs[input_index].default_value = group.inputs[input_index].default_value

        operator.report({'INFO'}, f"Settings were loaded for the group: {group.name}")

    connection.close()

    return {'FINISHED'}

class MATAPP_OT_load_material_settings(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_load_material_settings"
    bl_label = "Load Material Settings"
    bl_description = "Load material settings for the selected MA materail node group from the local database"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return load_material_settings(self, context)


class MATAPP_OT_open_in_file_browser(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_open_in_file_browser"
    bl_label = "Open File Browser"
    bl_description = "Open the selected MA materail or the selected image in a file browser"
	
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

        def get_image_absolute_path(image):
            return os.path.realpath(bpy.path.abspath(image.filepath, library=image.library))

        selected_nodes = context.selected_nodes

        if len(selected_nodes) == 0:
            self.report({'INFO'}, "Nothing is selected.")
            return {'CANCELLED'}

        something_relevant = False

        for node in selected_nodes:
            if node.type == 'TEX_IMAGE' and node.image != None:
                path = get_image_absolute_path(node.image)
                if os.path.exists(path):
                    open_in_file_browser(os.path.dirname(path))
                    something_relevant = True
                else:
                    self.report({'INFO'}, f'No image exists in the path "{path}" for the node "{node.name}".')
            elif node.type == 'GROUP':
                nodes = node.node_tree.nodes
                image_paths = [get_image_absolute_path(node.image) for node in nodes if node.type == 'TEX_IMAGE' and node.image != None]
                if len(image_paths) == 0:
                    self.report({'INFO'}, f'No image found in a group: {node.name}.')
                    continue
                image_paths = [path for path in image_paths if os.path.exists(path)]
                if len(image_paths) == 0:
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


class MATAPP_OT_transfer_settings(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_transfer_settings"
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


def setup_material(operator, context):

    nodes = operator.matapp_node_tree.nodes
    links = operator.matapp_node_tree.links
    inputs = operator.matapp_node_tree.inputs
    outputs = operator.matapp_node_tree.outputs

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

    triplanar_untiling_postfixes = ["_seams_x", "_seams_y", "_seams_z", "_x", "_y", "_z"]
    triplanar_postfixes = ["_x", "_y", "_z"]

    def add_separate_rgb(name):
            separate_rgb = operator.matapp_node_tree.nodes.new( type = 'ShaderNodeSeparateRGB' )
            (x, y) = nodes[name].location
            separate_rgb.location = (x + 400, y)

            links.new(nodes[name].outputs[0], separate_rgb.inputs[0])
            return separate_rgb

    def add_gamma_0_4545(name, index):
        gamma = operator.matapp_node_tree.nodes.new( type = 'ShaderNodeGamma' )
        (x, y) = nodes[name].location
        gamma.location = (x + 250, y)
        gamma.inputs[1].default_value = 1/2.2

        links.new(nodes[name].outputs[index], gamma.inputs[0])
        return gamma

    def add_gamma_0_4545_and_plug_output_to_mix_in(name, alpha_name, index):
            if operator.material_type == 1:
                gamma_0_4545 = add_gamma_0_4545(name, 0)
                links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
            elif operator.material_type == 2:
                gamma_0_4545 = add_gamma_0_4545(name, 0)
                links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
                gamma_0_4545 = add_gamma_0_4545(name + "_seams", 0)
                links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_seams_mix_in"].inputs[0])
            elif operator.material_type == 3:
                for postfix in triplanar_postfixes:
                    gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
                    links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])
            elif operator.material_type == 4:
                for postfix in triplanar_untiling_postfixes:
                    gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
                    links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    # needs to trace ao from ao_post_in
    # def add_separate_rgb_and_gamma_0_4545_and_plug_output_to_mix_in(name, alpha_name, index):
    #         if operator.material_type == 1:
    #             separate_rgb = add_separate_rgb(name)
    #             gamma_0_4545 = add_gamma_0_4545(separate_rgb, 0)
    #             links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
    #         elif operator.material_type == 2:
    #             gamma_0_4545 = add_gamma_0_4545(name, 0)
    #             links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
    #             gamma_0_4545 = add_gamma_0_4545(name + "_seams", 0)
    #             links.new(gamma_0_4545.outputs[index], nodes[alpha_name + "_seams_mix_in"].inputs[0])
    #         elif operator.material_type == 3:
    #             for postfix in triplanar_postfixes:
    #                 gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
    #                 links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])
    #         elif operator.material_type == 4:
    #             for postfix in triplanar_untiling_postfixes:
    #                 gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
    #                 links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def plug_output_to_mix_in(name, alpha_name, index):
        if operator.material_type == 1:
            links.new(nodes[name].outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
        elif operator.material_type == 2:
            links.new(nodes[name].outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
            links.new(nodes[name + "_seams"].outputs[index], nodes[alpha_name + "_seams_mix_in"].inputs[0])
        elif operator.material_type == 3:
            for postfix in triplanar_postfixes:
                links.new(nodes[name + postfix].outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])
        elif operator.material_type == 4:
            for postfix in triplanar_untiling_postfixes:
                links.new(nodes[name + postfix].outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def handle_bitmap():

        def add_gamma_2_2(node, index):
            gamma = operator.matapp_node_tree.nodes.new( type = 'ShaderNodeGamma' )
            (x, y) = node.location
            gamma.location = (x + 250, y)
            gamma.inputs[1].default_value = 2.2

            links.new(node.outputs[index], gamma.inputs[0])
            return gamma

        def set_bitmap_to_node(name):
            if operator.material_type == 1:
                nodes[name].image = current_image
            elif operator.material_type == 2:
                nodes[name].image = current_image
                nodes[name + "_seams"].image = current_image
            elif operator.material_type == 3:
                for postfix in triplanar_postfixes:
                    nodes[name + postfix].image = current_image
            elif operator.material_type == 4:
                for postfix in triplanar_untiling_postfixes:
                    nodes[name + postfix].image = current_image

        def add_separate_rgb_and_plug_output_to_mix_in(name, alpha_name, index):
            if operator.material_type == 1:
                separate_rgb = add_separate_rgb(name)
                links.new(separate_rgb.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
            elif operator.material_type == 2:
                separate_rgb = add_separate_rgb(name)
                links.new(separate_rgb.outputs[index], nodes[alpha_name + "_mix_in"].inputs[0])
                separate_rgb = add_separate_rgb(name + "_seams")
                links.new(separate_rgb.outputs[index], nodes[alpha_name + "_seams_mix_in"].inputs[0])
            elif operator.material_type == 3:
                for postfix in triplanar_postfixes:
                    separate_rgb = add_separate_rgb(name + postfix)
                    links.new(separate_rgb.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])
            elif operator.material_type == 4:
                for postfix in triplanar_untiling_postfixes:
                    separate_rgb = add_separate_rgb(name + postfix)
                    links.new(separate_rgb.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

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
                    if context.scene.matapp_properties.is_y_minus_normal_map:
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
                    if context.scene.matapp_properties.is_y_minus_normal_map:
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
        bitmap_resolutions.append(current_image.size)
        bitmap_type = current_image["ma_type"]
        packed_bitmap_type = len(bitmap_type)
        current_image["ma_order"] = index
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
                

    if not flags["opacity"]:
        outputs.remove(outputs["Alpha"])
    
    if not flags["emissive"]:
        outputs.remove(outputs["Emission"])

    if not flags["normal"]:
        if flags["bump"]:
            links.new(nodes["bump_post_out"].outputs[0], group_output_node.inputs["Normal"])
        else:
            outputs.remove(outputs["Normal"])
        inputs_to_remove = ["Y- Normal Map", "X Rotation′", "Y Rotation′"]
        for input_to_remove in inputs_to_remove:
            try:
                inputs.remove(inputs[input_to_remove])
            except:
                pass


    settings = {}
    for input in inputs:
        if input.type != 'STRING':
            settings[input.name] = input.default_value

    operator.matapp_node_tree["ma_factory_settings"] = settings
    operator.matapp_node_tree["ma_default_settings"] = settings
    operator.matapp_node_tree["ma_type"] = operator.material_type

    operator.matapp_node_tree["ma_flags"] = flags
        

class MATAPP_OT_apply_material(bpy.types.Operator, ImportHelper):
    bl_idname = "object.ma_apply_material"
    bl_label = "Apply Material"
    bl_description = "Apply material to active object"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
    )

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        layout.prop(context.scene.matapp_properties, "is_y_minus_normal_map")
        layout.prop(context.scene.matapp_properties, "use_untiling")
        layout.prop(context.scene.matapp_properties, "use_triplanar")
        layout.separator()
        layout.prop(context.scene.matapp_properties, "ensure_adaptive_subdivision")
        layout.prop(context.scene.matapp_properties, "load_settings")
        layout.separator()
        layout.prop(context.scene.matapp_properties, "a_for_ambient_occlusion")
        layout.prop(context.scene.matapp_properties, "not_rgb_plus_alpha")  

    def execute(self, context):
        if self.files[0].name == "":
            self.report({'INFO'}, "No files selected")
            return {'CANCELLED'}

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        self.name_conventions_file_path = os.path.join(script_file_directory, "bitmap_type_name_conventions.json")
        self.name_conventions = self.get_dictionary_from_json_file(self.name_conventions_file_path)
        if self.name_conventions == None:
            self.report({'ERROR'}, "The json file with name convetions is not found in path:" + self.name_conventions_file_path)
            return {'CANCELLED'}

        self.file_paths = [ os.path.join(self.directory, file.name) for file in self.files]
        bitmap_paths_and_types = self.define_bitmap_types(context)

        if bitmap_paths_and_types == None:
            self.report({'INFO'}, "No valid bitmaps found.")
            return {'CANCELLED'}
        
        self.image_data_blocks = []
        for bitmap_path, bitmap_type in bitmap_paths_and_types:
            image_data_block = bpy.data.images.load(filepath = bitmap_path, check_existing=True)
            image_data_block["ma_type"] = bitmap_type
            self.image_data_blocks.append(image_data_block)


        self.templates_file_path = os.path.join(script_file_directory, "def_mats.blend", "NodeTree")

        materail_type = "_ma_temp_"
        if context.scene.matapp_properties.use_triplanar:
            materail_type += "tri_"
        if context.scene.matapp_properties.use_untiling:
            materail_type += "unt_"

        bpy.ops.wm.append(directory = self.templates_file_path, filename = materail_type, set_fake = True)
        self.matapp_node_tree =  bpy.data.node_groups[materail_type]

        if materail_type == "_ma_temp_":
            self.material_type = 1
        elif materail_type == "_ma_temp_unt_":
            self.material_type = 2
        elif materail_type == "_ma_temp_tri_":
            self.material_type = 3
        elif materail_type == "_ma_temp_tri_unt_":
            self.material_type = 4

        self.matapp_node_tree.name = "M_" + self.material_name
        setup_material(self ,context)

        active_object = context.object
        if active_object == None:
            self.report({'INFO'}, "No active object. The material was added as a node group.")
            return {'FINISHED'}

        active_material = active_object.active_material
        if active_material:

            node_group = active_material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
            node_group.node_tree = self.matapp_node_tree
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
            node_group.node_tree = self.matapp_node_tree
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

        if context.scene.matapp_properties.ensure_adaptive_subdivision == True:
            ensure_adaptive_subdivision(self, context, new_material = True)

        if context.scene.matapp_properties.load_settings == True:
            load_material_settings(self, context, new_material = True, node_groups = [node_group])

        return {'FINISHED'}

    def get_dictionary_from_json_file(self, path):
        if os.path.exists(path):
            with open(path, "r") as f:
                json_data = json.load(f)
            return json_data
        else:
            return None

    def define_bitmap_types(self, context):

        def define_type(string):

            string_length = len(string)

            class Match:
                def __init__(self):
                    self.submatches = []
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

                    for submatch in self.submatches:
                        self.bitmap_types.append(match_to_bitmap_type(submatch))

                    if self.bitmap_types[0] in triple_channel_maps:
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
                        if separator_pattern.match(string, pos=first_char_index - 1):
                            self.is_pre_separated = True
                    elif first_char_index == 0:
                        self.is_pre_separated = True

                    last_char_index = self.submatches[-1].span()[1]
                    if last_char_index != string_length:
                        if separator_pattern.match(string, pos=last_char_index):
                            self.is_post_separated = True
                    elif last_char_index == string_length:
                        self.is_post_separated = True
                        
                    if self.is_pre_separated and self.is_post_separated:
                        self.is_separated = True

            def span_to_string(span):
                    return string[span[0]:span[1]]

            def match_to_bitmap_type(match):
                return  reverse_dictionary[span_to_string(match.span())]

            def length_of_string_from_match(match):
                return len(span_to_string(match.span()))

            def get_submatch(starting_index, patterns_names_to_avoid):
                submatches = []
                for pattern_name in bitmap_patterns_names:
                    if pattern_name in patterns_names_to_avoid:
                        continue
                    submatch = bitmap_type_patterns[pattern_name].match(string, pos=starting_index)
                    if submatch != None:
                        submatches.append(submatch)
                if not submatches:
                    return None
                else:
                    return max(submatches, key=length_of_string_from_match)

            def define_bitmap_type(starting_index):

                match = Match()

                for i in range(4):

                    if match.is_RGB_bitmap:
                        to_avoid = match.bitmap_types + triple_channel_maps
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

                if match.submatches:
                    return match
                else:
                    return None

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

            # import inspect
            # print()
            # for variants in possible_variants:
            #     variants = inspect.getmembers(variants)
            #     variants = [i for i in variants if not i[0].startswith('_') and not inspect.isroutine(i[1])]
            #     print(*variants, sep='\n')
            #     print()

            def submatch_to_string(submatch):
                return  string[submatch.span()[0]:submatch.span()[1]]

            def match_to_submatch_list(match):
                return [submatch_to_string(submatch) for submatch in match.submatches]

            def get_match_length(match):
                return len(''.join(match_to_submatch_list(match)))

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

                if len(''.join(match_to_submatch_list(match))) >= 3:
                    flag = False
                else:
                    for submatch in match.submatches:
                        if len(submatch_to_string(submatch)) > 1:
                            flag = False
                return flag

            if context.scene.matapp_properties.not_rgb_plus_alpha == True:
                for variant in possible_variants:
                    if len(variant.submatches) == 2:
                        variant.submatches = [variant.submatches[-1]]
                
            separated_matches_only = [match for match in possible_variants if match.is_separated == True]
            if separated_matches_only != []:
                result = match_to_submatch_list(separated_matches_only[-1])
                result = [reverse_dictionary[i] for i in result]
            else:
                not_one_letter_matches = [match for match in possible_variants if is_one_letter_match(match) == False]
                if not_one_letter_matches != []:
                    result = match_to_submatch_list(not_one_letter_matches[-1])
                    result = [reverse_dictionary[i] for i in result]
                else:
                    possible_variants.reverse()
                    result = max(possible_variants, key=get_match_length)
                    result = match_to_submatch_list(result)
                    result = [reverse_dictionary[i] for i in result]
            return result


        single_channel_maps = ["metallic", "roughness", "displacement", "ambient_occlusion", "bump", "opacity", "gloss", "specular"]
        triple_channel_maps = ["normal", "diffuse", "albedo", "emissive"]

        bitmap_type_patterns = {}
        for bitmap_type in self.name_conventions["bitmap"]["type"]:
            bitmap_type_names = self.name_conventions["bitmap"]["type"][bitmap_type]
            if context.scene.matapp_properties.a_for_ambient_occlusion == True:
                if bitmap_type == 'albedo':
                    try:
                        bitmap_type_names.remove("a")
                    except:
                        pass
                if bitmap_type == 'ambient_occlusion':
                    bitmap_type_names.append("a")
            bitmap_type_names.sort(reverse=True, key=len)
            bitmap_type_patterns[bitmap_type] = re.compile('|'.join(bitmap_type_names))

        separator_pattern = re.compile(r"[^a-zA-Z0-9]+|$")

        bitmap_patterns_names = list(bitmap_type_patterns)
    
        reverse_dictionary = {}
        for bitmap_type in self.name_conventions["bitmap"]["type"]:
            for name_variant in self.name_conventions["bitmap"]["type"][bitmap_type]:
                reverse_dictionary[name_variant] = bitmap_type

        bitmap_paths = []
        bitmap_names = []

        def if_any(string):
            for pattern_name in bitmap_patterns_names:
                if bitmap_type_patterns[pattern_name].search(string):
                    return True
            return False

        for file_path in self.file_paths:
            basename = os.path.splitext(os.path.basename(file_path))
            name = basename[0].lower()
            extension = basename[1].lower()
            if extension in self.name_conventions["bitmap"]["extension"] and if_any(name):
                bitmap_paths.append(file_path)
                bitmap_names.append(name)

        number_of_bitmaps = len(bitmap_names)

        if number_of_bitmaps == 0:
            return None
        elif number_of_bitmaps == 1:
            self.material_name = bitmap_names[0].rstrip("_-")
        else:
            material_name_match = SequenceMatcher(None, bitmap_names[0], bitmap_names[1]).find_longest_match(0, len(bitmap_names[0]), 0, len(bitmap_names[1]))
            if material_name_match:
                self.material_name = bitmap_names[0][material_name_match.a:material_name_match.a + material_name_match.size].rstrip("_-")
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
            if bitmap_type != None:
                final_bitmap_paths.append(bitmap_path)
                final_bitmap_types.append(bitmap_type)

        if len(final_bitmap_paths) == 0:
            return None

        return zip(final_bitmap_paths, final_bitmap_types)


class MATAPP_OT_convert_materail(bpy.types.Operator, MATAPP_node_editor_poll):
    bl_idname = "node.ma_convert_materail"
    bl_label = "Convert To"
    bl_description = "Convert the selected MA material"
    bl_options = {'REGISTER', 'UNDO'}

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        layout.prop(context.scene.matapp_properties, "convert_to_untiling")
        layout.prop(context.scene.matapp_properties, "convert_to_triplanar")
        layout.separator()

        layout.prop(context.scene.matapp_properties, "convert_and_replace_all_users")
        layout.prop(context.scene.matapp_properties, "convert_and_delete")


    def invoke(self, context, event):

        matapp_materials = get_all_ma_groups_from_selection(self, context)
        if len(matapp_materials) == 0:
            return {'CANCELLED'}

        @dataclass
        class Converting_Node_Group:
            node_tree: object
            node_groups: list = field(default_factory=list)


        node_trees = [group.node_tree for group in matapp_materials]
        node_trees = list(dict.fromkeys(node_trees))

        self.converting_node_groups = []
        for node_tree in node_trees:
            converting_node_group = Converting_Node_Group(node_tree)
            for group in matapp_materials:
                if group.node_tree == node_tree:
                    converting_node_group.node_groups.append(group)
            self.converting_node_groups.append(converting_node_group)
            

        return context.window_manager.invoke_props_dialog(self, width = 300)

    def execute(self, context):

        script_file_directory = os.path.dirname(os.path.realpath(__file__))
        self.templates_file_path = os.path.join(script_file_directory, "def_mats.blend", "NodeTree")
        
        for converting_node_group in self.converting_node_groups:

            image_data_blocks = [node.image for node in converting_node_group.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image != None]
            if len(image_data_blocks) == 0:
                self.report({'INFO'}, f"No image found in the group: {converting_node_group.node_tree.name}")
                continue
            self.image_data_blocks = list(dict.fromkeys(image_data_blocks))

            group_type = "_ma_temp_"
            if context.scene.matapp_properties.convert_to_triplanar:
                group_type += "tri_"
            if context.scene.matapp_properties.convert_to_untiling:
                group_type += "unt_"

            bpy.ops.wm.append(directory = self.templates_file_path, filename = group_type, set_fake = True)
            self.matapp_node_tree =  bpy.data.node_groups[group_type]

            if group_type == "_ma_temp_":
                self.material_type = 1
            elif group_type == "_ma_temp_unt_":
                self.material_type = 2
            elif group_type == "_ma_temp_tri_":
                self.material_type = 3
            elif group_type == "_ma_temp_tri_unt_":
                self.material_type = 4

            initial_node_tree_name = converting_node_group.node_tree.name
            initial_node_tree = converting_node_group.node_tree

            setup_material(self ,context)

            self.matapp_node_tree["ma_default_settings"] = converting_node_group.node_tree["ma_default_settings"]

            for name, value in self.matapp_node_tree["ma_default_settings"].items():
                try:
                    self.matapp_node_tree.inputs[name].default_value = value
                except:
                    pass

            if context.scene.matapp_properties.convert_and_replace_all_users:
                initial_node_tree.user_remap(self.matapp_node_tree)
            else:
                for node_group in converting_node_group.node_groups:
                    node_group.node_tree = self.matapp_node_tree

            if context.scene.matapp_properties.convert_and_delete:
                if initial_node_tree.users == 0 or (initial_node_tree.users == 1 and initial_node_tree.use_fake_user == True):
                    bpy.data.node_groups.remove(initial_node_tree)

            self.matapp_node_tree.name = initial_node_tree_name

            self.report({'INFO'}, f"Converted node tree: {initial_node_tree_name} --> {self.matapp_node_tree.name}")

        return {'FINISHED'}