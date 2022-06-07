from __future__ import annotations
import operator
import typing
import os
import sqlite3
import json
from collections import Counter

import bpy

from cached_property import cached_property

if __package__:
    from . import type_definer
    from . import image_utils
    from . import utils
    from . import bl_utils
    from . import data
else:
    import type_definer
    import image_utils
    import utils
    import bl_utils
    import data

# def lerp(value, in_min = 0, in_max = 1, out_min = 0, out_max = 1):
#     return out_min + (value - in_min) / (in_max - in_min) * (out_max - out_min)

# def clamp(value, minimum = 0, maximum = 1):
#     return min(max(value, minimum), maximum)

FILE_PATH = os.path.dirname(os.path.realpath(__file__))
DATA_PATH = os.path.join(FILE_PATH, "data.blend")


DEFAULT_ATTRS = {'__doc__', '__module__', '__slots__', 'bl_description', 'bl_height_default', 'bl_height_max', 'bl_height_min', 'bl_icon', 'bl_idname', 'bl_label', 'bl_rna', 'bl_static_type', 'bl_width_default', 'bl_width_max', 'bl_width_min', 'color', 'dimensions', 'draw_buttons', 'draw_buttons_ext', 'height', 'hide', 'input_template', 'inputs', 'internal_links', 'is_registered_node_type', 'label', 'location', 'mute', 'name', 'output_template', 'outputs', 'parent', 'poll', 'poll_instance', 'rna_type', 'select', 'show_options', 'show_preview', 'show_texture', 'socket_value_update', 'type', 'update', 'use_custom_color', 'width', 'width_hidden'}
INNER_ATTRS = {'texture_mapping', 'color_mapping'}
NOT_EXPOSED_ATTRS  = DEFAULT_ATTRS | INNER_ATTRS

class Socket_Wrapper():
    def __init__(self, socket: bpy.types.NodeSocket, owner: Node_Wrapper):
        self.__dict__["__native__"] = set(dir(socket))
        self.__native__.add('links') # a Blender bug
        self.__data__ = socket
        self.nodes: typing.List[typing.Tuple[Node_Wrapper , Socket_Wrapper]]
        self.nodes = []
        self.owner: Node_Wrapper = owner

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
        
    def new(self, type, identifier: typing.Union[str, int] = 0): 
        """
        `type`: node type to create
        `identifier`: socket identifier of the created node
        """
        node_tree_wrapper = self.owner.owner
        bl_node_tree = node_tree_wrapper.__data__
        x, y = self.location
        
        new_bl_node = bl_node_tree.nodes.new(type)
        
        new_node = Node_Wrapper(new_bl_node, node_tree_wrapper)
        node_tree_wrapper[new_bl_node] = new_node
        
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
    # https://developer.blender.org/D12695
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
                'RGBA': (*(value,)*3, 1), # not possible
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
                'RGBA': (*value, 1), # not possible
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
            if key >= len(self.identifiers):
                return None
            return dict.get(self, self.identifiers[key])
        else:
            return dict.get(self, key)
            
    def __setitem__(self, key, value):
        if isinstance(key, int):
            dict.__setitem__(self, self.identifiers[key], value)
        else:
            dict.__setitem__(self, key, value)

class Node_Wrapper:
    def __init__(self, node: bpy.types.ShaderNode, owner: Node_Tree_Wrapper):
        self.__dict__["__native__"] = set(dir(node))
        self.__native__.difference_update(("inputs", "outputs", "node_tree"))
        self.__data__ = node
        self.owner = owner
        # self.outputs: typing.Dict[typing.Union[str, int], Socket_Wrapper]
        self.outputs = self.o = Sockets_Wrapper((output.identifier, Socket_Wrapper(output, self)) for output in node.outputs)
        # self.inputs: typing.Dict[typing.Union[str, int], Socket_Wrapper]
        self.inputs = self.i = Sockets_Wrapper((input.identifier, Socket_Wrapper(input, self)) for input in node.inputs)

    @property
    def node_tree(self):
        return self.__data__.node_tree

    @node_tree.setter
    def node_tree(self, node_tree):
        self.__data__.node_tree = node_tree
        self.update_sockets()

    def update_sockets(self):

        new_sockets = []
        for socket in self.__data__.outputs:
            if socket.identifier in self.outputs:
                new_sockets.append((socket.identifier, self.outputs[socket.identifier]))
            else:
                new_sockets.append((socket.identifier,  Socket_Wrapper(socket, self)))
        self.outputs = self.o = Sockets_Wrapper(new_sockets)

        new_sockets = []
        for socket in self.__data__.inputs:
            if socket.identifier in self.inputs:
                new_sockets.append((socket.identifier, self.inputs[socket.identifier]))
            else:
                new_sockets.append((socket.identifier,  Socket_Wrapper(socket, self)))
        self.inputs = self.i = Sockets_Wrapper(new_sockets)
    
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
        
    def get_value(self, identifier, convert = True):
        if isinstance(identifier, int):
            value = self.__data__.inputs[identifier].default_value
        else:
            if identifier in self.inputs.keys():
                value = self.inputs[identifier].__data__.default_value
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
        del self.owner[self.__data__]
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
    def all_parents(self) -> typing.List[Node_Wrapper]:
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
            return self.get_value(key)
        
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

    @property
    def has_inputs(self):
        return any(len(input.nodes) != 0 for input in self.inputs)

