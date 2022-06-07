from __future__ import annotations
import operator
import threading
import typing
import os
import subprocess
import time
import math

import bpy
import mathutils
import blf

from cached_property import cached_property

class Register():
    def __init__(self, globals: dict):
        self.globals: dict = globals
        self.properties = {}
        self.menu_items = []

    @property
    def classes(self):
        return [module for name, module in self.globals.items() if name.startswith("ATOOL")]

    def property(self, name, value, bpy_type = bpy.types.WindowManager):
        self.properties[(bpy_type, name)] = value

    def menu_item(self, type, object):
        self.menu_items.append((type, object))
  
    def register(self):

        for c in self.classes:
            bpy.utils.register_class(c)

        for (bpy_type, name), value in self.properties.items():
            setattr(bpy_type, name, value)

        for menu, object in self.menu_items:
            menu.append(object)
            

    def unregister(self):

        for c in self.classes:
            bpy.utils.unregister_class(c)

        for bpy_type, name in self.properties:
            delattr(bpy_type, name)

        for menu, object in self.menu_items:
            menu.remove(object)

if __package__:
    from . import utils
    from . import node_utils
else:
    import utils
    import node_utils

DIR_PATH = os.path.dirname(os.path.realpath(__file__))


class Reference:
    """ Reference for using with undo/redo/reload """

    def __init__(self, block: bpy.types.ID, origin: bpy.types.ID = None):
        """
        `block`: data block to get reference for
        `origin`: origin of the ID, required for embedded `ShaderNodeTree`
        """
        
        id_data: bpy.types.ID = block.id_data
        self.is_embedded_data = id_data.is_embedded_data

        id_type = id_data.__class__.__name__

        if id_type not in ("Object", "Material", "ShaderNodeTree", "Image", "Library"):
            raise NotImplementedError("Reference for the type '{id_type}' is not yet implemented.")

        if id_type == 'ShaderNodeTree' and self.is_embedded_data: # if is material
            if origin is None:
                raise TypeError("Origin of the ShaderNodeTree is required.")
            self.origin = Reference(origin)

        self.id_type = id_type
        self.id_name = id_data.name

        library = id_data.library
        if library:
            self.library_path = library.filepath
        else:
            self.library_path = None

        try:
            self.path_from_id = block.path_from_id()
        except:
            self.path_from_id = None

    @staticmethod
    def get_collection_item(collection: bpy.types.bpy_prop_collection, id_name: str, library_path: str) -> bpy.types.ID:
        try:
            return collection[id_name, library_path]
        except:
            return None

    def get(self) -> bpy.types.bpy_struct:
        id_type = self.id_type

        if id_type == "Object":
            id_data = self.get_collection_item(bpy.data.objects, self.id_name, self.library_path)
        elif id_type == "Material":
            id_data = self.get_collection_item(bpy.data.materials, self.id_name, self.library_path)
        elif id_type == "ShaderNodeTree":
            if self.is_embedded_data: # if is material
                id_data = self.origin.get().node_tree
            else:
                id_data = self.get_collection_item(bpy.data.node_groups, self.id_name, self.library_path)
        elif id_type == "Image":
            id_data = self.get_collection_item(bpy.data.images, self.id_name, self.library_path)
        elif id_type == "Library":
            id_data = self.get_collection_item(bpy.data.libraries, self.id_name, self.library_path)
        
        if not id_data:
            return None

        if self.path_from_id:
            data = id_data.path_resolve(self.path_from_id)
        else:
            data = id_data

        return data


class Missing_File:
    # SUPPORTED_TYPES = ('Image', 'Library')

    def __init__(self, path, block):

        self.block = Reference(block)
        self.type: str
        self.type = block.__class__.__name__

        # if self.type not in self.SUPPORTED_TYPES:
        #     raise TypeError(f"The block '{block.name}' with type '{self.type}' is not supported.")

        self.path = path.lower()
        self.name = os.path.basename(self.path)

        self.found_paths = []
        self.closest_path: str = None

    def reload(self):
        block = self.block.get()
        block.filepath = self.closest_path
        block.reload()


