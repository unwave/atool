import itertools
import math
import os
import queue
import subprocess
import sys
import threading
import typing
from datetime import datetime

import bpy
import bmesh
import mathutils

from . import image_utils
from . import type_definer
from . data import AssetData, get_browser_items
from . shader_editor_operator import Material_Import_Properties, apply_material, get_definer_config
from . bl_utils import Reference
from . import utils
from . import bl_utils

# import webbrowser
# import numpy
# import uuid


class Object_Mode_Poll():
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'VIEW_3D' and context.mode == 'OBJECT'


def get_linked_objects_from_selected(operator, context):

        report = operator.report
        selected_objects = context.selected_objects

        if not selected_objects:
            report({'INFO'}, "Nothing is selected. Select a linked object.")
            return []

        objects_with_data = [object for object in selected_objects if object.data]

        if not objects_with_data:
            report({'INFO'}, "No objects with data.")
            return []

        linked_objects = [object for object in objects_with_data if object.data.library]

        if not linked_objects:
            report({'INFO'}, "No linked objects.")
            return []

        return linked_objects

def get_unique_libraries_from_selected_objects(operator, context):

    linked_objects = get_linked_objects_from_selected(operator, context)
    return list({object.data.library for object in linked_objects})
    
    
def get_current_browser_asset(operator, context):
    
    asset_data = context.window_manager.at_asset_data # type: AssetData
    if not asset_data:
        operator.report({'INFO'}, "The library is empty.")
        return

    asset_id = context.window_manager.at_asset_previews
    if asset_id == "/":
        operator.report({'INFO'}, "Select an asset.")
        return

    asset = asset_data.get(asset_id)
    if not asset:
        operator.report({'INFO'}, "Select an asset. Current is not available.")
        return

    return asset

