import itertools
import json
import math
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import typing
from collections import Counter

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils.geometry import area_tri

from . import image_utils
from . import type_definer
from . import view_3d_operator
from . bl_utils import Node_Tree_Wrapper, Reference
from . imohashxx import hashfile
from . utils import color_to_gray, deduplicate

# from timeit import default_timer as timer

MAT_TYPES = (None , "_at_temp_", "_at_temp_unt_", "_at_temp_tri_", "_at_temp_tri_unt_")

M_BASE = "_at_temp_"
M_TRIPLANAR = "tri_"
M_UNTILING = "unt_"

FILE_PATH = os.path.dirname(os.path.realpath(__file__))
DATA_PATH = os.path.join(FILE_PATH, "data.blend")
MATERIAL_SETTINGS_PATH = os.path.join(FILE_PATH, "material_settings.db")

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

def get_all_at_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            operator.report({'INFO'}, "Nothing is selected. Select a AT material node group.")
            return []

        groups = [node for node in selected_nodes if is_atool_material(node)]

        if not groups:
            operator.report({'INFO'}, "No AT materials found in the selection. Select a AT material node group.")
            return []

        return groups

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

def get_image_data_blocks(group):

        if group.bl_idname == "ShaderNodeGroup":
            node_tree = group.node_tree
        elif group.bl_idname == "ShaderNodeTree":
            node_tree = group

        image_data_blocks = [node.image for node in node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
        if not image_data_blocks:
            return None
        return deduplicate(image_data_blocks)

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

def get_node_tree_by_name(name, set_fake=True, link=False, relative=False, existing = True) -> bpy.types.ShaderNodeTree:

    if existing:
        node_group = bpy.data.node_groups.get(name)
        if node_group:
            return node_group

    with bpy.data.libraries.load(filepath = DATA_PATH, link=link, relative=relative) as (data_from, data_to):
        if not name in data_from.node_groups:
            return None
        data_to.node_groups = [name]
    
    node_group = data_to.node_groups[0]
    node_group.use_fake_user = set_fake
    
    return node_group
    

def add_at_blending_node(operator, context, two_nodes, blend_node_tree):

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

        return add_at_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), get_node_tree_by_name("Height Blend AT"))

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

        return add_at_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), get_node_tree_by_name("Detail Blend AT"))


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


def ensure_adaptive_subdivision(operator, context, object = None, material = None):

    context.scene.cycles.feature_set = 'EXPERIMENTAL'
    context.scene.cycles.preview_dicing_rate = operator.preview_dicing_rate
    context.scene.cycles.offscreen_dicing_scale = operator.offscreen_dicing_scale

    if object:
        object.cycles.use_adaptive_subdivision = True
        if object.modifiers:
            if object.modifiers[-1].type != 'SUBSURF':
                subdivision_modifier = object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
                subdivision_modifier.subdivision_type = 'SIMPLE'
        else:
            subdivision_modifier = object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
            subdivision_modifier.subdivision_type = 'SIMPLE'

    if not material:
        operator.report({'INFO'}, "No material specified.")
        return {'FINISHED'}

    material.cycles.displacement_method = 'DISPLACEMENT'
    node_tree = material.node_tree
    active_node = node_tree.nodes.active

    node_tree = Node_Tree_Wrapper(node_tree)
    output = node_tree.output
    if not output:
        operator.report({'INFO'}, "No material output node found.")
        return {'FINISHED'}

    displacement = output["Displacement"]
    if not displacement or (displacement and displacement.type != 'DISPLACEMENT'):
        displacement = output.i["Displacement"].new("ShaderNodeDisplacement", "Displacement")
        x, y = output.location
        displacement.location = (x, y - 150)

    if displacement["Height"]:
        return {'FINISHED'}

    if active_node:
        active_node = node_tree.nodes[active_node.name]
        height = active_node.o.get("Height")
        if height:
            height.join(displacement.i["Height"], move=False)
            return {'FINISHED'}

    surface = output["Surface"]
    if not surface:
        return {'FINISHED'}

    for children in surface.all_children:
        height = children.o.get("Height")
        if height:
            height.join(displacement.i["Height"], move=False)
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

        object = context.space_data.id_from
        material = context.space_data.id

        return ensure_adaptive_subdivision(self, context, object, material)


