import bpy

from . import utils
from . import bl_utils
from . import shader_editor_operator
from . import data

current_browser_asset_id = None


class ATOOL_PT_search(bpy.types.Panel):
    bl_idname = "ATOOL_PT_search"
    bl_label = ""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_context = "objectmode"

    def draw(self, context):
        column = self.layout.column()
        column.prop(context.window_manager, "at_current_page")
        column.prop(context.window_manager, "at_assets_per_page")

class ATOOL_PT_import_config(bpy.types.Panel):
    bl_idname = "ATOOL_PT_import_config"
    bl_label = "Material Import Config"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
 
    def draw(self, context):
        layout = self.layout
        layout.alignment = 'LEFT'
        shader_editor_operator.draw_import_config(context, layout)

class ATOOL_MT_actions(bpy.types.Menu):
    bl_idname = "ATOOL_MT_actions"
    bl_label = "Actions"

    def draw(self, context):
        layout = self.layout
        info = context.window_manager.at_browser_asset_info
        layout.prop(info, "is_shown", text = "Show Info")
        layout.prop(info, "is_id_shown", text = "Show ID Info")
        layout.operator("atool.open_info", icon='FILE_TEXT')
        layout.separator()
        layout.operator("atool.icon_from_clipboard", icon='IMAGE_DATA')
        layout.operator("atool.render_icon", icon='RESTRICT_RENDER_OFF')
        
        layout.operator("atool.reload_asset", text='Reload', icon='FILE_REFRESH').do_reimport = False
        layout.operator("atool.get_web_info", icon='INFO')
        layout.operator("atool.reload_asset", text='Reimport', icon='IMPORT').do_reimport = True
        layout.operator("atool.move_asset_to_desktop", icon='SCREEN_BACK')
        layout.separator()
        layout.operator("atool.import_files", icon="SHADING_TEXTURE")
        layout.operator("atool.process_auto", text = "Process Auto Folder", icon="NEWFOLDER")
        layout.operator("atool.get_web_asset", icon="URL")
        layout.separator()
        layout.popover("ATOOL_PT_import_config")
        
class ATOOL_MT_unreal(bpy.types.Menu):
    bl_idname = "ATOOL_MT_unreal"
    bl_label = "Unreal"

    def draw(self, context):
        layout = self.layout
        layout.operator("atool.import_unreal", icon="IMPORT")
        layout.operator("atool.copy_unreal_script", icon="COPYDOWN")
        layout.separator()
        layout.operator("atool.clear_custom_normals", icon="MOD_NORMALEDIT")
        layout.operator("atool.smooth_lowpoly", icon="MOD_SMOOTH")
            

class ATOOL_PT_panel(bpy.types.Panel):
    bl_idname = "ATOOL_PT_panel"
    bl_label = "Load Asset"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "objectmode"

    def draw(self, context):

        global current_browser_asset_id
        wm = context.window_manager
        info = wm.at_browser_asset_info
        asset_data = wm.at_asset_data # type: data.AssetData

        item_and_page_info = ''.join((
            "Item: ",
            str(wm.get("at_asset_previews", 0) + 1 + (wm.at_current_page-1) * asset_data.assets_per_page),
            "/",
            str(len(asset_data.search_result)), 
            "    ",
            "Page: ",
            str(wm.at_current_page), 
            "/",
            str(asset_data.number_of_pages)
            ))

        column = self.layout.column(align=False)
        column.prop(wm, "at_search")
        column.popover("ATOOL_PT_search", text=item_and_page_info)

        browser_and_navigation = column.column(align=True)

        previous_and_next_buttons = browser_and_navigation.row(align=True)
        previous_and_next_buttons.scale_x = 3
        previous_and_next_buttons.operator("atool.navigate", icon ='FRAME_PREV').button_index = 0
        previous_and_next_buttons.operator("atool.navigate", icon ='TRIA_LEFT').button_index = 1
        previous_and_next_buttons.operator("atool.open_gallery", text='', icon='FILE_IMAGE')
        previous_and_next_buttons.operator("atool.navigate", icon ='TRIA_RIGHT').button_index = 2
        previous_and_next_buttons.operator("atool.navigate", icon ='FRAME_NEXT').button_index = 3

        browser_and_side_buttons = browser_and_navigation.row(align=True)
        browser_and_side_buttons.template_icon_view(wm, "at_asset_previews", show_labels=True, scale=6.0, scale_popup=5.0)
        
        side_buttons = browser_and_side_buttons.column(align=True)
        side_buttons.operator("atool.pin_asset", text='', icon='PINNED')
        side_buttons.operator("atool.pin_active_asset", text='', icon='EYEDROPPER')
        side_buttons.operator("atool.open_asset_folder", text='', icon='FILE_FOLDER')
        side_buttons.operator("atool.open_blend", text='', icon='FILE_BLEND')
        side_buttons.operator("atool.render_icon", text='', icon='RESTRICT_RENDER_OFF')
        side_buttons.menu('ATOOL_MT_actions', text='', icon='DOWNARROW_HLT')

        column.separator()
        column.operator("atool.import_asset")
        column.separator()

        if info.is_shown:
            library_browser_asset_id = wm.at_asset_previews
            
            if current_browser_asset_id != library_browser_asset_id:
                current_browser_asset_id = library_browser_asset_id
                
                try:
                    asset = asset_data[library_browser_asset_id]

                    info["id"] = asset.id
                    info["name"] = asset.info.get("name", "")
                    info["url"] = asset.info.get("url", "")
                    info["author"] = asset.info.get("author", "")
                    info["author_url"] = asset.info.get("author_url", "")
                    info["licence"] = asset.info.get("licence", "")
                    info["licence_url"] = asset.info.get("licence_url", "")
                    info["description"] = asset.info.get("description", "")
                    info["tags"] = ' '.join(asset.info.get("tags", []))

                    dimensions = asset.info.get("dimensions", {})
                    info['x'] = dimensions.get("x", 1)
                    info['y'] = dimensions.get("y", 1)
                    info['z'] = dimensions.get("z", 0.1)
                except:
                    info["id"] = ""
                    info["name"] = ""
                    info["url"] = ""
                    info["author"] = ""
                    info["author_url"] = ""
                    info["licence"] = ""
                    info["licence_url"] = ""
                    info["description"] = ""
                    info["tags"] = ""
                    info['x'] = 1
                    info['y'] = 1
                    info['z'] = 0.1

                    # import traceback
                    # traceback.print_exc()

            if info.is_id_shown:
                row = column.row(align=True)
                row.operator("atool.open_asset_folder", text='', icon = 'FILE_FOLDER', emboss=False)
                row.prop(info, "id", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'SYNTAX_OFF', emboss=False).attr_name = "name"
            row.prop(info, "name", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'FILTER', emboss=False).attr_name = "tags"
            row.prop(info, "tags", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'URL', emboss=False).attr_name = "url"
            row.prop(info, "url", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'TEXT', emboss=False).attr_name = "description"
            row.prop(info, "description", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'USER', emboss=False).attr_name = "author"
            row.prop(info, "author", text="")

            row.operator("atool.open_attr", icon = 'LINKED', emboss=False).attr_name = "author_url"
            row.prop(info, "author_url", text="")

            row = column.row(align=True)
            row.operator("atool.open_attr", icon = 'COPY_ID', emboss=False).attr_name = "licence"
            row.prop(info, "licence", text="")

            row.operator("atool.open_attr", icon = 'LINKED', emboss=False).attr_name = "licence_url"
            row.prop(info, "licence_url", text="")

            row = column.column(align=True)
            row.prop(info, "x")
            row.prop(info, "y")
            row.prop(info, "z")



