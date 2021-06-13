from __future__ import annotations
import operator
from re import A
import typing
import os
import subprocess
import time
import math

import bpy
import mathutils
from cached_property import cached_property
import blf

try:
    from . import type_definer
except:
    import type_definer

DEFAULT_ATTRS = {'__doc__', '__module__', '__slots__', 'bl_description', 'bl_height_default', 'bl_height_max', 'bl_height_min', 'bl_icon', 'bl_idname', 'bl_label', 'bl_rna', 'bl_static_type', 'bl_width_default', 'bl_width_max', 'bl_width_min', 'color', 'dimensions', 'draw_buttons', 'draw_buttons_ext', 'height', 'hide', 'input_template', 'inputs', 'internal_links', 'is_registered_node_type', 'label', 'location', 'mute', 'name', 'output_template', 'outputs', 'parent', 'poll', 'poll_instance', 'rna_type', 'select', 'show_options', 'show_preview', 'show_texture', 'socket_value_update', 'type', 'update', 'use_custom_color', 'width', 'width_hidden'}
INNER_ATTRS = {'texture_mapping', 'color_mapping'}
NOT_EXPOSED_ATTRS  = DEFAULT_ATTRS | INNER_ATTRS

DIR_PATH = os.path.dirname(os.path.realpath(__file__))

def lerp(value, in_min = 0, in_max = 1, out_min = 0, out_max = 1):
    return out_min + (value - in_min) / (in_max - in_min) * (out_max - out_min)

def clamp(value, minimum = 0, maximum = 1):
    return min(max(value, minimum), maximum) 

class Socket_Wrapper():
    def __init__(self, socket, owner):
        self.__dict__["__native__"] = set(dir(socket))
        self.__data__ = socket
        self.nodes: typing.List[typing.Tuple[Node_Wrapper , Socket_Wrapper]]
        self.nodes = []
        self.owner: Node_Wrapper
        self.owner = owner

    def __getattr__(self, attr):
        if attr in self.__native__:
            return getattr(self.__data__, attr)
        else:
            return self.__getattribute__(attr)

    def __setattr__(self, attr, value):
        if attr in self.__native__:
            setattr(self.__data__, attr, value)
        else:
            super().__setattr__(attr, value)

    def __repr__(self):
        return ''.join(("<", self.__class__.__name__, " \"", self.identifier, "\">"))

    def __getitem__(self, index):
        return self.nodes[index]

    def __len__(self):
        return len(self.nodes)

    def __iter__(self):
        return iter(self.nodes)

    def __contains__(self, item):
        return True if item in self.nodes else False
    
    def __bool__(self): # ???
        return True

    def append(self, node):
        self.nodes.append(node)
        
    def new(self, type, identifier = 0): 
        """
        `type`: node type to create
        `identifier`: socket identifier of the created node
        """
        bl_node_tree = self.__data__.id_data
        x, y = self.location
        
        new_bl_node = bl_node_tree.nodes.new(type)
        
        new_node = Node_Wrapper(new_bl_node)
        
        if self.is_output:
            new_socket = new_node.inputs[identifier]
        else:
            new_socket = new_node.outputs[identifier]
            
        if new_socket == None:
            bl_node_tree.nodes.remove(new_bl_node)
            raise KeyError(f'No {"input" if self.is_output else "output"} socket "{identifier}" in the node "{new_node.name}"')
        
        self.join(new_socket)        
        return new_node
    
    def join(self, socket: Socket_Wrapper, move = True):

        bl_node_tree = self.__data__.id_data
        bl_links = bl_node_tree.links
        
        if self.is_output and not socket.is_output:
            self.nodes.append((socket.owner, socket))
            socket.owner.add_input(socket, self.owner, self)
            bl_links.new(self.__data__, socket.__data__)
        elif not self.is_output and socket.is_output:
            self.nodes.append((socket.owner, socket))
            socket.owner.add_output(socket, self.owner, self)
            bl_links.new(socket.__data__, self.__data__)
        else:
            raise TypeError(f'Invalid socket combination. The supplied socket must be {"input" if self.is_output else "output"}.')
            

        if move:
            if self.is_output:
                x, y = socket.location
                x -= 100
                shift = tuple(map(operator.sub, (x, y), self.location))
                self.owner.location = tuple(map(operator.add, self.owner.location, shift))
                for node in self.owner.all_children:
                    node.location = tuple(map(operator.add, node.location, shift))
            else:
                x, y = self.location
                x -= 100
                shift = tuple(map(operator.sub, (x, y), socket.location))
                socket.owner.location = tuple(map(operator.add, socket.owner.location, shift))
                for node in socket.owner.all_children:
                    node.location = tuple(map(operator.add, node.location, shift))
        
    @property
    def location(self):
        
        node = self.node
        x, y = node.location

        if node.type == 'GROUP':
            identifier = self.name
        else:
            identifier = self.identifier

        if self.is_output:
            index = node.outputs.find(identifier)
            x = x + node.width
            y = y - 35 - 21.5 * index
        else:
            index = node.inputs.find(identifier)
            
            attrs = [attr for attr in dir(node) if attr not in NOT_EXPOSED_ATTRS]
            if not attrs or node.show_options == False:
                attr_gap = 0
            elif len(attrs) == 1:
                attr_gap = 30
            else:
                attr_gap = 30 + (len(attrs) - 1) * 24.5
                
            y = y - 35 - 21.5*len(node.outputs) - 3 - attr_gap - 21.5 * index

        return x, y

    @property
    def default_value_converter(self):
        value = self.default_value
        type = self.type
        if type in ('VALUE', 'INT'):
            return {
                'VALUE': value,
                'RGBA': (*(value,)*3, 1), # not posible
                'VECTOR': (value,)*3
            }
        elif type == 'RGBA':
            return {
                'VALUE': value[0]*0.2126 + value[1]*0.7152 + value[2]*0.0722,
                'RGBA': value,
                'VECTOR': value[:3]
            }
        elif type == 'VECTOR':
            return {
                'VALUE': sum(value)/3,
                'RGBA': (*value, 1), # not posible
                'VECTOR': value
            }

