import itertools
import math
import os
import queue
import subprocess
import re
import threading
import typing
import operator
import json
import sys
from datetime import datetime

import bpy
import bmesh
import mathutils

from . import utils
from . import bl_utils
from . import node_utils
from . import image_utils
from . import type_definer

from . import data
from . import shader_editor_operator


# import webbrowser
# import numpy
# import uuid

register = bl_utils.Register(globals())

class Object_Mode_Poll():
    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'VIEW_3D' and context.mode == 'OBJECT'


def get_unique_libraries_from_selected_objects(operator, context):

    report = operator.report
    selected_objects = context.selected_objects
    if not selected_objects:
        report({'INFO'}, "Nothing is selected. Select an object with a library dependency.")
        return []

    libraries = {l for l in bpy.data.libraries}
    dependencies = bl_utils.Dependency_Getter()

    libraries_to_reload = []
    for object in selected_objects:
        for dependency in dependencies.get_object_dependencies_by_type(object, type = ('Library',)):
            if dependency in libraries:
                libraries_to_reload.append(dependency)

    return utils.deduplicate(libraries_to_reload)
    
def get_asset_data_and_id(operator: bpy.types.Operator, context: bpy.types.Context) -> typing.Tuple[data.AssetData, str]:

    asset_data = context.window_manager.at_asset_data # type: data.AssetData
    if not asset_data:
        operator.report({'INFO'}, "The library is empty.")
        return None, None

    asset_id = context.window_manager.at_asset_previews # type: str
    if asset_id == "/":
        operator.report({'INFO'}, "Select an asset.")
        return asset_data, None

    return asset_data, asset_id

def get_current_browser_asset(operator: bpy.types.Operator, context: bpy.types.Context) -> data.Asset:
    
    data, id = get_asset_data_and_id(operator, context)
    if not (data and id):
        return

    asset = data.get(id)
    if not asset:
        operator.report({'INFO'}, "Select an asset. Current is not available.")
        return

    return asset


class ATOOL_OT_os_open(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.os_open"
    bl_label = "Open File Browser"
    bl_description = "Open the selected objects dependencies in a file browser"

    def execute(self, context):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "Nothing is selected.")
            return {'CANCELLED'}

        dependencies = bl_utils.Dependency_Getter()
        filepaths = []

        for object in selected_objects:
            for dependency in dependencies.get_object_dependencies_by_type(object):
                filepath = bl_utils.get_block_abspath(dependency)
                if not os.path.exists(filepath):
                    continue
                filepaths.append(filepath)

        if not filepaths:
            self.report({'INFO'}, "No dependencies or files does not exist.")
            return {'CANCELLED'}

        filepaths = utils.deduplicate(filepaths)
        threading.Thread(target=utils.os_show, args=(self, filepaths,)).start()
        
        return {'FINISHED'}


class ATOOL_OT_reload_dependency(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.reload_dependency"
    bl_label = "Reload Dependency"
    bl_description = "Reload the selected objects dependencies"

    def execute(self, context):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "Nothing is selected. Select an object with a dependency.")
            return {'CANCELLED'}

        local_dependencies = set(bpy.data.libraries)
        local_dependencies |= set(bpy.data.images)
        dependencies = bl_utils.Dependency_Getter()

        dependencies_to_reload = [] 
        for object in selected_objects:
            for dependency in dependencies.get_object_dependencies_by_type(object):
                if dependency in local_dependencies: # is needed?
                    dependencies_to_reload.append(dependency)

        if not dependencies_to_reload:
            self.report({'INFO'}, "No dependency found.")
            return {'CANCELLED'}

        dependencies_to_reload = utils.deduplicate(dependencies_to_reload)
        # may be just remove images that belongs to libraries but need to test first
        dependencies_to_reload = [bl_utils.Reference(dependency) for dependency in dependencies_to_reload] # type: typing.List[bl_utils.Reference]
        for dependency in dependencies_to_reload:
            dependency = dependency.get()
            dependency.reload()
            self.report({'INFO'}, f"{dependency.name} has been reloaded.")
        
        return {'FINISHED'}


class ATOOL_OT_split_blend_file(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.split_blend_file"
    bl_label = "Split Blend"
    bl_description = "Move the selected objects to a new Blender session"
    bl_options = {'REGISTER', 'UNDO'}

    use_empty_startup : bpy.props.BoolProperty(name="Use Empty Startup", default = True)

    def execute(self, context):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "Nothing is selected. Select an object.")
            return {'CANCELLED'}

        temp_blend = os.path.join(bpy.app.tempdir, "atool_temp.blend")
        bpy.data.libraries.write(temp_blend, set(selected_objects))

        if self.use_empty_startup:
            script = "\n".join([
                "import bpy",
                f"bpy.ops.wm.read_homefile(use_empty=True)",
                f"with bpy.data.libraries.load(filepath=r\"{temp_blend}\") as (data_from, data_to): data_to.objects = {[object.name for object in selected_objects]}",
                "for object in data_to.objects: bpy.context.collection.objects.link(object)",
                "bpy.data.libraries.remove(bpy.data.libraries[0])"
            ])
        else:
            script = "\n".join([
                "import bpy",
                f"with bpy.data.libraries.load(filepath=r\"{temp_blend}\") as (data_from, data_to): data_to.objects = {[object.name for object in selected_objects]}",
                "for object in data_to.objects: bpy.context.collection.objects.link(object)",
                "bpy.data.libraries.remove(bpy.data.libraries[0])"
            ])

        # https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html
        subprocess.Popen([bpy.app.binary_path, "--python-expr", script], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)

        bpy.data.batch_remove(selected_objects)
    
        return {'FINISHED'}


class ATOOL_OT_move_to_library(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.move_to_library"
    bl_label = "Move To Library"
    bl_description = "Move the selected objects to the user library"

    def invoke(self, context, event):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "No selected objects.")
            return {'CANCELLED'}

        objects = [object for object in selected_objects if object.data and not object.data.library]
        if not objects:
            self.report({'INFO'}, "No valid objects.")
            return {'CANCELLED'}

        asset_data = context.window_manager.at_asset_data # type: data.AssetData

        if not asset_data.library:
            self.report({'INFO'}, "No library folder specified.")
            return {'CANCELLED'}

        template_info = context.window_manager.at_template_info
        self.objects = [bl_utils.Reference(object) for object in objects]
        
        info = {}
        info["name"] = template_info.name
        info["url"] = template_info.url
        info["tags"] = template_info.tags.split()
        info["author"] = template_info.author
        info["author_url"] = template_info.author_url
        info["licence"] = template_info.licence
        info["licence_url"] = template_info.licence_url
        info['do_move_images'] = template_info.do_move_images
        info['do_move_sub_assets'] = template_info.do_move_sub_assets

        self.process = threading.Thread(target=asset_data.add_to_library, args=(context, objects, info))
        self.process.start()

        self.timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


    def modal(self, context, event):

        if event.type != 'TIMER' or self.process.is_alive():
            return {'PASS_THROUGH'}

        self.process.join()

        return self.execute(context)
            

    def execute(self, context):

        self.report({'INFO'}, "The asset has been added.")

        # for object in self.objects:
        #     bpy.data.objects.remove(object.get())
            
        return {'FINISHED'}