class Node_Tree_Wrapper(typing.Dict[bpy.types.Node, Node_Wrapper], dict):
    def __init__(self, bl_node_tree: bpy.types.ShaderNodeTree):
              
        self.__data__ = bl_node_tree
        self.links = bl_node_tree.links
        self.nodes = bl_node_tree.nodes # typing.List[bpy.types.Node]

        for node in self.nodes:
            self[node] = Node_Wrapper(node, self)
        
        for link in self.links:
            if link.is_hidden or not link.is_valid:
                continue
            
            to_node = self[link.to_node]
            from_node = self[link.from_node]

            to_socket = link.to_socket
            from_socket = link.from_socket
            
            to_node.add_input(to_socket, from_node, from_socket)
            from_node.add_output(from_socket, to_node, to_socket)
            
    # def __getitem__(self, key: typing.Union[bpy.types.ShaderNode, Node_Wrapper]) -> Node_Wrapper:
    #     if isinstance(key, Node_Wrapper):
    #         key = key.__data__
    #     return super().__getitem__(key)

    @property
    def output(self):
        for target in ('ALL', 'CYCLES', 'EEVEE'):
            active_output = self.__data__.get_output_node(target)
            if active_output:
                return self[active_output]

    def __iter__(self) -> typing.Iterator[Node_Wrapper]:
        return iter(self.values())

    def get_by_type(self, type: str) -> typing.List[Node_Wrapper]:
        return [node for node in self.values() if node.type == type]
    
    def get_by_bl_idname(self, bl_idname: str) -> typing.List[Node_Wrapper]:
        return [node for node in self.values() if node.bl_idname == bl_idname]

    def new(self, type: str, node_tree: bpy.types.ShaderNodeTree = None):

        bl_node = self.nodes.new(type)

        if node_tree:

            if type != 'ShaderNodeGroup':
                raise BaseException('Can not assign a node tree to not a node group.')

            bl_node.node_tree = node_tree

        node = Node_Wrapper(bl_node, self)
        self[bl_node] = node
        return node

    @cached_property
    def displacement_input(self) -> Socket_Wrapper:
        output = self.output
        displacement = output.i["Displacement"].new("ShaderNodeDisplacement", "Displacement")
        displacement.space = 'WORLD'
        x, y = output.location
        displacement.location = (x, y - 150)
        return displacement.i["Height"]
    
    @property
    def active_node(self) -> Node_Wrapper:
        active = self.nodes.active
        if not active:
            return None
        return self[active]
    
    def find_principled(self, create = False, ignore_inputs = False) -> Node_Wrapper:
          
        active_node = self.active_node
        if active_node and active_node.bl_idname == 'ShaderNodeBsdfPrincipled' and not active_node.has_inputs:
            return active_node
        
        principled_nodes = self.get_by_type('BSDF_PRINCIPLED')

        for node in principled_nodes:

            if not node.select:
                continue
            
            if not ignore_inputs and node.has_inputs:
                continue
            
            return node

        if self.output:
            for node in self.output.all_children:
                
                if node.bl_idname != 'ShaderNodeBsdfPrincipled':
                    continue
                
                if not ignore_inputs and node.has_inputs:
                    continue

                return node
        
        for node in principled_nodes:
            
            if not ignore_inputs and node.has_inputs:
                continue
            
            return node
        
        if create:
            return self.new('ShaderNodeBsdfPrincipled')
        
        return None


def get_node_tree_by_name(name, filepath = DATA_PATH, link=False, relative=False, existing = True) -> bpy.types.ShaderNodeTree:

    if existing:
        node_group = bpy.data.node_groups.get(name)
        if node_group:
            return node_group

    with bpy.data.libraries.load(filepath = filepath, link=link, relative=relative) as (data_from, data_to):
        if not name in data_from.node_groups:
            return None
        data_to.node_groups = [name]
    
    node_group = data_to.node_groups[0]
    
    return node_group

def is_atool_extra_node_tree(node_name: str):
    material_output = bpy.data.node_groups[node_name].nodes.get("Group Output")
    if material_output:
        if material_output.label == "__atool_extra__":
            return True
    return False

def get_atool_extra_node_tree(node_name: str, filepath: str = DATA_PATH, link = False, relative = False, existing = True):
    """ `name`: name without prefixes"""
    
    possible_names = [
        node_name,
        node_name + " AT",
        node_name + " ATOOL",
        node_name + " ATOOL EXTRA",
    ]
    
    if existing:
        for name in possible_names:
            node_group = bpy.data.node_groups.get(name)
            if node_group and is_atool_extra_node_tree(name):
                return node_group
            
    present_node_groups_names = {node_group.name for node_group in bpy.data.node_groups}

    with bpy.data.libraries.load(filepath = filepath, link=link, relative=relative) as (data_from, data_to):
        name_with_prefix = "++" + node_name
        if not name_with_prefix in data_from.node_groups:
            return None

        new_node_name = node_name
        for index, name in enumerate(possible_names[:-1]):
            if name in present_node_groups_names:
                new_node_name = possible_names[index + 1]
                
        data_to.node_groups = [name_with_prefix]

    node_group = data_to.node_groups[0]
    node_group.use_fake_user = True
    node_group.name = new_node_name
    
    return node_group