class Dependency_Getter(dict):
    """Getting Image and Library dependencies. This class will be extended if needed."""

    def __init__(self):
        self._children = None # type: typing.Dict[bpy.types.object, typing.List[bpy.types.object]]
    
    def cached(func):
        
        def wrapper(self: Dependency_Getter, *args, **kwargs):
            id_data = args[0]
            id_type = id_data.__class__

            id_type_cache = self.get(id_type)
            if not id_type_cache:
                self[id_type] = id_type_cache = {}

            dependencies = id_type_cache.get(id_data)
            if not dependencies:
                id_type_cache[id_data] = dependencies = func(self, *args, **kwargs)

            return dependencies

        return wrapper

    @property
    def children(self):

        if self._children:
            return self._children

        self._children = utils.list_by_key(bpy.data.objects, operator.attrgetter('parent'))
        return self._children

    @cached
    def get_node_tree_dependencies(self, node_tree: bpy.types.NodeTree):
        
        dependencies = {} # type: typing.Dict[bpy.types.ID, typing.List[bpy.types.ID]]
        def add(dependency, ID = node_tree):
            utils.map_to_list(dependencies, ID, dependency)

        if node_tree.library and node_tree.library.filepath:
            add(node_tree.library)

        for node in node_tree.nodes:
            
            if node.type == 'TEX_IMAGE' and node.image and node.image.source == 'FILE' and node.image.filepath:
                add(node.image)

            elif node.type == 'GROUP' and node.node_tree:
                # add(node.node_tree)
                add(self.get_node_tree_dependencies(node.node_tree), node.node_tree)
                
        return dependencies

    @cached
    def get_material_dependencies(self, material:  bpy.types.Material):
        return self.get_node_tree_dependencies(material.node_tree)

    @cached
    def get_collection_dependencies(self, collection: bpy.types.Collection):

        dependencies = {} # type: typing.Dict[bpy.types.ID, typing.List[bpy.types.ID]]
        def add(dependency):
            utils.map_to_list(dependencies, collection, dependency)

        if collection.library and collection.library.filepath:
            add(collection.library)
        
        for object in collection.all_objects:
            add(self.get_object_dependencies(object))

        return dependencies

    @cached
    def get_object_dependencies(self, object: bpy.types.Object):

        dependencies = {} # type: typing.Dict[bpy.types.ID, typing.List[bpy.types.ID]]
        def add(source, ID: bpy.types.ID = object):
            utils.map_to_list(dependencies, ID, source)

        if object.library and object.library.filepath:
            add(object.library)

        if object.data:
            if object.data.library and object.data.library.filepath:
                add(object.data.library)
                # add(object.data)
                # add(object.data.library, object.data)

            if hasattr(object.data, 'materials'):
                for material in object.data.materials:
                    if material:
                        add(self.get_material_dependencies(material))
                        # add(material)
                        # add(self.get_material_dependencies(material), material)

        if object.instance_type == 'COLLECTION' and object.instance_collection:
            # add(object.instance_collection)
            add(self.get_collection_dependencies(object.instance_collection))

        if object.instance_type in ('VERTS', 'FACES'):
            for child in self.children[object]:
                # add(child)
                add(self.get_object_dependencies(child))

        particle_systems = [modifier.particle_system.settings for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM'] # type: typing.List[bpy.types.ParticleSettings]
        for particle_system in particle_systems:

            if particle_system.render_type == 'COLLECTION' and particle_system.instance_collection:
                add(self.get_collection_dependencies(particle_system.instance_collection))
                # add(particle_system.instance_collection)
                # add(particle_system)
                # add(self.get_collection_dependencies(particle_system.instance_collection), particle_system)
            elif particle_system.render_type == 'OBJECT' and particle_system.instance_object:
                add(self.get_object_dependencies(particle_system.instance_object))
                # add(particle_system.instance_object)
                # add(particle_system)
                # add(self.get_object_dependencies(particle_system.instance_object), particle_system)

        return dependencies

    def get_dependencies(self, ID: bpy.types.ID):
        if ID.__class__ == bpy.types.Object:
            return self.get_object_dependencies(ID)
        elif ID.__class__ == bpy.types.Collection:
            return self.get_collection_dependencies(ID)
        elif ID.__class__ == bpy.types.Material:
            return self.get_material_dependencies(ID)
        elif ID.__class__ == bpy.types.NodeTree:
            return self.get_node_tree_dependencies(ID)

    def get_by_type(self, dependencies: dict, type = ('Library', 'Image')):
        """ Recursively getting dependencies by `type` """

        result = []

        for IDs in dependencies.values():
            for ID in IDs:
                if ID.__class__.__name__ in type:
                    result.append(ID)

                sub_dependencies = self.get_dependencies(ID)
                if sub_dependencies:
                    result.extend(self.get_by_type(sub_dependencies, type = type))
        
        return utils.deduplicate(result)

    def get_object_dependencies_by_type(self, object: bpy.types.Object, type = ('Library', 'Image')):

        result = []

        for IDs in self.get_object_dependencies(object).values():
            for ID in IDs:
                id_type = ID.__class__.__name__
                if not id_type in type:
                    continue
                if id_type == 'Image' and not ID.source == 'FILE':
                    continue
                result.append(ID)

        return utils.deduplicate(result)


def arrange_by_materials(objects: typing.Iterable[bpy.types.Object], by_materials = True, by_images = True):

    sets = {} # type: typing.Dict[frozenset, typing.List[bpy.types.Object]]
    sets['empty'] = []

    def append(object):
        
        if object.data and hasattr(object.data, 'materials'):
            materials = [material for material in object.data.materials if material]
        else:
            materials = None

        if not materials:
            sets['empty'].append(object)
            return

        object_set = []
        
        if by_images:
            all_images = []
            for material in materials:
                all_images.extend(node_utils.get_all_images(material.node_tree))
            object_set.extend(all_images)
        
        if by_materials:
            object_set.extend(materials)

        if not object_set:
            sets['empty'].append(object)
            return

        object_set = frozenset(object_set)
        
        for set in sets:
            if object_set.isdisjoint(set):
                continue
                
            if object_set.issubset(set):
                sets[set].append(object)
            else:
                sets[set].append(object)
                sets[set|object_set] = sets[set]
                del sets[set]
                
            return
            
        sets[object_set] = [object]

    for object in objects:
        append(object)

    if not sets['empty']:
        del sets['empty']
        
    last_y = 0
    last_offset = 0
    y_offset = 0

    for i, objects in enumerate(sets.values()):
        
        xs = []
        ys = []
        for object in objects:
            x, y, z = object.dimensions # not available for new meshes ?
            xs.append(x)
            ys.append(y)
        x = max(xs)
        y = max(ys)
        
        if i != 0:
            y_offset = max(y, last_y) + last_offset

        last_y = y
        last_offset = y_offset
            
        for j, object in enumerate(objects):
            object.location = (j*x,  y_offset, 0)


def run_blender(filepath: str = None, script: str = None, argv: list = None, use_atool = True, library_path: str = None, stdout = None):

    args = [bpy.app.binary_path, '-b', '--factory-startup']

    if filepath:
        args.append(filepath)

    if script:
        args.extend(('--python', script))

    args.append('--')

    if use_atool:
        atool_path = f'"{DIR_PATH}"' if " " in DIR_PATH else DIR_PATH
        args.extend(('-atool_path', atool_path))
        if library_path:
            library_path = f'"{library_path}"' if " " in library_path else library_path
            args.extend(('-atool_library_path', library_path))
        
    if argv:
        args.extend(argv)

    return subprocess.run(args, stdout=stdout, check = True, text = True)


def get_world_dimensions(objects: typing.Iterable[bpy.types.Object]):
    
    vertices = []
    for o in objects:
        bound_box = o.bound_box
        matrix_world = o.matrix_world
        vertices.extend([matrix_world @ mathutils.Vector(v) for v in bound_box])
        
    xs = []
    ys = []
    zs = []
    for v in vertices:
        xs.append(v[0])
        ys.append(v[1])
        zs.append(v[2])

    max_x = max(xs)
    min_x = min(xs)
    
    max_y = max(ys)
    min_y = min(ys)
    
    max_z = max(zs)
    min_z = min(zs)
        
    x = abs(max_x - min_x)
    y = abs(max_y - min_y)
    z = abs(max_z - min_z)

    loc_x = (max_x + min_x)/2
    loc_y = (max_y + min_y)/2
    loc_z = (max_z + min_z)/2
    
    return (x, y, z), (loc_x, loc_y, loc_z)


DRAWER_SLEEP_TIME = 1/16

class Progress_Drawer:

    def draw_callback(self):

        blf.position(0, 15, 30 + self.indent * 30, 0)
        blf.size(0, 20, 72)
        blf.draw(0, self.string)

    def string_update(self):
        start_time = time.time()
        last_index = 0
        total = self.total
        prefix = self.prefix
        show_multiplier = self.show_multiplier

        while self.is_running:
            if last_index == self._index:
                time.sleep(DRAWER_SLEEP_TIME)
                continue

            current_time = time.time()

            past_time = int(current_time - start_time)
            past_min, past_sec = divmod(past_time, 60)

            remain_time = int(past_time/self._index * (total - self._index))
            remain_min, remain_sec = divmod(remain_time, 60)

            total_time = int(past_time/self._index * (total - self._index) + past_time)
            total_min, total_sec = divmod(int(total_time), 60)

            self.string = ' | '.join((
                f"{prefix}: {int(self._index / total * 100)}%",
                f"{self._index * show_multiplier} / {total * show_multiplier}",
                f"Total: {total_min}:{total_sec:02d} Past: {past_min}:{past_sec:02d} Remain: {remain_min}:{remain_sec:02d}"
            ))

            time.sleep(DRAWER_SLEEP_TIME)

    def __iter__(self):

        if not self.total:
            self.total = len(self.iterator)
        if not self.total:
            return

        self.show_multiplier = 1
        if self.is_file:
            self.show_multiplier = CHUNK_SIZE

        self.is_running = 1
        self._index = 1
        threading.Thread(target = self.string_update, args = (), daemon = True).start()

        for index, item in enumerate(self.iterator, start = 1):
            self._index = index
            yield item

        self.is_running = 0

    def __init__(self, iterator: typing.Iterable, total: int = None, prefix = '', indent = 0, is_file = False):
        self.iterator = iterator
        self.total = total
        self.prefix = prefix
        self.indent = indent
        self.is_file = is_file

        self.string = ''
    
    def __enter__(self):
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, tuple(), 'WINDOW', 'POST_PIXEL')
        self.next = DRAWER_SLEEP_TIME
        bpy.app.timers.register(self.update_view_3d_regions, persistent = True)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.next = None
        bpy.types.SpaceView3D.draw_handler_remove(self.handler, 'WINDOW')

    def update_view_3d_regions(self):
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            region.tag_redraw()
        return self.next

