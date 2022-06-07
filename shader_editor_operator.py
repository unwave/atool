# from __future__ import annotations ???
import itertools
import json
import math
import operator as _operator
import os
import queue
import sqlite3
import threading
import typing
from collections import Counter

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper
import mathutils
from mathutils.geometry import area_tri

from . imohashxx import hashfile

from . import utils
from . import image_utils
from . import type_definer
from . import bl_utils
from . import node_utils
from . import data


# from timeit import default_timer as timer

MAT_TYPES = (None , "_at_temp_", "_at_temp_unt_", "_at_temp_tri_", "_at_temp_tri_unt_")

M_BASE = "_at_temp_"
M_TRIPLANAR = "tri_"
M_UNTILING = "unt_"

FILE_PATH = os.path.dirname(os.path.realpath(__file__))
MATERIAL_SETTINGS_PATH = os.path.join(FILE_PATH, "material_settings.db")

register = bl_utils.Register(globals())

class Shader_Editor_Poll:
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'NODE_EDITOR' and context.space_data.tree_type == 'ShaderNodeTree'


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

def get_at_groups_from_selection(operator, context):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            operator.report({'INFO'}, "Nothing is selected. Select a AT material node group.")
            return []

        groups = [node for node in selected_nodes if is_atool_material(node)]

        if not groups:
            operator.report({'INFO'}, "No AT materials found in the selection. Select a AT material node group.")
            return []

        return groups

def get_groups_from_selection(operator, context):

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
        return utils.deduplicate(image_data_blocks)

def find_image_block_by_type(blocks , type):
    for block in blocks:
        lt_type = bl_utils.backward_compatibility_get(block, ("at_type", "ma_type"))
        if type in lt_type:
            type_index = lt_type.index(type)
            if len(lt_type) <= 2:
                channel_names = {0: 'RGB', 1: 'A'}
                return (block, channel_names[type_index])
            else:
                channel_names = {0: 'R', 1: 'G', 2: 'B', 3: 'A'}
                return (block, channel_names[type_index])
    return None


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
        geometry_normal_node = nodes.new(type="ShaderNodeGroup")
        geometry_normal_node.node_tree = node_utils.get_atool_extra_node_tree('Undisplaced Normal')
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

        return add_at_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), node_utils.get_node_tree_by_name("Height Blend AT"))

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

        return add_at_blending_node(self, context, (selected_nodes[0], selected_nodes[1]), node_utils.get_node_tree_by_name("Detail Blend AT"))


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


def ensure_adaptive_subdivision(operator: bpy.types.Operator, context: bpy.types.Context, object: bpy.types.Object = None, material: bpy.types.ShaderNodeTree = None, output: bpy.types.ShaderNode = None):

    if context.scene.cycles.feature_set !='EXPERIMENTAL':
        context.scene.cycles.feature_set = 'EXPERIMENTAL'
    if context.scene.cycles.preview_dicing_rate != operator.preview_dicing_rate:
        context.scene.cycles.preview_dicing_rate = operator.preview_dicing_rate
    if context.scene.cycles.offscreen_dicing_scale != operator.offscreen_dicing_scale:
        context.scene.cycles.offscreen_dicing_scale = operator.offscreen_dicing_scale

    if object:
        object.cycles.use_adaptive_subdivision = True
        if object.modifiers:
            if object.modifiers[-1].type != 'SUBSURF':
                subdivision_modifier = object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
                subdivision_modifier.subdivision_type = 'SIMPLE'
            else:
                subdivision_modifier = object.modifiers[-1]
                subdivision_modifier.show_viewport = True
                subdivision_modifier.show_render = True
        else:
            subdivision_modifier = object.modifiers.new('Adaptive Subdivision', 'SUBSURF')
            subdivision_modifier.subdivision_type = 'SIMPLE'

    if not material:
        operator.report({'INFO'}, "No material specified.")
        return {'FINISHED'}

    material.cycles.displacement_method = 'DISPLACEMENT'
    material.update_tag()

    node_tree = material.node_tree # type: bpy.types.ShaderNodeTree
    active_node = node_tree.nodes.active

    node_tree = node_utils.Node_Tree_Wrapper(node_tree)

    if output:
        if not isinstance(output, node_utils.Node_Wrapper):
            output = node_tree[output]
    else:
        output = node_tree.output

    if not output:
        operator.report({'INFO'}, "No material output node found.")
        return {'FINISHED'}

    displacement = output["Displacement"]
    if not displacement or (displacement and displacement.type != 'DISPLACEMENT'):
        displacement = output.i["Displacement"].new("ShaderNodeDisplacement", "Displacement")
        displacement.space = 'WORLD'
        x, y = output.location
        displacement.location = (x, y - 150)

    if displacement["Height"]:
        return {'FINISHED'}

    if active_node:
        active_node = node_tree[active_node]
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

                operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the {index} channel in the image: {block.name}")
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
            map_range.label = "Normalized"


            links.new(to_map_range.outputs[0], map_range.inputs[0])

            operator.report({'INFO'}, f"Min: {minimum}, max: {maximum} for the image: {block.name}")
            
    return {'FINISHED'}

