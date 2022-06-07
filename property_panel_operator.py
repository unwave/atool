# import typing

import bpy
import mathutils

from . import bl_utils
register = bl_utils.Register(globals())

class Property_Panel_Poll:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "output"

    @classmethod
    def poll(cls, context):
        return context.engine in cls.COMPAT_ENGINES


class ATOOL_PT_default_world(Property_Panel_Poll, bpy.types.Panel):
    bl_label = "Atool"
    bl_context = "world"
    bl_options = {'DEFAULT_CLOSED'}
    COMPAT_ENGINES = {'CYCLES', 'BLENDER_EEVEE'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        wm = context.window_manager

        col = layout.column(align=True)
        operator = col.operator("atool.set_world")
        operator.engine = context.scene.render.engine


def get_cycles_world():
    world = bpy.data.worlds.new(name='Default')
    world.use_nodes = True
    nodes = world.node_tree.nodes
    background = [node for node in nodes if node.type == 'BACKGROUND'][0]
    sky = nodes.new('ShaderNodeTexSky')
    sky.sun_rotation = 2
    sky.sun_elevation = 0.7854
    world.node_tree.links.new(sky.outputs[0], background.inputs[0])
    return world

def get_eevee_world():
    world = bpy.data.worlds.new(name='Default')
    world.use_nodes = True
    nodes = world.node_tree.nodes
    background = [node for node in nodes if node.type == 'BACKGROUND'][0]
    sky = nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'HOSEK_WILKIE'
    sky.sun_direction
    world.node_tree.links.new(sky.outputs[0], background.inputs[0])
    return world

class ATOOL_OT_set_world(bpy.types.Operator):
    bl_idname = "atool.set_world"
    bl_label = "Cycles World"
    bl_description = "Set a deafult world"
    bl_options = {'REGISTER', 'UNDO'}
    
    # engine: bpy.props.EnumProperty(
    #     items = [
    #         ('BLENDER_EEVEE', 'EEVEE', ''),
    #         ('CYCLES', 'Cycles', '')
    #     ],
    #     default = 'CYCLES'
    # )

    def execute(self, context: bpy.types.Context):
        scene = context.scene

        # if self.engine == 'CYCLES':
        scene.view_settings.exposure = -3.5
        scene.view_settings.view_transform = 'Filmic'
        scene.view_settings.look = 'Medium Contrast'
        scene.world = get_cycles_world()
        # elif self.engine == 'BLENDER_EEVEE':
            # scene.world = get_eevee_world()

        return {'FINISHED'}
    

class ATOOL_OT_add_camera_visibility_vertex_group(bpy.types.Operator):
    bl_idname = "atool.add_camera_visibility_vertex_group"
    bl_label = "Camera Visibility Vertex Group"
    bl_description = "Add a camera visibility vertex group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.context):

        camera_object = context.scene.camera
        if not camera_object:
            self.report({'INFO'}, "Set a camera.")
            return {'CANCELLED'}

        camera_data = camera_object.data

        object = context.object
        if object.type != 'MESH' or not object.data:
            self.report({'INFO'}, f"Select a mesh object.")
            return {'CANCELLED'}

        initial_mode = context.object.mode
        bpy.ops.object.mode_set(mode='OBJECT')

        turned_off_modifiers = []
        for modifier in object.modifiers:
            if modifier.show_viewport and modifier.type in bl_utils.VERTEX_CHANGING_MODIFIER_TYPES:
                modifier.show_viewport = False
                turned_off_modifiers.append(modifier)

        camera_translation, camera_rotation, camera_scale = camera_object.matrix_world.decompose()

        vectors = [mathutils.Vector(vector) for vector in camera_data.view_frame(scene = context.scene)]
        camera_plane_normals = [camera_rotation @ vectors[index].cross(vectors[index + 1]) for index in range(-2, 2)]

        object_matrix_world = object.matrix_world

        all_ver_indexes = range(len(object.data.vertices))

        vertex_group = object.vertex_groups.get('camera_visibility')
        if not vertex_group:
            vertex_group = object.vertex_groups.new(name='camera_visibility')
        vertex_group.add(all_ver_indexes, 1, 'REPLACE')

        depsgraph = context.evaluated_depsgraph_get()
        object = object.evaluated_get(depsgraph)
        #mesh = object.to_mesh(preserve_all_data_layers = True, depsgraph = depsgraph)
        mesh = object.data
        
        origin = object_matrix_world.inverted() @ camera_translation
        hit_vertices = []
        for vertex in mesh.vertices:

            target = vertex.co
        
            if any(normal.dot(object_matrix_world @ target - camera_translation) < 0 for normal in camera_plane_normals):
                continue
            
            result, location, normal, index = object.ray_cast(origin, target - origin)
            
            if result and (location - target).length <= 0.0001:
                hit_vertices.append(vertex.index)
                
        vert_to_poly = {index: [] for index in all_ver_indexes}
        for p in mesh.polygons:
            for v in p.vertices:
                vert_to_poly[v].append(p)
        
        final_vert_indexes = []
        for hit_vert in hit_vertices:
            for poly in vert_to_poly[hit_vert]:
                final_vert_indexes.extend(poly.vertices)

        vertex_group.add(all_ver_indexes, 0, 'REPLACE')
        vertex_group.add(final_vert_indexes, 1, 'REPLACE')

        for modifier in turned_off_modifiers:
            modifier.show_viewport = True

        bpy.ops.object.mode_set(mode=initial_mode)

        return {'FINISHED'}


class ATOOL_OT_mix_vertex_groups(bpy.types.Operator):
    bl_idname = "atool.mix_vertex_groups"
    bl_label = "Mix Vertex Groups"
    bl_description = "Mix vertex groups with the modifier"
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.StringProperty()
    source: bpy.props.StringProperty()
    do_apply: bpy.props.BoolProperty(default = True)
    operation: bpy.props.EnumProperty(items = [
        ('SUB', "Subtract", "", 1),
        ('MUL', "Multiply", "", 2),
    ], name = 'Operation')

    def invoke(self, context, event):
        self.target = context.object.vertex_groups.active.name
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop_search(self, "target", context.object, "vertex_groups", text = 'Target')
        layout.prop_search(self, "source", context.object, "vertex_groups", text = 'Source')
        layout.prop(self, "do_apply", text = 'Apply Modifier')
        layout.prop(self, "operation")

    def execute(self, context):

        if not self.target:
            self.report({'INFO'}, 'Specify the target')
            return {'CANCELLED'}

        if not self.source:
            self.report({'INFO'}, 'Specify the source')
            return {'CANCELLED'}

        object = context.object

        modifier = object.modifiers.new(name = self.target, type='VERTEX_WEIGHT_MIX')
        modifier.mix_mode = self.operation
        modifier.vertex_group_a = self.target
        modifier.vertex_group_b = self.source
        modifier.mix_set = 'A'

        modifier_index = len(object.modifiers) - 1
        while 1:
            
            if modifier_index == 0:
                break

            if object.modifiers[modifier_index - 1].type == 'VERTEX_WEIGHT_MIX':
                break

            bpy.ops.object.modifier_move_up(modifier = modifier.name)
            modifier_index -= 1

        if self.do_apply:
            bpy.ops.object.modifier_apply(modifier = modifier.name)

        return {'FINISHED'}


def vertex_group_menu(self, context):
    layout = self.layout # type: bpy.types.UILayout
    
    column = layout.column(align=True)
    column.separator()
    column.operator("atool.add_camera_visibility_vertex_group")

    column = layout.column(align=True)
    column.enabled = bool(context.object) and bool(context.object.vertex_groups)
    column.separator()
    column.operator("atool.mix_vertex_groups")

register.menu_item(bpy.types.MESH_MT_vertex_group_context_menu, vertex_group_menu)