def get_all_images(node_tree: bpy.types.NodeTree):
    all_images = []
    for node in node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            all_images.append(bl_utils.get_block_abspath(node.image))
        elif node.type == 'GROUP' and node.node_tree:
            all_images.extend(get_all_images(node.node_tree))
    return all_images

def get_material(
        textures: typing.Union[typing.List[image_utils.Image], typing.List[str]], 
        name = 'New Material',
        use_displacement = False,
        displacement_scale = 0.1,
        invert_normal_y = {},
        use_fake_user = False,
        type_definer_config = None
    ):

    material = bpy.data.materials.new(name = name)
    material.use_nodes = True
    material.use_fake_user = use_fake_user
    material.cycles.displacement_method = 'DISPLACEMENT'

    textures_dict = {}
    for texture in textures:
        if texture.__class__ is image_utils.Image:
            textures_dict[texture.path] = texture.type
        else:
            stem, ext = os.path.splitext(os.path.basename(texture))
            texture_type = type_definer.get_type(stem, type_definer_config)
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

    image_nodes = [node for node in node_tree.nodes if node.type == 'TEX_IMAGE']
    if image_nodes:
        x_locations = [node.location[0] for node in image_nodes]
        min_x_location = min(x_locations)
        for node in image_nodes:
            x, y = node.location
            node.location = (min_x_location, y)

    return material



class Material_Base:
    def __init__(self):
        self.asset: data.Asset = None
        self.images: typing.Iterable[image_utils.Image] = None
        self.operator: bpy.types.Operator = None
        
        self._displacement_scale: float = None
        self._is_y_minus_normal_map: bool = None
        
    @property
    def name(self):
        names = []
        for image in self.images:
            names.append(image.name)
        name = utils.get_longest_substring(names)

        if len(name) < 2:
            name = 'New Material'
            
        return name
    
    def report(self, type: set, message: str):
        if self.operator:
            self.operator.report(type, message)
        else:
            print(type[0], message)
            
    @property
    def displacement_scale(self):
        
        if self._displacement_scale:
            return self._displacement_scale
        
        if self.asset and self.asset.get('dimensions'):
            return self.asset['dimensions'].get('z', 0.07)
        
        return 0.07
    
    @displacement_scale.setter
    def displacement_scale(self, value: float):
        self._displacement_scale = value
        
    @property
    def is_y_minus_normal_map(self):
        
        if self._is_y_minus_normal_map != None:
            return self._is_y_minus_normal_map
        
        if self.asset and self.asset.get('material_settings'):
            return self.asset['material_settings'].get('Y- Normal Map', False)
        
        return False
        
    @is_y_minus_normal_map.setter
    def is_y_minus_normal_map(self, value: float):
        self._is_y_minus_normal_map = value
    
    @classmethod
    def from_paths(cls, paths: typing.Iterable[str],  type_definer_config = {'is_rgb_plus_alpha': True}):
        material = cls()
        
        with image_utils.Image_Cache_Database() as db:
            material.images = [image_utils.Image.from_db(path, db) for path in paths]
        
        return material
    
    def set_viewport_colors(self, material: bpy.types.Material):
        for image in self.images:
            for channel, subtype in image.iter_type():
                if subtype in {"diffuse", "albedo"}:
                    material.diffuse_color = image.get_dominant_color(channel) + [1]
                elif subtype == "roughness":
                    material.roughness = utils.color_to_gray(image.get_dominant_color(channel))
                elif subtype == "gloss":
                    material.roughness = 1 - utils.color_to_gray(image.get_dominant_color(channel))
                elif subtype == "metallic":
                    material.metallic = utils.color_to_gray(image.get_dominant_color(channel))
                    
    def get_aspect_ratio(self):
        
        aspect_ratios = [image.aspect_ratio for image in self.images]
        if all(ratio == aspect_ratios[0] for ratio in aspect_ratios):
            aspect_ratio = aspect_ratios[0]
        else:
            aspect_ratio = Counter(aspect_ratios).most_common(1)[0][0]
            self.report({'INFO'}, f"Imported bitmaps have different aspect ratios, the ratio set to {aspect_ratio}")
            
        return aspect_ratio