class Sockets_Wrapper(typing.Dict[typing.Union[str, int], Socket_Wrapper], dict):
    def __init__(self, *args, **kwargs):
        super().__init__( *args, **kwargs)
        self.identifiers = tuple(dict.keys(self))
    
    def __getitem__(self, key) -> Socket_Wrapper:
        if isinstance(key, int):
            return dict.__getitem__(self, self.identifiers[key])
        else:
            return dict.__getitem__(self, key)

    def __iter__(self):
        return iter(self.values())

    def get(self, key) -> Socket_Wrapper:
        if isinstance(key, int):
            key = self.identifiers.get(key)
            if not key:
                return None
            return dict.get(self, key)
        else:
            return dict.get(self, key)
            
    def __setitem__(self, key, value):
        if isinstance(key, int):
            dict.__setitem__(self, self.identifiers[key], value)
        else:
            dict.__setitem__(self, key, value)

class Node_Wrapper:
    def __init__(self, node):
        self.__dict__["__native__"] = set(dir(node))
        self.__native__.difference_update(("inputs", "outputs"))
        self.__data__ = node
        # self.outputs: typing.Dict[typing.Union[str, int], Socket_Wrapper]
        self.outputs = Sockets_Wrapper((output.identifier, Socket_Wrapper(output, self)) for output in node.outputs)
        self.o = self.outputs
        # self.inputs: typing.Dict[typing.Union[str, int], Socket_Wrapper]
        self.inputs = Sockets_Wrapper((input.identifier, Socket_Wrapper(input, self)) for input in node.inputs)
        self.i = self.inputs
    
    def __repr__(self):
        return ''.join(("<", self.__class__.__name__, " \"", self.name, "\">"))
        
    def __getattr__(self, attr):
        if attr in self.__native__:
            return getattr(self.__data__, attr)
        else:
            return self.__getattribute__(attr)
        
    def __setattr__(self, attr, value):
        if attr in self.__native__:
            setattr(self.__data__, attr, value)
        else:
            super().__setattr__(attr, value)
            
    def __iter__(self) -> typing.Iterator[Socket_Wrapper]:
        return iter(self.inputs.values())
    
    def __contains__(self, item):
        return True if item in self.inputs.values() else False
    
    def __len__(self):
        return len(self.inputs)
    
    def __bool__(self): # ???
        return True
        
    def __getitem__(self, key) -> Node_Wrapper:
        
        if isinstance(key, int):
            socket = self.inputs[self.__data__.inputs[key].identifier]
        else:
            socket = self.inputs[key]
        
        nodes = socket.nodes
        node = nodes[0][0] if nodes else None
        return node
    
    def get(self, key, is_output = True):
        
        if isinstance(key, int):
            if is_output:
                socket = self.outputs[self.__data__.outputs[key].identifier]
            else:
                socket = self.inputs[self.__data__.inputs[key].identifier]
        else:
            if is_output:
                socket = self.outputs[key]
            else:
                socket = self.inputs[key]
            
        nodes = socket.nodes
        return nodes[0] if nodes else None
        
    def add_input(self, to_socket, from_node, from_socket):
        self.inputs[to_socket.identifier].append((from_node, from_node.outputs[from_socket.identifier]))
    
    def add_output(self, from_socket, to_node, to_socket):
        self.outputs[from_socket.identifier].append((to_node, to_node.inputs[to_socket.identifier]))
        
    def value(self, key, convert = True):
        if isinstance(key, int):
            value = self.__data__.inputs[key].default_value
        else:
            if key in self.inputs.keys():
                value = self.inputs[key].__data__.default_value
            else:
                return None
        try:
            return tuple(value)
        except:
            return value
        
    def delete(self):
        children: typing.List[Node_Wrapper]
        children = []
        parents: typing.List[Node_Wrapper]
        parents = []
        
        for input in self.inputs.values():
            for link in input.nodes:
                children.append(link[0])
                link[1].nodes.remove((self, input))
        
        for output in self.outputs.values():
            for link in output.nodes:
                parents.append(link[0])
                link[1].nodes.remove((self, output))
                
        bl_node_tree = self.__data__.id_data
        bl_node_tree.nodes.remove(self.__data__)
        
        return children, parents   
                
    @property
    def children(self):
        return [node[0] for socket in self.inputs.values() for node in socket.nodes]
    
    @property
    def all_children(self) -> typing.List[Node_Wrapper]:
        nodes = []
        for socket in self.inputs.values():
            for node in socket.nodes:
                nodes.append(node[0])
                nodes.extend(node[0].all_children)
        return list(dict.fromkeys(nodes))
    
    @property
    def parents(self):
        return [node[0] for socket in self.outputs.values() for node in socket.nodes]
    
    @property
    def all_parents(self):
        nodes = []
        for socket in self.outputs.values():
            for node in socket.nodes:
                nodes.append(node[0])
                nodes.extend(node[0].all_parents)
        return list(dict.fromkeys(nodes))
    
    def get_input(self, key, socket_only = False):
        """ Get the socket inputting socket or a value if the socket is not connected. """
        socket = self.inputs[key]
        if socket.nodes:
            return socket.nodes[0][1]
        else:
            if socket_only:
                return None
            return self.value(key)
        
    def set_input(self, key, value):
        socket = self.inputs.get(key)
        if socket:
            if isinstance(value, Socket_Wrapper):
                socket.join(value)
            else:
                socket.default_value = value
        
    def set_inputs(self, settings):
        attributes = settings.pop("Attributes", None)
        if attributes:
            for attribute, value in attributes.items():
                if hasattr(self.__data__, attribute):
                    setattr(self.__data__, attribute, value)
        for key, value in settings.items():
            if value != None:
                self.set_input(key, value)
                
    def lerp_input(self, value, from_min = 0, from_max = 1, to_min = 0, to_max = 1, clamp = False, clamp_min = 0, clamp_max = 1):
        if isinstance(value, Socket_Wrapper):
            map_range = value.new("ShaderNodeMapRange", "Value")
            map_range.inputs["From Min"].default_value = from_min
            map_range.inputs["From Max"].default_value = from_max
            map_range.inputs["To Min"].default_value = to_min
            map_range.inputs["To Max"].default_value = to_max
            map_range.clamp = clamp
            value = map_range.outputs["Result"]
        else:
            value = to_min + (value - from_min) / (from_max - from_min) * (to_max - to_min)
            if clamp:
                value = min(max(value, clamp_min), clamp_max)
        return value
    
    def get_pbr_inputs(self, approximate = True):
        """ Get the PBR inputs. """
                
        if self.type == "BSDF_ANISOTROPIC":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Roughness": self.get_input("Roughness"),
                "Anisotropic": self.get_input("Anisotropy"),
                "Anisotropic Rotation": self.get_input("Rotation"),
                "Normal": self.get_input("Normal", True),
                "Tangent": self.get_input("Tangent", True),
                "Attributes": {"distribution": self.distribution}
            }
        elif self.type == "BSDF_DIFFUSE":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Roughness": self.get_input("Roughness"),
                "Normal": self.get_input("Normal", True)
            }
            if approximate:
                pbr["Roughness"] = self.lerp_input(pbr["Roughness"], to_min = 0.75)
        elif self.type == "EMISSION":
            pbr = {
                "Emission": self.get_input("Color"),
                "Emission Strength": self.get_input("Strength")
            }
        elif self.type == "BSDF_GLASS":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Roughness": self.get_input("Roughness"),
                "IOR": self.get_input("IOR"),
                "Normal": self.get_input("Normal", True),
                "Attributes": {"distribution": self.distribution}
            }
        elif self.type == "BSDF_GLOSSY":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Roughness": self.get_input("Roughness"),
                "Normal": self.get_input("Normal", True),
                "Metallic": 1
            }
            # SHARP BECKMANN GGX ASHIKHMIN_SHIRLEY MULTI_GGX
            distribution = self.distribution
            if distribution == 'SHARP':
                pbr["Roughness"] = 0
            elif distribution in ('BECKMANN', 'ASHIKHMIN_SHIRLEY'):
                pbr["Roughness"] = self.lerp_input(pbr["Roughness"], to_max = 0.7)
                
            if distribution not in ('GGX', 'MULTI_GGX'):
                distribution = 'GGX'
                
            pbr["Attributes"] = {"distribution": distribution}

        elif self.type == "BSDF_REFRACTION":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Roughness": self.get_input("Roughness"),
                "IOR": self.get_input("IOR"),
                "Normal": self.get_input("Normal", True),
                "Attributes": {"distribution": self.distribution}
            }
        elif self.type == "SUBSURFACE_SCATTERING":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Subsurface": self.get_input("Scale"),
                "Subsurface Radius": self.get_input("Radius"),
                #"Texture Blur": self.get_input("Texture Blur"),
                #"Sharpness": self.get_input("Sharpness"),
                "Normal": self.get_input("Normal", True),
                "Attributes": {"falloff": self.falloff}
            }
        elif self.type == "BSDF_TOON":
            pbr = {
                "Base Color": self.get_input("Color"),
                #"Size": self.get_input("Size"),
                #"Smooth": self.get_input("Smooth"),
                "Normal": self.get_input("Normal", True),
                #"Attributes": {"component": self.component}
            }
        elif self.type == "BSDF_TRANSLUCENT":
            pbr = {
                "Base Color": self.get_input("Color"),
                "Normal": self.get_input("Normal", True),
            }
        elif self.type == "BSDF_TRANSPARENT":
            pbr = {
                "Base Color": self.get_input("Color"),
            }
        elif self.type == "BSDF_VELVET":
            pbr = {
                "Base Color": self.get_input("Color"),
                #"Sheen": self.get_input("Sigma"),
                "Normal": self.get_input("Normal", True),
            }
        return pbr

    def get_pbr_socket(self, map_type):
        if map_type == "albedo":
            return self.inputs["Base Color"]
        elif map_type == "ambient_occlusion":
            pass
        elif map_type == "bump":
            bump = self.inputs["Normal"].new('ShaderNodeBump')
            return bump.inputs['Height']
        elif map_type == "diffuse":
            return self.inputs["Base Color"]
        elif map_type == "displacement":
            pass
        elif map_type == "emissive":
            return self.inputs["Emission"]
        elif map_type == "gloss":
            invert = self.inputs["Roughness"].new('ShaderNodeInvert')
            return invert.inputs['Color']
        elif map_type == "metallic":
            return self.inputs['Metallic']
        elif map_type == "normal":
            normal_map = self.inputs["Normal"].new('ShaderNodeNormalMap')
            return normal_map.inputs['Color']
        elif map_type == "opacity":
            return self.inputs['Alpha']
        elif map_type == "roughness":
            return self.inputs['Roughness']
        elif map_type == "specular":
            return self.inputs['Specular']

