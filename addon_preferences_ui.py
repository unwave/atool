import bpy
from . import addon_updater_ops

class ATOOL_PT_addon_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    library_path: bpy.props.StringProperty(
        name="Library",
        subtype='FILE_PATH',
        description="A path to a library folder"
    )
    auto_path: bpy.props.StringProperty(
        name="Auto",
        subtype='FILE_PATH',
        description="A path to folder to be autoprocessed on the startup"
    )

    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=False,
        )
    updater_intrval_months: bpy.props.IntProperty(
        name='Months',
        description="Number of months between checking for updates",
        default=0,
        min=0
        )
    updater_intrval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
        max=31
        )
    updater_intrval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
        )
    updater_intrval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "library_path")
        layout.prop(self, "auto_path")
        layout.operator('atool.data_paths')
        addon_updater_ops.update_settings_ui(self,context)


class ATOOL_OT_update_data_paths(bpy.types.Operator):
    bl_idname = 'atool.data_paths'
    bl_label = 'Update'
    bl_options = {"REGISTER", "UNDO"}
 
    def execute(self, context):

        asset_data = context.window_manager.at_asset_data

        addon_preferences = context.preferences.addons[__package__].preferences

        asset_data.library = addon_preferences.library_path
        asset_data.auto = addon_preferences.auto_path

        asset_data.update()

        return {"FINISHED"}