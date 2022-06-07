import math

import bpy

from . import bl_utils
from . import utils

register = bl_utils.Register(globals())

class Poll:
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'VIEW_3D' and context.mode == 'POSE'

class ATOOL_OT_select_action(bpy.types.Operator, Poll):
    bl_idname = "atool.select_action"
    bl_label = "Select Action"
    bl_description = "Select the action and set the animation preview range."

    action_name: bpy.props.StringProperty()

    def execute(self, context):

        init_use_keyframe_insert_auto = context.scene.tool_settings.use_keyframe_insert_auto
        context.scene.tool_settings.use_keyframe_insert_auto = False

        action = bpy.data.actions.get(self.action_name)

        context.object.animation_data.action = action

        start, end = action.frame_range
        context.scene.use_preview_range = True
        context.scene.frame_preview_start = int(start)
        context.scene.frame_preview_end = int(end)

        bpy.ops.pose.transforms_clear()
        bpy.ops.pose.select_all(action='INVERT')
        bpy.ops.pose.transforms_clear()
        bpy.ops.pose.select_all(action='INVERT')

        context.scene.tool_settings.use_keyframe_insert_auto = init_use_keyframe_insert_auto

        return {'FINISHED'}


class ATOOL_PT_action_selector(bpy.types.Panel):
    bl_idname = "ATOOL_PT_action_selector"
    bl_label = "Action Selector"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = ".posemode"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: bpy.context):

        column = self.layout.column()

        pose_object = context.pose_object
        column.label(text = "Armature: " + str(pose_object.name))

        animation_data = pose_object.animation_data
        if not animation_data:
            column.label(text = "No actions.")
            return

        actions = [strip.action for track in animation_data.nla_tracks for strip in track.strips]
        if not actions:
            column.label(text = "No actions.")
            return

        actions = utils.deduplicate(actions)
        actions.sort(key = lambda action: action.name)
                
        for action in actions:
            column.operator("atool.select_action", text = str(action.name)).action_name = action.name