class Node_Tree_Wrapper(typing.Dict[str, Node_Wrapper], dict):
    def __init__(self, node_tree):
              
        self.node_tree = node_tree
        self.links = node_tree.links
        self.nodes = node_tree.nodes

        for node in self.nodes:
            self[node.name] = Node_Wrapper(node)
        
        for link in self.links:
            if link.is_hidden or not link.is_valid:
                continue
            
            to_node = self[link.to_node.name]
            from_node = self[link.from_node.name]

            to_socket = link.to_socket
            from_socket = link.from_socket
            
            to_node.add_input(to_socket, from_node, from_socket)
            from_node.add_output(from_socket, to_node, to_socket)

    @property
    def output(self):
        for target in ('ALL', 'CYCLES', 'EEVEE'):
            active_output = self.node_tree.get_output_node(target)
            if active_output:
                return self[active_output.name]

    def __iter__(self) -> typing.Iterator[Node_Wrapper]:
        return iter(self.values())

    def get_by_type(self, type) -> typing.List[Node_Wrapper]:
        return [node for node in self.values() if node.type == type]

    def new(self, type):
        node = Node_Wrapper(self.nodes.new(type))
        self[node.name] = node
        return node

    @cached_property
    def displacement_input(self) -> Socket_Wrapper:
        output = self.output
        displacement = output.i["Displacement"].new("ShaderNodeDisplacement", "Displacement")
        displacement.space = 'WORLD'
        x, y = output.location
        displacement.location = (x, y - 150)
        return displacement.i["Height"]


