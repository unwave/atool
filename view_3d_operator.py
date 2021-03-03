import bpy
import sys
import os
import subprocess
# import uuid
# import webbrowser

import itertools
from datetime import datetime

import math
import mathutils #type: ignore
# import numpy

from .data import get_browser_items

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
    
def os_open(operator, path):
    platform = sys.platform
    if platform=='win32':
        os.startfile(path)
    elif platform=='darwin':
        subprocess.Popen(['open', path])
    else:
        try:
            subprocess.Popen(['xdg-open', path])
        except OSError:
            operator.report({'INFO'}, "Current OS is not supported.")
            import traceback
            traceback.print_exc()

def web_open(string , is_url = False):

    starts_with_http = string.startswith("https://") or string.startswith("http://")

    if is_url:
        if not starts_with_http:
            url = "https://" + string
        else:
            url = string
    else:
        if starts_with_http:
            url = string
        else:
            url = fr"https://www.google.com/search?q={string}"
    
    import webbrowser
    webbrowser.open(url, new=2, autoraise=True)

def get_current_browser_asset(operator, context):
    library = context.window_manager.at_asset_data.data
    if not library:
        operator.report({'INFO'}, "The library is empty.")
        return

    asset_id = context.window_manager.at_asset_previews
    if asset_id == "/":
        operator.report({'INFO'}, "Select an asset.")
        return

    return library[asset_id]