def iter_with_progress(iterator: typing.Iterable, indent = 0, prefix = '', total: int = None):

    if bpy.app.background:
        for i in iterator:
            yield i
        return

    with Progress_Drawer(iterator, prefix = prefix, total = total, indent = indent) as drawer:
        for i in drawer:
            yield i
        
CHUNK_SIZE = 4096

def download_with_progress(response, path: str, total: int, region: bpy.types.Region = None, indent = 0, prefix = ''):

    if bpy.app.background or not total:
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
        return

    total_chunks = math.ceil(total/CHUNK_SIZE)

    with Progress_Drawer(range(total_chunks), is_file = True, prefix = prefix, total = total_chunks, indent = indent) as drawer:
        with open(path, "wb") as f:
            for i, chunk in zip(drawer, response.iter_content(chunk_size=4096)):
                f.write(chunk)


def abspath(path, library:bpy.types.Library = None):
    return os.path.realpath(bpy.path.abspath(path, library = library))

def get_block_abspath(block: bpy.types.ID):
    return os.path.realpath(bpy.path.abspath(block.filepath, library = block.library))

def backward_compatibility_get(object: bpy.types.ID, attr_name: typing.Iterable[str], sentinel = object()):
    for i, attr in enumerate(attr_name):
        value = object.get(attr, sentinel) 
        if value == sentinel:
            continue

        if i != 0:
            del object[attr]
            object[attr_name[0]] = value
            
        return value
    return None