class Reference:
    """ Reference for using with undo/redo """

    def __init__(self, object, origin = None):
        """
        `object`: object to get reference for
        `origin`: origin of the ID, required for embedded `ShaderNodeTree`
        """
        id_data = object.id_data
        is_embedded_data = id_data.is_embedded_data
        self.is_embedded_data = is_embedded_data

        id_type = id_data.__class__.__name__

        if id_type not in ("Object", "Material", "ShaderNodeTree", "Image", "Library"):
            raise NotImplementedError("Reference for the type '{id_type}' is not yet implemented.")

        if id_type == 'ShaderNodeTree' and is_embedded_data: # if is material
            if origin is None:
                raise TypeError("Origin of the ShaderNodeTree is required.")
            self.origin = Reference(origin)

        self.id_type = id_type
        self.id_name = id_data.name

        id_library = id_data.library
        if id_library:
            self.id_library = id_library.filepath
        else:
            self.id_library = None

        try:
            self.path_from_id = object.path_from_id()
        except:
            self.path_from_id = None

    def get(self):
        id_type = self.id_type

        if id_type == "Object":
            id_data = bpy.data.objects.get(self.id_name, self.id_library)
        elif id_type == "Material":
            id_data = bpy.data.materials.get(self.id_name, self.id_library)
        elif id_type == "ShaderNodeTree":
            if self.is_embedded_data: # if is material
                id_data = self.origin.get().node_tree
            else:
                id_data = bpy.data.node_groups.get(self.id_name, self.id_library)
        elif id_type == "Image":
            id_data = bpy.data.images.get(self.id_name, self.id_library)
        elif id_type == "Library":
            id_data = bpy.data.libraries.get(self.id_name, self.id_library)
        
        if not id_data:
            return None

        if self.path_from_id:
            object = id_data.path_resolve(self.path_from_id)
        else:
            object = id_data

        return object

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