def normalize_texture(operator, context, new_material = False, node_groups = None):

    if node_groups is None:
        node_groups = []

    def find_max_and_min(image, channel):

        image = image_utils.Image.from_block(image, define_type = False)
        minimum, maximum = image.get_min_max(channel)

        return minimum, maximum
    
    if new_material:
        groups = node_groups
        images = []
    else:
        groups = operator.groups
        images = operator.images

    nodes = context.space_data.edit_tree.nodes
    links = context.space_data.edit_tree.links

    for group in groups:

        image_data_blocks = get_image_data_blocks(group)
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
                    result = find_max_and_min(image, 'RGB')
            elif to_height_mix_in.type == 'GAMMA':
                image = to_height_mix_in.inputs[0].links[0].from_node.image
                result = find_max_and_min(image, 'RGB')
            elif to_height_mix_in.type == 'SEPRGB':
                image = to_height_mix_in.inputs[0].links[0].from_node.image
                channel= height_mix_in_input_link.from_socket.name
                result = find_max_and_min(image, channel)
            else:
                operator.report({'WARNING'}, "Cannot find height texture")
                continue

            if result:
                minimum, maximum = result
                group.inputs["From Min"].default_value = minimum
                group.inputs["From Max"].default_value = maximum
                group.node_tree.inputs["From Min"].default_value = minimum
                group.node_tree.inputs["From Max"].default_value = maximum

                operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the displacement bitmap in the group: {group.name}")

        if operator.normalize_roughness:
            roughness_output = group.outputs.get("Roughness")
            if roughness_output:
                is_gloss = False
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "roughness")
                if not block_and_channel_name:
                    block_and_channel_name = find_image_block_by_type(image_data_blocks , "gloss")
                    is_gloss = True
                if block_and_channel_name:
                    block, channel_name = block_and_channel_name
                    result = find_max_and_min(block, channel_name)
                    
                    minimum, maximum = result
                    if is_gloss:
                        maximum = 1 - minimum
                        minimum = 1 - maximum
                    
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

                    operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the roughness in the group: {group.name}")

            else:
                operator.report({'INFO'}, f"No roughness in the group: {group.name}")
        
        if operator.normalize_specular:
            specular_output = group.outputs.get("Specular")
            if specular_output:
                block_and_channel_name = find_image_block_by_type(image_data_blocks , "specular")
                if block_and_channel_name:
                    block, channel_name = block_and_channel_name
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

            _image = image_utils.Image.from_block(block, define_type = False)
            results = [_image.get_min_max(channel) for channel in 'RGB']

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
            result = find_max_and_min(block, 'RGB')

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
    bl_description = "Normalize a texture range of a AT material or an image node texture."
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



def set_default_settings(operator, context, node_groups):

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
        node_groups = get_all_groups_from_selection(self, context)
        if not node_groups:
            return {'CANCELLED'}

        return set_default_settings(self, context, node_groups)


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

        groups = get_all_at_groups_from_selection(self, context)

        for group in groups:

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

        groups = get_all_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        try:
            connection = sqlite3.connect(MATERIAL_SETTINGS_PATH)
            cursor = connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id TEXT PRIMARY KEY,
                    hash_name TEXT,
                    last_path TEXT,
                    data TEXT
                    )
            """)
        except sqlite3.Error as e:
            self.report({'ERROR'}, "Cannot connect to a material settings database.")
            self.report({'ERROR'}, e)
            return {'CANCELLED'}

        set_default_settings(self, context, groups)
        
        for group in groups:

            inputs = group.node_tree.inputs
            nodes = group.node_tree.nodes

            material_settings = {input.name: round(input.default_value, 6) for input in inputs if input.type != 'STRING'}

            atool_id = group.node_tree.get("atool_id")
            if atool_id:
                library = context.window_manager.at_asset_data.data
                library[atool_id].update_info({"material_settings": material_settings})
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
        

            updated_setting_ids = []
            cursor.execute(f"SELECT * FROM settings WHERE id in ({', '.join(['?']*len(image_hashes))})", image_hashes)
            existing_image_settings = cursor.fetchall()
            for image_setting in existing_image_settings:
                id = image_setting[0]
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


def load_material_settings(operator, context, node_groups = None, node_trees = None):
    
    if node_groups is None: node_groups = []
    if node_trees is None: node_trees = []

    try:
        connection = sqlite3.connect(MATERIAL_SETTINGS_PATH)
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id TEXT PRIMARY KEY,
                hash_name TEXT,
                last_path TEXT,
                data TEXT
                )
        """)
    except sqlite3.Error as e:
        operator.report({'ERROR'}, "Cannot connect to a material settings database.")
        operator.report({'ERROR'}, e)
        return {'CANCELLED'}

    node_trees.extend(deduplicate([group.node_tree for group in node_groups]))
    node_trees = {node_tree: [group for group in node_groups if group.node_tree == node_tree] for node_tree in node_trees}
        
    for node_tree, groups in node_trees.items():

        material_settings = None

        atool_id = node_tree.get("atool_id")
        if atool_id:
            library = context.window_manager.at_asset_data.data
            material_settings = library[atool_id].info.get("material_settings")
            if material_settings:
                operator.report({'INFO'}, f"Settings were loaded for the library material: {node_tree.name}. ID: {atool_id}")
        
        if not atool_id or not material_settings:
            nodes = node_tree.nodes

            image_paths = [os.path.realpath(bpy.path.abspath(node.image.filepath, library=node.image.library)) for node in nodes if node.type == 'TEX_IMAGE' and node.image]
            if not image_paths:
                operator.report({'INFO'}, f"No image was found in the material: {node_tree.name}")
                continue
            image_paths = deduplicate(image_paths)
            image_hashes = [hashfile(image_path, hexdigest=True) for image_path in image_paths]

            cursor.execute(f"SELECT * FROM settings WHERE id in ({', '.join(['?']*len(image_hashes))})", image_hashes)
            all_image_settings = cursor.fetchall()

            if not all_image_settings:
                operator.report({'INFO'}, f"No settings were found for the material: {node_tree.name}")
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

            operator.report({'INFO'}, f"Settings were loaded from the database for the group: {node_tree.name}")

        for key, value in material_settings.items():
            node_input = node_tree.inputs.get(key)
            if node_input:
                node_input.default_value = value

        default_settings = backward_compatibility_get(node_tree, "at_default_settings", "ma_default_settings")
        if default_settings:
            default_settings.update(material_settings)
        else:
            node_tree["at_default_settings"] = material_settings

        for group in groups:
            for input_index in range(len(group.inputs)):
                group.inputs[input_index].default_value = node_tree.inputs[input_index].default_value

    connection.close()

    return {'FINISHED'}