def get_library_by_path(path: str) -> bpy.types.Library:
    path = abspath(path)
    for library in bpy.data.libraries:
        if abspath(library.filepath) == path:
            return library 
    
def get_context_copy_with_object(context: bpy.types.Context, object: bpy.types.Object) -> dict:
    override = context.copy()
    override['selectable_objects'] = [object]
    override['selected_objects'] = [object]
    override['selected_editable_objects'] = [object]
    override['editable_objects'] = [object]
    override['visible_objects'] = [object]
    override['active_object'] = object
    override['object'] = object
    return override

def get_context_copy_with_objects(context: bpy.types.Context, active_object: bpy.types.Object , objects: typing.Iterable[bpy.types.Object]) -> dict:
    override = context.copy()
    override['selectable_objects'] = list(objects)
    override['selected_objects'] = list(objects)
    override['selected_editable_objects'] = list(objects)
    override['editable_objects'] = list(objects)
    override['visible_objects'] = list(objects)
    override['active_object'] = active_object
    override['object'] = active_object
    return override

class Operator_Later_Caller:
    
    def execute(self, context):
        raise NotImplementedError('This function needs to be overridden.')

        # example
        func = self.get_later_caller(bpy.ops, context.copy(), 'EXEC_DEFAULT', True, key_argument = 'key_argument')
        bpy.app.timers.register(func)
        return {'FINISHED'}
    
    @staticmethod
    def get_later_caller(func, context: dict = None, execution_context: str = None, undo: bool = None, **key_arguments) -> typing.Callable:
        
        arguments = []
        for argument in (context, execution_context, undo):
            if argument == None:
                continue
            arguments.append(argument)
   
        def call_later() -> None:
            func(*arguments, **key_arguments)
            
        return call_later