class ATOOL_PT_save_asset(bpy.types.Panel):
    bl_idname = "ATOOL_PT_save_asset"
    bl_label = "Save Asset"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "objectmode"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        column = self.layout.column(align=False)  

        self.asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not self.asset_data.library:
            column.label(text="No library folder specified.")
            return

        self.selected_objects = context.selected_objects
        if not self.selected_objects:
            column.label(text="No object selected.")
            return

        self.info = context.window_manager.at_template_info
        
        column.label(text=f"ID: {self.id}")
        column.label(text=f"Name: {self.id.replace('_', ' ')}")
        column.label(text=f"Objects: {len(self.selected_objects)}")
        column.prop(self.info, "do_move_images", text=f"Include images: {len(self.used_images)}")

        column.prop(self.info, "name", icon='SYNTAX_OFF', icon_only=True)
        column.prop(self.info, "tags", icon='FILTER', icon_only=True)
        column.prop(self.info, "url", icon='URL', icon_only=True)
        column.prop(self.info, "description", icon='TEXT', icon_only=True)

        row = column.row(align=True)
        row.prop(self.info, "author", icon='USER', text="")
        row.prop(self.info, "author_url", icon='LINKED', text="")

        row = column.row(align=True)
        row.prop(self.info, "licence", icon='COPY_ID', text="")
        row.prop(self.info, "licence_url", icon='LINKED', text="")

        # column.prop(self.info, "do_move_sub_asset")
        
        column.operator("atool.move_to_library", text="Save")

    @property
    def id(self):
        id = utils.get_slug(self.info.get("name", "")).strip('-_')
        if not id:
            id = utils.get_slug(utils.get_longest_substring([object.name for object in self.selected_objects])).strip('-_')
        if not id:
            id = "untitled_" + utils.get_time_stamp()
        id = self.asset_data.ensure_unique_id(id)
        return id

    @property
    def used_images(self):
        all_images = []
        for object in self.selected_objects:
            if not (object.data and hasattr(object.data, 'materials')):
                continue
            for material in object.data.materials:
                all_images.extend(bl_utils.get_all_images(material.node_tree))
        return utils.deduplicate(all_images)


class ATOOL_PT_view_3d_tools(bpy.types.Panel):
    bl_idname = "ATOOL_PT_view_3d_tools"
    bl_label = "Tools"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "objectmode"

    def draw(self, context):

        column = self.layout.column()
        subcolumn = column.column(align=True)
        subcolumn.operator("atool.os_open")
        subcolumn.operator("atool.reload_library")
        subcolumn.operator("atool.find_missing")
        subcolumn.operator("atool.split_blend_file")
        column.separator()
        subcolumn = column.column(align=True)
        subcolumn.operator("atool.distibute")
        subcolumn.operator("atool.match_displacement")
        column.separator()
        column.operator("atool.dolly_zoom")
        column.operator("atool.unrotate")
        column.operator("atool.arrage_by_materials")
        column.separator()
        column.menu('ATOOL_MT_unreal')
        column.separator()
        column.operator("atool.render_partial")

def update_ui():
    global current_browser_asset_id
    current_browser_asset_id = None

"""
    https://docs.blender.org/api/current/bpy.types.UILayout.html?highlight=ui#bpy.types.UILayout.template_icon_view
    javascript to remove icon names from https://docs.blender.org/api/current/bpy.types.UILayout.html

    var paragraphs = document.getElementsByTagName('p');
    for (let paragraph of paragraphs) {
        var result = paragraph.innerHTML.search("TRACKING_CLEAR_FORWARDS'");
        if (result != -1){
            paragraph.remove();
        }
    }
"""