class ATOOL_OT_load_material_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.load_material_settings"
    bl_label = "Load Material Settings"
    bl_description = "Load material settings for the selected AT material node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        groups = get_all_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        return load_material_settings(self, context, node_groups = groups)


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


def get_uv_scale_multiplier(context, object, uv = None, transform = False, triangulate = False):

    depsgraph = context.evaluated_depsgraph_get()

    bm = bmesh.new()
    bm.from_object(object, depsgraph)
    
    if transform:
        bm.transform(object.matrix_world)
    if triangulate:
        bmesh.ops.triangulate(bm, faces=bm.faces)

    mesh_area = sum(f.calc_area() for f in bm.faces)

    if uv:
        uv_layer = bm.loops.layers.uv[uv]
    else:
        uv_layer = bm.loops.layers.uv.active

    uv_layer = bm.loops.layers.uv.active
    uv_area = sum(area_tri(*(vert[uv_layer].uv for vert in face)) for face in bm.calc_loop_triangles())
    
    bm.free()
    
    return math.sqrt(mesh_area/uv_area)

class ATOOL_OT_set_uv_scale_multiplier(bpy.types.Operator):
    bl_idname = "atool.set_uv_scale_multiplier"
    bl_label = "Match World Scale"
    bl_description = "Match the active mesh UV scale to the world scale. See F9 redo panel for settings"
    bl_options = {'REGISTER', 'UNDO'}

    transform: bpy.props.BoolProperty(
        name="Apply Transforms",
        description="Apply the object's transforms",
        default = False
        )

    triangulate: bpy.props.BoolProperty(
        name="Triangulate",
        description="Triangulate the object geometry",
        default = False
        )

    def execute(self, context):

        object = context.space_data.id_from
        if not object:
            self.report({'INFO'}, "No object selected.")
            return {'CANCELLED'}

        if not (object.data and object.data.uv_layers):
            self.report({'INFO'}, "The object has not uv layers.")
            return {'CANCELLED'}

        self.groups = get_all_at_groups_from_selection(self, context)
        if not self.groups:
            return {'CANCELLED'}

        self.uv = None
        multiplier = get_uv_scale_multiplier(context, object, self.uv, self.transform, self.triangulate)
        
        for group in self.groups:
            if group:
                group.inputs["Scale"].default_value = multiplier
        self.report({'INFO'}, "UV matching is done.")

        return {'FINISHED'}
        


class ATOOL_PROP_import_config(bpy.types.PropertyGroup):

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

def draw_import_config(context, layout):

    config = context.window_manager.at_import_config

    layout.prop(config, "a_for_ambient_occlusion")
    layout.prop(config, "not_rgb_plus_alpha")

    layout.prop(config, "use_ignore_by_type")
    if config.use_ignore_by_type:
        layout.prop(config, "ignore_by_type", text='')

    layout.prop(config, "use_ignore_by_format")
    if config.use_ignore_by_format:
        layout.prop(config, "ignore_by_format", text='')

    layout.prop(config, "use_prefer_over")
    if config.use_prefer_over:
        layout.prop(config, "prefer_over", text='')