class Blend_Import:

    link: bpy.props.BoolProperty(
        name="Link", 
        description="Link asset instead of appending", 
        default= True
        )
    ignore: bpy.props.StringProperty(
        name="Ignore", 
        description="Do not import asset that starts with the string", 
        default = "#"
        )
    
    # only_as_collections: bpy.props.BoolProperty(
    #     name="As Collections", 
    #     description="Only link instanced collections", 
    #     default= True
    #     )
    
    move_to_cursor: bpy.props.BoolProperty(
        name="Move To Cursor", 
        description="Move objects to the 3d cursor", 
        default= True
        )
    
    as_drag_and_drop: bpy.props.BoolProperty(
        name="As Blend Drop", 
        description="Import as a blend drop", 
        default = False
        )
    
    delete_unused_links: bpy.props.BoolProperty(
        name="Clear Unused Liked IDs", 
        description="Deletes all unused links of the imported blend file. Use this when the append gives you a linked object as it was linked before", 
        default = True
        )

    def draw_blend_import(self, layout: bpy.types.UILayout):
        if not self.as_drag_and_drop:
            box = layout.box().column(align=True)
            box.prop(self, "link")
            # if self.link:
                # box.prop(self, "only_as_collections")
            box.prop(self, "move_to_cursor")
            box.prop(self, "ignore")
        layout.separator()
        
        layout.prop(self, "delete_unused_links")
        layout.separator()
        
        box = layout.box().column(align=True)
        box.prop(self, "as_drag_and_drop")
        if self.as_drag_and_drop:
            box.operator("wm.link", text="Link", icon='LINK_BLEND').filepath = self.blend
            box.operator("wm.append", text="Append", icon='APPEND_BLEND').filepath = self.blend
    
    @property        
    def library(self):
        if self._library:
            return self._library.get()
        
    @library.setter
    def library(self, library: bpy.types.Library):
        self._library = bl_utils.Reference(library)

    def import_blend(self, context):
        self._library: bl_utils.Reference = None
        self.was_library_linked_before = None
        
        if self.as_drag_and_drop:
            
            library = bl_utils.get_library_by_path(self.blend)
            if library:
                if not library.users_id:
                    bpy.data.libraries.remove(library)
                else:
                    if self.delete_unused_links:
                        to_clear = []
                        for id in library.users_id:
                            if id.library == library:
                                users = id.users
                                if not users or users == 1 or users == 2 and id.use_fake_user:
                                    to_clear.append(id)
                        bpy.data.batch_remove(to_clear)
            
            if self.is_repeat():
                if self.was_library_linked_before == False and self.library:
                    bpy.data.libraries.remove(self.library)
                
            return {'FINISHED'}
        
        self.blend: str
        self.atool_id: str
        self.pre_load_libraries = set(bpy.data.libraries)

        with bpy.data.libraries.load(self.blend, link = self.link) as (data_from, data_to):
            data_to.collections = data_from.collections
            data_to.objects = data_from.objects
            # if not self.only_as_collections:
                # data_to.objects = data_from.objects

        library = bl_utils.get_library_by_path(self.blend)
        
        self.library = library
        self.was_library_linked_before = False
        if library in self.pre_load_libraries:
            self.was_library_linked_before = True

        if not (data_to.collections or data_to.objects):
            self.report({'INFO'}, "Nothing to import from the blend file.")
            if not self.was_library_linked_before:
                bpy.data.libraries.remove(library)
            return {'FINISHED'}

        library_version = library.version
        if library_version < (2,80,0):
            report = "2.79- blend file."
            if data_to.collections:
                report += f" {len(data_to.collections)} groups are imported as collections."
            self.report({'INFO'}, report)
            
        def import_objects_and_collections():
            pass

        objects = []
        objects_to_remove = []
        for object in data_to.objects:
            if self.ignore and object.name.startswith(self.ignore):
                objects_to_remove.append(object)
            else:
                objects.append(object)
        if objects_to_remove:
            bpy.data.batch_remove(objects_to_remove)

        imported = {}
        final_objects = []
        context_collection_objects =  set(context.collection.objects)

        def add_object(object, collection):
            object["atool_id"] = self.atool_id

            if self.link:
                imported_object = imported.get((object.name, object.library))
                if imported_object:
                    return imported_object

                object_override = object.override_create(remap_local_usages=False)
                object_override["atool_id"] = self.atool_id
                collection.objects.link(object_override)
                object_override.select_set(True)

                imported[(object.name, object.library)] = object_override
                return object_override
            else:
                # if already linked there is a blender problem with appending
                # object = object.copy() # only copies the object, not it's sub ids
                # object = object.make_local(clear_proxy = False)
                # bpy.ops.object.make_local(type='SELECT_OBJECT')
                # bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', object=False, obdata=False, material=False, animation=False)
                if not object in context_collection_objects:
                    collection.objects.link(object)
                object.select_set(True)
                return object

        collection_objects = set()
        for collection in data_to.collections:

            if self.ignore and collection.name.startswith(self.ignore):
                for object in list(collection.all_objects):
                    bpy.data.objects.remove(object)
                    objects.remove(object)
                bpy.data.collections.remove(collection)
                continue

            new_collection = bpy.data.collections.new(collection.name)
            context.scene.collection.children.link(new_collection)

            for object in collection.all_objects:
                collection_objects.add(object)
                final_objects.append(add_object(object, new_collection))
        
        for object in objects:
            if object in collection_objects:
                continue
            final_objects.append(add_object(object, context.collection))
        
        if self.move_to_cursor:
            cursor_location = context.scene.cursor.location
            for object in set(final_objects):
                if not object.parent:
                    object.matrix_world.translation += cursor_location

        if not self.link:
            return {'FINISHED'}

        imported_objects = {object.name: object for object in final_objects}

        for object in imported_objects.values():
            
            object.use_fake_user = False
            
            parent = object.parent
            if parent and parent.library == library:
                object.parent = imported_objects.get(parent.name)
        
            modifiers = [modifier for modifier in object.modifiers if modifier.type == 'ARMATURE']
            if modifiers:
                for modifier in modifiers:
                    modifier.object = imported_objects.get(modifier.object.name)

        return {'FINISHED'}


class ATOOL_OT_import_asset(bpy.types.Operator, Object_Mode_Poll, shader_editor_operator.Modal_Material_Import, Blend_Import):
    bl_idname = "atool.import_asset"
    bl_label = "Import"
    bl_description = "Import asset"
    bl_options = {'REGISTER', 'UNDO'}

    images: typing.List[image_utils.Image]

    def draw(self, context):
        layout = self.layout
        # layout.use_property_split = True
        layout.alignment = 'LEFT'

        if self.asset_type == 'material':
            self.draw_material_import(layout)
        elif self.asset_type == 'blend':
            self.draw_blend_import(layout)

    def invoke(self, context, event):
        
        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
        
        self.asset_type = None
        self.asset = asset
        
        if asset.is_blend:
            self.asset_type = 'blend'
            self.blend = asset.blend
            self.atool_id = asset.id
            return self.execute(context)

        image_paths = asset.get_images()
        if image_paths:
            self.asset_type = 'material'
            
            self.image_paths = image_paths
            self.set_asset(asset)
            
            object = context.object
            if object:
                self.set_object(object)
                material = object.active_material
                if material:
                    self.set_material(material)
            
            self.start_images_preload(context)
            return {'RUNNING_MODAL'}
            
        self.report({'INFO'}, "Nothing to import.")
        return {'CANCELLED'} 

    def execute(self, context):
        if self.asset_type == 'blend':
            return self.import_blend(context)
        
        assert self.asset_type == 'material'
        return self.apply_material(context)
        


