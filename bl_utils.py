from __future__ import annotations
import operator
import typing

import bpy

DEFAULT_ATTRS = {'__doc__', '__module__', '__slots__', 'bl_description', 'bl_height_default', 'bl_height_max', 'bl_height_min', 'bl_icon', 'bl_idname', 'bl_label', 'bl_rna', 'bl_static_type', 'bl_width_default', 'bl_width_max', 'bl_width_min', 'color', 'dimensions', 'draw_buttons', 'draw_buttons_ext', 'height', 'hide', 'input_template', 'inputs', 'internal_links', 'is_registered_node_type', 'label', 'location', 'mute', 'name', 'output_template', 'outputs', 'parent', 'poll', 'poll_instance', 'rna_type', 'select', 'show_options', 'show_preview', 'show_texture', 'socket_value_update', 'type', 'update', 'use_custom_color', 'width', 'width_hidden'}
INNER_ATTRS = {'texture_mapping', 'color_mapping'}
NOT_EXPOSED_ATTRS  = DEFAULT_ATTRS | INNER_ATTRS

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
    
    def join(self, socket, move = True):

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


class Node_Tree_Wrapper:
    def __init__(self, node_tree):
              
        self.node_tree = node_tree
        self.links = node_tree.links

        self.nodes: typing.Dict[str, Node_Wrapper]
        self.nodes = {}

        self.output: Node_Wrapper
        self.output = None
        
        for link in self.links:
            if link.is_hidden or not link.is_valid:
                continue
            
            to_node = self.nodes.get(link.to_node.name)
            if not to_node:
                to_node = Node_Wrapper(link.to_node)
                self.nodes[to_node.name] = to_node
            
            from_node = self.nodes.get(link.from_node.name)
            if not from_node:
                from_node = Node_Wrapper(link.from_node)
                self.nodes[from_node.name] = from_node

            to_socket = link.to_socket
            from_socket = link.from_socket
            
            to_node.add_input(to_socket, from_node, from_socket)
            from_node.add_output(from_socket, to_node, to_socket)

        
        for target in ('ALL', 'CYCLES', 'EEVEE'):
            active_output = node_tree.get_output_node(target)
            if active_output:
                self.output = self.nodes[active_output.name]
                break

    def __getitem__(self, name) -> Node_Wrapper:
        return self.nodes[name]

    def __iter__(self) -> typing.Iterator[Node_Wrapper]:
        return iter(self.nodes.values())

    def get_by_type(self, type) -> typing.List[Node_Wrapper]:
        return [node for node in self.nodes.values() if node.type == type]


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

        if id_type not in ("Object", "Material", "ShaderNodeTree"):
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
        
        if not id_data:
            return None

        if self.path_from_id:
            object = id_data.path_resolve(self.path_from_id)
        else:
            object = id_data

        return object
