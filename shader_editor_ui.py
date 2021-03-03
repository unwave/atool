import bpy

class MATAPP_properties(bpy.types.PropertyGroup):
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
    load_settings: bpy.props.BoolProperty(
        name="Load Settings",
        description="Load the imported material's settings from the database",
        default = False
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



class MATAPP_PT_tools(bpy.types.Panel):
    bl_idname = "MATAPP_PT_tools"
    bl_label = "Material Applier"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = "UI"
    bl_category = "MA"

    @classmethod
    def poll(cls, context):
        if context.space_data.tree_type == 'ShaderNodeTree':
            return True
        else:
            return False

    def draw(self, context):
        
        layout = self.layout

        column = layout.column()

        subcolumn_1 = column.column(align=True)
        subcolumn_1.operator("object.ma_apply_material", text = "Add", icon='ADD')
        subcolumn_1.operator("node.ma_convert_materail", text = "Convert", icon='MODIFIER')
        column.separator()

        column.operator("node.ma_make_material_links", text = "Link", icon='DRIVER')
        column.separator()

        subcolumn_2 = column.column(align=True)
        subcolumn_2.operator("node.ma_add_height_blend", text = "Height Blend", icon='RNDCURVE')
        subcolumn_2.operator("node.ma_add_detail_blend", text = "Detail Blend", icon='MOD_UVPROJECT')
        column.separator()

        column.operator("node.ma_normalize_height_range", text = "Normalize Image", icon='SEQ_HISTOGRAM')
        column.operator("node.ma_ensure_adaptive_subdivision", text = "Ensure Adaptive Subdivision", icon='MOD_NOISE')
        column.separator()

        column.operator("node.ma_open_in_file_browser", text = "Open File Browser", icon='FILEBROWSER')
        column.operator("node.ma_append_extra_nodes", text = "Append Extra Nodes", icon='NODE')
        column.separator()

        column.label(text='Settings', icon='PROPERTIES')
        subrow_1 = column.column(align=True)
        subrow_1.operator("node.ma_transfer_settings", text = "Transfer", icon='ANIM')
        subrow_1.operator("node.ma_bake_node_group_defaults", text = "Bake", icon='OUTLINER_DATA_GP_LAYER')
        column.separator()

        subrow_2 = column.column(align=True)
        subrow_2.operator("node.ma_restore_default_settings", text = "Reset", icon='FILE_REFRESH')
        subrow_2.operator("node.ma_restore_factory_settings", text = "Factory", icon='FILE_BLANK')
        column.separator()

        subrow_3 = column.column(align=True)
        subrow_3.operator("node.ma_load_material_settings", text = "Load", icon='PASTEDOWN')
        subrow_3.operator("node.ma_save_material_settings", text = "Save", icon='COPYDOWN')

        
        

        

        
        