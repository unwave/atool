import bpy

class ATOOL_PT_tools(bpy.types.Panel):
    bl_idname = "ATOOL_PT_tools"
    bl_label = "Tools"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = "UI"
    bl_category = "AT"

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'

    def draw(self, context):
        
        layout = self.layout

        column = layout.column()

        subcolumn = column.column(align=True)
        subcolumn.operator("atool.apply_material", text = "Import From", icon='ADD')
        subcolumn.operator("atool.convert_material", text = "Convert", icon='MODIFIER')
        subcolumn.operator("atool.replace_material", text = "Replace", icon='PASTEFLIPDOWN')
        column.separator()

        column.operator("atool.make_material_links", text = "Link", icon='DRIVER')
        column.separator()

        subcolumn = column.column(align=True)
        subcolumn.operator("atool.add_height_blend", text = "Height Blend", icon='RNDCURVE')
        subcolumn.operator("atool.add_detail_blend", text = "Detail Blend", icon='MOD_UVPROJECT')
        column.separator()

        column.operator("atool.normalize_height_range", text = "Normalize Image", icon='SEQ_HISTOGRAM')
        column.operator("atool.ensure_adaptive_subdivision", text = "Ensure Adaptive Subdivision", icon='MOD_NOISE')
        column.operator("atool.set_uv_scale_multiplier", icon='UV_DATA')
        column.operator("atool.to_pbr", icon='MATERIAL_DATA')
        column.operator("atool.ungroup")
        column.separator()

        column.operator("atool.open_in_file_browser", text = "Open File Browser", icon='FILEBROWSER')
        column.operator("atool.append_extra_nodes", text = "Append Extra Nodes", icon='NODE')
        column.separator()

        column.label(text='Settings', icon='PROPERTIES')
        subcolumn = column.column(align=True)
        subcolumn.operator("atool.transfer_settings", text = "Transfer", icon='ANIM')
        subcolumn.operator("atool.bake_node_group_defaults", text = "Bake", icon='OUTLINER_DATA_GP_LAYER')
        column.separator()

        subcolumn = column.column(align=True)
        subcolumn.operator("atool.restore_default_settings", text = "Reset", icon='FILE_REFRESH')
        subcolumn.operator("atool.restore_factory_settings", text = "Factory", icon='FILE_BLANK')
        column.separator()

        subcolumn = column.column(align=True)
        subcolumn.operator("atool.load_material_settings", text = "Load", icon='PASTEDOWN')
        subcolumn.operator("atool.save_material_settings", text = "Save", icon='COPYDOWN')