def get_definer_config(context):

    prop = context.window_manager.at_import_config

    config = {
        "ignore_type": [],
        "ignore_format": [],
        "prefer_type": [],
        "prefer_format": [],
        "custom": {},
        "is_rgb_plus_alpha": not prop.not_rgb_plus_alpha
    }

    if prop.use_ignore_by_type:
        config["ignore_type"] = prop.ignore_by_type.split(" ")
    if prop.use_ignore_by_format:
        config["ignore_format"] = prop.ignore_by_format.split(" ")
    if prop.use_prefer_over:
        config["prefer_type"] = [tuple(pare.split("-")) for pare in prop.prefer_over.split(" ")]
    if prop.a_for_ambient_occlusion:
        config["custom"]["ambient_occlusion"] = ["a"]

    return config


def get_at_node_tree(operator, context, material_type_name, is_converting = False):
    """
    Requires as part of `operator`:
    `images`: List[image_utils.Image]
    `is_y_minus_normal_map`: bool
    """

    node_tree = get_node_tree_by_name(material_type_name, existing = False)

    material_type: int
    material_type = MAT_TYPES.index(material_type_name)

    images: typing.List[image_utils.Image]
    images = operator.images

    is_y_minus_normal_map: bool
    is_y_minus_normal_map = operator.is_y_minus_normal_map

    nodes = node_tree.nodes
    links = node_tree.links
    inputs = node_tree.inputs
    outputs = node_tree.outputs

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
            separate_rgb = node_tree.nodes.new( type = 'ShaderNodeSeparateRGB' )
            (x, y) = nodes[name].location
            separate_rgb.location = (x + 400, y)

            links.new(nodes[name].outputs[0], separate_rgb.inputs[0])
            return separate_rgb

    def add_gamma_0_4545(name, index):
        gamma = node_tree.nodes.new( type = 'ShaderNodeGamma' )
        (x, y) = nodes[name].location
        gamma.location = (x + 250, y)
        gamma.inputs[1].default_value = 1/2.2

        links.new(nodes[name].outputs[index], gamma.inputs[0])
        return gamma

    def add_gamma_0_4545_and_plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[material_type]:
            gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
            links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[material_type]:
            links.new(nodes[name + postfix].outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

    def add_gamma_2_2(node, index):
            gamma = node_tree.nodes.new( type = 'ShaderNodeGamma' )
            (x, y) = node.location
            gamma.location = (x + 250, y)
            gamma.inputs[1].default_value = 2.2

            links.new(node.outputs[index], gamma.inputs[0])
            return gamma

    def set_bitmap_to_node(name):
        for postfix in postfixes[material_type]:
            nodes[name + postfix].image = current_image

    def add_separate_rgb_and_plug_output_to_mix_in(name, alpha_name, index):
        for postfix in postfixes[material_type]:
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
                    if is_y_minus_normal_map:
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
                    if is_y_minus_normal_map:
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

    for index, image in enumerate(images):
        current_image = image.data_block
        bitmap_type = backward_compatibility_get(current_image, "at_type", "ma_type")
        packed_bitmap_type = len(bitmap_type)
        current_image["at_order"] = index # not yet used
        handle_bitmap()
        operator.report({'INFO'}, "The bitmap " + str(os.path.basename(current_image.filepath)) + " was set as: " + str(bitmap_type))

    group_output_node = nodes["Group Output"]

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


    if not is_converting:
        aspect_ratios = [image.aspect_ratio for image in images]
        if all(ratio == aspect_ratios[0] for ratio in aspect_ratios):
            aspect_ratio = aspect_ratios[0]
        else:
            aspect_ratio = Counter(aspect_ratios).most_common(1)[0][0]
            operator.report({'INFO'}, f"Imported bitmaps have diffrent aspect ratios, the ratio set to {aspect_ratio}")

        if aspect_ratio > 1:
            inputs["Y Scale"].default_value = aspect_ratio
        elif aspect_ratio < 1:
            inputs["X Scale"].default_value = 1/aspect_ratio

        for image in images:
            for channel, subtype in image.iter_type():
                if subtype == "displacement":
                    min, max = image.min_max[channel]
                    node_tree.inputs["From Min"].default_value = min
                    node_tree.inputs["From Max"].default_value = max

    settings = {}
    for input in inputs:
        if input.type != 'STRING':
            settings[input.name] = input.default_value

    node_tree["at_factory_settings"] = settings
    node_tree["at_default_settings"] = settings
    node_tree["at_type"] = material_type
    node_tree["at_flags"] = flags # not yet used

    return node_tree

def apply_material(operator, context, object = None, material = None):
    """
    Requires as part of `operator`:
    `images`: List[image_utils.Image]
    `use_triplanar`: bool
    `use_untiling`: bool
    `asset_name`: str
    `height_scale`: float
    `atool_id`: str
    `load_settings`: bool
    `ensure_adaptive_subdivision`: bool
    """

    material_type = M_BASE
    if operator.use_triplanar:
        material_type += M_TRIPLANAR
    if operator.use_untiling:
        material_type += M_UNTILING

    node_tree = get_at_node_tree(operator ,context, material_type)
    node_tree.name = operator.asset_name if operator.asset_name else "M_" + operator.material_name

    if operator.height_scale != None:
        node_tree.inputs["Scale′"].default_value = operator.height_scale

    if operator.atool_id:
        node_tree["atool_id"] = operator.atool_id

    if operator.load_settings:
        load_material_settings(operator, context, node_trees = [node_tree])

    if not object:
        operator.report({'INFO'}, "The material was added as a node group.")
        return {'FINISHED'}

    if material:
        node_group = material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
        node_group.node_tree = node_tree
        node_group.name = node_group.node_tree.name

        node_group.width = 300
        node_group.show_options = False

        principled_node = material.node_tree.nodes.get("Principled BSDF")
        if principled_node:
            (x, y) = principled_node.location
        else:
            (x, y) = (0, 0)

        node_group.location = (x - 400, y)
    else:
        material = bpy.data.materials.new(name="New Material")
        material.use_nodes = True
        object.data.materials.append(material)

        node_group = material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
        node_group.node_tree = node_tree
        node_group.name = node_group.node_tree.name
        node_group.width = 300
        node_group.show_options = False
        
        links = material.node_tree.links

        principled_node = material.node_tree.nodes["Principled BSDF"]
        (x, y) = principled_node.location
        node_group.location = (x - 400, y)

        names_to_ignore = {"Height", "Seam"}
        for output in node_group.outputs:
            if output.name not in names_to_ignore:
                links.new(node_group.outputs[output.name], principled_node.inputs[output.name])

    for image in operator.images:
        for channel, subtype in image.iter_type():
            if subtype in {"diffuse", "albedo"}:
                material.diffuse_color = image.dominant_color[channel] + [1]
            elif subtype == "roughness":
                material.roughness = color_to_gray(image.dominant_color[channel])
            elif subtype == "gloss":
                material.roughness = 1 - color_to_gray(image.dominant_color[channel])
            elif subtype == "metallic":
                material.metallic = color_to_gray(image.dominant_color[channel])

    if operator.ensure_adaptive_subdivision:
        ensure_adaptive_subdivision(operator, context, object, material)

    return {'FINISHED'}


class Material_Import_Properties:
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

    def draw_material_import(self, layout):
        layout.alignment = 'LEFT'

        layout.prop(self, "use_untiling")
        layout.prop(self, "use_triplanar")

        layout.separator()
        layout.prop(self, "is_y_minus_normal_map")
        layout.prop(self, "load_settings")
        layout.prop(self, "ensure_adaptive_subdivision")
        if self.ensure_adaptive_subdivision:
            layout.prop(self, "preview_dicing_rate")
            layout.prop(self, "offscreen_dicing_scale")


class ATOOL_OT_apply_material(bpy.types.Operator, ImportHelper, Material_Import_Properties):
    bl_idname = "atool.apply_material"
    bl_label = "Apply Material"
    bl_description = "Apply material to active object"
    # bl_options = {'REGISTER', 'UNDO'} modal redo panel does not work with modal dialogs

    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        self.draw_material_import(layout)
        draw_import_config(context, layout)

    def execute(self, context):

        self.height_scale = None
        self.asset_name = None
        self.atool_id = None

        if self.files[0].name == "":
            self.report({'INFO'}, "No files selected.")
            return {'CANCELLED'}
        images = [os.path.join(self.directory, file.name) for file in self.files]

        self.object = None
        self.material = None

        object = context.space_data.id_from
        if object:
            self.object = Reference(object)

        material = context.space_data.id
        if material:
                self.material = Reference(material)

        config = get_definer_config(context)
        
        self.queue = queue.Queue()
        config["queue"] = self.queue

        self.process = threading.Thread(target=type_definer.define, args=(images, config))
        self.process.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            if not self.process.is_alive():
                self.process.join()

                try:
                    result = self.queue.get(block=False)[0]
                except:
                    self.report({"ERROR"}, "The type definer failed. See the console for the error.")
                    return {'CANCELLED'}

                for report in result["report"]:
                    self.report(*report)

                if not result["ok"]:
                    return {'FINISHED'}

                self.images = result["images"]
                self.material_name = result["material_name"]

                for image in self.images:
                    image.data_block = bpy.data.images.load(filepath = image.path, check_existing=True)
                    image.set_bl_props(image.data_block)

                object = None
                material = None

                if self.object:
                    object = self.object.get()
                if self.material:
                    material = self.material.get()

                return apply_material(self, context, object, material)
                
        return {'PASS_THROUGH'}


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
    replace_all_users: bpy.props.BoolProperty(
        name="Replace All",
        description="Replace all users of the initial material with the converted one",
        default = False
        )
    delete_unused: bpy.props.BoolProperty(
        name="Delete",
        description="Delete the initial material if it has zero users",
        default = True
        )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'
        layout.prop(self, "convert_to_untiling")
        layout.prop(self, "convert_to_triplanar")
        layout.separator()
        layout.prop(self, "replace_all_users")
        layout.prop(self, "delete_unused")

    def invoke(self, context, event):

        if not get_all_at_groups_from_selection(self, context):
            return {'CANCELLED'}
            
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def execute(self, context):

        groups = get_all_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        node_trees = deduplicate([group.node_tree for group in groups])
        node_trees = {node_tree: [group for group in groups if group.node_tree == node_tree] for node_tree in node_trees}

        self.is_y_minus_normal_map = None
        
        for node_tree, groups in node_trees.items():

            image_data_blocks = get_image_data_blocks(node_tree)
            if not image_data_blocks:
                self.report({'INFO'}, f"No image found in the node tree: {node_tree.name}")
                continue
            self.images = [image_utils.Image.from_block(block) for block in image_data_blocks]

            initial_node_tree_name = node_tree.name
            initial_node_tree = node_tree

            type = M_BASE
            if self.convert_to_triplanar:
                type += M_TRIPLANAR
            if self.convert_to_untiling:
                type += M_UNTILING

            node_tree = get_at_node_tree(self, context, type, is_converting = True)

            default_settings = backward_compatibility_get(initial_node_tree, "at_default_settings", "ma_default_settings")
            node_tree["at_default_settings"] = default_settings.to_dict()
            
            for name, value in default_settings.items():
                try: node_tree.inputs[name].default_value = value
                except: pass

            atool_id = initial_node_tree.get("atool_id")
            if atool_id:
                node_tree["atool_id"] = atool_id

            if self.replace_all_users:
                initial_node_tree.user_remap(node_tree)
            else:
                for group in groups:
                    group.node_tree = node_tree

            if self.delete_unused:
                if not initial_node_tree.users or (initial_node_tree.users == 1 and initial_node_tree.use_fake_user):
                    bpy.data.node_groups.remove(initial_node_tree)

            node_tree.name = initial_node_tree_name

            self.report({'INFO'}, f"Converted node tree: {initial_node_tree_name} --> {node_tree.name}")

        return {'FINISHED'}


class ATOOL_OT_replace_material(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.replace_material"
    bl_label = "Replace"
    bl_description = "Replace the selected AT material with the active browser material"
    bl_options = {'REGISTER', 'UNDO'}

    replace_all_users: bpy.props.BoolProperty(
        name="Replace All",
        description="Replace all users of the initial material with the new one",
        default = False
        )
    delete_unused: bpy.props.BoolProperty(
        name="Delete Unused",
        description="Delete the initial material if it has zero users",
        default = True
        )
    reset_settings: bpy.props.BoolProperty(
        name="Reset Settings",
        description="Reset settings back to defaults",
        default = True
        )
    load_settings: bpy.props.BoolProperty(
        name="Load Settings",
        description="Load the imported material's settings",
        default = True
        )
    is_y_minus_normal_map: bpy.props.BoolProperty(
        name="Y- Normal Map",
        description="Invert the green channel for DirectX style normal maps",
        default = False
        )

    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'
        layout.prop(self, "is_y_minus_normal_map")
        layout.prop(self, "load_settings")
        layout.prop(self, "replace_all_users")
        layout.prop(self, "delete_unused")

    def invoke(self, context, event):
        
        groups = get_all_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        origin = context.space_data.id
        if origin.node_tree != context.space_data.edit_tree:
            origin = context.space_data.edit_tree

        self.targets = [Reference(group, origin) for group in groups]

        asset = view_3d_operator.get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
        
        images = asset.get_imags()
        if not images:
            self.report({'INFO'}, "Nothing to import.")
            return {'CANCELLED'}

        info = asset.info
        self.atool_id = asset.id

        self.height_scale = None
        dimensions = info.get("dimensions")
        if dimensions:
            x, y, z = dimensions
            self.height_scale = z * min(x, y)

        self.asset_name = info.get("name")

        config = get_definer_config(context)

        self.queue = queue.Queue()
        config["queue"] = self.queue
        config["asset"] = asset

        self.process = threading.Thread(target=type_definer.define, args=(images, config))
        self.process.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):

        if event.type == 'TIMER':
            if not self.process.is_alive():
                self.process.join()

                try:
                    result = self.queue.get(block=False)[0]
                except:
                    self.report({"ERROR"}, "The type definer failed. See the console for the error.")
                    return {'CANCELLED'}

                for report in result["report"]:
                    self.report(*report)

                if not result["ok"]:
                    return {'FINISHED'}

                self.images = result["images"]
                self.material_name = result["material_name"]
                
                return self.execute(context)

        return {'PASS_THROUGH'}

    def execute(self, context):

        groups = [target.get() for target in self.targets] 
        
        if not groups:
            self.report({"INFO"}, "All targets were deleted.")
            return {'CANCELLED'}

        for image in self.images:
            image.data_block = bpy.data.images.load(filepath = image.path, check_existing=True)
            image.set_bl_props(image.data_block)

        types = {}
        for group in groups:
            type = backward_compatibility_get(group.node_tree, "at_type", "ma_type")
            if not type:
                type = 2
            if type in types:
                types[type].append(group)
            else:
                types[type] = [group]
        types = types
        
        node_trees = deduplicate([group.node_tree for group in groups])

        for type, groups in types.items():

            node_tree = get_at_node_tree(self, context, MAT_TYPES[type])
            node_tree.name = self.asset_name if self.asset_name else "M_" + self.material_name

            if self.height_scale != None:
                node_tree.inputs["Scale′"].default_value = self.height_scale

            if self.atool_id:
                node_tree["atool_id"] = self.atool_id

            if self.load_settings:
                load_material_settings(self, context, node_trees = [node_tree])

            if self.replace_all_users:
                for old_node_tree in deduplicate([group.node_tree for group in groups]):
                    if not old_node_tree:
                        continue
                    old_node_tree.user_remap(node_tree)
                    self.report({'INFO'}, f"{old_node_tree.name} was changed to {node_tree.name}")

                if self.reset_settings:
                    for nodes in [material.node_tree.nodes for material in bpy.data.materials] + [node_tree.nodes for node_tree in bpy.data.node_groups]:
                        for node in nodes:
                            if node.type == 'GROUP' and node.node_tree == node_tree:
                                for input_index in range(len(group.inputs)):
                                    try: group.inputs[input_index].default_value = node_tree.inputs[input_index].default_value
                                    except: pass
            else:
                for group in groups:
                    if not group:
                        continue
                    group.node_tree = node_tree
                    self.report({'INFO'}, f"{group.name}'s node tree was changed to {node_tree.name}")

                    if self.reset_settings:
                        for input_index in range(len(group.inputs)):
                            try: group.inputs[input_index].default_value = node_tree.inputs[input_index].default_value
                            except: pass

        if self.delete_unused:
            for node_tree in node_trees:
                if not node_tree: 
                    continue
                if not node_tree.users or (node_tree.users == 1 and node_tree.use_fake_user):
                    bpy.data.node_groups.remove(node_tree)
        
        return {'FINISHED'}


# full material output

class ATOOL_OT_ungroup(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.ungroup"
    bl_label = "Ungroup"
    bl_description = "Ungroup the node group preserving default values. See the redo panel by pressing F9 for settings"
    bl_options = {'REGISTER', 'UNDO'}

    do_delete_unused: bpy.props.BoolProperty(
        name="Delete Unused",
        description="Delete unused node groups",
        default = False
        )

    do_change_inner: bpy.props.BoolProperty(
        name="Change Inner",
        description="Change inner inputs default values instead",
        default = True
        )

    def execute(self, context):
        groups = get_all_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        edit_tree = context.space_data.edit_tree
        node_tree = Node_Tree_Wrapper(edit_tree)
        added_nodes = []
        
        for group in groups:
            group = node_tree[group.name]
            group_tree = group.node_tree

            for input in group:
                if not input.nodes:
                    type = input.type
                    default_value = input.default_value
                    if type in ('VALUE', 'INT'):
                        value = input.new("ShaderNodeValue")
                        value.o[0].default_value = default_value
                        value.label = input.name
                        added_nodes.append(value.__data__)
                    elif type == 'RGBA':
                        rgb = input.new("ShaderNodeRGB")
                        rgb.o[0].default_value = default_value
                        rgb.label = input.name
                        added_nodes.append(rgb.__data__)
                    elif type == 'VECTOR':
                        xyz = input.new("ShaderNodeCombineXYZ")
                        xyz.i["X"].default_value, xyz.i["Y"].default_value, xyz.i["Z"].default_value = tuple(default_value)
                        xyz.label = input.name
                        added_nodes.append(xyz.__data__)

            edit_tree.nodes.active = group.__data__
            bpy.ops.node.group_ungroup()

            if self.do_delete_unused:
                if not group_tree.users or (group_tree.users == 1 and group_tree.use_fake_user):
                    bpy.data.node_groups.remove(group_tree)

        if self.do_change_inner:
            node_tree = Node_Tree_Wrapper(context.space_data.edit_tree)
            added_nodes = [node_tree[node.name] for node in added_nodes]
            for node in added_nodes:
                output = node.outputs[0]
                output_type = output.type
                if node.type == 'COMBXYZ':
                    default_value = (node.i["X"].default_value, node.i["Y"].default_value, node.i["Z"].default_value)
                    convert = {
                        'VALUE': sum(default_value)/3,
                        'RGBA': (*default_value, 1), # not posible
                        'VECTOR': default_value
                    }
                else:
                    default_value = output.default_value if output_type == 'VALUE' else tuple(output.default_value)
                    convert = output.default_value_converter
                for subnode, socket in output.nodes:
                    type = socket.type
                    if default_value == (socket.default_value if socket.type == 'VALUE' else tuple(socket.default_value)):
                        continue
                    elif type == 'RGBA' and output_type != 'RGBA' and \
                        ((type == 'VALUE' and convert['VALUE'] < 0) or (type == 'VECTOR' and any(i < 0 for i in convert['VECTOR']))):
                        rgb = socket.new("ShaderNodeRGB")
                        rgb.o[0].default_value = default_value
                        rgb.label = node.label
                    elif socket.hide_value == True or subnode.type == "REROUTE":
                        if output_type == 'VALUE':
                            value = socket.new("ShaderNodeValue")
                            value.o[0].default_value = default_value
                            value.label = node.label
                        elif output_type == 'RGBA':
                            rgb = socket.new("ShaderNodeRGB")
                            rgb.o[0].default_value = default_value
                            rgb.label = node.label
                        elif output_type == 'VECTOR':
                            xyz = socket.new("ShaderNodeCombineXYZ")
                            xyz.i["X"].default_value, xyz.i["Y"].default_value, xyz.i["Z"].default_value = tuple(default_value)
                            xyz.label = node.label
                    else:
                        socket.default_value = convert[type]
                node.delete()
    
        return {'FINISHED'}
 

class ATOOL_OT_to_pbr(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.to_pbr"
    bl_label = "Convert To PBR"
    bl_description = "WORK IN PROGRESS. Convert the active material to PBR"
    bl_options = {'REGISTER', 'UNDO'}

    convert_displacement: bpy.props.BoolProperty(
        name="Convert Normal From Displacement",
        description="Convert the displacement output normal contribution to the shader to PBR",
        default = False
        )

    # def invoke(self, context, event):
    #     return context.window_manager.invoke_props_popup(self, event)

    def execute(self, context):

        # edit_tree = context.space_data.edit_tree
        node_tree = context.space_data.node_tree


        if not node_tree:
            self.report({'INFO'}, "No active material.")
            return {'FINISHED'}

        o = Node_Tree_Wrapper(node_tree).output

        surface = o["Surface"]

        def get_principled():
            return o.i["Surface"].new("ShaderNodeBsdfPrincipled", "BSDF")

        if surface.type in {'BSDF_GLOSSY', 'BSDF_DIFFUSE'}:
            principled = get_principled()
            principled.set_inputs(surface.get_pbr_inputs())
            surface.delete()
        elif surface.type == "MIX_SHADER":
            principled = get_principled()
            children = surface.children
            if {getattr(node, "type") for node in children} == {'BSDF_GLOSSY', 'BSDF_DIFFUSE'}:
                for node in children:
                    if node.type == 'BSDF_DIFFUSE':
                        principled.set_inputs(node.get_pbr_inputs())
                for node in children:
                    if node.type == 'BSDF_GLOSSY':
                        principled.set_input("Roughness", node.get_pbr_inputs()["Roughness"])
                for node in children:
                    node.delete()
                surface.delete()

        if self.convert_displacement:
            displacement = o["Displacement"]
            if displacement and displacement.type == "DISPLACEMENT":
                bump = principled.inputs["Normal"].new("ShaderNodeBump", "Normal")
                bump.set_input("Normal", displacement.get_input("Normal"))
                bump.set_input("Distance", displacement.get_input("Scale"))
                bump.set_input("Height", displacement.get_input("Height"))
                if displacement.space == "OBJECT":
                    object = context.space_data.id_from
                    value_1 = sum(object.scale)/3 # todo: need to get a shader version for it
                    bump.inputs["Distance"].default_value *= value_1
                displacement.delete()
        
        return {'FINISHED'}