class ATOOL_OT_open_library_in_file_browser(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.os_open"
    bl_label = "Open File Browser"
    bl_description = "Open the selected objects libraries in a file browser"

    def execute(self, context):

        files = []

        for library in get_unique_libraries_from_selected_objects(self, context):
            file_dir = os.path.realpath(bpy.path.abspath(library.filepath))
            files.append(file_dir)
        
        if files:
            threading.Thread(target=utils.os_show, args=(self, files,)).start()
        
        return {'FINISHED'}


class ATOOL_OT_reload_library(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.reload_library"
    bl_label = "Reload Library"
    bl_description = "Reload the selected objects libraries"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        libraries_to_reload = get_unique_libraries_from_selected_objects(self, context)

        # test it because it seems you cannot undo a library reload
        # https://docs.blender.org/api/current/bpy.types.Operator.html#bpy.types.Operator.execute
        if not libraries_to_reload:
            return {'CANCELLED'}
        
        for library in libraries_to_reload:
            library.reload()
            self.report({'INFO'}, f"{library.name} has been reloaded.")
        
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
    bl_options = {'REGISTER', 'UNDO'}

    # link_back: bpy.props.BoolProperty(name = "Link Back", default = False)
    # Will undo work with the database?

    def execute(self, context):

        selected_objects = context.selected_objects
        if not selected_objects:
            self.report({'INFO'}, "No selected objects.")
            return {'CANCELLED'}

        objects_to_move = [object for object in selected_objects if object.data and not object.data.library]
        if not objects_to_move:
            self.report({'INFO'}, "No valid objects.")
            return {'CANCELLED'}

        asset_data = context.window_manager.at_asset_data # type: AssetData

        if not asset_data.library:
            self.report({'INFO'}, "No library folder specified.")
            return {'CANCELLED'}

        template_info = context.window_manager.at_template_info
        

        info = {}
        info["name"] = template_info.name
        info["url"] = template_info.url
        info["author"] = template_info.author
        info["licence"] = template_info.licence
        info["tags"] = template_info.tags.split()


        asset_id, blend_file_path = asset_data.add_to_library(context, objects_to_move, info)

        with bpy.data.libraries.load(filepath=blend_file_path, link=True) as (data_from, data_to): 
            data_to.objects = data_from.objects

        for linked_object, original_object in zip(data_to.objects, objects_to_move):
            original_object_matrix_world = original_object.matrix_world
            bpy.data.objects.remove(original_object)

            object_overried = linked_object.override_create()
            object_overried.matrix_world = original_object_matrix_world
            context.collection.objects.link(object_overried)
            object_overried["atool_id"] = asset_id
            linked_object["atool_id"] = asset_id
            
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

    def draw_blend_import(self, layout):
        layout.prop(self, "link")
        layout.prop(self, "ignore")

    def import_blend(self, context):
        self.blend: str
        self.atool_id: str

        with bpy.data.libraries.load(self.blend, link = self.link) as (data_from, data_to):
            data_to.collections = data_from.collections
            data_to.objects = data_from.objects
            
        imported_library = None
        for library in bpy.data.libraries:
            if library.filepath == self.blend:
                imported_library = library
                if not (data_to.collections or data_to.objects):
                    self.report({'INFO'}, "Nothing to import from the blend file.")
                    bpy.data.libraries.remove(library)
                    return {'FINISHED'}
                library_version = library.version
                if library_version < (2,80,0):
                    report = "2.79- blend file."
                    if data_to.collections:
                        report += f" {len(data_to.collections)} groups are imported as collections."
                    self.report({'INFO'}, report)
        
        objects = []
        for object in data_to.objects:
            if self.ignore and object.name.startswith(self.ignore):
                bpy.data.objects.remove(object)
            else:
                objects.append(object)

        imported = {}
        final_objects = []

        def add_object(object, collection):
            object["atool_id"] = self.atool_id

            if self.link:
                imported_object = imported.get((object.name, object.library))
                if imported_object:
                    return imported_object

                object_overried = object.override_create(remap_local_usages=False)
                object_overried["atool_id"] = self.atool_id
                collection.objects.link(object_overried)
                object_overried.select_set(True)

                imported[(object.name, object.library)] = object_overried
                return object_overried
            else:
                collection.objects.link(object)
                object.select_set(True)
                return object

        collection_objects = []
        for collection in data_to.collections:

            if self.ignore and collection.name.startswith(self.ignore):
                for object in collection.all_objects:
                    bpy.data.objects.remove(object)
                    objects.remove(object)
                bpy.data.collections.remove(collection)
                continue

            new_collection = bpy.data.collections.new(collection.name)
            context.scene.collection.children.link(new_collection)

            for object in collection.all_objects:
                collection_objects.append(object)
                final_objects.append(add_object(object, new_collection))
    
        for object in objects:
            if object in collection_objects:
                continue
            final_objects.append(add_object(object, context.collection))

        if not self.link:
            return {'FINISHED'}

        imported_objects = {object.name: object for object in final_objects}

        for object in imported_objects.values():
            object.use_fake_user = False
            parent = object.parent
            if parent and parent.library == imported_library:
                object.parent = imported_objects.get(parent.name)

        return {'FINISHED'}


class ATOOL_OT_import_asset(bpy.types.Operator, Object_Mode_Poll, Material_Import_Properties, Blend_Import):
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

        self.asset_type = None

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
        self.asset = asset
        self.atool_id = asset.id

        blends = [file.path for file in os.scandir(asset.path) if file.path.endswith(".blend")]
        if blends:
            self.blend = max(blends, key=os.path.getmtime)
            self.asset_type = 'blend'
            return self.execute(context)

        images = asset.get_imags()
        if images:

            self.object = None
            self.material = None

            object = context.object
            if object:
                self.object = Reference(object)
                material = object.active_material
                if material:
                    self.material = Reference(material)

            self.asset_type = 'material'

            info = self.asset.info

            self.dimensions = {'x': 1, 'y': 1, 'z': 0.1}
            self.dimensions.update(info["dimensions"])

            self.asset_name = info.get("name")

            config = get_definer_config(context)
            
            self.queue = queue.Queue()
            config["queue"] = self.queue
            config["asset"] = self.asset

            self.process = threading.Thread(target=type_definer.define, args=(images, config))
            self.process.start()

            wm = context.window_manager
            self._timer = wm.event_timer_add(0.1, window=context.window)
            wm.modal_handler_add(self)
            return {'RUNNING_MODAL'}
            
        self.report({'INFO'}, "Nothing to import.")
        return {'CANCELLED'}

    def modal(self, context, event):

        if event.type == 'TIMER':
            if not self.process.is_alive():
                self.process.join()

                try:
                    result = self.queue.get(block=False)[0]
                except:
                    self.report({"ERROR"}, "The type definer failed. See the console for the error.")
                    return {'CANCELLED'}

                for report in result["report"]:
                    self.report(*report)

                if not result["ok"]:
                    return {'FINISHED'}

                self.images = result["images"]
                self.material_name = result["material_name"]

                return self.execute(context)
                
        return {'PASS_THROUGH'}

    def execute(self, context):

        if self.asset_type == 'blend':
            return self.import_blend(context)

        assert self.asset_type == 'material'

        for image in self.images:
            image.data_block = bpy.data.images.load(filepath = image.path, check_existing=True)
            image.set_bl_props(image.data_block)

        object = None
        material = None

        if self.object:
            object = self.object.get()
        if self.material:
            material = self.material.get()

        return apply_material(self, context, object, material)


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

        self.report({'INFO'}, "The zip files have beed extracted.")
        return {'FINISHED'}
        

class ATOOL_OT_open_gallery(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_gallery"
    bl_label = "Open Gallery"
    bl_description = "Open Gallery"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        images = [file.path for file in os.scandir(asset.gallery)]
        if not images:
            self.report({'INFO'}, "No gallery.")
            return {'CANCELLED'}
        latest_image = max(images, key=os.path.getmtime)
        utils.os_open(self, latest_image)
            
        return {'FINISHED'}


class ATOOL_OT_pin_active_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.pin_active_asset"
    bl_label = "Pin Active Asset"
    bl_description = "Pin the active object if it is an asset"

    def execute(self, context):

        asset = context.object
        if not asset:
            self.report({'INFO'}, "No active object.")
            return {'CANCELLED'}

        id = asset.get("atool_id")
        if not id:
            self.report({'INFO'}, "The active object is not an asset.")
            return {'CANCELLED'}

        context.window_manager.at_search = "id:" + id

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

    button_index : bpy.props.IntProperty()

    def execute(self, context):
        wm = context.window_manager
        asset_data = wm.at_asset_data # type: AssetData
        
        last_index = len(get_browser_items(None, None)) - 1
        current_index = wm.get("at_asset_previews", 0)

        if self.button_index == 0: # previous page
            asset_data.go_to_prev_page()
            wm["at_asset_previews"] = min(wm["at_asset_previews"], len(get_browser_items(None, None)) - 1)
        elif self.button_index == 1: # previous asset
            if current_index == 0:
                asset_data.go_to_prev_page()
                wm["at_asset_previews"] = len(get_browser_items(None, None)) - 1
            else:
                wm["at_asset_previews"] = current_index - 1
        elif self.button_index == 2: # next asset
            if current_index == last_index:
                asset_data.go_to_next_page()
                wm["at_asset_previews"] = 0
            else:
                wm["at_asset_previews"] = current_index + 1
        elif self.button_index == 3: # next page
            asset_data.go_to_next_page()
            wm["at_asset_previews"] = min(wm["at_asset_previews"], len(get_browser_items(None, None)) - 1)

        wm["at_current_page"] = asset_data.current_page

        return {'FINISHED'}


class ATOOL_OT_reload_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.reload_asset"
    bl_label = "Reload Asset"
    bl_description = "Reload Asset"

    do_reimport: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        asset_data = context.window_manager.at_asset_data # type: AssetData

        if not asset_data:
            self.report({'INFO'}, "The library is empty.")
            return {'CANCELLED'}

        asset_id = context.window_manager.at_asset_previews
        if asset_id == "/":
            self.report({'INFO'}, "Select an asset.")
            return {'CANCELLED'}

        threading.Thread(target=asset_data.reload_asset, args=(asset_id, context, self.do_reimport)).start()

        return {'FINISHED'}


class temp_image:
    def __init__(self, x, y):
        self.width = x
        self.height = y
        
    def __enter__(self):
        import uuid
        self.image = bpy.data.images.new(str(uuid.uuid1()), width=self.width, height=self.height, float_buffer=True, is_data=True)
        return self.image
    
    def __exit__(self, type, value, traceback):
        bpy.data.images.remove(self.image)
           
class uv_override:
    def __init__(self, material, uv_image):
        self.material = material
        self.uv_image = uv_image
        
    def __enter__(self):
        
        def get_node_trees(starting_node_tree, node_trees = None):
            if node_trees == None:
                node_trees = set()
            node_trees.add(starting_node_tree)
            for node in starting_node_tree.nodes:
                if node.type == 'GROUP' and node.node_tree != None:
                    get_node_trees(node.node_tree, node_trees)
            return node_trees
        
        node_trees = list(get_node_trees(self.material.node_tree))
        
        self.initial_links = {node_tree: [] for node_tree in node_trees}
        self.temp_nodes = {node_tree: [] for node_tree in node_trees}
        
        for node_tree in node_trees:
            nodes = node_tree.nodes
            links = node_tree.links
            
            uv_image_node = nodes.new('ShaderNodeTexImage')
            uv_image_node.image = self.uv_image
            uv_image_node.interpolation = 'Closest'
            
            self.temp_nodes[node_tree].append(uv_image_node)
            uv_output = uv_image_node.outputs[0]
            
            for link in links:
                node_type = link.from_node.type
                if node_type == "UVMAP":
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)
                elif node_type == "TEX_COORD" and link.from_socket.name == "UV":
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)
            
            for node in [node for node in nodes if node.type == "TEX_IMAGE" and node != uv_image_node and not node.inputs[0].links]:
                links.new(uv_output, node.inputs[0])
        
    
    def __exit__(self, type, value, traceback):
        for node_tree, initial_links in self.initial_links.items():
            links = node_tree.links
            for link in initial_links:
                links.new(link[0], link[1])
                
        for node_tree, temp_nodes in self.temp_nodes.items():
            nodes = node_tree.nodes
            for temp_node in temp_nodes:
                nodes.remove(temp_node)
                
class baking_image_node:
    def __init__(self, material, image):
        self.nodes = material.node_tree.nodes
        self.image = image
        
    def __enter__(self):
        image_node = self.nodes.new('ShaderNodeTexImage')
        image_node.image = self.image
        image_node.select = True
        self.initial_active_node = self.nodes.active
        self.nodes.active = image_node
        self.image_node = image_node
    
    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.image_node)
        self.nodes.active = self.initial_active_node