class ATOOL_OT_extract_zips(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.extract_zips"
    bl_label = "Extract Zip Files"
    bl_description = ""

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        extracted_files = asset.extract_zips()
        if not extracted_files:
            self.report({'INFO'}, "No zip files to extract.")
            return {'CANCELLED'}

        self.report({'INFO'}, "The zip files have been extracted.")
        return {'FINISHED'}
        

class ATOOL_OT_open_gallery(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_gallery"
    bl_label = "Open Gallery"
    bl_description = "Open Gallery"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        if not os.path.exists(asset.gallery):
            self.report({'INFO'}, "No gallery.")
            return {'CANCELLED'}

        images = [file.path for file in os.scandir(asset.gallery)]
        if not images:
            self.report({'INFO'}, "The gallery is empty.")
            return {'CANCELLED'}

        latest_image = max(images, key=os.path.getmtime)
        utils.os_open(self, latest_image)
            
        return {'FINISHED'}


class ATOOL_OT_pin_active_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.pin_active_asset"
    bl_label = "Pin Active Asset"
    bl_description = "Pin the active object if it is an asset"

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not asset_data:
            self.report({'INFO'}, "The library is empty.")
            return {'CANCELLED'}

        selected_objects = context.selected_objects # type: typing.List[bpy.types.Object]
        if not selected_objects:
            self.report({'INFO'}, "No object selected.")
            return {'CANCELLED'}

        objects = asset_data.get_assets_from_objects(selected_objects)
        if not objects:
            self.report({'INFO'}, "No assets selected.")
            return {'CANCELLED'}

        active_object = context.object
        active_id = None
        for object, assets in objects.items():
            if object == active_object:
                active_id = assets[0].id
                break

        if not active_id:
            active_id = list(objects.items())[0][1][0].id

        assets = [asset for assets in objects.values() for asset in assets]
        assets = utils.deduplicate(assets)

        query = ''
        for asset in assets:
            if " " in asset.id:
                query += f'id:"{asset.id}" '  
            else:
                query += f'id:{asset.id} '

        context.window_manager.at_search = query
        context.window_manager.at_asset_previews = active_id

        return {'FINISHED'}



class ATOOL_OT_open_attr(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_attr"
    bl_label = ""
    bl_description = "Click to open or search"

    attr_name: bpy.props.StringProperty()

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
            
        attr = asset.info.get(self.attr_name)

        if not attr:
            self.report({'INFO'}, "Empty.")
            return {'CANCELLED'}

        if isinstance(attr, list):
            attr = ' '.join(attr)

        if "quixel.com/megascans/home" in attr:
            match = re.search(r"(?<=assetId=)[a-zA-Z0-9]+", attr)
            if match:
                attr += f'&search={match.group(0)}'
            
        utils.web_open(attr)
            
        return {'FINISHED'}


class ATOOL_OT_open_asset_folder(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_asset_folder"
    bl_label = "Open Asset Folder"
    bl_description = "Open Asset Folder"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        utils.os_open(self, asset.path)
        
        return {'FINISHED'}


class ATOOL_OT_pin_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.pin_asset"
    bl_label = "Pin Asset"
    bl_description = "Pin Asset"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        context.window_manager.at_search = "id:" + asset.id

        return {'FINISHED'}


class ATOOL_OT_navigate(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.navigate"
    bl_label = ""
    bl_description = "Navigation"

    button_index: bpy.props.IntProperty()
    
    @property
    def last_index(self):
        return len(data.get_browser_items(None, None)) - 1

    @property
    def current(self):
        return self.wm["at_asset_previews"]

    @current.setter
    def current(self, index):
        self.wm["at_asset_previews"] = index

    def execute(self, context):
        wm = context.window_manager
        self.wm = wm
        asset_data = wm.at_asset_data # type: data.AssetData     
        
        last_index = self.last_index
        current_index = wm.get("at_asset_previews", 0)

        if self.button_index == 0: # previous page
            asset_data.go_to_prev_page()
            self.current = min(self.current, self.last_index)
        elif self.button_index == 1: # previous asset
            if current_index == 0:
                asset_data.go_to_prev_page()
                self.current = self.last_index
            else:
                self.current = current_index - 1
        elif self.button_index == 2: # next asset
            if current_index == last_index:
                asset_data.go_to_next_page()
                self.current = 0
            else:
                self.current = current_index + 1
        elif self.button_index == 3: # next page
            asset_data.go_to_next_page()
            self.current = min(self.current, self.last_index)

        wm["at_current_page"] = asset_data.current_page

        return {'FINISHED'}


class ATOOL_OT_reload_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.reload_asset"
    bl_label = "Reload Asset"
    bl_description = "Reload Asset"

    do_reimport: bpy.props.BoolProperty(default=False)

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not (data and id):
            return {'CANCELLED'}

        asset = data[id]
        if self.do_reimport and asset.is_remote:
            self.report({'INFO'}, "Reimporting remote assets is not allowed.")
            return {'CANCELLED'}

        threading.Thread(target=data.reload_asset, args=(id, context, self.do_reimport)).start()

        return {'FINISHED'}


class ATOOL_OT_match_displacement(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.match_displacement"
    bl_label = "Match Displacement"
    bl_description = "Make the particles match the shader displacement of the object. Works only for UV based materials"
    bl_options = {'REGISTER', 'UNDO'}

    random_rotation: bpy.props.BoolProperty(name = "Random Rotation", default = True)

    def execute(self, context):
        self.context = context
        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, "No selected objects.")
            return {'CANCELLED'}

        jobs = []
        for object in selected_objects:

            if object.type != 'MESH':
                self.report({'INFO'}, f"\"{object.name}\" is not a mesh. Skipped.")
                continue

            object_materials = [slot for slot in object.data.materials if slot]
            if not object_materials:
                self.report({'INFO'}, f"\"{object.name}\" has no materials. Skipped.")
                continue

            active_material = object.active_material
            if active_material:
                material = active_material
                self.report({'INFO'}, f"'{object.name}': trying active material '{material.name}'.")
            else:
                material = object_materials[0]
                self.report({'INFO'}, f"'{object.name}': active material socket is None, trying '{material.name}'.")

            node_tree = node_utils.Node_Tree_Wrapper(material.node_tree)

            material_output = node_tree.output
            if not material_output:
                self.report({'INFO'}, f"'{material.name}' has no material output node. '{object.name}' is skipped.")
                continue

            displacement = material_output['Displacement']
            if not displacement:
                self.report({'INFO'}, f"'{material.name}' material output node has no displacement input. '{object.name}' is skipped.")
                continue

            if displacement.type != 'DISPLACEMENT':
                self.report({'INFO'}, f"'{material.name}' material output node has no connection with a displacement node. '{object.name}' is skipped.")
                continue

            height_node = displacement['Height']
            if not height_node:
                self.report({'INFO'}, f"\"{material.name}\" has no height output. \"{object.name}\" is skipped.")
                continue
              
            particle_systems_modifiers = [modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM']
            if not particle_systems_modifiers:
                self.report({'INFO'}, f"\"{object.name}\" has no particle systems. Skipped.")
                continue
            
            filtered_particle_systems_modifiers = []
            for modifier in particle_systems_modifiers:
                particle_system = modifier.particle_system
                
                if not modifier.show_viewport:
                    self.report({'INFO'}, f"'{particle_system.name}' system of '{object.name}' is enabled in the viewport. Skipped.")
                    continue
                
                particles_settings = particle_system.settings
                
                if particles_settings.child_type == 'INTERPOLATED':
                    self.report({'INFO'}, f"Particle systems with interpolated children are not supported. '{particle_system.name}' system of '{object.name}' object is skipped.")
                    continue
                
                if not particles_settings.count:
                    self.report({'INFO'}, f"'{particle_system.name}' system of '{object.name}' object has zero particles. Skipped")
                    continue
                
                filtered_particle_systems_modifiers.append(modifier)
            
            if not filtered_particle_systems_modifiers:
                continue
            
            x, y, z = object.scale
            if not (math.isclose(x, y, rel_tol = 1e-05) and math.isclose(x, z, rel_tol = 1e-05) and math.isclose(y, z, rel_tol = 1e-05)):
                self.report({'WARNING'}, f"\"{object.name}\" has non uniform scale. The result may be incorrect.")
            
            scale = displacement.get_value('Scale')
            if displacement.space == 'OBJECT':
                # object_scale = mathutils.Vector(object.scale)
                scale = mathutils.Vector(object.scale) * scale
            
            jobs.append((object, material, filtered_particle_systems_modifiers))
        
        if not jobs:
            self.report({'INFO'}, "No valid object selected.")
            return {'CANCELLED'}
        
        
        start = datetime.now()
        
        initial_active_object = context.object
        
        bpy.ops.mesh.primitive_plane_add(location=(0.0, 0.0, -100))
        bake_plane = context.object
        bake_plane.name = "__bake_plane__"
        self.bake_plane = bake_plane
        
        cycles_samples = self.context.scene.cycles.samples
        self.context.scene.cycles.samples = 1
        
        for object, material, modifiers in jobs:
            
            self.bake_plane.at_uv_multiplier = object.at_uv_multiplier
            
            for modifier in modifiers:
                object.particle_systems.active_index = object.particle_systems.find(modifier.particle_system.name)
                self.pre_process(object, modifier)
                with node_utils.Isolate_Object_Render(object, modifier):
                    self.bake_plane.hide_render = False
                    self.match_system(object, material, modifier)

        bpy.data.objects.remove(bake_plane, do_unlink=True)
        
        self.context.scene.cycles.samples = cycles_samples
        
        context.view_layer.objects.active = initial_active_object
        
        for object in selected_objects:
            object.select_set(True)

        print("All time:", datetime.now() - start)

        return {'FINISHED'}
    
    def pre_process(self, object: bpy.types.Object, modifier: bpy.types.ParticleSystemModifier):
        particle_system = modifier.particle_system
        particles_settings = particle_system.settings
        
        if particles_settings.type == 'EMITTER':
            self.context.scene.frame_set(1)
            
            if particle_system.point_cache.is_baked:
                bpy.ops.ptcache.free_bake({'point_cache': particle_system.point_cache})

        override = bl_utils.get_context_copy_with_object(self.context, object)
        bpy.ops.particle.edited_clear(override)
        
        if particles_settings.type == 'EMITTER':
            particles_settings.frame_start = 1
            particles_settings.frame_end = 1
            particles_settings.normal_factor = 1
        
        particles_settings.tangent_factor = 0
        particles_settings.object_align_factor[0] = 0
        particles_settings.object_align_factor[1] = 0
        particles_settings.object_align_factor[2] = 0

        if particles_settings.type == 'EMITTER':
            seed = particle_system.seed
            particle_system.seed = seed
    
    def match_system(self, object: bpy.types.Object, material: bpy.types.Material,  modifier: bpy.types.ParticleSystemModifier):
        
        evaluated_object: bpy.types.Object = object.evaluated_get(self.context.evaluated_depsgraph_get())
        
        modifier = evaluated_object.modifiers[modifier.name]
        particle_system = modifier.particle_system
        particle_system_settings = particle_system.settings
        
        shifts = self.get_shifts(modifier, material)
        
        if particle_system_settings.type == 'HAIR':
            self.match_hair_system(modifier, shifts, object, evaluated_object)
        else:
            self.match_emitter_system(modifier, shifts)
        
    def get_shifts(self, modifier: bpy.types.ParticleSystemModifier, material: bpy.types.Material):
        
        node_tree = node_utils.Node_Tree_Wrapper(material.node_tree)
        material_output = node_tree.output
        displacement = material_output['Displacement']
        midlevel = displacement.get_value('Midlevel')
        scale = displacement.get_value('Scale')
        height_output_socket = displacement.inputs['Height'].nodes[0][1]
        
        particle_system = modifier.particle_system    
        particles = particle_system.particles
        number_of_particles = len(particles)
        
        x = 1
        y = number_of_particles

        flat_list_3 = [0] * (3 * number_of_particles)
        flat_list_4 = [0] * (4 * number_of_particles)

        # if has a bad geometry such as n-gons or big twisted faces the coordinates will be incorrect
        flat_uvs = []
        for particle in particles:
            uv = particle.uv_on_emitter(modifier = modifier)
            flat_uvs.extend((uv[0], uv[1], 0, 1))
        
        if not self.bake_plane.data.materials:
            self.bake_plane.data.materials.append(material)
        else:
            self.bake_plane.data.materials[0] = material
            
        with node_utils.Temp_Image(x, y) as uvs_image, node_utils.Temp_Image(x, y) as displacement_image:

            uvs_image.pixels.foreach_set(flat_uvs)

            with node_utils.UV_Override(material, uvs_image), \
                node_utils.Baking_Image_Node(material, displacement_image), \
                node_utils.Output_Override(material, material_output, height_output_socket):
                
                start2 = datetime.now()
                
                override = bl_utils.get_context_copy_with_object(self.context, self.bake_plane)
                bpy.ops.object.bake(override, type='EMIT')
                
                print("Bake time:", datetime.now() - start2)
                
            displacement_image.pixels.foreach_get(flat_list_4)
            heights = flat_list_4[0::4]

        particles.foreach_get('velocity', flat_list_3)
        
        normals = map(mathutils.Vector, zip(*[iter(flat_list_3)]*3))
        
        shifts = [normal.normalized() * (height - midlevel) * scale for normal, height in zip(normals, heights)]
        
        return shifts
    
    def match_hair_system(self, modifier: bpy.types.ParticleSystemModifier, shifts: typing.List[mathutils.Vector], object: bpy.types.Object, evaluated_object: bpy.types.Object):
        particle_system = modifier.particle_system
        particles = particle_system.particles
 
        matrix_world = object.matrix_world
        translation, rotation, scale = matrix_world.decompose()
        translation.zero()
        scale = mathutils.Vector( (1 / scale[0], 1 / scale[0], 1 / scale[0]) )
        matrix = mathutils.Matrix.LocRotScale(translation, rotation, scale)
        
        for particle, shift in zip(particles, shifts):                        
            for key in particle.hair_keys:
                new_co = key.co_object(evaluated_object, modifier, particle) + shift @ matrix
                key.co_object_set(evaluated_object, modifier, particle, new_co)
        
        if self.random_rotation:
            self.set_random_rotation(particle_system, )
        
        override = bl_utils.get_context_copy_with_object(self.context, object)
        bpy.ops.particle.particle_edit_toggle(override)
        bpy.ops.particle.particle_edit_toggle(override)
    
    def match_emitter_system(self, modifier: bpy.types.ParticleSystemModifier, shifts: typing.List[mathutils.Vector]):
        particle_system = modifier.particle_system
        particles = particle_system.particles
        
        flat_list_3 = [0] * (3 * len(particles))
        particles.foreach_get('location', flat_list_3)
        
        old_location = map(mathutils.Vector, zip(*[iter(flat_list_3)]*3))  
        
        new_location = [x + y for x, y in zip(old_location, shifts)]
        new_location = list(itertools.chain.from_iterable(new_location))
        particles.foreach_set('location', new_location)
        
        if self.random_rotation:
            self.set_random_rotation(particle_system)

        self.context.scene.frame_set(2)
        self.context.scene.frame_set(1)
        bpy.ops.ptcache.bake_from_cache({'point_cache': particle_system.point_cache})
        
    def set_random_rotation(self, particle_system: bpy.types.ParticleSystems):
        particles = particle_system.particles
        number_of_particles = len(particles)
        
        flat_list_4 = [0] * (4 * number_of_particles)
        particles.foreach_get('rotation', flat_list_4)

        current_rotation = map(mathutils.Quaternion, zip(*[iter(flat_list_4)]*4))
        import numpy
        numpy.random.seed(particle_system.seed)
        random_rotation = map(mathutils.Quaternion, itertools.repeat((1.0, 0.0, 0.0)), numpy.random.uniform(-math.pi, math.pi, number_of_particles))

        new_rotation = [a @ b for a, b in zip(current_rotation, random_rotation)]
        new_rotation =  list(itertools.chain.from_iterable(new_rotation))
        particles.foreach_set('rotation', new_rotation)


class ATOOL_OT_get_web_info(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.get_web_info"
    bl_label = "Get Info From Url"
    bl_description = "Get the asset info from the url"

    def execute(self, context):
        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        if not asset.info.get("url"):
            self.report({'INFO'}, "No url.")
            return {'CANCELLED'}

        threading.Thread(target=asset.get_web_info, args=(context,)).start()

        return {'FINISHED'}


class ATOOL_OT_open_info(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_info"
    bl_label = "Open Info"
    bl_description = "Open __info__.json"

    def execute(self, context):
        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        utils.os_open(self, asset.json_path)
        return {'FINISHED'}


class ATOOL_OT_get_web_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.get_web_asset"
    bl_label = "Download Asset"
    bl_description = "Download an asset by its URL"

    url: bpy.props.StringProperty(
        name="URL",
        options = {'SKIP_SAVE'}
        )
    
    def draw(self, context):
        layout = self.layout
        # layout.use_property_decorate = False
        layout.use_property_split = False
        # layout.alignment = 'LEFT'
        layout.prop(self, "url", text='', icon='URL')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width = 400)

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not asset_data.library:
            self.report({'INFO'}, "No library folder specified.")
            return {'CANCELLED'}

        if not self.url:
            self.report({'INFO'}, "No URL specified.")
            return {'CANCELLED'}

        threading.Thread(target=asset_data.web_get_asset, args=(self.url, context)).start()

        return {'FINISHED'}


class ATOOL_OT_distribute(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.distribute"
    bl_label = "Distribute"
    bl_description = "Distribute the selection to the active object with a particle system"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name = 'Name', default = 'New Particles')

    def invoke(self, context, event):
        self.seed = int(mathutils.noise.random() * 9999)
        return self.execute(context)

    def execute(self, context):

        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, f"No selected objects. Select at least two objects.")
            return {'CANCELLED'}

        if len(selected_objects) == 1:
            self.report({'INFO'}, f"Only one object is selected. Select at least two objects.")
            return {'CANCELLED'}

        target = context.object
        if not hasattr(target, 'modifiers'):
            self.report({'INFO'}, f"{target.name} cannot have particles.")
            return {'CANCELLED'}
        
        particles_objects = context.selected_objects.copy()
        particles_objects.remove(context.object)

        longest_substring = utils.get_longest_substring([object.name for object in particles_objects])
        if len(longest_substring) >= 3:
            self.name = longest_substring
    
        particle_system_modifier = target.modifiers.new(name = self.name, type='PARTICLE_SYSTEM')

        if not particle_system_modifier:
            self.report({'INFO'}, f"{target.name} cannot have particles.")
            return {'CANCELLED'}

        particle_system = particle_system_modifier.particle_system
        
        particle_system.name = self.name
        particle_system.seed = self.seed

        settings = particle_system.settings
        settings.name = self.name
        settings.use_modifier_stack = True
        settings.type = 'HAIR'
        settings.distribution = 'RAND'
        settings.use_advanced_hair = True
        settings.use_rotations = True
        settings.rotation_mode = 'NOR_TAN'
        settings.use_rotation_instance = True
        settings.use_collection_pick_random = True
        settings.hair_length = 1
        settings.particle_size = 1

        collection = bpy.data.collections.new(self.name + " Particle Collection")
        # context.scene.collection.children.link(collection)
        for object in particles_objects:
            collection.objects.link(object)

            initial_rotation_mode = object.rotation_mode
            object.rotation_mode = 'XYZ'
            object.rotation_euler = (0, math.radians(90), 0)
            object.rotation_mode = initial_rotation_mode

        settings.render_type = 'COLLECTION'
        settings.instance_collection = collection

        settings.size_random = 0.5
        settings.rotation_factor_random = 0.05
        settings.phase_factor_random = 2

        return {'FINISHED'}


class ATOOL_OT_process_auto(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.process_auto"
    bl_label = "Process Auto"
    bl_description = "Process the auto import folder"
    bl_options = {'REGISTER'}

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not asset_data.auto:
            self.report({'INFO'}, f"The auto import folder is not specified.")
            return {'CANCELLED'}

        threading.Thread(target=asset_data.update_auto, args=(context,)).start()
        self.report({'INFO'}, f"The auto import started.")

        return {'FINISHED'}


class ATOOL_OT_dolly_zoom(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.dolly_zoom"
    bl_label = "Dolly Zoom"
    bl_description = "Match the camera distance from the object to the target focal length in the way the screen size of the object is the same"
    bl_options = {'REGISTER', 'UNDO'}

    focal_length: bpy.props.FloatProperty(
        name="Focal Length",
        description="Target focal length",
        default = 50
        )
    
    def invoke(self, context , event):
        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, f"No selected objects. Select two objects. The active object must be a camera.")
            return {'CANCELLED'}

        active_object = context.object
        if active_object.type != 'CAMERA':
            self.report({'INFO'}, f"The active object must be a camera.")
            return {'CANCELLED'}

        if len(selected_objects) == 1:
            self.report({'INFO'}, f"Only a camera is selected. Select also an object.")
            return {'CANCELLED'}
        
        self.camera = bl_utils.Reference(active_object)
        self.focal_length = active_object.data.lens
        return self.execute(context)

    def execute(self, context):
        camera = self.camera.get()
        objects = context.selected_objects.copy()
        objects.remove(camera)
        
        target_point = sum((object.matrix_world.translation for object in objects), start = mathutils.Vector())/len(objects)
        dist = (camera.matrix_world.translation - target_point).length

        fov = camera.data.angle
        width = 2 * dist * math.tan(fov/2)
         
        if self.focal_length == 0:
            self.focal_length = 1
            self.report({'INFO'}, f"The focal length cannot be zero. Set to 1.")
            
        target_fov = 2 * math.atan(camera.data.sensor_width/(2 * self.focal_length))

        delta = width/(2 * math.tan(target_fov/2))

        delta = mathutils.Vector((0, 0, dist - delta))
        delta.rotate(camera.matrix_world.to_euler())

        camera.location -= delta
        camera.data.angle = target_fov

        return {'FINISHED'}


class ATOOL_OT_find_missing(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.find_missing"
    bl_label = "Find Missing"
    bl_description = "Find missing files with Everything"
    bl_options = {'REGISTER', 'UNDO'}

    prefer_descending: bpy.props.BoolProperty(name="Prefer Descending", default = True)
    prefer_asset_folder: bpy.props.BoolProperty(name="Prefer Asset Folder", default = True)

    by_closest_path_to: bpy.props.EnumProperty(
                name = 'Closest Path To',
                items = [
                    ('blend', 'Blend File', 'The blend file location if saved'),
                    ('last', 'Last Known Location', 'The last known location of the file'),
                    ('auto', 'Auto', 'Prefer the last known location if not got filtered')
                ],
                default = 'blend')

    # reload: bpy.props.BoolProperty(name="Reload", default = True)

    def invoke(self, context, event):

        missing_files = [] # type: typing.List[bl_utils.Missing_File]

        for block in bpy.data.images:
            if block.source == 'FILE':
                path = bl_utils.get_block_abspath(block)
                if not os.path.exists(path):
                    missing_files.append(bl_utils.Missing_File(path, block))

        for block in bpy.data.libraries:
            path = bl_utils.get_block_abspath(block)
            if not os.path.exists(path):
                missing_files.append(bl_utils.Missing_File(path, block))

        if not missing_files:
            self.report({'INFO'}, f"No missing files.")
            return {'CANCELLED'}
        self.missing_files = missing_files # type: typing.List[bl_utils.Missing_File]
        self.asset_data: data.AssetData
        self.asset_data = context.window_manager.at_asset_data

        self.process = threading.Thread(target=self.find_files)
        self.process.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

        
    def modal(self, context, event):

        if event.type == 'TIMER':
            if not self.process.is_alive():
                self.process.join()
                return self.execute(context)

        return {'PASS_THROUGH'}

    def find_files(self):

        self.missing_files_by_path = utils.list_by_key(self.missing_files, operator.attrgetter('path')) # type: typing.Dict[str, typing.List[bl_utils.Missing_File]]
        
        names = [os.path.basename(path) for path in self.missing_files_by_path.keys()]
        found_files = utils.EVERYTHING.find(names)
        if not found_files:
            self.found_files_by_name = {}
            return

        self.found_files_by_name = utils.list_by_key(found_files, lambda x: os.path.basename(x.lower())) # type: typing.Dict[str, typing.List[str]]
    
        self.asset_paths = [asset.path for asset in self.asset_data.values()]


    def filter_descending(self, file, found_files):
            filtered_files = []
            local_base = os.path.dirname(file)
            for path in found_files:
                try:
                    if os.path.commonpath((local_base, path)) == local_base:
                        filtered_files.append(path)
                except:
                    pass
            return filtered_files

    def filter_asset_folder(self, file, found_files):

        asset_folder = None
        for path in self.asset_paths:
            try:
                if os.path.commonpath((file, path)) == path:
                    asset_folder = path
                    break
            except:
                pass

        if asset_folder is None:
            return None

        filtered_files = []
        for path in found_files:
            try:
                if os.path.commonpath((path, asset_folder)) == asset_folder:
                    filtered_files.append(path)
            except:
                pass
        return filtered_files

    def execute(self, context):
        
        if not self.found_files_by_name:

            if not self.missing_files_by_path:
                self.report({'INFO'}, f"No missing files found.")

            for path in self.missing_files_by_path:
                self.report({'WARNING'}, f"{path} is missing but not found.")

            if self.missing_files_by_path:
                self.report({'WARNING'}, f"Some files are missing but not found.")
            
            return {'CANCELLED'}

        for path, files in self.missing_files_by_path.items():
            paths = self.found_files_by_name.get(os.path.basename(path))
            if not paths:
                self.report({'WARNING'}, f"{path} is missing but not found.")
                continue

            start = bpy.data.filepath if bpy.data.is_saved else path
            filtered = None

            if self.prefer_descending:
                filtered = self.filter_descending(start, paths)
                if filtered:
                    paths = filtered
                elif start != path:
                    filtered = self.filter_descending(path, paths)
                    if filtered:
                        paths = filtered

            if self.prefer_asset_folder:
                filtered = self.filter_asset_folder(start, paths)
                if filtered:
                    paths = filtered
                elif start != path:
                    filtered = self.filter_asset_folder(path, paths)
                    if filtered:
                        paths = filtered

            if self.by_closest_path_to == 'last':
                start = path
            elif self.by_closest_path_to == 'auto':
                if filtered == None and bpy.data.is_saved:
                    start = path
            
            closest_path = utils.get_closest_path(start, paths)
            for file in files: # blocks with the same missing source path
                file.closest_path = closest_path

        for file in self.missing_files:
            if file.closest_path is not None:
                self.report({'INFO'}, f"The {file.type.lower()} '{file.name}' has been found in {file.closest_path}.")
                file.reload()

        return {'FINISHED'}


class ATOOL_OT_remap_paths(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.remap_paths"
    bl_label = "Remap Path"
    bl_description = """Remap descending paths to relative and others to absolute"""
    bl_options = {'REGISTER', 'UNDO'}

    do_asset_path: bpy.props.BoolProperty(name="Remap asset's path relative to library if appropriate", default = True)

    def execute(self, context):
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report({'INFO'}, f"Save the blend before remapping.")
            return {'CANCELLED'}

        asset_data, id = get_asset_data_and_id(operator, context)
        library_exists = bool(asset_data.library)
        is_blend_asset = asset_data.is_sub_asset(blend_path)

        def is_descending(path):
            if library_exists and is_blend_asset and asset_data.is_sub_asset(path):
                return True

            blend_dir = os.path.dirname(blend_path)
            dir =  os.path.dirname(path)

            try:
                common_path = os.path.commonpath((blend_dir, dir))
                if os.path.commonpath((blend_dir, common_path)) == blend_dir:
                    return True
            finally:
                return False

        # cannot remap the path of a library image data block
        blocks = [block for block in bpy.data.images if block.source == 'FILE' and block.filepath and not block.library]
        blocks += [block for block in bpy.data.libraries if block.filepath]

        was_relative = 0
        was_absolute = 0
        to_relative = 0
        to_absolute = 0

        for block in blocks:
            path = block.filepath
            abs_path = bl_utils.get_block_abspath(block)
            if not os.path.exists(abs_path):
                continue

            if path.startswith('//'):
                was_relative += 1
            else:
                was_absolute += 1

            if is_descending(path):
                block.filepath = bpy.path.relpath(path)
                to_relative += 1
            else:
                block.filepath = abs_path
                to_absolute += 1

        if any((was_relative, was_absolute)):
            self.report({'INFO'}, f"Relative: {was_relative} -> {to_relative}. Absolute: {was_absolute} -> {to_absolute}.")
        else:
            self.report({'INFO'}, f"No external dependencies.")

        return {'FINISHED'}



class ATOOL_OT_unrotate(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.unrotate"
    bl_label = "Unrotate"
    bl_description = "Rotate the object to align the average normal and tangent of the selected faces with the global axises"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, f"Select an objects.")
            return {'CANCELLED'}

        for object in selected_objects:
            if object.type != 'MESH':
                self.report({'INFO'}, f"The object '{object.name}' is not a mesh.")
                continue

            mesh = object.data
            if not mesh:
                self.report({'INFO'}, f"The object '{object.name}' has no geometry data.")
                continue

            bm = bmesh.new()
            bm.from_mesh(mesh)

            # face =  bm.faces.active
            # normal = face.normal
            # tangent = face.calc_tangent_edge()

            faces = [face for face in bm.faces if face.select]

            if not faces:
                self.report({'INFO'}, f"The object '{object.name}' has no faces selected.")
                continue

            normals = [face.normal for face in faces]
            tangents = [face.calc_tangent_edge_pair() for face in faces]

            def get_average(vectors):
                vector = vectors[0]
                if len(vectors) > 1:
                    for n in vectors[1:]:
                        vector = vector.lerp(n, 0.5)
                return vector

            normal = get_average(normals)
            tangent = get_average(tangents)

            Z = mathutils.Vector((0,0,1))
            X = mathutils.Vector((-1,0,0))

            normal_rot = normal.rotation_difference(Z)

            tangent.rotate(normal_rot)
            tangent_rot = tangent.rotation_difference(X)
            swing, twist = tangent_rot.to_swing_twist('Z')
            twist = mathutils.Euler(Z * twist)

            normal_rot.rotate(twist)

            initial_rotation_mode = object.rotation_mode
            object.rotation_mode = 'QUATERNION'
            object.rotation_quaternion = normal_rot
            object.rotation_mode = initial_rotation_mode

        return {'FINISHED'}


class ATOOL_OT_icon_from_clipboard(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.icon_from_clipboard"
    bl_label = "Icon From Clipboard"
    bl_description = "Create asset preview from the clipboard"

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not (data and id):
            return {'CANCELLED'}

        threading.Thread(target=data.icon_from_clipboard, args = (id, context)).start()

        return {'FINISHED'}


class ATOOL_OT_render_icon(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.render_icon"
    bl_label = "Render Icon"
    bl_description = "Create an asset preview by rendering"

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not (data and id):
            return {'CANCELLED'}

        threading.Thread(target=data.render_icon, args = (id, context)).start()

        return {'FINISHED'}


class ATOOL_OT_import_unreal(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.import_unreal"
    bl_label = "Import Unreal"
    bl_description = "Import an Unreal Engine asset."

    directory: bpy.props.StringProperty(
        name="Asset Path",
        description="Folder with __unreal_assets__.json file",
        maxlen=1024,
        subtype='FILE_PATH',
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        directory = self.directory

        def to_path(name):
            return os.path.join(directory, name)

        json_file = to_path('__unreal_assets__.json')
        if not os.path.exists(json_file):
            self.report({'INFO'}, f"Not an unreal asset.")
            return {'CANCELLED'}

        with open(json_file) as info_file:
            info = json.load(info_file) # type: dict

        meshes = info.get("meshes")
        materials = info.get("materials")
        textures_info = info.get("textures")

        converted_textures = []

        if not any((meshes, materials, textures_info)):
            self.report({'INFO'}, f"Nothing to import.")
            return {'CANCELLED'}

        def get_mesh_material(name, use_fake_user = False):
            material = materials[name]
            if isinstance(material, list):

                textures = []
                invert_normal_y = {}
                for texture in material:

                    basename = texture
                    path = to_path(texture)
                    if not os.path.exists(path):
                        print(f"{path} does not exist.")
                        continue

                    converted_textures.append(path)

                    basename_without_suffix = os.path.splitext(basename)[0]
                    info = textures_info[basename_without_suffix]

                    path = image_utils.convert_unreal_image(path, bgr_to_rgb=info['is_bugged_bgr'])
                    invert_normal_y[path] = not info['flip_green_channel']
                    textures.append(path)

                material = materials[name] = node_utils.get_material(textures, name = name, invert_normal_y = invert_normal_y, use_fake_user = use_fake_user)
            return material

        import io_scene_fbx.import_fbx as import_fbx # type: ignore
        bl_increment_match = re.compile(r"\.001")

        bl_objects = []

        for name, slot_to_material in meshes.items():

            bpy.ops.object.select_all(action='DESELECT')
            import_fbx.load(self, context, filepath=to_path(name))
            mesh = context.selected_objects[0]
            bl_objects.append(mesh)

            for slot in mesh.material_slots:
                slot_name = slot.material.name

                if bl_increment_match.match(slot_name[-4:]):
                    if not slot_name in set(slot_to_material.keys()) | set(slot_to_material.values()):
                        slot_name = slot_name[:-4]

                material_name = slot_to_material[slot_name]
                bpy.data.materials.remove(slot.material)
                slot.material = get_mesh_material(material_name)

        # separate materials
        for name in materials:
            get_mesh_material(name, use_fake_user = True)

        separate_textures = []
        # separate textures
        for file in os.scandir(directory):

            if file.path in converted_textures:
                continue

            stem, ext = os.path.splitext(file.name)

            if ext.lower() not in ('.tga', '.bmp'):
                continue

            info = textures_info.get(stem)
            if info:
                bgr_to_rgb = info['is_bugged_bgr']
                is_gl_normal = info['flip_green_channel']
            else:
                bgr_to_rgb = False
                is_gl_normal = False

            path = image_utils.convert_unreal_image(file.path, bgr_to_rgb=bgr_to_rgb)

            separate_textures.append(path)

        if separate_textures:
            self.report({'INFO'}, f"{len(separate_textures)} separete textures are converted.")

        # bl_utils.arrange_by_materials(bl_objects) # not available for new meshes ?

        return {'FINISHED'}

class ATOOL_OT_copy_unreal_script(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.copy_unreal_script"
    bl_label = "Copy Unreal Script"
    bl_description = "Copy the Unreal script to execute inside Unreal"

    def execute(self, context):
        import pyperclip
        script = utils.get_script('unreal_export.py', read = True)
        pyperclip.copy(script)
        self.report({'INFO'}, f"The script has been copied.")
        return {'FINISHED'}


class ATOOL_OT_arrange_by_materials(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.arrange_by_materials"
    bl_label = "Arrange By Materials"
    bl_description = "Arrange the selected objects into a grid by their disjointed sets of materials"
    bl_options = {'REGISTER', 'UNDO'}

    by_images: bpy.props.BoolProperty(name="By Textures", default = True, description="Group by used texture path.")
    by_materials: bpy.props.BoolProperty(name="By Materials", default = True, description="Group by used materials.")

    def execute(self, context):
        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, f"No selected objects.")
            return {'CANCELLED'}

        bl_utils.arrange_by_materials(selected_objects, by_materials=self.by_materials, by_images=self.by_images)

        return {'FINISHED'}

class ATOOL_OT_move_asset_to_desktop(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.move_asset_to_desktop"
    bl_label = "Move To Desktop"
    bl_description = "Move the active asset to the desktop removing it from the library"

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not (data and id):
            return {'CANCELLED'}

        threading.Thread(target=data.move_asset_to_desktop, args = (id, context)).start()

        return {'FINISHED'}

class ATOOL_OT_open_blend(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_blend"
    bl_label = "Open Blend"
    bl_description = "Open the last modified blend file."

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        blend = asset.blend
        if not blend:
            self.report({'INFO'}, f"No blends.")
            return {'CANCELLED'}

        utils.os_open(self, blend)

        return {'FINISHED'}


class ATOOL_OT_clear_custom_normals(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.clear_custom_normals"
    bl_label = "Clear Custom Normals"
    bl_description = "Clear custom normals, sharp edges and recalculate normals"

    def execute(self, context):

        objects = [object for object in context.selected_objects if object.type == 'MESH' and object.data]
        if not objects:
            self.report({'INFO'}, f"No valid selected objects.")
            return {'CANCELLED'}

        for object in objects:
            mesh = object.data

            mesh.use_auto_smooth = False
            mesh.free_normals_split()

            bm = bmesh.new()
            bm.from_mesh(mesh)

            bmesh.ops.recalc_face_normals(bm, faces = bm.faces)
            for edge in bm.edges:
                edge.smooth = True

            bm.to_mesh(mesh)

        return {'FINISHED'}

class ATOOL_OT_smooth_lowpoly(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.smooth_lowpoly"
    bl_label = "Smooth Lowpoly"
    bl_description = "Smooth lowpoly geometry with modifies"

    def execute(self, context):

        objects = [object for object in context.selected_objects if object.type == 'MESH' and object.data]
        if not objects:
            self.report({'INFO'}, f"No valid selected objects.")
            return {'CANCELLED'}

        for object in objects:
            subdivision = object.modifiers.new(name = "Subdivision", type='SUBSURF')
            subdivision.subdivision_type = 'SIMPLE'
            subdivision.render_levels = 2
            subdivision.levels = 2
            subdivision.show_expanded = False

            smooth = object.modifiers.new(name = "LaplacianSmooth", type='LAPLACIANSMOOTH')
            smooth.iterations = 10
            smooth.lambda_factor = 0.35
            smooth.lambda_border = 0
            smooth.use_volume_preserve = False
            smooth.use_normalized = True
            smooth.show_expanded = False

        return {'FINISHED'}


class Image_Import_Properties:

    name: bpy.props.StringProperty(
        name='Name',
        options={'SKIP_SAVE'}
    )

    is_y_minus_normal_map: bpy.props.BoolProperty(
        name="Y- Normal Map",
        description="Invert the green channel for DirectX style normal maps",
        default = False
        )

    x: bpy.props.FloatProperty(name='X', min = 0, default = 1)
    y: bpy.props.FloatProperty(name='Y', min = 0, default = 1)
    z: bpy.props.FloatProperty(name='Z', min = 0, default = 0.1)

    def draw_images_import(self, layout):
        layout.alignment = 'LEFT'

        layout.prop(self, "name")
        layout.prop(self, "is_y_minus_normal_map")
        layout.prop(self, "x")
        layout.prop(self, "y")
        layout.prop(self, "z")

    def get_info(self):
        return {
            'name': self.name,
            "dimensions": {
                "x": self.x,
                "y": self.y,
                "z": self.z
            },
            'material_settings': {
                'Y- Normal Map': 1 if self.is_y_minus_normal_map else 0
            }
        }


class ATOOL_OT_import_files(bpy.types.Operator, Image_Import_Properties, Object_Mode_Poll):
    bl_idname = "atool.import_files"
    bl_label = "New From Files"
    bl_description = "Create an asset from selected files. Does not include folders, for this case use the auto folder or put the asset directly to the library"

    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        self.draw_images_import(layout)
        layout.separator()
        shader_editor_operator.draw_import_config(context, layout)

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not data:
            return {'CANCELLED'}

        if self.files[0].name == "":
            self.report({'INFO'}, "No files selected.")
            return {'CANCELLED'}
        files = [os.path.join(self.directory, file.name) for file in self.files]

        threading.Thread(target=data.add_files_to_library, args=(context, files, self.get_info())).start()

        return {'FINISHED'}


class ATOOL_OT_render_partial(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.render_partial"
    bl_label = "Render Partial Via CMD"
    bl_description = "Render image in parts from the command line with .bat file"

    dicing: bpy.props.IntProperty(default=2)

    def invoke(self, context, event):

        if not context.scene.camera:
            self.report({'INFO'}, "Set a camera.")
            return {'CANCELLED'}

        if not bpy.data.is_saved:
            self.report({'INFO'}, "Save the file to render.")
            return {'CANCELLED'}

        if bpy.data.is_dirty:
            self.report({'WARNING'}, "The file is dirty. You might what to save it.")

        return context.window_manager.invoke_props_dialog(self, width = 200)

    def execute(self, context):

        def escape(string):
            if ' ' in string:
                string = f'"{string}"'
            return string

        if bpy.app.version < (2,91,0):
            python_binary = bpy.app.binary_path_python
        else:
            python_binary = sys.executable

        python_binary = escape(python_binary)
        blender_binary = escape(bpy.app.binary_path)

        script = escape(utils.get_script('render_worker.py'))

        blend_path = escape(bpy.data.filepath)

        bat_file_path = os.path.join(os.path.dirname(bpy.data.filepath) , 'partial_render.bat')

        with open(bat_file_path, 'w',encoding='utf-8') as bat_file:
            bat_file.write(f'{python_binary} {script} -blender {blender_binary} -file {blend_path} -dicing {self.dicing}')

        self.report({'INFO'}, "Bat file created.")

        return {'FINISHED'}


class ATOOL_OT_test_draw(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.test_draw"
    bl_label = "Test Draw"

    def execute(self, context):

        # threading.Thread(target=work, args=(context.region, 1), daemon=True).start()
        threading.Thread(target=self.work, args=(context.region, 0), daemon=True).start()

        return {'FINISHED'}
    
    @staticmethod
    def work(region, indent):
        divider = 120
        import time
        from timeit import default_timer as timer

        total_time = 60
        init_time = 1/divider
        sleep_time = init_time
        
        for i in bl_utils.iter_with_progress(range(divider * total_time), indent = indent, prefix = str(indent)):
            start = timer()
            time.sleep(sleep_time)
            t = timer() - start

            if t > init_time:
                sleep_time -= min(sleep_time/100 ,0.001 / min( 0.1, t/init_time))
            elif t < init_time:
                sleep_time += min(sleep_time/100 ,0.001 / min( 0.1, init_time/t))
        
        print("sleep_time:", sleep_time)
        print("init:", init_time)
        print("sleep_time/init_time:", sleep_time/init_time)
    

class ATOOL_OT_show_current_blend(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.show_current_blend"
    bl_label = "Show Current Blend"
    bl_description = "Show the current blend file in the file browser"

    def execute(self, context):

        if not bpy.data.is_saved:
            self.report({'INFO'}, f"The blend is not saved.")
            return {'CANCELLED'}

        utils.os_show(self, (bpy.data.filepath, ))

        return {'FINISHED'}


class ATOOL_OT_replace_objects_with_active(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.replace_objects_with_active"
    bl_label = "Replace With Active"
    bl_description = "Replace the selected objects with copies of the active"

    def execute(self, context: bpy.types.Context):
        
        active_object = context.object # type: bpy.types.Object
        if not active_object:
            self.report({'INFO'}, f"No active object.")
            return {'CANCELLED'}
        
        selected_objects = context.selected_objects # type: typing.List[bpy.types.Object]
        selected_objects.remove(active_object)
        if not selected_objects:
            self.report({'INFO'}, f"Select at least two objects")
            return {'CANCELLED'}
        
        for object in selected_objects:
            
            object_copy = active_object.copy() # type: bpy.types.Object
            # object_copy.data = active_object.data.copy()
            
            for collection in object.users_collection:
                collection.objects.link(object_copy)
            
            object_copy.matrix_world = object.matrix_world
            
        bpy.data.batch_remove(selected_objects)

        return {'FINISHED'}


class ATOOL_OT_cap_resolution(bpy.types.Operator):
    bl_idname = "atool.cap_resolution"
    bl_label = "Cap Resolution"
    bl_description = "Cap Resolution"
    bl_options = {'REGISTER', 'UNDO'}
    
    cap_max_x_res: bpy.props.IntProperty(name='X Max Resolution', default = 3840)
    cap_max_y_res: bpy.props.IntProperty(name='Y Max Resolution ', default = 2160)

    def execute(self, context: bpy.types.Context):
        x_res = context.scene.render.resolution_x
        y_res = context.scene.render.resolution_y

        max_x_res = self.cap_max_x_res
        max_y_res = self.cap_max_y_res
        
        def cap_by_x():
            context.scene.render.resolution_x = max_x_res
            context.scene.render.resolution_y = y_res * max_x_res / x_res
        
        def cap_by_y():
            context.scene.render.resolution_x = x_res * max_y_res / y_res
            context.scene.render.resolution_y = max_y_res
            
        if x_res > y_res:
            if x_res > max_x_res:
                cap_by_x()
                
            elif y_res > max_y_res:
                cap_by_y()
        else:
            if y_res > max_y_res:
                cap_by_y()
                
            elif x_res > max_x_res:
                cap_by_x()   

        return {'FINISHED'}
    

class ATOOL_OT_select_linked(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.select_linked"
    bl_label = "Select Linked"
    bl_description = "Select objects with the same dependencies"

    def execute(self, context: bpy.types.Context):
        
        selected_objects = context.selected_objects # type: typing.List[bpy.types.Object]
        if not selected_objects:
            self.report({'INFO'}, "No object selected.")
            return {'CANCELLED'}
        
        dependencies = bl_utils.Dependency_Getter()
        
        selected_dependencies = []
        for object in selected_objects:
            selected_dependencies.extend(dependencies.get_object_dependencies_by_type(object))
        
        selected_dependencies = set(selected_dependencies)
        
        for object in context.selectable_objects:
            
            if selected_dependencies.isdisjoint(dependencies.get_object_dependencies_by_type(object)):
                continue
            
            object.select_set(True)

        return {'FINISHED'}
    
class ATOOL_OT_copy_attribution(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.copy_attribution"
    bl_label = "Copy Attribution"
    bl_description = "Copy the used assets attributions"

    def execute(self, context: bpy.types.Context):
        
        objects = bpy.data.objects
        if not objects:
            self.report({'INFO'}, "No objects.")
            return {'CANCELLED'}
        
        asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not asset_data:
            self.report({'INFO'}, "The library is empty.")
            return {'CANCELLED'}
        
        objects = asset_data.get_assets_from_objects(objects)
        if not objects:
            self.report({'INFO'}, "No assets found.")
            return {'CANCELLED'}
        
        
        all_assets = [] # type: typing.List[data.Asset]
        for object, assets in objects.items():
            all_assets.extend(assets)
        all_assets = utils.deduplicate(all_assets)
        
        text = ""
        asset_row_names = ('name', 'url', 'author', 'author_url', 'licence', 'licence_url')
        for asset in all_assets:
            text += "\t".join([asset.get(name, '') for name in asset_row_names])
            text += "\t" + ", ".join(asset.get('tags', ()))
            text += "\n"
        
        import pyperclip
        pyperclip.copy(text)

        return {'FINISHED'}
    
    

class ATOOL_OT_delete_file_cache(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.delete_file_cache"
    bl_label = "Delete Asset File Cache"
    bl_description = "Delete the asset's file cache"

    def execute(self, context: bpy.types.Context):
        
        data, id = get_asset_data_and_id(self, context)
        if not (data and id):
            return {'CANCELLED'}
        
        asset = data[id]
        
        file_info = asset.info.get("file_info")
        if file_info == None:
            self.report({'INFO'}, "No file cache.")
            return {'CANCELLED'}
        
        asset.info.pop('file_info')
        asset.save(update = False)
        self.report({'INFO'}, "The file cache has been deleted.")
        
        return {'FINISHED'}
    
    
class ATOOL_OT_delete_all_file_caches(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.delete_all_file_caches"
    bl_label = "Delete All Asset File Caches"
    bl_description = "Delete file caches of all the assets"
    
    def draw(self, context):
        layout = self.layout
        # layout.alignment = 'LEFT'
        layout.label(text = "All the file caches will be deleted. This is not reversible.", icon='ERROR')
    
    def invoke(self, context, event):

        self.asset_data = context.window_manager.at_asset_data # type: data.AssetData
        if not self.asset_data:
            operator.report({'INFO'}, "The library is empty.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=350)

    def execute(self, context: bpy.types.Context):
        
        counter = 0
        for asset in self.asset_data.values():
            file_info = asset.info.get("file_info")
            if file_info == None:
                continue
        
            asset.info.pop("file_info")
            asset.save(update = False)
            counter += 1
            
        if counter:
            self.report({'INFO'}, f"{counter} file caches deleted.")
        else:
            self.report({'INFO'}, f"No file caches found.")
        
        return {'FINISHED'}
    

class ATOOL_OT_import_sketchfab(bpy.types.Operator):
    bl_idname = "atool.import_sketchfab"
    bl_label = "Import Sketchfab ZIP"
    bl_description = "WIP"
    bl_options = {'REGISTER', 'UNDO'}
    
    geometry_type: bpy.props.StringProperty(
        options={'HIDDEN'}
    )
    
    __annotations__.update(bpy.types.IMPORT_SCENE_OT_obj.__annotations__)
    __annotations__.update(bpy.types.IMPORT_SCENE_OT_fbx.__annotations__)
    
    filepath: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        # layout.alignment = 'LEFT'
        # layout.use_property_decorate = False
        # layout.prop(self, 'filepath')
           
        class Dummy_sfile:
            active_operator = self
        
        class Dummy_Context:
            space_data = Dummy_sfile()
        
        main_self =  self
        class Dummy_Self:
            def __init__(self, label: str = None):
                self.layout = main_self.layout.box()
                if label != None:
                    self.layout.label(text = label)
            
        dummy_context = Dummy_Context()
        
        if self.geometry_type == '.obj':
            layout.label(text = "OBJ Import:")
            bpy.types.OBJ_PT_import_include.draw(Dummy_Self("Include"), dummy_context)
            bpy.types.OBJ_PT_import_transform.draw(Dummy_Self("Transform"), dummy_context)
            bpy.types.OBJ_PT_import_geometry.draw(Dummy_Self("Geometry"), dummy_context)
        elif self.geometry_type == '.fbx':
            layout.label(text = "FBX Import:")
            bpy.types.FBX_PT_import_include.draw(Dummy_Self("Include"), dummy_context)
            bpy.types.FBX_PT_import_transform.draw(Dummy_Self("Transform"), dummy_context)
            bpy.types.FBX_PT_import_transform_manual_orientation.draw_header(Dummy_Self("Transform Manual"), dummy_context)
            bpy.types.FBX_PT_import_transform_manual_orientation.draw(Dummy_Self(), dummy_context)
            bpy.types.FBX_PT_import_animation.draw_header(Dummy_Self("Animation"), dummy_context)
            bpy.types.FBX_PT_import_animation.draw(Dummy_Self(), dummy_context)
            bpy.types.FBX_PT_import_armature.draw(Dummy_Self("Armature"), dummy_context)

    def execute(self, context: bpy.types.Context):
        # self.path = r'D:\asset\data\worldmachine-terrain\worldmachine-terrain.zip'
        # self.path = r'D:\source\my_misc\projects_temp_loc\any_no_ref_1\temp_asset\desert-runner.zip'
        path = self.filepath
        
        stem, ext = os.path.splitext(os.path.basename(path))
        extraction_dir = os.path.join(bpy.app.tempdir, stem)
        source_dir = os.path.join(extraction_dir, 'source')
        textures_dir = os.path.join(extraction_dir, 'textures')
        
        files = utils.extract_zip(path, path = extraction_dir, extract = 'False')
        
        for file in files:
            if not (os.path.commonpath((source_dir, file)) == source_dir or os.path.commonpath((textures_dir, file)) == textures_dir):
                self.report({'INFO'}, f"Not valid sketchfab zip.")
                return {'CANCELLED'}
        
        if not self.is_repeat():
            self.extracted_files = utils.extract_zip(path, path = extraction_dir)
        
        files = self.extracted_files
        files = utils.File_Filter.from_files(files)
        
        geometry_files = files.get_by_type('geometry')
        
        if not geometry_files:
            self.report({'INFO'}, f"No geometry to import or file is not supported.")
            return {'CANCELLED'}
        
        geometry = geometry_files[0]
        
        suffix = geometry.suffix.lower()
        
        init_selected_objects = context.selected_objects
        for object in init_selected_objects:
            object.select_set(False)
            
        import_objects = []
        
        if suffix == '.obj':
            self.geometry_type = '.obj'
            bpy.ops.import_scene.obj(filepath = str(geometry))
            
        elif suffix == '.fbx':
            self.geometry_type = '.fbx'
                        
            key_args = {}
            for key in bpy.types.IMPORT_SCENE_OT_fbx.__annotations__.keys():
                value = getattr(self, key)
                if value:
                    key_args[key] = value
                    
            key_args['filepath'] = str(geometry)
            bpy.ops.import_scene.fbx(**key_args) 
            
        else:
            self.report({'INFO'}, f"No geometry was imported.")
            return {'CANCELLED'}
        
        import_objects = context.selected_objects
            
        image_files = [str(file) for file in files.get_by_type('image')]
            
        for object in import_objects:
            for material in object.data.materials:
                
                node_tree = node_utils.Node_Tree_Wrapper(material.node_tree)
                
                image_nodes = node_tree.get_by_bl_idname('ShaderNodeTexImage')
                
                # config = shader_editor_operator.get_definer_config(context)
                config = type_definer.Filter_Config()
                
                if image_nodes:
                    with image_utils.Image_Cache_Database() as db:
                        images = [image_utils.Image.from_block(node.image, define_type = False, type_definer_config = config) for node in image_nodes]
                    config.set_common_prefix((image.name for image in images))
                else:
                    config.set_common_prefix_from_paths(image_files)
                    with image_utils.Image_Cache_Database() as db:
                        images = [image_utils.Image.from_db(image, db, type_definer_config = config) for image in image_files]
                        
                # principled = node_tree.find_principled(ignore_inputs = True)
                # if principled:
                #     for child in principled.all_children:
                #         child.delete()
                
                images_filtered, report_list = type_definer.filter_by_config(images, config)
                    
                for report in report_list:
                    self.report(*report)
                
                new_material = node_utils.Material.from_image_objects(images_filtered)
                new_material.target_material = material
                new_material.set_viewport_colors(new_material.bl_material)
                
                excluded_images = set(images).difference(images_filtered)
                for index, image in enumerate(excluded_images):
                    node_tree = new_material.node_tree
                    image_node = node_tree.new('ShaderNodeTexImage')
                    image_node.image = bpy.data.images.load(filepath = image.path, check_existing=True)
                    x, y = image_node.location
                    image_node.location = x - 800, - y * index

                return {'FINISHED'}

        return {'FINISHED'}

class ATOOL_OT_import_sketchfab_zip_caller(bpy.types.Operator, Object_Mode_Poll, bl_utils.Operator_Later_Caller):
    bl_idname = "atool.import_sketchfab_zip_caller"
    bl_label = "Import SketchFab ZIP"
    bl_description = "Import SketchFab ZIP file. Supported: FBX, OBJ"
    
    filename_ext = '.zip'
    
    filter_glob: bpy.props.StringProperty(
        default='*.zip',
        options={'HIDDEN'}
    )
    
    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )
    
    filepath: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'}
    )
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context: bpy.types.Context):
        func = self.get_later_caller(bpy.ops.atool.import_sketchfab, execution_context = 'INVOKE_DEFAULT', undo = True, filepath = self.filepath)
        # func = self.get_later_caller(bpy.ops.atool.import_sketchfab, context.copy(), 'EXEC_DEFAULT', True, filepath = self.filepath)
        bpy.app.timers.register(func)
        return {'FINISHED'}


register.property(
    'at_adapt_subdiv_setup_object', 
    bpy.props.PointerProperty(type = bpy.types.Object),
    bpy.types.Object
)
    
class ATOOL_OT_setup_adaptive_subdivision(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.setup_adaptive_subdivision"
    bl_label = "Adapt Subdiv Setup"
    bl_description = "FOR BLENDER 3! Apply an adaptive subdivision setup for the selected objects for the active camera"
    bl_options = {'REGISTER', 'UNDO'}
    
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
        min= 1
        )
    subdivision_rate: bpy.props.IntProperty(
        name="The subdivision rate for a base mash to generated a close-up mesh.",
        default = 4,
        min = 0,
        soft_max = 7,
        options = {'SKIP_SAVE'}
        )
    
    def execute(self, context: bpy.types.Context):
        
        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "Select an object.")
            return {'CANCELLED'}
        
        meshes = [object for object in selected_objects if object.type == 'MESH']
        if not meshes:
            self.report({'INFO'}, "Only mesh objects supported.")
            return {'CANCELLED'}
        
        object = context.object
        initial_active_object = object
        
        def copy_object(object):
            
            object_copy = object.copy()
            for collection in object.users_collection:
                collection.objects.link(object_copy)
                
            object.at_adapt_subdiv_setup_object = object_copy
            object_copy.select_set(False)
            object_copy.name = object.name + ' AS Setup'
            
            return object_copy
        
        def move_modifier_to_first(modifier):
            if bpy.app.version < (2,90,0):
                for _ in range(len(object_copy.modifiers)):
                    bpy.ops.object.modifier_move_up(modifier = modifier.name)
            else:
                bpy.ops.object.modifier_move_to_index(modifier = modifier.name, index=0)   
        
        particle_systems = []
        if object.at_adapt_subdiv_setup_object:
            prev_object = object.at_adapt_subdiv_setup_object
            particle_systems = [modifier.particle_system.settings for modifier in prev_object.modifiers if modifier.type == 'PARTICLE_SYSTEM'] # type: typing.List[bpy.types.ParticleSettings]
            bpy.data.objects.remove(object.at_adapt_subdiv_setup_object)
            
        for modifier_name in ('__AT_ASS_SUBSURF__', '__AT_ASS_DATA_TRANSFER__', '__AT_ASS_DISPLACE__'):
            modifier = object.modifiers.get(modifier_name)
            if modifier:
                object.modifiers.remove(modifier)
            
        from . import property_panel_operator
        
        if len(object.data.vertices) < 1000:
            # property_panel_operator.ATOOL_OT_add_camera_visibility_vertex_group.execute(self, context)
            override = bl_utils.get_context_copy_with_object(context, object)
            bpy.ops.atool.add_camera_visibility_vertex_group(override)
            
            object_copy = copy_object(object)
            object_copy.data = object_copy.data.copy()
            
            # override = bl_utils.get_context_copy_with_object(context, object_copy)
            # bpy.ops.object.mode_set(mode='OBJECT')
            # bpy.ops.object.select_all(action='DESELECT')
            
            has_subsurf_modifier = False
            for modifier in object_copy.modifiers:
                if modifier.type == 'SUBSURF':
                    modifier_name = modifier.name
                    has_subsurf_modifier = True
                    break
                
            if not has_subsurf_modifier:
                modifier = object_copy.modifiers.new('__AT_ASS_SUBSURF__', 'SUBSURF')
                modifier.show_expanded = False
                modifier.subdivision_type = 'SIMPLE'
                modifier.levels = self.subdivision_rate
            
            context.view_layer.objects.active = object_copy
            bpy.ops.object.select_all(action='DESELECT')
            object_copy.select_set(True)
            bpy.ops.object.convert()
            
            # for modifier in object_copy.modifiers:
            #     override = bl_utils.get_context_copy_with_object(context, object_copy)
            #     bpy.ops.object.modifier_apply(override, modifier=modifier.name)
            
            # context.view_layer.objects.active = object_copy
            # bpy.ops.object.modifier_apply(modifier="__AT_ASS_SUBSURF__")
            
            # depsgraph = context.evaluated_depsgraph_get()
            # object_copy = object_copy.evaluated_get(depsgraph)
            # object_copy.data = object_copy.to_mesh(depsgraph = depsgraph)

            override = bl_utils.get_context_copy_with_object(context, object_copy)
            bpy.ops.atool.add_camera_visibility_vertex_group(override)
            # property_panel_operator.ATOOL_OT_add_camera_visibility_vertex_group.execute(self, context)
            
            modifier = object_copy.modifiers.new('__AT_ASS_MASK__', 'MASK')
            modifier.show_expanded = False
            modifier.vertex_group = 'camera_visibility'
            if bpy.app.version >= (3,0,0):
                modifier.use_smooth = True # this is necessary for some reason
                
            override = bl_utils.get_context_copy_with_object(context, object_copy)
            bpy.ops.object.modifier_apply(override, modifier="__AT_ASS_MASK__")
            
            if not has_subsurf_modifier:
                modifier = object.modifiers.new('__AT_ASS_SUBSURF__', 'SUBSURF')
                modifier.show_expanded = False
                modifier.subdivision_type = 'SIMPLE'
                modifier.levels = self.subdivision_rate
            
            modifier = object.modifiers.new('__AT_ASS_DATA_TRANSFER__', 'DATA_TRANSFER')
            modifier.show_expanded = False
            modifier.object = object_copy
            modifier.use_vert_data = True
            modifier.data_types_verts = {'VGROUP_WEIGHTS'}
            modifier.layers_vgroup_select_src = 'camera_visibility'
            modifier.layers_vgroup_select_dst = 'camera_visibility'
            
            modifier = object.modifiers.new('__AT_ASS_DISPLACE__', 'DISPLACE')
            modifier.show_expanded = False
            modifier.vertex_group = "camera_visibility"
            modifier.strength = -0.05
            
        else:
            override = bl_utils.get_context_copy_with_object(context, object)
            bpy.ops.atool.add_camera_visibility_vertex_group(override)
            # property_panel_operator.ATOOL_OT_add_camera_visibility_vertex_group.execute(self, context)
            
            object_copy = copy_object(object)

            modifier = object.modifiers.new('__AT_ASS_DISPLACE__', 'DISPLACE')
            modifier.vertex_group = 'camera_visibility'
            modifier.strength = -0.05

            modifier = object_copy.modifiers.new('__AT_ASS_MASK__', 'MASK')
            modifier.vertex_group = 'camera_visibility'
            if bpy.app.version >= (3,0,0):
                modifier.use_smooth = True
                
        context.view_layer.objects.active = initial_active_object
                
        for particle_system in particle_systems:
            override = bl_utils.get_context_copy_with_object(context, object_copy)
            bpy.ops.object.particle_system_add(override)
            object_copy.particle_systems.active.settings = particle_system
            
        if particle_systems:
            override = bl_utils.get_context_copy_with_object(context, object_copy)
            bpy.ops.atool.match_displacement(override)    
        
        from . import shader_editor_operator
        shader_editor_operator.ensure_adaptive_subdivision(self, context, object_copy, object_copy.active_material)
        
        return {'FINISHED'}


class ATOOL_OT_add_remote_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.add_remote_asset"
    bl_label = "Add Remote Asset"
    bl_description = "Create a remote asset from a folder without using the library folder"

    directory: bpy.props.StringProperty(
        subtype='DIR_PATH',
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):

        data, id = get_asset_data_and_id(self, context)
        if not data:
            return {'CANCELLED'}

        if not os.path.exists(self.directory):
            self.report({'INFO'}, "The folder does not exists.")
            return {'CANCELLED'}

        json_path = os.path.join(self.directory, '__asset__.json')
        if os.path.exists(json_path):
            self.report({'INFO'}, "The folder is already an asset. Only one asset per folder is allowed.")
            return {'CANCELLED'}

        threading.Thread(target=data.add_remote_asset, args=(self.directory, context)).start()

        return {'FINISHED'}


class ATOOL_OT_open_url(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_url"
    bl_label = "URL"
    bl_description = "Click to open"

    url: bpy.props.StringProperty()

    def execute(self, context):
       
        utils.web_open(self.url)
            
        return {'FINISHED'}