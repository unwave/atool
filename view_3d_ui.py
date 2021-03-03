import bpy

# import inspect
# print(*inspect.getmembers(self), sep="\n")

# draw_count = 0
# global draw_count
# print("Draw count: ", draw_count)
# draw_count += 1

current_asset_id = None
current_icon_id = None
current_browser_asset_id = None

class ATOOL_PT_object(bpy.types.Panel):
    bl_idname = "ATOOL_PT_object"
    bl_label = "ATool"
    bl_category = "AT"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(context.object.get("atool_id"))

    def draw(self, context):

        column = self.layout.column()
        atool_id = context.object["atool_id"]

        global current_asset_id
        global current_icon_id
        asset_info = context.window_manager.at_asset_info
        
        if current_asset_id != atool_id:
            asset_data = context.window_manager.at_asset_data
            active_asset = asset_data.data[atool_id]

            icon = asset_data.preview_collection.get(active_asset.icon)
            if not icon:
                icon = asset_data.preview_collection.load(active_asset.icon, active_asset.icon, 'IMAGE')

            asset_info["name"] = active_asset.info["name"]
            asset_info["url"] = active_asset.info["url"]
            asset_info["author"] = active_asset.info["author"]
            asset_info["licence"] = active_asset.info["licence"]
            asset_info["tags"] = ' '.join(active_asset.info["tags"])

            current_asset_id = atool_id
            current_icon_id = icon.icon_id

        column.template_icon(icon_value = current_icon_id, scale=5.8)
        column.prop(asset_info, "name")
        column.prop(asset_info, "url")
        column.prop(asset_info, "author")
        column.prop(asset_info, "licence")
        column.prop(asset_info, "tags")

class ATOOL_PT_search(bpy.types.Panel):
    bl_idname = "ATOOL_PT_search"
    bl_label = ""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_context = "objectmode"

    def draw(self, context):
        column = self.layout.column()
        # , text='Go to page:'
        column.prop(context.window_manager, "at_current_page")
        column.prop(context.window_manager, "at_assets_per_page")

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
        browser_asset_info = wm.at_browser_asset_info
        asset_data = wm.at_asset_data

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
        previous_and_next_buttons.operator("atool.open_gallery", icon='FILE_IMAGE')
        previous_and_next_buttons.operator("atool.navigate", icon ='TRIA_RIGHT').button_index = 2
        previous_and_next_buttons.operator("atool.navigate", icon ='FRAME_NEXT').button_index = 3

        browser_and_side_buttons = browser_and_navigation.row(align=True)
        browser_and_side_buttons.template_icon_view(wm, "at_asset_previews", show_labels=True, scale=6.0, scale_popup=5.0)
        
        side_buttons = browser_and_side_buttons.column(align=True)
        side_buttons.operator("atool.open_asset_folder", icon='FILE_FOLDER')
        side_buttons.operator("atool.pin_asset", icon='PINNED')
        side_buttons.operator("atool.reload_asset", icon='FILE_REFRESH')
        side_buttons.prop(browser_asset_info, "is_shown", icon_only=True, icon = "INFO")

        column.separator()
        column.operator("atool.import_asset")
        column.operator("atool.process_auto")
        column.operator("atool.get_info_from_url")
        column.separator()

        if browser_asset_info.is_shown:
            library_browser_asset_id = wm.at_asset_previews
            
            if current_browser_asset_id != library_browser_asset_id:
                current_browser_asset_id = library_browser_asset_id
                
                try:
                    library_browser_asset = asset_data.data[library_browser_asset_id]

                    browser_asset_info["name"] = library_browser_asset.info["name"]
                    browser_asset_info["url"] = library_browser_asset.info["url"]
                    browser_asset_info["author"] = library_browser_asset.info["author"]
                    browser_asset_info["licence"] = library_browser_asset.info["licence"]
                    browser_asset_info["tags"] = ' '.join(library_browser_asset.info["tags"])
                except:
                    browser_asset_info["name"] = ""
                    browser_asset_info["url"] = ""
                    browser_asset_info["author"] = ""
                    browser_asset_info["licence"] = ""
                    browser_asset_info["tags"] = ""

            name_row = column.row(align=True)
            name_row.operator("atool.search_name", icon = 'SYNTAX_OFF', emboss=False)
            name_row.prop(browser_asset_info, "name", text="")

            url_row = column.row(align=True)
            url_row.operator("atool.open_url", icon = 'URL', emboss=False)
            url_row.prop(browser_asset_info, "url", text="")

            author_row = column.row(align=True)
            author_row.operator("atool.search_author", icon = 'USER', emboss=False)
            author_row.prop(browser_asset_info, "author", text="")

            licence_row = column.row(align=True)
            licence_row.operator("atool.search_licence", icon = 'COPY_ID', emboss=False)
            licence_row.prop(browser_asset_info, "licence", text="")

            tags_tow = column.row(align=True)
            tags_tow.operator("atool.search_tags", icon = 'FILTER', emboss=False)
            tags_tow.prop(browser_asset_info, "tags", text="")
               

class ATOOL_PT_save_asset(bpy.types.Panel):
    bl_idname = "ATOOL_PT_save_asset"
    bl_label = "Save Asset"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "objectmode"

    def draw(self, context):
        
        column = self.layout.column(align=False)
        template_info = context.window_manager.at_template_info
        column.prop(template_info, "name", icon='SYNTAX_OFF', icon_only=True)
        column.prop(template_info, "url", icon='URL', icon_only=True)
        column.prop(template_info, "author", icon='USER', icon_only=True)
        column.prop(template_info, "licence", icon='COPY_ID', icon_only=True)
        column.prop(template_info, "tags", icon='FILTER', icon_only=True)
        column.operator("atool.move_to_library")


class ATOOL_PT_view_3d_tools(bpy.types.Panel):
    bl_idname = "ATOOL_PT_view_3d_tools"
    bl_label = "Tools"
    bl_category = "AT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_context = "objectmode"

    def draw(self, context):

        column = self.layout.column()
        column.operator("atool.os_open")
        column.operator("atool.reload_library")
        column.operator("atool.split_blend_file")
        column.operator("atool.distibute")
        column.operator("atool.match_displacement")


def update_ui():
    global current_asset_id
    global current_icon_id
    global current_browser_asset_id

    current_asset_id = None
    current_icon_id = None
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