class output_override:
    def __init__(self, material, material_output, traget_socket_output):
        self.nodes = material.node_tree.nodes
        self.links = material.node_tree.links
        self.material_output = material_output
        self.traget_socket_output = traget_socket_output
        
    def __enter__(self):
        if self.material_output.inputs[0].links:
            self.material_output_initial_socket_input = self.material_output.inputs[0].links[0].from_socket
        else:
            self.material_output_initial_socket_input = None

        self.emission_node = self.nodes.new('ShaderNodeEmission')
        
        self.links.new(self.traget_socket_output, self.emission_node.inputs[0])
        self.links.new(self.emission_node.outputs[0], self.material_output.inputs[0])
    
    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.emission_node)
        if self.material_output_initial_socket_input:
            self.links.new(self.material_output_initial_socket_input, self.material_output.inputs[0])

class ATOOL_OT_match_displacement(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.match_displacement"
    bl_label = "Match Displacement"
    bl_description = "Make the particles match the shader displacement of the object. Works only for UV based materials"
    bl_options = {'REGISTER', 'UNDO'}

    random_rotation: bpy.props.BoolProperty(name = "Random Rotation", default = True)

    def execute(self, context):
        start = datetime.now()

        selected_objects = context.selected_objects
        initial_active_object = context.object

        if not selected_objects:
            self.report({'INFO'}, "No selected objects.")
            return {'CANCELLED'}

        context.scene.frame_set(1)

        bpy.ops.mesh.primitive_plane_add(location=(0.0, 0.0, -100))
        bake_plane = context.object
        bake_plane.name = "__bake_plane__"

        for object in selected_objects:

            if object.type != 'MESH':
                self.report({'INFO'}, f"\"{object.name}\" is not a mesh. Skipped.")
                continue

            object_materials = object.data.materials

            if not object_materials:
                self.report({'INFO'}, f"\"{object.name}\" has no materials. Skipped.")
                continue

            if len(object_materials) != 1:
                self.report({'INFO'}, f"\"{object.name}\" has more than one material. Trying for active.")
                material = object.active_material
            else:
                material = object_materials[0]

            nodes = material.node_tree.nodes

            material_output = None
            for node in nodes:
                if node.type == 'OUTPUT_MATERIAL' and node.is_active_output:
                    material_output = node
                    break

            if not material_output:
                self.report({'INFO'}, f"\"{material.name}\" has no material output node. \"{object.name}\" is skipped.")
                continue

            material_output_displacement_links = material_output.inputs[2].links
            if not material_output_displacement_links:
                self.report({'INFO'}, f"\"{material.name}\" material output node has no displacement input. \"{object.name}\" is skipped.")
                continue

            displacement_node = material_output_displacement_links[0].from_node
            if displacement_node.type != 'DISPLACEMENT':
                self.report({'INFO'}, f"\"{material.name}\" material output node has no connection with a displacement node. \"{object.name}\" is skipped.")
                continue

            midlevel = displacement_node.inputs[1].default_value
            scale = displacement_node.inputs[2].default_value

            height_links = displacement_node.inputs[0].links
            if not height_links:
                self.report({'INFO'}, f"\"{material.name}\" has no height output. \"{object.name}\" is skipped.")
                continue
            else:
                height_output_socket = height_links[0].from_socket
            
            particle_systems_modifiers = [modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM']

            if not particle_systems_modifiers:
                self.report({'INFO'}, f"\"{object.name}\" has no particle systems. Skipped.")
                continue

            bake_plane.at_uv_multiplier = object.at_uv_multiplier

            for modifier in particle_systems_modifiers:
                particle_system = modifier.particle_system

                if particle_system.point_cache.is_baked:
                    bpy.ops.ptcache.free_bake({'point_cache': particle_system.point_cache})

                bpy.ops.particle.edited_clear({'active_object': object})

                particles_settings = particle_system.settings

                particles_settings.type = 'EMITTER'

                particles_settings.frame_start = 1
                particles_settings.frame_end = 1

                particles_settings.normal_factor = 1
                particles_settings.tangent_factor = 0
                particles_settings.object_align_factor[0] = 0
                particles_settings.object_align_factor[1] = 0
                particles_settings.object_align_factor[2] = 0

                seed = particle_system.seed
                particle_system.seed = seed

            evaluated_object = context.evaluated_depsgraph_get().id_eval_get(object)

            particle_systems_modifiers = [modifier for modifier in evaluated_object.modifiers if modifier.type == 'PARTICLE_SYSTEM']

            for modifier in particle_systems_modifiers:

                particle_system = modifier.particle_system
                particles = particle_system.particles
                number_of_particles = len(particles)
                seed = particle_system.seed

                x = 1
                y = number_of_particles

                flat_list_3 = [0] * (3 * number_of_particles)
                flat_list_4 = [0] * (4 * number_of_particles)

                flat_uvs = []
                for particle in particle_system.particles:
                    uv = particle.uv_on_emitter(modifier=modifier)
                    flat_uvs.extend((uv[0], uv[1], 0, 1))
                
                if not bake_plane.data.materials:
                    bake_plane.data.materials.append(material)
                else:
                    bake_plane.data.materials[0] = material
                    
                with temp_image(x, y) as uvs_image, temp_image(x, y) as displacement_image:

                    uvs_image.pixels.foreach_set(flat_uvs)

                    with uv_override(material, uvs_image), baking_image_node(material, displacement_image), output_override(material, material_output, height_output_socket):
                        
                        cycles_samples = context.scene.cycles.samples
                        context.scene.cycles.samples = 1
                        
                        start2 = datetime.now()
                        # bpy.ops.object.bake({'active_object': bake_plane}, type='EMIT')
                        bpy.ops.object.bake(type='EMIT') # scene update
                        print("Bake time:", datetime.now() - start2)

                        context.scene.cycles.samples = cycles_samples
                        
                    displacement_image.pixels.foreach_get(flat_list_4)
                    heights = flat_list_4[0::4]

                particles.foreach_get("velocity", flat_list_3)
                normals = map(mathutils.Vector, zip(*[iter(flat_list_3)]*3))

                shift = [normal * (height - midlevel) * scale for normal, height in zip(normals, heights)]

                particles.foreach_get("location", flat_list_3)
                old_location = map(mathutils.Vector, zip(*[iter(flat_list_3)]*3))

                new_location = [x + y for x, y in zip(old_location, shift)]
                new_location = list(itertools.chain.from_iterable(new_location))

                particles.foreach_set("location", new_location)

                if self.random_rotation:

                    particles.foreach_get("rotation", flat_list_4)

                    current_rotation = map(mathutils.Quaternion, zip(*[iter(flat_list_4)]*4))
                    import numpy
                    numpy.random.seed(seed)
                    random_rotation = map(mathutils.Quaternion, itertools.repeat((1.0, 0.0, 0.0)), numpy.random.uniform(-math.pi, math.pi, number_of_particles))

                    new_rotation = [a @ b for a, b in zip(current_rotation, random_rotation)]
                    new_rotation =  list(itertools.chain.from_iterable(new_rotation))
                    particles.foreach_set("rotation", new_rotation)
                
                context.scene.frame_set(2)
                context.scene.frame_set(1)

                bpy.ops.ptcache.bake_from_cache({'point_cache': particle_system.point_cache})
                
        bpy.data.objects.remove(bake_plane, do_unlink=True)
        context.view_layer.objects.active = initial_active_object

        print("All time:", datetime.now() - start)

        return {'FINISHED'}


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

        asset_data = context.window_manager.at_asset_data # type: AssetData
        if not asset_data.library:
            self.report({'INFO'}, "No library folder specified.")
            return {'CANCELLED'}

        if not self.url:
            self.report({'INFO'}, "No URL specified.")
            return {'CANCELLED'}

        threading.Thread(target=asset_data.web_get_asset, args=(self.url, context)).start()

        return {'FINISHED'}


class ATOOL_OT_distibute(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.distibute"
    bl_label = "Distibute"
    bl_description = "Distibute the selection to the active object with a particle system"
    bl_options = {'REGISTER', 'UNDO'}

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
        particles_objects.remove(target)
    
        particle_system_modifier = target.modifiers.new(name = "__atool__", type='PARTICLE_SYSTEM')

        if not particle_system_modifier:
            self.report({'INFO'}, f"{target.name} cannot have particles.")
            return {'CANCELLED'}

        particle_system = particle_system_modifier.particle_system
        
        particle_system.seed = int(mathutils.noise.random() * 9999)

        settings = particle_system.settings
        settings.type = 'HAIR'
        settings.distribution = 'RAND'
        settings.use_advanced_hair = True
        settings.use_rotations = True
        settings.rotation_mode = 'NOR_TAN'
        settings.use_rotation_instance = True
        settings.use_collection_pick_random = True
        settings.hair_length = 1
        settings.particle_size = 1

        collection = bpy.data.collections.new("__atool_particle_collection__")
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

        asset_data = context.window_manager.at_asset_data # type: AssetData
        if not asset_data.auto:
            self.report({'INFO'}, f"The auto import folder is not specified.")
            return {'CANCELLED'}

        threading.Thread(target=asset_data.update_auto).start()
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

    def execute(self, context):

        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, f"No selected objects. Select two objects.")
            return {'CANCELLED'}

        active_object = context.object
        if active_object.type != 'CAMERA':
            self.report({'INFO'}, f"The active object must be a camera.")
            return {'CANCELLED'}

        if len(selected_objects) == 1:
            self.report({'INFO'}, f"Only one object is selected. Select two objects.")
            return {'CANCELLED'}

        camera = active_object
        objects = context.selected_objects.copy()
        objects.remove(camera)

        target = objects[0]
 
        dist = (camera.matrix_world.translation - target.matrix_world.translation).length

        fov = camera.data.angle
        width = 2 * dist * math.tan(fov/2)
            
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
    bl_description = "Find missing files with Everyting"
    bl_options = {'REGISTER', 'UNDO'}

    prefer_desending: bpy.props.BoolProperty(name="Prefer Desending", default = True)
    prefer_asset_folder: bpy.props.BoolProperty(name="Prefer Asset Folder", default = True)
    # reload: bpy.props.BoolProperty(name="Reload", default = True)

    def invoke(self, context, event):

        missing_files = [] # type: typing.List[bl_utils.Missing_File]

        for block in bpy.data.images:
            if block.source == 'FILE':
                path = bpy.path.abspath(block.filepath)
                if not os.path.exists(path):
                    missing_files.append(bl_utils.Missing_File(path, block))

        for block in bpy.data.libraries:
            path = bpy.path.abspath(block.filepath)
            if not os.path.exists(path):
                missing_files.append(bl_utils.Missing_File(path, block))

        if not missing_files:
            self.report({'INFO'}, f"No missing files.")
            return {'CANCELLED'}
        self.missing_files = missing_files # type: typing.List[bl_utils.Missing_File]
        self.asset_data: AssetData
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

        missing_files_by_path = {} # type: typing.Dict[str, typing.List[bl_utils.Missing_File]]
        self.missing_files_by_path = missing_files_by_path
        for file in self.missing_files:
            file_path = file.path
            path_list = missing_files_by_path.get(file_path)
            if path_list:
                path_list.append(file)
            else:
                missing_files_by_path[file_path] = [file]
        
        names = [os.path.basename(path) for path in missing_files_by_path.keys()]
        found_files = utils.find(names)
        if not found_files:
            self.found_files_by_name = {}
            return

        found_files_by_name = {} # type: typing.Dict[str, typing.List[str]]
        self.found_files_by_name = found_files_by_name
        for file in found_files:
            file = file.lower()
            name = os.path.basename(file)
            name_list = found_files_by_name.get(name)
            if name_list:
                name_list.append(file)
            else:
                found_files_by_name[name] = [file]
    
        self.asset_paths = [asset.path for asset in self.asset_data.values()]
        

    def filter_desending(self, file, found_files):
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
            self.report({'INFO'}, f"No missing files found.")
            return {'CANCELLED'}

        for path, files in self.missing_files_by_path.items():
            paths = self.found_files_by_name.get(os.path.basename(path))
            if not paths:
                self.report({'WARNING'}, f"{path} not found.")
                continue

            if self.prefer_desending:
                filtered = self.filter_desending(path, paths)
                if filtered:
                    paths = filtered

            if self.prefer_asset_folder:
                filtered = self.filter_asset_folder(path, paths)
                if filtered:
                    paths = filtered
            
            closest_path = utils.get_closest_path(path, paths)
            for file in files:
                file.closest_path = closest_path

        for file in self.missing_files:
            if file.closest_path is not None:
                self.report({'INFO'}, f"The {file.type.lower()} '{file.name}' has been found in {file.closest_path}.")
                file.reload()

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
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data # type: AssetData
        if not asset_data:
            self.report({'INFO'}, "The library is empty.")
            return

        asset_id = context.window_manager.at_asset_previews
        if asset_id == "/":
            self.report({'INFO'}, "Select an asset.")
            return

        threading.Thread(target=asset_data.icon_from_clipboard, args = (asset_id, context)).start()

        return {'FINISHED'}