def get_material(textures: typing.List[str], name = 'New Material', use_displacement = False, displacement_scale = 0.1, invert_normal_y = {}, use_fake_user = False, type_definer_config = {'is_rgb_plus_alpha': True}):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    material.use_fake_user = use_fake_user
    material.cycles.displacement_method = 'DISPLACEMENT'

    textures_dict = {}
    for texture in textures:
        texture_type = type_definer.get_type(os.path.basename(texture), type_definer_config)
        textures_dict[texture] = texture_type
            
    node_tree = Node_Tree_Wrapper(material.node_tree)
    principled = node_tree.get_by_type('BSDF_PRINCIPLED')[0]

    for path, type in textures_dict.items():
        if not type:
            continue
        
        if 'opacity' in type:
            material.blend_method = 'CLIP'
        
        image_node = node_tree.new('ShaderNodeTexImage')
        image = bpy.data.images.load(filepath = path, check_existing=True)
        image_node.image = image

        def set_displacement(output):
            displacement_input = node_tree.displacement_input # type: Socket_Wrapper
            displacement_input.owner.i['Scale'].default_value = displacement_scale
            displacement_input.join(output, move = False)
        
        if type[0] not in ("diffuse", "albedo", "emissive", "ambient_occlusion"):
            image.colorspace_settings.name = 'Non-Color'
        
        is_moved = False
        type_len = len(type)
        
        if type_len in (1, 2):
            subtype = type[0]
            output = image_node.outputs[0]
            
            if subtype == 'normal' and invert_normal_y[path]:
                mix = output.new('ShaderNodeMixRGB', 'Color1')
                mix.blend_type = 'DIFFERENCE'
                mix.inputs['Fac'].default_value = 1
                mix.inputs['Color2'].default_value = (0, 1, 0, 1)
                output = mix.outputs['Color']

            if use_displacement and subtype == 'displacement':
                set_displacement(output)
                continue
            
            socket = principled.get_pbr_socket(subtype)
            if socket:
                socket.join(output, move = not is_moved)
                is_moved = True
                
        elif type_len in (3, 4):
            separate = image_node.outputs[0].new('ShaderNodeSeparateRGB')
            for index, subtype in enumerate(type):
                if index == 3:
                    break

                output = separate.outputs[index]

                if use_displacement and subtype == 'displacement':
                    set_displacement(output)
                    continue

                socket = principled.get_pbr_socket(subtype)
                if socket:
                    socket.join(output, move = not is_moved)
                    is_moved = True
                    
        if type_len in (2, 4):
            image.alpha_mode = 'CHANNEL_PACKED'

            subtype = type[type_len - 1]
            output = image_node.outputs['Alpha']

            if use_displacement and subtype == 'displacement':
                set_displacement(output)
                continue

            input_alpha = principled.get_pbr_socket(subtype)
            if input_alpha:
                input_alpha.join(output, move = not is_moved)

    image_nodes = [node for node in node_tree.node_tree.nodes if node.type == 'TEX_IMAGE']
    x_locations = [node.location[0] for node in image_nodes]
    min_x_location = min(x_locations)
    for node in image_nodes:
        x, y = node.location
        node.location = (min_x_location, y)

    return material