class ATOOL_OT_open_library_in_file_browser(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.os_open"
    bl_label = "Open File Browser"
    bl_description = "Open the selected objects libraries in a file browser"

    def execute(self, context):

        for library in get_unique_libraries_from_selected_objects(self, context):
            file_dir = os.path.dirname(os.path.realpath(bpy.path.abspath(library.filepath)))
            os_open(self, file_dir)
        
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

        asset_data = context.window_manager.at_asset_data

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


class ATOOL_OT_import_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.import_asset"
    bl_label = "Import"
    bl_description = ""
    bl_options = {'REGISTER', 'UNDO'}

    link: bpy.props.BoolProperty(name="Link", description="Link asset instead of appending", default= True)
    ignore: bpy.props.StringProperty(name="Ignore", description="Do not import asset that starts with the string", default = "#")

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        blends = [file.path for file in os.scandir(asset.path) if file.path.endswith(".blend")]
        if not blends:
            # bpy.ops.atool.apply_material(from_asset_browser=True)
            result = bpy.ops.atool.apply_material('INVOKE_DEFAULT', from_asset_browser = True)
            return {'FINISHED'} if result == {'FINISHED'} else {'CANCELLED'}
            # self.report({'INFO'}, "No blends.")
            # return {'CANCELLED'}

        latest_blend = max(blends, key=os.path.getmtime)

        with bpy.data.libraries.load(latest_blend) as (data_from, data_to): pass

        imported_library = None
        library_version = None
        for library in bpy.data.libraries:
            if library.filepath == latest_blend:
                library_version = library.version
                imported_library = library
                break
        assert imported_library != None, "The working library not found."

        with bpy.data.libraries.load(latest_blend, link = self.link) as (data_from, data_to):
        
            if library_version < (2,80,0) or not data_from.collections:
                is_importing_objects = True
                data_to.objects = [object for object in data_from.objects if not object.startswith(self.ignore)]
            else: # does not import root collection objects!
                is_importing_objects = False
                data_to.collections = [collection for collection in data_from.collections if not collection.startswith(self.ignore)]

        if not data_to.objects and not data_to.collections:
            self.report({'INFO'}, "Nothing to import.")
            bpy.data.libraries.remove(imported_library)
            return {'CANCELLED'}

        imported_objects = []
        if is_importing_objects:
            for object in data_to.objects:
                context.collection.objects.link(object)

                object["atool_id"] = asset.id

                if not self.link:
                    object.select_set(True)
                    continue
                
                object_overried = object.override_create(remap_local_usages=True)
                object_overried["atool_id"] = asset.id
                object_overried.select_set(True)

                imported_objects.append(object_overried)

        else:
            for collection in data_to.collections:
                
                new_collection = bpy.data.collections.new(collection.name)
                context.scene.collection.children.link(new_collection)

                for object in list(collection.all_objects):

                    if object.name.startswith(self.ignore):
                        bpy.data.objects.remove(object)
                        continue

                    new_collection.objects.link(object)

                    object["atool_id"] = asset.id

                    if not self.link:
                        object.select_set(True)
                        continue

                    object_overried = object.override_create(remap_local_usages=True)
                    object_overried["atool_id"] = asset.id
                    object_overried.select_set(True)

                    imported_objects.append(object_overried)

        if not self.link:
            return {'FINISHED'}

        imported_objects = {object.name: object for object in imported_objects}

        for object in imported_objects.values():
            object.use_fake_user = False
            parent = object.parent
            if parent and parent.library == imported_library:
                object.parent = imported_objects.get(parent.name)
            
        return {'FINISHED'}

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
    bl_label = ""
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
        os_open(self, latest_image)
            
        return {'FINISHED'}
 

class ATOOL_OT_search_name(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.search_name"
    bl_label = ""
    bl_description = "Name. Click to open or search"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
            
        web_open(asset.info["name"])
            
        return {'FINISHED'}

class ATOOL_OT_open_url(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_url"
    bl_label = ""
    bl_description = "Url. Click to open or search"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        web_open(asset.info["url"], is_url = True)
            
        return {'FINISHED'}

class ATOOL_OT_search_author(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.search_author"
    bl_label = ""
    bl_description = "Author. Click to open or search"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
            
        web_open(asset.info["author"])
            
        return {'FINISHED'}


class ATOOL_OT_search_licence(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.search_licence"
    bl_label = ""
    bl_description = "Licence. Click to open or search"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
            
        web_open(asset.info["licence"])
            
        return {'FINISHED'}

class ATOOL_OT_search_tags(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.search_tags"
    bl_label = ""
    bl_description = "Tags. Click to open or search"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}
            
        web_open(' '.join(asset.info["tags"]))
            
        return {'FINISHED'}


class ATOOL_OT_open_asset_folder(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.open_asset_folder"
    bl_label = ""
    bl_description = "Open Folder"

    def execute(self, context):

        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        os_open(self, asset.path)
        
        return {'FINISHED'}


class ATOOL_OT_pin_asset(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.pin_asset"
    bl_label = ""
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
        asset_data = wm.at_asset_data
        
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
    bl_label = ""
    bl_description = "Reload Asset"

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data

        library = asset_data.data
        if not library:
            self.report({'INFO'}, "The library is empty.")
            return {'CANCELLED'}

        asset_id = context.window_manager.at_asset_previews
        if asset_id == "/":
            self.report({'INFO'}, "Select an asset.")
            return {'CANCELLED'}

        asset_data.reload_asset(asset_id, context)

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
    bl_description = "Make the particles match the shader displacement of the object"
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
                    print("rotation set")
                
                context.scene.frame_set(2)
                context.scene.frame_set(1)

                bpy.ops.ptcache.bake_from_cache({'point_cache': particle_system.point_cache})
                
        bpy.data.objects.remove(bake_plane, do_unlink=True)
        context.view_layer.objects.active = initial_active_object

        print("All time:", datetime.now() - start)

        return {'FINISHED'}

class ATOOL_OT_get_info_from_url(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.get_info_from_url"
    bl_label = "Get Info From Url"
    bl_description = "Get the asset info from the url"

    def execute(self, context):
        asset = get_current_browser_asset(self, context)
        if not asset:
            return {'CANCELLED'}

        report = asset.get_info_from_url()
        from . data import update_search
        update_search(context.window_manager, None)
        self.report({'INFO'}, report)
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
        particles_objects = context.selected_objects.copy()
        particles_objects.remove(target)

        collection = bpy.data.collections.new("__atool_particle_collection__")
        # context.scene.collection.children.link(collection)
        for object in particles_objects:
            collection.objects.link(object)
            object.rotation_euler[0] = 0
            object.rotation_euler[1] = math.radians(90)
            object.rotation_euler[2] = 0

    
        particle_system_modifier = target.modifiers.new(name = "__atool__", type='PARTICLE_SYSTEM')
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

        settings.render_type = 'COLLECTION'
        settings.instance_collection = collection

        settings.size_random = 0.5
        settings.rotation_factor_random = 0.05
        settings.phase_factor_random = 2

        return {'FINISHED'}

class ATOOL_OT_process_auto(bpy.types.Operator, Object_Mode_Poll):
    bl_idname = "atool.process_auto"
    bl_label = "Process Auto"
    bl_description = "Process the auto import folder."
    bl_options = {'REGISTER'}

    def execute(self, context):

        asset_data = context.window_manager.at_asset_data
        if not asset_data.auto:
            self.report({'INFO'}, f"The auto import folder is not specified.")
            return {'CANCELLED'}

        asset_data.update_auto()
        self.report({'INFO'}, f"The auto import is done.")

        return {'FINISHED'}