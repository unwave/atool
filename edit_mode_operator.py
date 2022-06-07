import math

import bpy

from . import bl_utils

register = bl_utils.Register(globals())


class Edit_Mod_Poll:
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'VIEW_3D' and context.mode == 'EDIT_MESH'

class ATOOL_OT_triangulate_ngons(bpy.types.Operator, Edit_Mod_Poll):
    bl_idname = "atool.triangulate_ngons"
    bl_label = "Triangulate Ngons"
    bl_description = "Triangulate n-gons with 5+ edges"

    def execute(self, context): # redo with bmesh
        bpy.ops.object.mode_set(mode='OBJECT')
        object = bpy.context.object

        modifier = object.modifiers.new(name = "__temp__", type='TRIANGULATE')
        modifier.min_vertices = 5
        modifier.quad_method = 'BEAUTY'
        bpy.ops.object.modifier_apply(modifier=modifier.name)

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.tris_convert_to_quads(face_threshold=math.pi, shape_threshold=math.pi)
        bpy.ops.mesh.select_all(action='DESELECT')

        return {'FINISHED'}


class ATOOL_PT_edit_mode(bpy.types.Panel):
    bl_idname = "ATOOL_PT_edit_mode"
    bl_label = "Tools"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "mesh_edit"

    def draw(self, context):

        column = self.layout.column()
        subcolumn = column.column(align=True)
        subcolumn.operator("atool.triangulate_ngons")