def get_all_images(node_tree):
    all_images = []
    for node in node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            all_images.append(bpy.path.abspath(node.image.filepath))
        elif node.type == 'GROUP' and node.node_tree:
            all_images.extend(get_all_images(node.node_tree))
    return all_images

def arrage_by_materials(objects: typing.Iterable[bpy.types.Object], by_materials = True, by_images = True):

    sets = {} # type: typing.Dict[frozenset, typing.List[bpy.types.Object]]
    sets['empty'] = []

    def append(object):
        
        materials = object.data.materials
        if not materials:
            sets['empty'].append(object)
            return

        object_set = []
        
        if by_images:
            all_images = []
            for material in materials:
                all_images.extend(get_all_images(material.node_tree))
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


def run_blender(filepath: str = None, script: str = None, argv: list = None, use_atool = True, library_path: str = None, stdout = subprocess.DEVNULL):

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

    return subprocess.run(args, stdout=stdout, check = True)


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


class Progress_Drawer:

    def draw_callback(self):

        blf.position(0, 15, 30 + self.indent * 30, 0)
        blf.size(0, 20, 72)
        blf.draw(0, self.string)

    def __iter__(self):
        total = self.total
        prefix = self.prefix

        start_time = time.time()
        past_time = 0

        show_mult = 1
        if self.is_file:
            show_mult = CHUNK_SIZE

        if not self.total:
            total = len(self.iterator)

        for index, item in enumerate(self.iterator, start = 1):
            yield item

            current_time = time.time()

            past_time = int(current_time - start_time)
            past_min, past_sec = divmod(past_time, 60)

            remain_time = int(past_time/index * (total - index))
            remain_min, remain_sec = divmod(remain_time, 60)

            total_time = int(past_time/index * (total - index) + past_time)
            total_min, total_sec = divmod(int(total_time), 60)

            self.string = f'{prefix}: {int(index/total * 100)}% | {index*show_mult}/{total*show_mult} | Past: {past_min}:{past_sec:02d} Remain: {remain_min}:{remain_sec:02d} Total: {total_min}:{total_sec:02d}'

        # self.string = ''.join(( prefix, str(index), '/', str(total), ' | Past: ', str(past_min), ':', str(past_sec), ' Remain: ', str(remain_min), ':', str(remain_sec) ))

    def __init__(self, iterator: typing.Iterable, total: int = None, prefix = '', indent = 0, is_file = False):
        self.iterator = iterator
        self.total = total
        self.prefix = prefix
        self.indent = indent
        self.is_file = is_file

        self.string = ''
    
    def __enter__(self):
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, tuple(), 'WINDOW', 'POST_PIXEL')
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        bpy.types.SpaceView3D.draw_handler_remove(self.handler, 'WINDOW')

def get_regions() -> typing.List[bpy.types.Region]:
    if bpy.app.background:
        return None
    
    regions = []
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas: 
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        regions.append(region)
    return regions

def iter_with_progress(iterator: typing.Iterable, indent = 0, prefix = '', total: int = None):
    regions = get_regions()

    if not regions:
        for i in iterator:
            yield i
        return

    with Progress_Drawer(iterator, prefix = prefix, total = total, indent = indent) as drawer:
        for i in drawer:
            for region in regions:
                region.tag_redraw()
            yield i
        for region in regions:
            region.tag_redraw()
        
CHUNK_SIZE = 4096

def download_with_progress(response, path: str, total: int, region: bpy.types.Region = None, indent = 0, prefix = ''):
    regions = get_regions()

    if not regions or not total:
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
        return

    total_cunks = math.ceil(total/CHUNK_SIZE)

    with Progress_Drawer(range(total_cunks), is_file = True, prefix = prefix, total = total_cunks, indent = indent) as drawer:
        with open(path, "wb") as f:
            for i, chunk in zip(drawer, response.iter_content(chunk_size=4096)):
                for region in regions:
                    region.tag_redraw()
                f.write(chunk)
            for region in regions:
                region.tag_redraw()