class Material(Material_Base):
    def __init__(self):
        super().__init__()
        self._bl_material: bpy.types.Material = None
        self._node_tree: Node_Tree_Wrapper = None
        
        self.target_material: bpy.types.Material = None
        self.generated_image_nodes: typing.List[Node_Tree_Wrapper] = []
    
    @classmethod
    def from_asset(cls, asset: data.Asset,  type_definer_config: type_definer.Filter_Config = None):
        material = cls()
        
        material.asset = asset
        material.images = [image_utils.Image.from_asset_info(path, asset.info, type_definer_config) for path in asset.get_images()]
        if type_definer_config:
            material.images = type_definer.filter_by_config(material.images, type_definer_config)
        
        return material
    
    
    @classmethod
    def from_image_objects(cls, images: typing.Iterable[image_utils.Image]):
        material = cls()
        material.images = images
        return material
    
    @property
    def bl_material(self):
        
        if self._bl_material:
            return self._bl_material
        
        self._bl_material = self.get()
        return self._bl_material
        
    @property
    def node_tree(self):
        
        if self._node_tree:
            return self._node_tree
        
        self._node_tree = Node_Tree_Wrapper(self.bl_material.node_tree)
        return self._node_tree
    
    @staticmethod
    def get_uv_multiplier_attribute_node(node_tree: Node_Tree_Wrapper):
        attribute = node_tree.new('ShaderNodeAttribute')
        attribute.label = "UV Multiplier"
        attribute.attribute_type = 'OBJECT'
        attribute.attribute_name = 'at_uv_multiplier'
        for socket in attribute.o:
            if socket.name != 'Fac':
                socket.hide = True
        attribute.show_options = False
        return attribute
                    
    def set_uv_scale_multiplier(self, nodes: typing.Iterable[Node_Wrapper] = None):
        
        if nodes:
            iterable = nodes
        else:
            iterable = self.node_tree
        
        uv_inputs = []
        for node in iterable:
            if node.bl_idname == 'ShaderNodeTexImage':
                uv_inputs.append(node.inputs['Vector'])
        
        if uv_inputs:
            attribute = self.get_uv_multiplier_attribute_node(self.node_tree)
            
            vector_math = attribute.outputs['Fac'].new('ShaderNodeVectorMath')
            vector_math.operation = 'DIVIDE'
            vector_math.label = 'Dimensions X Y'
            vector_math.show_options = False
            vector_math.inputs['Vector'].default_value = (1, 1, 0)
            vector_math.inputs['Vector_001'].default_value = (1, 1, 0)
            
            if self.asset:
                dimensions = self.asset.info.get("dimensions") # type: dict
                x = dimensions.get('x')
                y = dimensions.get('y')
                vector_math.inputs['Vector_001'].default_value = (x if x else 1, y if y else 1, 0)
                    
            mapping = vector_math.outputs[0].new('ShaderNodeMapping', 'Scale')  
            mapping.outputs['Vector'].join(uv_inputs[0])
            mapping.inputs['Vector'].new('ShaderNodeUVMap')             
            
            for input in uv_inputs[1:]:
                mapping.outputs['Vector'].join(input, move = False)
                
    def get_height_output(self, prefer_active = True):
        node_tree = self.node_tree
        active_node = node_tree.nodes.active
        output = node_tree.output
        
        if not output:
            self.report({'INFO'}, "No material output node found.")
            return None
        
        if prefer_active:
            active_node = node_tree[active_node]
            height = active_node.o.get("Height")
            if height:
                return height
            
        surface = output["Surface"]
        if not surface:
            self.report({'INFO'}, "No surface shader output.")
            return None
        
        for children in surface.all_children:
            height = children.o.get("Height")
            if height:
                return height
        
        self.report({'INFO'}, "Cannot find height. Select a node with a \"Height\" output socket.")
        return None
        
                
    def set_displacement_from_socket(self, prefer_active = True):
        self.bl_material.cycles.displacement_method = 'DISPLACEMENT'
        self.bl_material.update_tag()

        node_tree = self.node_tree
        output = node_tree.output

        if not output:
            self.report({'INFO'}, "No material output node found.")
            return

        displacement = output["Displacement"]
        if not displacement or (displacement and displacement.type != 'DISPLACEMENT'):
            displacement = node_tree.displacement_input() # type: Socket_Wrapper

        if displacement["Height"]:
            return
        
        height = self.get_height_output(prefer_active)
        if height:
            height.join(displacement.i["Height"], move=False)
            
    def set_displacement_from_image(self):
        self.bl_material.cycles.displacement_method = 'DISPLACEMENT'
        self.bl_material.update_tag()

        displacement_image = None # type: image_utils.Image
        for image in self.images:
            if 'displacement' in image.type:
                displacement_image = image
                break
        
        if not displacement_image:
            # self.report({'INFO'}, "No displacement image.")
            return
        
        type_len = len(displacement_image.type)
        type_index = displacement_image.type.index('displacement')
        
        def set_displacement(output: Socket_Wrapper):

            minimum, maximum = displacement_image.get_min_max('RGB')
            if minimum > 0 or maximum < 1:
                map_range = output.new(type = 'ShaderNodeMapRange')
                map_range.inputs[1].default_value = minimum
                map_range.inputs[2].default_value = maximum
                output = map_range.outputs['Result']

            displacement_input = self.node_tree.displacement_input # type: Socket_Wrapper
            x, y = displacement_input.owner.location
            displacement_input.owner.location = (x - 300, y - 750)
            displacement_input.owner.i['Scale'].default_value = self.displacement_scale
            displacement_input.join(output, move = False)
        
        for node in self.node_tree:
            if node.type == 'TEX_IMAGE' and node.image and bl_utils.get_block_abspath(node.image) == displacement_image.path:
                if type_len in (1, 2):
                    set_displacement(node.outputs[type_index])
                elif type_len in (3, 4):
                    if type_index == 4:
                        set_displacement(node.outputs[type_index])
                    else:
                        node_output = node['Color']
                        if not node_output or not node_output.bl_idname in ('ShaderNodeSeparateRGB', 'ShaderNodeSeparateXYZ'):
                            node_output = node.outputs['Color'].new('ShaderNodeSeparateRGB')
                        set_displacement(node_output.outputs[type_index])
                return
                            
        displacement_input = self.node_tree.displacement_input # type: Socket_Wrapper
        x, y = displacement_input.owner.location
        displacement_input.owner.location = (x - 300, y - 750)
        displacement_input.owner.inputs['Scale'].default_value = self.displacement_scale
        
        input = displacement_input
        minimum, maximum = displacement_image.get_min_max('RGB')
        if minimum > 0 or maximum < 1:
            map_range = displacement_input.new(type = 'ShaderNodeMapRange')
            map_range.inputs[1].default_value = minimum
            map_range.inputs[2].default_value = maximum
            input = map_range.inputs[0]
            
        image_block = bpy.data.images.load(filepath = displacement_image.path, check_existing = True)
        
        if type_len in (1, 2):
            image_node = input.new('ShaderNodeTexImage', type_index)
            image_node.image = image_block
        elif type_len in (3, 4):
            if type_index == 4:
                image_node = input.new('ShaderNodeTexImage', type_index)
                image_node.image = image_block
            else:
                input = input.new('ShaderNodeSeparateRGB', type_index)
                image_node = input.new('ShaderNodeTexImage')
                image_node.image = image_block
                
        self.generated_image_nodes.append(image_node)
    
    def get(self) -> bpy.types.Material:  
         
        if self.target_material:
            bl_material = self.target_material
            # bl_material.name = self.name
        else:
            bl_material = bpy.data.materials.new(name = self.name)
            bl_material.use_nodes = True
        
        node_tree = Node_Tree_Wrapper(bl_material.node_tree)
        
        principled = node_tree.find_principled(create = True)

        image_nodes = []

        for texture in self.images:
            
            type = texture.type
            if not type:
                continue
            
            type_len = len(type)
            
            if 'opacity' in type:
                bl_material.blend_method = 'CLIP'
                
            if type_len == 1 and type[0] == 'displacement':
                continue
            
            path = texture.path
            image_node = node_tree.new('ShaderNodeTexImage')
            image_nodes.append(image_node)
            image = bpy.data.images.load(filepath = path, check_existing=True)
            image_node.image = image
            
            if type[0] not in ("diffuse", "albedo", "emissive"):
                image.colorspace_settings.name = 'Non-Color'
            
            is_moved = False
            
            
            if type_len in (1, 2): # RGB , RGB + A
                subtype = type[0]
                output = image_node.outputs[0]
                
                if subtype == 'normal' and self.is_y_minus_normal_map:
                    mix = output.new('ShaderNodeMixRGB', 'Color1')
                    mix.blend_type = 'DIFFERENCE'
                    mix.inputs['Fac'].default_value = 1
                    mix.inputs['Color2'].default_value = (0, 1, 0, 1)
                    output = mix.outputs['Color']

                if subtype == 'displacement':
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

                    if subtype == 'displacement':
                        continue

                    socket = principled.get_pbr_socket(subtype)
                    if socket:
                        socket.join(output, move = not is_moved)
                        is_moved = True
                        
            if type_len in (2, 4):
                image.alpha_mode = 'CHANNEL_PACKED'

                subtype = type[type_len - 1]
                output = image_node.outputs['Alpha']

                if subtype == 'displacement':
                    continue

                input_alpha = principled.get_pbr_socket(subtype)
                if input_alpha:
                    input_alpha.join(output, move = not is_moved)
        

        # image_nodes = [node for node in node_tree if node.type == 'TEX_IMAGE']
        if image_nodes:
            x_locations = [node.location[0] for node in image_nodes]
            min_x_location = min(x_locations)
            for node in image_nodes:
                x, y = node.location
                node.location = (min_x_location, y)
                
            self.generated_image_nodes.extend(image_nodes)

        return bl_material


    