class ATOOL_OT_normalize_range(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.normalize_range"
    bl_label = "Normalize:"
    bl_description = "Normalize a texture range of an AT material or an image node texture."
    bl_options = {'REGISTER', 'UNDO'}

    normalize_height: bpy.props.BoolProperty(
        name="Height",
        description="Normalize a AT material height range",
        default = True
        )
    normalize_roughness: bpy.props.BoolProperty(
        name="Roughness",
        description="Normalize a AT material roughness range",
        default = False
        )
    normalize_specular: bpy.props.BoolProperty(
        name="Specular",
        description="Normalize a AT material specular range",
        default = False
        )
    normalize_separately: bpy.props.BoolProperty(
        name="Separately",
        description="Normalize texture channels separately for image nodes",
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
        
        self.images = [node for node in self.images if node.image.source == 'FILE' and os.path.exists(bl_utils.get_block_abspath(node.image))]

        if not self.images and not self.groups:
            self.report({'INFO'}, "Only written to disk images are allowed.")
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
        
        to_import_names = []
        to_import = []

        present_node_groups_names = {node_group.name for node_group in bpy.data.node_groups}

        with bpy.data.libraries.load(filepath = templates_file_path) as (data_from, data_to):
            for node_group in data_from.node_groups:
                
                node_name = node_group[2:]
                if not node_group.startswith("++"):
                    continue

                new_node_name = node_name
                if node_name in present_node_groups_names:
                    if node_utils.is_atool_extra_node_tree(node_name):
                        continue
                    new_node_name = node_name + " AT"
                elif node_name + " AT" in present_node_groups_names:
                    if node_utils.is_atool_extra_node_tree(node_name + " AT"):
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
                    try:
                        value = group.inputs[input_index].default_value
                        group.node_tree.inputs[input_index].default_value = value
                        settings[group.inputs[input_index].name] = value
                    except:
                        import traceback
                        traceback.print_exc()

            default_settings = bl_utils.backward_compatibility_get(group.node_tree, ("at_default_settings", "ma_default_settings"))

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
        node_groups = get_groups_from_selection(self, context)
        if not node_groups:
            return {'CANCELLED'}

        return set_default_settings(self, context, node_groups)


class ATOOL_OT_restore_default_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.restore_default_settings"
    bl_label = "Restore Defaults"
    bl_description = "Restore default settings of a node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        node_groups = get_groups_from_selection(self, context)

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

        groups = get_at_groups_from_selection(self, context)

        for group in groups:

            settings = bl_utils.backward_compatibility_get(group.node_tree, ("at_factory_settings", "ma_factory_settings"))

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

        groups = get_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        set_default_settings(self, context, groups)

        with node_utils.Material_Settings_Database() as settings_db:
        
            for group in groups:

                node_tree = group.node_tree
                inputs = group.node_tree.inputs
                nodes = group.node_tree.nodes

                image_paths = [bl_utils.get_block_abspath(node.image) for node in nodes if node.type == 'TEX_IMAGE' and node.image]
                image_paths = utils.deduplicate(image_paths)

                if not image_paths:
                    self.report({'INFO'}, f"No image was found in the material: {group.name}")
                    continue

                material_settings = {input.name: round(input.default_value, 6) for input in inputs if input.type != 'STRING'}

                library = context.window_manager.at_asset_data # type: data.AssetData

                if any(library.is_sub_asset(path) for path in image_paths):
                    asset = utils.get_most_common(library.get_asset_by_path(path) for path in image_paths) # type: data.Asset
                    
                    asset.update_info({"material_settings": material_settings})
                    self.report({'INFO'}, f"The settings have been saved for the library group: {group.name}. ID: {asset.id}")
                    
                    if not self.save_to_database:
                        continue

                settings_db.set(image_paths, material_settings)

                self.report({'INFO'}, f"The settings have been saved to the database for the group: {group.name}")

        return {'FINISHED'}

def load_material_settings(operator, context, node_groups = None, node_trees = None):
    
    if node_groups is None: node_groups = []
    if node_trees is None: node_trees = []

    node_trees = {node_tree: [] for node_tree in node_trees}
    node_trees.update(utils.list_by_key(node_groups, _operator.attrgetter('node_tree')))

    with node_utils.Material_Settings_Database() as settings_db:
            
        for node_tree, groups in node_trees.items():

            material_settings = None

            image_paths = [bl_utils.get_block_abspath(node.image) for node in node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
            image_paths = utils.deduplicate(image_paths)

            if not image_paths:
                operator.report({'INFO'}, f"No image was found in the material: {node_tree.name}")
                continue

            library = context.window_manager.at_asset_data # type: data.AssetData

            if any(library.is_sub_asset(path) for path in image_paths):
                asset = utils.get_most_common(library.get_asset_by_path(path) for path in image_paths) # type: data.Asset

                material_settings = asset.info.get("material_settings")
                if material_settings:
                    operator.report({'INFO'}, f"Settings were loaded for the library material: {node_tree.name}. ID: {asset.id}")
            
            if not material_settings:
                material_settings = settings_db.get(image_paths)
                if material_settings:
                    operator.report({'INFO'}, f"Settings were loaded from the database for the group: {node_tree.name}")

            if not material_settings:
                operator.report({'INFO'}, f"No settings were found for the material: {node_tree.name}")
                continue

            inputs = node_tree.inputs
            for key, value in material_settings.items():
                node_input = inputs.get(key)
                if node_input:
                    node_input.default_value = value

            default_settings = bl_utils.backward_compatibility_get(node_tree, ("at_default_settings", "ma_default_settings"))
            if default_settings:
                default_settings.update(material_settings)
            else:
                node_tree["at_default_settings"] = material_settings

            for group in groups:
                for input_index in range(len(group.inputs)):
                    group.inputs[input_index].default_value = node_tree.inputs[input_index].default_value

    return {'FINISHED'}


class ATOOL_OT_load_material_settings(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.load_material_settings"
    bl_label = "Load Material Settings"
    bl_description = "Load material settings for the selected AT material node group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        groups = get_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        return load_material_settings(self, context, node_groups = groups)


class ATOOL_OT_open_in_file_browser(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.open_in_file_browser"
    bl_label = "Open File Browser"
    bl_description = "Open the selected AT material or the selected image in a file browser"
	
    def execute(self, context):

        selected_nodes = context.selected_nodes

        if not selected_nodes:
            self.report({'INFO'}, "Nothing is selected.")
            return {'CANCELLED'}
        
        files = []
        
        def append(node: bpy.types.Node):
            
            if node.type == 'TEX_IMAGE' and node.image:
                path = bl_utils.get_block_abspath(node.image)
                
                if not os.path.exists(path):
                    
                    if node.image.packed_files:
                        self.report({'INFO'}, f"The image '{path}' of the node '{node.name}' is packed and does not have original at the path.")
                    else:
                        self.report({'INFO'}, f'No image exists in the path "{path}" for the node "{node.name}".')
                        
                    return
                
                files.append(path)
                
            elif node.type == 'GROUP':
                for node in node.node_tree.nodes:
                    append(node)
                
        for node in selected_nodes:
            append(node)

        if not files:
            self.report({'INFO'}, "The selected nodes do not reference images excising on a disk.")
            return {'CANCELLED'}

        files = utils.deduplicate(files)
        threading.Thread(target=utils.os_show, args=(self, files,)).start() 

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


def get_uv_scale_multiplier(context, object, uv = None, transform = True, triangulate = False):

    if object.data.is_editmode:
        bm = bmesh.from_edit_mesh(object.data).copy()
    else:
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

    uv_area = sum(area_tri(*(vert[uv_layer].uv for vert in face)) for face in bm.calc_loop_triangles())
    
    bm.free()
    
    return math.sqrt(mesh_area/uv_area)


register.property(
    'at_uv_multiplier', 
    bpy.props.FloatProperty(default = 1),
    bpy.types.Object
)


def set_uv_scale_multiplier(operator, context, objects = [], node_trees = {}, transform = True, triangulate = False):
    
    initial_active_object = context.object
    
    for object in objects:
        if object.type != 'MESH':
            
            override = bl_utils.get_context_copy_with_object(context, object)
            try:
                bpy.ops.object.convert(override, keep_original=True)
            except:
                operator.report({'INFO'}, f"The object '{object.name}' of type {object.type} is not supported.")
                continue
            
            converted_object = context.object
            multiplier = get_uv_scale_multiplier(context, converted_object, None, transform, triangulate)
            bpy.data.objects.remove(converted_object)
            object.select_set(True)
        else:
            
            if not (object.data and object.data.uv_layers):
                operator.report({'INFO'}, f"The object '{object.name}' has not uv layers.")
                continue
        
            multiplier = get_uv_scale_multiplier(context, object, None, transform, triangulate)
            
        object.at_uv_multiplier = multiplier
        object.update_tag()
        
    context.view_layer.objects.active = initial_active_object

    for node_tree, groups in node_trees.items():

        if not groups:
            continue

        node_tree = node_utils.Node_Tree_Wrapper(node_tree)

        for group in groups:
            if not isinstance(group, node_utils.Node_Wrapper):
                group = node_tree[group]

            if not "Global Scale" in group.inputs.keys():
                continue
            
            has_uv_multiplier = False

            input = group["Global Scale"]
            if input:
                for node in [input] + input.all_children:
                    if node.type == 'ATTRIBUTE' and node.attribute_type == 'OBJECT' and node.attribute_name == 'at_uv_multiplier':
                        has_uv_multiplier = True
                        break

            if has_uv_multiplier:
                continue
            
            attribute = node_utils.Material.get_uv_multiplier_attribute_node(node_tree)
            attribute.outputs['Fac'].join(group.i["Global Scale"])
            x, y = attribute.location
            attribute.location = (x, y - 2 *21.5)

    context.scene.frame_set(context.scene.frame_current) # update EEVEE viewport


class ATOOL_OT_set_uv_scale_multiplier(bpy.types.Operator):
    bl_idname = "atool.set_uv_scale_multiplier"
    bl_label = "Match World Scale"
    bl_description = "Match the active mesh UV scale to the world scale. See F9 redo panel for settings"
    bl_options = {'REGISTER', 'UNDO'}

    transform: bpy.props.BoolProperty(
        name="Apply Transforms",
        description="Apply the object's transforms",
        default = True
        )

    triangulate: bpy.props.BoolProperty(
        name="Triangulate",
        description="Triangulate the object geometry",
        default = False
        )

    only_selected: bpy.props.BoolProperty(
        name="Only Selected",
        description="Add UV multiplier inputs only to selected AT node groups.",
        default = False
        )

    def execute(self, context):

        object = context.space_data.id_from
        if not object:
            self.report({'INFO'}, "No object selected.")
            return {'CANCELLED'}

        selected_objects = context.selected_objects

        objects = selected_objects
        if object not in selected_objects:
            objects.append(object)

        groups = []
        if self.only_selected:
            groups = get_at_groups_from_selection(self, context)
        else:
            if context.space_data.edit_tree:
                groups = [node for node in context.space_data.edit_tree.nodes if is_atool_material(node)]

        node_trees = {context.space_data.edit_tree: groups}

        set_uv_scale_multiplier(self, context, objects, node_trees, self.transform, self.triangulate)

        self.report({'INFO'}, "UV matching is done.")
        return {'FINISHED'}
        


class ATOOL_PROP_import_config(bpy.types.PropertyGroup):

    a_for_albedo: bpy.props.BoolProperty(
        name="A For Albedo",
        description="Solve the ambiguity. The default is A for ambient occlusion",
        default = False
        )
    not_rgb_plus_alpha: bpy.props.BoolProperty(
        name="Not RGB + Alpha",
        description="An debug cases which excludes RGB+A type combinations. An example to solve: \"Wall_A_\" plus a single channel map name",
        default = False
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
        default = ""
        )
    use_ignore_by_format: bpy.props.BoolProperty(
        name="Ignore Format",
        description="Ignore bitmap by file format",
        default = False
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

    layout.prop(config, "a_for_albedo")
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

def get_definer_config(context) -> type_definer.Filter_Config:

    prop = context.window_manager.at_import_config
    
    config = type_definer.Filter_Config()

    config.is_rgb_plus_alpha = not prop.not_rgb_plus_alpha

    if prop.use_ignore_by_type:
        config.ignore_type.extend(prop.ignore_by_type.split(" "))
    if prop.use_ignore_by_format:
        config.ignore_format.extend(prop.ignore_by_format.split(" "))
    if prop.use_prefer_over:
        config.prefer_type.extend(tuple(pare.split("-")) for pare in prop.prefer_over.split(" "))
    if prop.a_for_albedo:
        config.custom["albedo"] = ["a"]

    return config

register.property(
    'at_import_config',
    bpy.props.PointerProperty(type=ATOOL_PROP_import_config)
)

def apply_dimensions(target, dimensions):
    node = None
    node_tree = None

    if target.bl_idname == "ShaderNodeGroup":
        node = target
        node_tree = target.node_tree
    elif target.bl_idname == "ShaderNodeTree":
        node_tree = target

    default_settings = bl_utils.backward_compatibility_get(node_tree, ("at_default_settings", "ma_default_settings"))

    for letter, name in (('x', "X Scale"), ('y', "Y Scale"), ('z', "Scale′")):
        value = dimensions.get(letter)
        if value:
            default_settings[name] = value
            node_tree.inputs[name].default_value = value
            if node:
                node.inputs[name].default_value = value




class Material_Import_Properties:

    use_groups: bpy.props.BoolProperty(
        name="Use Groups",
        description="Use material node groups",
        default = True
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

    is_y_minus_normal_map: bpy.props.BoolProperty(
        name="Y- Normal Map",
        description="Invert the green channel for DirectX style normal maps",
        default = False
        )
    load_settings: bpy.props.BoolProperty(
        name="Load Settings",
        description="Load the imported material's settings",
        default = True
        )

    ensure_adaptive_subdivision: bpy.props.BoolProperty(
        name="Use Displacement",
        description="Ensure adaptive subdivision setup for the active object",
        default = False
        )
    preview_dicing_rate: bpy.props.FloatProperty(
        name="Subdivision: Preview Dicing Rate",
        default = 1,
        soft_min=0.5,
        max=1000
        )
    offscreen_dicing_scale: bpy.props.FloatProperty(
        name="Subdivision: Offscreen Dicing Scale",
        default = 16,
        min=1
        )

    do_set_uv_scale_multiplier: bpy.props.BoolProperty(
        name="Match World Scale",
        description="Calculate and apply UV multiplier",
        default = True
        )
    uv_multiplier_transform: bpy.props.BoolProperty(
        name="UV Multiplier: Apply Transforms",
        description="Apply the object's transforms",
        default = True
        )
    uv_multiplier_triangulate: bpy.props.BoolProperty(
        name="UV Multiplier: Triangulate",
        description="Triangulate the object geometry",
        default = False
        )


    def draw_material_import(self, layout):     
        layout.alignment = 'LEFT'

        box = layout.box().column(align=True)
        box.prop(self, "use_groups")
        if self.use_groups:
            box.prop(self, "use_untiling")
            box.prop(self, "use_triplanar")
        layout.separator()
        
        layout.prop(self, "is_y_minus_normal_map")
        layout.prop(self, "load_settings")
        layout.separator()

        box = layout.box().column(align=True)
        box.prop(self, "ensure_adaptive_subdivision")
        if self.ensure_adaptive_subdivision:
            box.prop(self, "preview_dicing_rate")
            box.prop(self, "offscreen_dicing_scale")

        box = layout.box().column(align=True)
        box.prop(self, "do_set_uv_scale_multiplier")
        if self.do_set_uv_scale_multiplier:
            box.prop(self, "uv_multiplier_transform")
            box.prop(self, "uv_multiplier_triangulate")


class Modal_Material_Import(Material_Import_Properties):
    def __init__(self):
        
        self.image_paths: typing.List[str]
        self.asset: data.Asset = None
        
        self.images: typing.List[image_utils.Image] = None
        self.report_list: typing.List[typing.Tuple[str, str]]
        self.thread: threading.Thread
        
        self.dimensions: dict = None
        self.asset_name: str = None
        
        self.object: bl_utils.Reference = None
        self.material: bl_utils.Reference = None
        
    def set_asset(self, asset: data.Asset):
        self.asset = asset
        self.dimensions = {'x': 1, 'y': 1, 'z': 0.1}
        self.dimensions.update(self.asset.info["dimensions"])
        self.asset_name = self.asset.info.get("name")
        
    def set_object(self, object: bpy.types.Object):
        self.object = bl_utils.Reference(object)
        
    def set_material(self, material: bpy.types.Material):
        self.material = bl_utils.Reference(material)
        
    def set_targets_from_node_editor(self, context: bpy.types.Context):
        object = context.space_data.id_from
        if object:
            self.set_object(object)

        material = context.space_data.id
        if material:
            self.set_material(material)
            
    def get_targets(self) -> typing.Tuple[bpy.types.Object, bpy.types.Material]:
        
        if self.object:
            object = self.object.get()
        else:
            object = None
            
        if self.material:
            material = self.material.get()
        else:
            material = None
            
        return object, material
    
    def start_images_preload(self, context: bpy.types.Context):
        
        config = get_definer_config(context)
        config.set_common_prefix_from_paths(self.image_paths)
        
        def job():
            
            def pre_process(images: typing.List[image_utils.Image]):
                no_height = "displacement" not in set(itertools.chain.from_iterable([image.type for image in images]))
                
                for image in images:
                    image.pre_process(no_height = no_height)
                    image.update_source()
                    
                if self.asset:
                    self.asset.update_info()
                
            if self.asset:
                images = [image_utils.Image.from_asset_info(image, self.asset.info, config) for image in self.image_paths]
                images, report_list = type_definer.filter_by_config(images, config)
                pre_process(images)
            else:
                with image_utils.Image_Cache_Database() as db:
                    images = [image_utils.Image.from_db(image, db, config) for image in self.image_paths]
                    images, report_list = type_definer.filter_by_config(images, config)
                    pre_process(images)
                    
            self.images = images
            self.report_list = report_list
        
        self.thread = threading.Thread(target=job, args=())
        self.thread.start()
        
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):

        if event.type != 'TIMER' or self.thread.is_alive():
            return {'PASS_THROUGH'}

        if self.images == None:
            self.report({"ERROR"}, "The type definer failed. See the console for the error.")
            return {'CANCELLED'}

        for report in self.report_list:
            self.report(*report)

        if not self.images:
            self.report({"INFO"}, "All the images were excluded.")
            return {'FINISHED'}

        return self.apply_material(context)

    
    def apply_material(self, context: bpy.types.Context):
        
        for image in self.images:
            image.data_block = bpy.data.images.load(filepath = image.path, check_existing=True)
            image.set_bl_props(image.data_block)
        
        object, target_material = self.get_targets()

        if not self.use_groups:
            
            new_material = node_utils.Material.from_image_objects(self.images)
            if target_material:
                new_material.target_material = target_material
            new_material.is_y_minus_normal_map = self.is_y_minus_normal_map
            new_material.set_viewport_colors(new_material.bl_material)
            
            material = new_material.bl_material
            
            if self.asset:
                new_material.asset = self.asset
        
            if self.ensure_adaptive_subdivision:
                new_material.set_displacement_from_image()
                ensure_adaptive_subdivision(self, context, object, material)
                
            if self.do_set_uv_scale_multiplier:
                new_material.set_uv_scale_multiplier(new_material.generated_image_nodes)
                set_uv_scale_multiplier(self, context, (object,), {}, self.uv_multiplier_transform, self.uv_multiplier_triangulate)

            if not (object and object.data and hasattr(object.data, "materials")):
                self.report({'INFO'}, "The material was added as a data block.")
                return {'FINISHED'}
            
            if target_material:
                return {'FINISHED'}

            if not object.data.materials:
                object.data.materials.append(material)
                return {'FINISHED'}

            if object.active_material == None:
                object.active_material = material
                return {'FINISHED'}

            took_an_empty_slot = False
            for index, slot in enumerate(object.data.materials):
                if slot == None:
                    object.data.materials[index] = material
                    took_an_empty_slot = True
                    break

            if not took_an_empty_slot:
                object.data.materials.append(material)
            
            object.active_material_index = len(object.data.materials) - 1
            # object.active_material = material

            return {'FINISHED'}


        material_type = M_BASE
        if self.use_triplanar:
            material_type += M_TRIPLANAR
        if self.use_untiling:
            material_type += M_UNTILING
            
        node_tree = node_utils.Material_Node_Tree.new(type = material_type)
        node_tree.images = self.images
        node_tree.operator = self
        
        bl_node_tree = node_tree.bl_node_tree
        
        material_name = self.asset_name if self.asset_name else "M_" + utils.get_longest_substring([image.name for image in self.images]).strip(" ").rstrip(" _-")
        bl_node_tree.name = material_name

        if self.asset:
            bl_node_tree["atool_id"] = self.asset.id

        if self.load_settings:
            load_material_settings(self, context, node_trees = [bl_node_tree])
            
        node_tree.set_ratio()
        node_tree.set_displacement()

        if self.dimensions:
            apply_dimensions(bl_node_tree, self.dimensions)

        if not (object and object.data and hasattr(object.data, "materials")):
            self.report({'INFO'}, "The material was added as a node group.")
            return {'FINISHED'}

        material_output = None

        if target_material:
            node_group = target_material.node_tree.nodes.new( type = 'ShaderNodeGroup' )
            node_group.node_tree = bl_node_tree
            node_group.name = node_group.node_tree.name

            node_group.width = 300
            node_group.show_options = False

            material_node_tree = node_utils.Node_Tree_Wrapper(target_material.node_tree)
            output = material_node_tree.output
            node_group = material_node_tree[node_group]

            principled_node = material_node_tree.find_principled()   
            if principled_node:
                node_group.location = principled_node.location - mathutils.Vector((400, 0))

                for input in principled_node.inputs:
                    socket = node_group.outputs.get(input.identifier)
                    if socket:
                        socket.join(input, move = False)

                if output:
                    for node in node_group.all_parents:
                        if node.type == 'OUTPUT_MATERIAL':
                            material_output = node
                            break

        else:
            material = bpy.data.materials.new(name = bl_node_tree.name)
            material.use_nodes = True

            if not object.data.materials:
                object.data.materials.append(material)
            else:
                object.active_material = material
            
            material_node_tree = node_utils.Node_Tree_Wrapper(material.node_tree)
            principled_node = material_node_tree.get_by_type('BSDF_PRINCIPLED')[0]

            node_group = material_node_tree.new('ShaderNodeGroup')
            node_group.node_tree = bl_node_tree
            node_group.name = bl_node_tree.name
            node_group.width = 300
            node_group.show_options = False
        
            node_group.location = principled_node.location - mathutils.Vector((400, 0))

            for input in principled_node.inputs:
                socket = node_group.outputs.get(input.identifier)
                if socket:
                    socket.join(input, move = False)

            target_material = material

        node_tree.set_viewport_colors(target_material)

        if self.ensure_adaptive_subdivision:
            ensure_adaptive_subdivision(self, context, object, target_material, material_output)

        if self.do_set_uv_scale_multiplier:
            set_uv_scale_multiplier(self, context, (object,), {target_material.node_tree: (node_group,)}, self.uv_multiplier_transform, self.uv_multiplier_triangulate)

        return {'FINISHED'}



class ATOOL_OT_apply_material(bpy.types.Operator, ImportHelper, Modal_Material_Import):
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
        layout.separator()
        box = layout.box().column(align=True, heading='Import Config:')
        draw_import_config(context, box)

    def execute(self, context: bpy.types.Context):
        
        if self.files[0].name == "":
            self.report({'INFO'}, "No files selected.")
            return {'CANCELLED'}
        self.image_paths = [os.path.join(self.directory, file.name) for file in self.files]
          
        self.set_targets_from_node_editor(context)
        self.start_images_preload(context)
        return {'RUNNING_MODAL'}


class ATOOL_OT_convert_material(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.convert_material"
    bl_label = "Convert To"
    bl_description = "Convert the selected AT material node group"
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

        if not get_at_groups_from_selection(self, context):
            return {'CANCELLED'}
            
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def execute(self, context):

        groups = get_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        node_trees = utils.list_by_key(groups, _operator.attrgetter('node_tree'))

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
                
            node_tree = node_utils.Material_Node_Tree.new(type)
            node_tree.images = self.images
            node_tree.operator = self
            bl_node_tree = node_tree.bl_node_tree
            node_tree = bl_node_tree

            default_settings = bl_utils.backward_compatibility_get(initial_node_tree, ("at_default_settings", "ma_default_settings"))
            if not default_settings:
                set_default_settings(self, context, groups)
                default_settings = initial_node_tree["at_default_settings"]
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


class ATOOL_OT_replace_material(bpy.types.Operator, Shader_Editor_Poll, Modal_Material_Import):
    bl_idname = "atool.replace_material"
    bl_label = "Replace"
    bl_description = "Replace the selected AT material node group with the active browser material"
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
        
        groups = get_at_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        origin = context.space_data.id
        if origin.node_tree != context.space_data.edit_tree:
            origin = context.space_data.edit_tree

        self.targets = [bl_utils.Reference(group, origin) for group in groups]

        from . import view_3d_operator
        asset = view_3d_operator.get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
        
        self.image_paths = asset.get_images()
        if not self.image_paths:
            self.report({'INFO'}, "Nothing to import.")
            return {'CANCELLED'}

        self.set_asset(asset)
        self.start_images_preload(context)
        self.apply_material = self.execute
        return {'RUNNING_MODAL'}

    def execute(self, context):

        groups = [target.get() for target in self.targets] 
        
        if not groups:
            self.report({"INFO"}, "All targets were deleted.")
            return {'CANCELLED'}

        for image in self.images:
            image.data_block = bpy.data.images.load(filepath = image.path, check_existing=True)
            image.set_bl_props(image.data_block)

        def get_type(group):
            type = bl_utils.backward_compatibility_get(group.node_tree, ("at_type", "ma_type"))
            if not type:
                type = 2
            return type

        types = utils.list_by_key(groups, get_type) # type: typing.Dict[int, typing.List[bpy.types.ShaderNodeGroup]]
        
        node_trees = utils.deduplicate([group.node_tree for group in groups])

        for type, groups in types.items():
            
            node_tree = node_utils.Material_Node_Tree.new(type = MAT_TYPES[type])
            node_tree.images = self.images
            node_tree.operator = self
            generated_material_name = node_tree.name
            bl_node_tree = node_tree.bl_node_tree
            
            node_tree_wrapper = node_tree
            node_tree = bl_node_tree
            node_tree.name = self.asset_name if self.asset_name else generated_material_name

            if self.asset:
                node_tree["atool_id"] = self.asset.id

            if self.load_settings:
                load_material_settings(self, context, node_trees = [node_tree])
                
            node_tree_wrapper.set_ratio()
            node_tree_wrapper.set_displacement()

            if self.dimensions:
                apply_dimensions(node_tree, self.dimensions)

            if self.replace_all_users:
                for old_node_tree in utils.deduplicate([group.node_tree for group in groups]):
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
                    self.report({'INFO'}, f"'{group.node_tree.name}' node tree of '{group.name}' group was replaced with '{node_tree.name}'")
                    group.node_tree = node_tree
                    

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


class ATOOL_OT_material_from_selected(bpy.types.Operator, Shader_Editor_Poll, Modal_Material_Import):
    bl_idname = "atool.material_from_selected"
    bl_label = "From Selection"
    bl_description = "Construct a material from selected texture nodes"
    bl_options = {'REGISTER', 'UNDO'}

    # delete_used_nodes: bpy.props.BoolProperty(
    #     name="Delete Used",
    #     description="Delete the used texture node",
    #     default = False
    #     )
    
    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'

        self.draw_material_import(layout)
        
    def invoke(self, context, event):
        
        selected_nodes = context.selected_nodes

        if not selected_nodes:
            self.report({'INFO'}, "Nothing is selected. Select texture nodes.")
            return {'CANCELLED'}

        texture_nodes = [node for node in selected_nodes if node.bl_idname == 'ShaderNodeTexImage' and node.image and node.image.source == 'FILE' and os.path.exists(bl_utils.get_block_abspath(node.image))]

        if not texture_nodes:
            self.report({'INFO'}, "No texture node with image.")
            return {'CANCELLED'}
        
        self.image_paths = [bl_utils.get_block_abspath(node.image) for node in texture_nodes]
        self.set_targets_from_node_editor(context)

        self.start_images_preload(context)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        self.apply_material(context)
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

    def invoke(self, context, event):
        context.window_manager.invoke_props_popup(self, event)
        return self.execute(context)

    def execute(self, context):
        groups = get_groups_from_selection(self, context)
        if not groups:
            return {'CANCELLED'}

        edit_tree = context.space_data.edit_tree
        node_tree = node_utils.Node_Tree_Wrapper(edit_tree)
        added_nodes: typing.List[bpy.types.Node] = []
        
        for group in groups:
            group = node_tree[group]
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
            node_tree = node_utils.Node_Tree_Wrapper(context.space_data.edit_tree)
            added_nodes = [node_tree[node] for node in added_nodes] # type: typing.List[node_utils.Node_Wrapper]
            for node in added_nodes:
                output = node.outputs[0]
                output_type = output.type
                if node.type == 'COMBXYZ':
                    default_value = (node.i["X"].default_value, node.i["Y"].default_value, node.i["Z"].default_value)
                    convert = {
                        'VALUE': sum(default_value)/3,
                        'RGBA': (*default_value, 1), # not possible
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

        o = node_utils.Node_Tree_Wrapper(node_tree).output

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


class ATOOL_OT_bake_active_node(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.bake_active_node"
    bl_label = "Bake Active"
    bl_description = "WORK IN PROGRESS. Bake the active node output to texture"
    bl_options = {'REGISTER', 'UNDO'}
    
    is_data: bpy.props.BoolProperty(
        name="Is Data",
        description="Create image with non-color data color space",
        default = False
        )
    
    width: bpy.props.IntProperty(
        name="X Resolution",
        description="Width of the image",
        default = 1024
        )

    height: bpy.props.IntProperty(
        name="Y Resolution",
        description="Height of the image",
        default = 1024
        )

    modifiers_as_in_viewport: bpy.props.BoolProperty(
        name="Modifiers As In Viewport",
        description="Bake with modifiers that are visible in the viewport.",
        default = True
        )

    turn_off_modifiers: bpy.props.BoolProperty(
        name="Turn Off Vertex Changing Modifiers",
        description="Turn off the vertex changing modifiers for render.",
        default = True
        )

    bake_with_applied_modifiers: bpy.props.BoolProperty(
        name="Bake With Applied Modifiers",
        description="Bake using a copy with applied modelers.",
        default = False
        )
    
    def invoke(self, context, event):

        self.edit_tree = context.space_data.edit_tree
        self.node_tree = context.space_data.node_tree
        
        if not(self.edit_tree and self.node_tree):
            self.report({'INFO'}, "Select a material.")
            return {'CANCELLED'}
        
        if self.edit_tree != self.node_tree:
            self.report({'INFO'}, "Only the base level nodes are allowed.")
            return {'CANCELLED'}
        
        self.selected_nodes = context.selected_nodes
        if not self.selected_nodes:
            self.report({'INFO'}, "Select a node.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width = 200)

    def execute(self, context: bpy.context):
        
        object = context.space_data.id_from # type: bpy.types.Object
        material = context.space_data.id

        if self.modifiers_as_in_viewport:
            init_modifiers: typing.List[dict] = []
            for modifier in object.modifiers:

                init_modifiers.append({
                    'modifier': modifier,
                    'show_render': modifier.show_render,
                    'show_viewport': modifier.show_viewport
                })

                modifier.show_render = modifier.show_viewport

        if self.turn_off_modifiers:
            turned_off_modifiers = []
            for modifier in object.modifiers:

                if not modifier.show_render:
                    continue

                if not modifier.type in bl_utils.VERTEX_CHANGING_MODIFIER_TYPES:
                    continue

                modifier.show_render = False
                turned_off_modifiers.append(modifier)

        if self.bake_with_applied_modifiers:

            inti_mode = context.object.mode
            bpy.ops.object.mode_set(mode='OBJECT')

            override = bl_utils.get_context_copy_with_object(context, object)
            try:
                bpy.ops.object.convert(override, keep_original=True)
            except:
                self.report({'INFO'}, f"The object '{object.name}' of type {object.type} is not supported.")
                return {'CANCELLED'}
                
            orig_object = object
            object = context.object
        
        node_tree = node_utils.Node_Tree_Wrapper(self.node_tree)
        active_node = node_tree[self.selected_nodes[0]]
        
        image_node = node_tree.new('ShaderNodeTexImage')
        x, y = active_node.location
        image_node.location = x + 200, y
        
        import uuid
        image = bpy.data.images.new(str(uuid.uuid1()), width=self.width, height=self.height, float_buffer=True, is_data=self.is_data)
        if not self.is_data:
            image.colorspace_settings.name = 'sRGB'
        
        image_node.image = image
        image_node.select = True
        node_tree.nodes.active = image_node.__data__
        
        with node_utils.Output_Override(material, node_tree.output, active_node.outputs[0]), \
            node_utils.Isolate_Object_Render(object):
            
            initial_cycles_samples = context.scene.cycles.samples
            context.scene.cycles.samples = 1
            initial_engine = context.scene.render.engine
            context.scene.render.engine = 'CYCLES'
            
            override = bl_utils.get_context_copy_with_object(context, object)
            bpy.ops.object.bake(override, type='EMIT')
            
            context.scene.render.engine = initial_engine
            context.scene.cycles.samples = initial_cycles_samples

        if self.bake_with_applied_modifiers:
            bpy.data.objects.remove(object)
            context.view_layer.objects.active = orig_object
            bpy.ops.object.mode_set(mode = inti_mode)

        if self.turn_off_modifiers:
            for modifier in turned_off_modifiers:
                modifier.show_render = True

        if self.modifiers_as_in_viewport:
            for modifier in init_modifiers:
                modifier['modifier'].show_render = modifier['show_render']
            
        return {'FINISHED'}
    

class ATOOL_OT_arrange_nodes_by_name_length(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.arrange_nodes_by_name"
    bl_label = "Arrange By File Name"
    bl_description = "Arrange image nodes by longest file name substrings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        
        edit_tree = context.space_data.edit_tree
        node_tree = context.space_data.node_tree
        
        if not(edit_tree and node_tree):
            self.report({'INFO'}, "Select a material.")
            return {'CANCELLED'}
        
        selected_nodes = [node for node in context.selected_nodes if node.bl_idname == 'ShaderNodeTexImage']
        if not selected_nodes:
            self.report({'INFO'}, "Select images nodes.")
            return {'CANCELLED'}
        
        substring_cache = {}
        def get_substring(a, b):
            
            key = frozenset((a, b))
            
            substring = substring_cache.get(key)
            if substring != None:
                return substring
            
            if not (a.image and b.image):
                substring_cache[key] = ""
                return ""
            
            if not (a.image.filepath and b.image.filepath):
                substring_cache[key] = ""
                return ""
            
            name_a = os.path.basename(bl_utils.get_block_abspath(a.image))
            name_b = os.path.basename(bl_utils.get_block_abspath(b.image))
            substring = utils.get_longest_substring((name_a, name_b))
            substring_cache[key] = substring
            
            return substring
             
        groups = {}   
        for node in selected_nodes:
            
            substrings = []
            for other_node in selected_nodes:
                
                if other_node == node:
                    continue
                
                substrings.append(get_substring(node, other_node))
            
            if substrings:
                key = max(substrings, key=len)
            else:
                key = ''
            
            group = groups.get(key)
            if group:
                group.append(node)
            else:
                groups[key] = [node]
        
        origin_x = 0
        origin_y = 0
        for node in selected_nodes:
            x, y = node.location
            origin_x += x
            origin_y += y
        
        origin_x /= len(selected_nodes)
        origin_y /= len(selected_nodes)
        
        for index_group, group in enumerate(groups.values()):
            for index_node, node in enumerate(group):
                node.location = (origin_x + index_group * 300, origin_y - index_node * 300)
        
        return {'FINISHED'}
    
    
    
class ATOOL_OT_override_linked_material(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "atool.override_linked_material"
    bl_label = "Make Local"
    bl_description = "WIP. Use the Redo F9 panel. Supposed to do: Override the active linked material, but makes local instated. https://developer.blender.org/T73318"
    bl_options = {'REGISTER', 'UNDO'}
    
    override_for: bpy.props.EnumProperty(
        name = 'Override For',
        items = [
            ('active_slot', 'Active Slot', 'Only for active material slot'),
            ('active_object', 'Active Object', 'Only for selected object material slots'),
            ('selected', 'Selected Objects', 'For all selected objects material slots'),
            ('all', 'Scene Objects', 'For all scene object material slots')
        ],
        default = 'selected')
    
    def invoke(self, context, event):
        edit_tree = context.space_data.edit_tree
        node_tree = context.space_data.node_tree
        
        if not(edit_tree and node_tree):
            self.report({'INFO'}, "Select a material.")
            return {'CANCELLED'}
        
        if edit_tree != node_tree:
            self.report({'INFO'}, "Only a material for now.")
            
        context_object = context.space_data.id_from
        context_material = context.space_data.id
        
        if context_material.override_library:
            self.report({'INFO'}, "The material is already overridden.")
            return {'CANCELLED'}
        
        if not context_material.library:
            self.report({'INFO'}, "The material is not linked.")
            return {'CANCELLED'}
        
        self.context_object = bl_utils.Reference(context_object)
        self.context_material = bl_utils.Reference(context_material)

        context.window_manager.invoke_props_popup(self, event)
        return self.execute(context) 

    def execute(self, context: bpy.types.Context):
        
        context_object = self.context_object.get()
        context_material = self.context_material.get()

        jobs: typing.Dict[bpy.types.Object, typing.List[int]] = {}
        
        def get_slot_indexes(object: bpy.types.Object, material: bpy.types.Material):
            return [index for index, material_slot in enumerate(object.material_slots) if material_slot.material == material]
        
        if self.override_for == 'active_slot':
            active_material_slot = context_object.material_slots[context_object.active_material_index]
            if context_material != active_material_slot.material:
                self.report({'INFO'}, "The active material slot of the object does not hold the material your are trying to override. Try to unpin material from the shader editor")
                return {'CANCELLED'}
            jobs[context_object] = [context_object.active_material_index]
        elif self.override_for == 'active_object':
            jobs[context_object] = get_slot_indexes(context_object, context_material)
        elif self.override_for == 'selected':
            for object in context.selected_objects:
                jobs[object] = get_slot_indexes(object, context_material)
        elif self.override_for == 'all':
            for object in bpy.data.objects:
                if object.override_library or not object.library:
                    jobs[object] = get_slot_indexes(object, context_material)
        
        override = bl_utils.get_context_copy_with_objects( context, context_object, utils.deduplicate(list(jobs.keys())) )
        bpy.ops.object.make_local(override, type='SELECT_OBJECT')
        
        first_override = True
        for object, slot_indexes in jobs.items():
            
            # object.make_local() does not work
            
            for material_slot in object.material_slots:
                    if not material_slot.link == 'OBJECT':
                        material = material_slot.material
                        material_slot.link = 'OBJECT'
                        material_slot.material = material
            
            for index in slot_indexes:
                material_slot = object.material_slots[index]
                material_to_override = material_slot.material
                                
                if first_override:
                    material_slot.material = material_to_override.make_local()
                    overridden_material = material_slot.material
                    overridden_material.use_fake_user = True
                    first_override = False
                else: 
                    material_slot.material = overridden_material
        
        return {'FINISHED'}