VERTEX_CHANGING_MODIFIER_TYPES = {'ARRAY', 'BEVEL', 'BOOLEAN', 'BUILD', 'DECIMATE', 'EDGE_SPLIT', 'NODES', 'MASK', 'MIRROR', 'MULTIRES', 'REMESH', 'SCREW', 'SKIN', 'SOLIDIFY', 'SUBSURF', 'TRIANGULATE', 'VOLUME_TO_MESH', 'WELD', 'WIREFRAME', 'EXPLODE', 'FLUID', 'OCEAN', 'PARTICLE_INSTANCE'}

class Object_Mode_Poll():
    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'VIEW_3D' and context.mode == 'OBJECT'


def get_local_view_objects(context):
    # Regression: object.local_view_get and object.visible_in_viewport_get() always returns False
    # https://developer.blender.org/T95197

    space_view_3d = context.space_data

    if type(space_view_3d) != bpy.types.SpaceView3D: # will crash if space_view_3d is None
        raise TypeError(f'The context is incorrect. For context.space_data expected a SpaceView3D type, not {type(space_view_3d)}')

    depsgraph = context.evaluated_depsgraph_get()

    if bpy.data.objects and hasattr(bpy.data.objects[0], 'visible_in_viewport_get'):
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).visible_in_viewport_get(space_view_3d)]
    else:
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).local_view_get(space_view_3d)]