MAT_TYPES = (None , "_at_temp_", "_at_temp_unt_", "_at_temp_tri_", "_at_temp_tri_unt_")
M_BASE = "_at_temp_"
M_TRIPLANAR = "tri_"
M_UNTILING = "unt_"

POSTFIXES = {
    1: ("",),
    2: ("", "_seams"),
    3: ("_x", "_y", "_z"),
    4: ("_seams_x", "_seams_y", "_seams_z", "_x", "_y", "_z")
}

class Material_Node_Tree(Material_Base):
    def __init__(self):
        super().__init__()
        self._node_tree: Node_Tree_Wrapper = None
        self._bl_node_tree: bpy.types.ShaderNodeTree = None
        self._type: str
        
    @classmethod
    def new(cls, type: str):
        material = cls()
        material._type = type
        return material
        
    @property
    def type(self):
        return self._type
        
    @type.setter
    def type(self, value: str):
        self._type = value
    
    @property
    def bl_node_tree(self):
        if self._bl_node_tree:
            return self._bl_node_tree
        
        self._bl_node_tree = self.get()
        return self._bl_node_tree

    def get(self):

        node_tree = get_node_tree_by_name(self._type, existing = False)
        material_type: int = MAT_TYPES.index(self._type)

        nodes = node_tree.nodes
        links = node_tree.links
        inputs = node_tree.inputs
        outputs = node_tree.outputs

        flags = {
            "albedo": False,
            "diffuse": False,
            "ambient_occlusion": False,
            "metallic": False,
            "specular": False,
            "roughness": False,
            "gloss": False,
            "displacement": False,
            "bump": False,
            "opacity": False,
            "emissive": False,
            "normal": False
        }

        def add_separate_rgb(name):
                separate_rgb = node_tree.nodes.new( type = 'ShaderNodeSeparateRGB' )
                (x, y) = nodes[name].location
                separate_rgb.location = (x + 400, y)

                links.new(nodes[name].outputs[0], separate_rgb.inputs[0])
                return separate_rgb

        def add_gamma_0_4545(name, index):
            gamma = node_tree.nodes.new( type = 'ShaderNodeGamma' )
            (x, y) = nodes[name].location
            gamma.location = (x + 250, y)
            gamma.inputs[1].default_value = 1/2.2

            links.new(nodes[name].outputs[index], gamma.inputs[0])
            return gamma

        def add_gamma_0_4545_and_plug_output_to_mix_in(name, alpha_name, index):
            for postfix in POSTFIXES[material_type]:
                gamma_0_4545 = add_gamma_0_4545(name + postfix, 0)
                links.new(gamma_0_4545.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

        def plug_output_to_mix_in(name, alpha_name, index):
            for postfix in POSTFIXES[material_type]:
                links.new(nodes[name + postfix].outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

        def add_gamma_2_2(node, index):
                gamma = node_tree.nodes.new( type = 'ShaderNodeGamma' )
                (x, y) = node.location
                gamma.location = (x + 250, y)
                gamma.inputs[1].default_value = 2.2

                links.new(node.outputs[index], gamma.inputs[0])
                return gamma

        def set_bitmap_to_node(name):
            for postfix in POSTFIXES[material_type]:
                nodes[name + postfix].image = current_image

        def add_separate_rgb_and_plug_output_to_mix_in(name, alpha_name, index):
            for postfix in POSTFIXES[material_type]:
                separate_rgb = add_separate_rgb(name + postfix)
                links.new(separate_rgb.outputs[index], nodes[alpha_name + postfix + "_mix_in"].inputs[0])

        def handle_bitmap():

            def separate_rgb_and_plug_output_to_post_in():
                separate_rgb = add_separate_rgb(bitmap_type[0] + "_mix_out")
                for i in range(3):
                    if bitmap_type[i] == "ambient_occlusion":
                        gamma_2_2 = add_gamma_2_2(separate_rgb, i)
                        links.new(gamma_2_2.outputs[0], nodes[bitmap_type[i] + "_post_in"].inputs[0])
                    elif bitmap_type[i] == "displacement":
                        add_separate_rgb_and_plug_output_to_mix_in(bitmap_type[0], "displacement", i)
                    else:
                        links.new(separate_rgb.outputs[i], nodes[bitmap_type[i] + "_post_in"].inputs[0])
                    flags[bitmap_type[i]] = True

            # RGB
            if packed_bitmap_type == 1:
                if bitmap_type[0] in {"diffuse", "albedo", "emissive", "ambient_occlusion"}:
                    current_image.colorspace_settings.name = 'sRGB'
                else:
                    current_image.colorspace_settings.name = 'Non-Color'

                set_bitmap_to_node(bitmap_type[0])
                flags[bitmap_type[0]] = True
                return

            # RGB + A
            if packed_bitmap_type == 2:
                if bitmap_type[0] in {"diffuse", "albedo", "emissive", "ambient_occlusion"}:
                    current_image.colorspace_settings.name = 'sRGB'
                else:
                    current_image.colorspace_settings.name = 'Non-Color'

                current_image.alpha_mode = 'CHANNEL_PACKED'

                set_bitmap_to_node(bitmap_type[0])
                plug_output_to_mix_in(bitmap_type[0], bitmap_type[1], 1)
                flags[bitmap_type[0]] = True
                flags[bitmap_type[1]] = True
                return
            
            # R + G + B
            if packed_bitmap_type == 3:
                current_image.colorspace_settings.name = 'Non-Color'
                set_bitmap_to_node(bitmap_type[0])
                separate_rgb_and_plug_output_to_post_in()
                return

            # R + G + B + A
            if packed_bitmap_type == 4:
                current_image.colorspace_settings.name = 'Non-Color'
                current_image.alpha_mode = 'CHANNEL_PACKED'

                set_bitmap_to_node(bitmap_type[0])
                separate_rgb_and_plug_output_to_post_in()
                plug_output_to_mix_in(bitmap_type[0], bitmap_type[3], 1)
                flags[bitmap_type[3]] = True
                return

        for index, image in enumerate(self.images):
            current_image = image.data_block
            bitmap_type = bl_utils.backward_compatibility_get(current_image, ("at_type", "ma_type"))
            packed_bitmap_type = len(bitmap_type)
            current_image["at_order"] = index # not yet used
            handle_bitmap()
            self.report({'INFO'}, "Image " + str(os.path.basename(current_image.filepath)) + " was set as: " + str(bitmap_type))
            
        if self.is_y_minus_normal_map:
            inputs["Y- Normal Map"].default_value = 1

        group_output_node = nodes["Group Output"]

        if flags["albedo"]:
            if flags["ambient_occlusion"]:
                links.new(nodes["albedo_and_ao_post_out"].outputs[0], group_output_node.inputs["Base Color"])
            else:
                links.new(nodes["albedo_post_in"].outputs[0], group_output_node.inputs["Base Color"])

        if flags["diffuse"] and not flags["ambient_occlusion"]:
            links.new(nodes["diffuse_post_in"].outputs[0], group_output_node.inputs["Base Color"])

        
        if not flags["albedo"] and not flags["diffuse"]:
            if flags["ambient_occlusion"]:
                links.new(nodes["ambient_occlusion_post_out"].outputs[0], group_output_node.inputs["Base Color"])
            else:
                outputs.remove(outputs["Base Color"])

        if not flags["ambient_occlusion"]:
            inputs.remove(inputs["AO"])

        if not flags["metallic"]:
            outputs.remove(outputs["Metallic"])

        if not flags["specular"]:
            outputs.remove(outputs["Specular"])

        if not flags["roughness"] and not flags["gloss"]:
            outputs.remove(outputs["Roughness"])

        if not flags["roughness"] and flags["gloss"]:
            links.new(nodes["gloss_post_out"].outputs[0], group_output_node.inputs["Roughness"])

        if not flags["displacement"]:
            
            if flags["diffuse"]:
                add_gamma_0_4545_and_plug_output_to_mix_in("diffuse", "displacement", 0)
                self.report({'INFO'}, "No displacement bitmap found, diffuse used instead")
            elif flags["albedo"]:
                add_gamma_0_4545_and_plug_output_to_mix_in("albedo", "displacement", 0)
                self.report({'INFO'}, "No displacement bitmap found, albedo used instead")
            elif flags["ambient_occlusion"]:
                # only works for a separate ao map
                add_gamma_0_4545_and_plug_output_to_mix_in("ambient_occlusion", "displacement", 0)
                self.report({'INFO'}, "No displacement bitmap found, ambient occlusion used instead")
            else:
                outputs.remove(outputs["Height"])
                inputs_to_remove = []
                for input_to_remove in inputs_to_remove:
                    inputs.remove(inputs[input_to_remove])
                self.report({'INFO'}, "No displacement bitmap found.")
                    

        if not flags["opacity"]:
            outputs.remove(outputs["Alpha"])
        
        if not flags["emissive"]:
            outputs.remove(outputs["Emission"])

        if not flags["normal"]:
            if flags["bump"]:
                links.new(nodes["bump_post_out"].outputs[0], group_output_node.inputs["Normal"])
            else:
                outputs.remove(outputs["Normal"])
            for input_to_remove in ("Y- Normal Map", "X Rotation′", "Y Rotation′"):
                try:
                    inputs.remove(inputs[input_to_remove])
                except:
                    pass


        settings = {}
        for input in inputs:
            if input.type != 'STRING':
                settings[input.name] = input.default_value

        node_tree["at_factory_settings"] = settings
        node_tree["at_default_settings"] = settings
        node_tree["at_type"] = material_type
        node_tree["at_flags"] = flags # not yet used
        
        return node_tree
    

    def set_ratio(self):
        
        aspect_ratio = self.get_aspect_ratio()
        if aspect_ratio > 1:
            self.bl_node_tree.inputs["X Scale"].default_value *= aspect_ratio
        elif aspect_ratio < 1:
            self.bl_node_tree.inputs["Y Scale"].default_value *= 1/aspect_ratio
            
    def set_displacement(self):
        for image in self.images:
            for channel, subtype in image.iter_type():
                if subtype == "displacement":
                    min, max = image.min_max[channel]
                    self.bl_node_tree.inputs["From Min"].default_value = min
                    self.bl_node_tree.inputs["From Max"].default_value = max
                    return
        
    @staticmethod
    def is_at_node_tree(group: typing.Union[bpy.types.ShaderNodeGroup, bpy.types.ShaderNodeTree]) -> bool:
        
        if group.bl_idname == "ShaderNodeGroup":
            node_tree = group.node_tree
        elif group.bl_idname == "ShaderNodeTree":
            node_tree = group
        else:
            return False
        
        if not node_tree:
            return False
        
        material_output = node_tree.nodes.get("Group Output")
        if not material_output:
            return False
        
        return  material_output.label == "__atool_material__" or material_output.label.startswith("matapptemp") # matapp backward compatibility
    
    def load_material_settings(self, db: Material_Settings_Database = None):
        
        def set_settings(material_settings):
            for key, value in material_settings.items():
                node_input = self.bl_node_tree.inputs.get(key)
                if node_input:
                    node_input.default_value = value

            default_settings = bl_utils.backward_compatibility_get(self.bl_node_tree, ("at_default_settings", "ma_default_settings"))
            if default_settings:
                default_settings.update(material_settings)
            else:
                self.bl_node_tree["at_default_settings"] = material_settings

        atool_id = self.bl_node_tree.get("atool_id")
        if atool_id:
            material_settings = self.asset.get("material_settings")
            if material_settings:
                set_settings(material_settings)
                self.report({'INFO'}, f"Settings were loaded for the library material: {self.bl_node_tree.name}. ID: {atool_id}")
                return
        
        image_paths = []
        for node in self.bl_node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                image_paths.append(bl_utils.get_block_abspath(node.image))
                
        if not image_paths:
            self.report({'INFO'}, f"No image was found in the material: {self.bl_node_tree.name}")
            return
        
        if not db: # ?
            return
                
        image_paths = utils.deduplicate(image_paths)
        images = [image_utils.Image(path) for path in image_paths]
        image_hashes = [image.hash for image in images]
        
        material_settings = db.get(image_hashes)
        if not material_settings:
            self.report({'INFO'}, f"No settings were found for the material: {self.bl_node_tree.name}")
            return

        set_settings(material_settings)
        self.report({'INFO'}, f"Settings were loaded from the database for the group: {self.bl_node_tree.name}")

        # for group in groups:
        #     for input_index in range(len(group.inputs)):
        #         group.inputs[input_index].default_value = node_tree.inputs[input_index].default_value
    

MATERIAL_SETTINGS_PATH = os.path.join(FILE_PATH, "material_settings.db")

class Material_Settings_Database:
    def __enter__(self, report: function = None):
        try:
            self.connection = sqlite3.connect(MATERIAL_SETTINGS_PATH)
            self.cursor = self.connection.cursor()
            self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        id TEXT PRIMARY KEY,
                        hash_name TEXT,
                        last_path TEXT,
                        data TEXT
                        )
                """)
        except sqlite3.Error as e:
            if report:
                report({'ERROR'}, "Cannot connect to a material settings database.")
                report({'ERROR'}, e)
            raise BaseException("Cannot connect to a material settings database." + e)
        return self
        
    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.commit()
        self.cursor.close()
        self.connection.close()
        
    def get(self, image_paths: typing.Iterable[str]) -> dict:
        
        image_hashes = [utils.get_file_hash(image_path) for image_path in image_paths]

        self.cursor.execute(f"SELECT * FROM settings WHERE id in ({', '.join(['?']*len(image_hashes))})", image_hashes)
        all_image_settings = self.cursor.fetchall()
        
        if not all_image_settings:
            return {}
        
        material_settings = {}
        for image_settings in all_image_settings:
            settings = json.loads(image_settings[3])
            for name, value in settings.items():
                if name not in material_settings.keys():
                    material_settings[name] = [value]
                else:     
                    material_settings[name].append(value)

        for key in material_settings.keys():
            material_settings[key] = utils.get_most_common(material_settings[key])
            
        return material_settings
        
    def set(self, image_paths, material_settings: dict):

        image_hashes = [utils.get_file_hash(image_path) for image_path in image_paths]
        image_path_by_id = dict(zip(image_hashes, image_paths))

        updated_setting_ids = []
        self.cursor.execute(f"SELECT * FROM settings WHERE id in ({', '.join(['?']*len(image_hashes))})", image_hashes)
        existing_image_settings = self.cursor.fetchall()
        
        for image_setting in existing_image_settings:
            id = image_setting[0]
            old_setting = json.loads(image_setting[3])
            old_setting.update(material_settings)
            new_setting = json.dumps(old_setting, ensure_ascii=False)
            self.cursor.execute("""
            UPDATE settings
            SET last_path = ?,
                data = ?
            WHERE
                id = ? 
            """, (image_path_by_id[id], new_setting, id))
            updated_setting_ids.append(id)

        material_settings_json = json.dumps(material_settings, ensure_ascii=False)
        for image_hash, image_path in image_path_by_id.items():
            if image_hash not in updated_setting_ids:
                self.cursor.execute(
                "INSERT INTO settings (id, hash_name, last_path, data) VALUES(?,?,?,?)", 
                (image_hash, "imohashxx", image_path, material_settings_json))
        

class Temp_Image:
    def __init__(self, x, y):
        self.width = x
        self.height = y
        
    def __enter__(self):
        import uuid
        self.image = bpy.data.images.new(str(uuid.uuid1()), width=self.width, height=self.height, float_buffer=True, is_data=True)
        return self.image
    
    def __exit__(self, type, value, traceback):
        bpy.data.images.remove(self.image, do_unlink=True)
           
class UV_Override:
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
                temp_node.image = None # fixes blender.exe image_acquire_ibuf EXCEPTION_ACCESS_VIOLATION crash
                nodes.remove(temp_node)
                
class Baking_Image_Node:
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

class Output_Override:
    def __init__(self, material: bpy.types.Material, material_output: Node_Wrapper, target_socket_output: Socket_Wrapper):
        self.nodes = material.node_tree.nodes
        self.links = material.node_tree.links
        self.material_output = material_output.__data__
        self.target_socket_output = target_socket_output.__data__
        
    def __enter__(self):
        if self.material_output.inputs[0].links:
            self.material_output_initial_socket_input = self.material_output.inputs[0].links[0].from_socket
        else:
            self.material_output_initial_socket_input = None

        self.emission_node = self.nodes.new('ShaderNodeEmission')
        
        self.links.new(self.target_socket_output, self.emission_node.inputs[0])
        self.links.new(self.emission_node.outputs[0], self.material_output.inputs[0])
    
    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.emission_node)
        if self.material_output_initial_socket_input:
            self.links.new(self.material_output_initial_socket_input, self.material_output.inputs[0])


class Isolate_Object_Render:
    def __init__(self, object: bpy.types.Object, modifier: bpy.types.ParticleSystemModifier = None):
        self.object: bpy.types.Object = object
        self.modifier: bpy.types.ParticleSystemModifier = modifier
        self.init_state: typing.Dict[bpy.types.Object, bool] = {}
        self.init_state_modifiers: typing.Dict[bpy.types.ParticleSystemModifier, bool] = {}
        
    def __enter__(self):
        for object in bpy.data.objects:
            self.init_state[object] = object.hide_render
            if object != self.object:
                object.hide_render = True
        
        modifiers = [modifier for modifier in self.object.modifiers if modifier.type == 'PARTICLE_SYSTEM']
        for modifier in modifiers:
            self.init_state_modifiers[modifier] = modifier.show_render
            if modifier != self.modifier:
                modifier.show_render = False
    
    def __exit__(self, type, value, traceback):
        for object, hide_render in self.init_state.items():
            object.hide_render = hide_render
        
        for modifier, show_render in self.init_state_modifiers.items():
            modifier.show_render = show_render
