
""" An Unreal script to execute inside an Unreal instance. """
import unreal # type: ignore
import os
import json
import datetime
import tempfile

def get_desktop():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return winreg.QueryValueEx(key, "Desktop")[0]
    except:
        return os.path.expanduser("~/Desktop")


def get_unique_key(dict, key, sentinel = object()):
    index = 2
    initial_key = key
    while dict.get(key, sentinel) is not sentinel:
        key = initial_key + f'_{index}'
        index += 1
    return key

def find_key_by_value(dict, value_to_find, default = None):
    for key, value in dict.items():
        if value == value_to_find:
            return key
    return None

def map_unique(dict, traget_name, value):
    key = find_key_by_value(dict, value)
    if not key:
        key = get_unique_key(dict, traget_name)
        dict[key] = value
    return key


def parse_attrs(string):
    attrs = {}
    for attr in string.strip().split():
        name, value = attr.strip().split('=')
        attrs[name] = value.strip("\"'")
    return attrs

def process_list(string):
        values = []
        value = ''
        bracket_sum = 0
        for char in string:
            if char == '(':
                bracket_sum += 1
            elif char == ')':
                bracket_sum -= 1
            value += char
            
            if not bracket_sum and char == ',':
                value = value[:-1]
                values.append(parse_string_attrs(value))
                value = ''
        values.append(parse_string_attrs(value))
        return values
        
def process_dict(string):
    values = {}
    name = ''
    value = ''
    reading_name = True
    bracket_sum = 0
    for char in string:
        if reading_name:
            if char == ',':
                return process_list(string)
            elif char != '=':
                name += char
            elif char == '=':
                reading_name = False
        else:
            if char == '(':
                bracket_sum += 1
            elif char == ')':
                bracket_sum -= 1
            value += char
            
            if not bracket_sum and char == ',':
                value = value[:-1]
                values[name] = parse_string_attrs(value)
                name = ''
                value = ''
                reading_name = True
    values[name] = parse_string_attrs(value)
    return values

def parse_string_attrs(string, is_list = False):

    if not string.startswith('('):
        return string
    
    string = string[1:-1]
    
    if string.startswith('('):
        return process_list(string)
    else:
        return process_dict(string)

def parse_t3d(lines,  item = None):
    if item == None:
        item = {}
        item['subitems'] = []
        
    reading_object = False

    for line in lines:
        line = line.rstrip('\r\n')

        if reading_object:
            if line.startswith('   '):
                subitem['lines'].append(line[3:])
                continue
            else:
                subitem.update(parse_t3d(subitem.pop('lines'), item = subitem))

        if line.startswith('Begin Object'):
            subitem = parse_attrs(line[13:])
            subitem['lines'] = []
            subitem['attrs'] = {}
            subitem['subitems'] = []
            reading_object = True
        elif line.startswith('End Object'):
            
            for attr in ('subitems', 'attrs'):
                if not subitem.get(attr):
                    subitem.pop(attr)
                
            item['subitems'].append(subitem)
            reading_object = False
        else:
            name, value = line.split('=', 1)
            item['attrs'][name] = parse_string_attrs(value)
            
    return item
        

def get_fbx_export_option():
    options = unreal.FbxExportOption()
    options.collision = False
    options.level_of_detail = False
    options.vertex_color = True
    return options

def get_export_task(filename, object, options = None):
    task = unreal.AssetExportTask()
    task.automated = True
    task.replace_identical = True
    task.filename = filename
    task.object = object
    if options:
        task.options = options
    return task

def get_textures(material):
    type = material.__class__.__name__
    
    if type in ('StaticMaterial', 'SkeletalMaterial'):
        material = material.material_interface
        type = material.__class__.__name__
        
    if type == 'MaterialInstanceConstant':
        textures = []
        for parameter_name in unreal.MaterialEditingLibrary.get_texture_parameter_names(material.get_base_material()):
            texture = unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(material, parameter_name)
            if texture:
                textures.append(texture)
        return textures
    elif type == 'Material':
        return unreal.MaterialEditingLibrary.get_used_textures(material)
    else:
        raise BaseException(f"Material '{material.get_name()}' has unsupported type '{type}'.")


class Textures(dict):
    def append(self, texture):
        return map_unique(self, texture.get_name(), texture)

    def export_iter(self, dir_path, texture_info):
        for name, texture in self.items():

            info = texture_info[name]

            if info['format'] == 'TSF_G8':
                format = '.bmp'
                exporter = unreal.TextureExporterBMP
            else:
                format = '.tga'
                exporter = unreal.TextureExporterTGA

            name = texture.get_name() + format
            yield name
            
            filename = os.path.join(dir_path, name)
            exporter.run_asset_export_task(get_export_task(filename, texture))

    def get_dict(self):
        info = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            total_frames =  len(self)
            with unreal.ScopedSlowTask(total_frames, "Getting Info...") as slow_task:
                slow_task.make_dialog(True)

                for name, texture in self.items():

                    slow_task.enter_progress_frame(1, 'Getting Info: ' + name)

                    if slow_task.should_cancel():
                        raise BaseException("Aborted.")

                    t3d_filename = os.path.join(temp_dir, name + '.t3d')
                    unreal.ObjectExporterT3D.run_asset_export_task(get_export_task(t3d_filename , texture))

                    with open(t3d_filename, 'r',encoding='utf-8') as t3d_file:
                        t3d = parse_t3d(t3d_file.readlines())

                    format = t3d['subitems'][0]['attrs']['Source']['Format']

                    info[name] = {
                        'flip_green_channel': texture.flip_green_channel,
                        'is_bugged_bgr': format == "TSF_RGBA16",
                        'format': format
                    }
        return info

class Materials(dict):
    def __init__(self, textures: Textures):
        self.textures = textures

    def append(self, material):
        textures = {self.textures.append(texture) for texture in get_textures(material)}
        return map_unique(self, material.get_name(), textures)

    def append_from_mesh(self, mesh):
        slot_to_material = {}

        type = mesh.__class__.__name__
        materials = mesh.static_materials if type == 'StaticMesh' else mesh.materials # 'SkeletalMesh'

        for material in materials:
            material = material.material_interface

            textures = {self.textures.append(texture) for texture in get_textures(material)}

            material_name = target_material = material.get_name()
            key = map_unique(self, material_name, textures)
            if key != material.get_name():
                target_material = key

            slot_to_material[material_name] = target_material

        return slot_to_material

    def get_dict(self, texture_info):
        dict = {}
        for name, textures in self.items():
            material_textures = []
            for texture in textures:
                info = texture_info[texture]

                if info['format'] == 'TSF_G8':
                    format = '.bmp'
                else:
                    format = '.tga'
                material_textures.append(texture + format)

            dict[name] = material_textures
        return dict

class Meshes(dict):
    def __init__(self, materials: Materials):
        self.materials = materials
        
    def append(self, mesh):
        materials = self.materials.append_from_mesh(mesh)
        return map_unique(self, mesh.get_name(), (mesh, materials))

    def export_iter(self, dir_path, options = get_fbx_export_option()):
        for name, (mesh, materials) in self.items():
            name = name + '.fbx'
            yield name

            file_name = os.path.join(dir_path, name)
            unreal.ExporterFBX.run_asset_export_task(get_export_task(file_name, mesh, options))
        
    def get_dict(self):
        return {name + '.fbx': materials for name, (mesh, materials) in self.items()}


def export(assets, dir_path):
    
    textures = Textures()
    materials = Materials(textures)
    meshes = Meshes(materials)
    
    for asset in assets:

        type = asset.__class__.__name__
    
        if type in ('StaticMesh', 'SkeletalMesh'):
            meshes.append(asset)

        elif type in ('Material', 'MaterialInstanceConstant'):
            materials.append(asset)
            
        elif type in ('Texture2D', 'Texture'):
            textures.append(asset)

        else:
            print(f"Asset '{asset.get_name()}' has unsupported type '{type}'.")
    
    if not any((textures, materials, meshes)):
        return
    
    os.makedirs(dir_path, exist_ok = True)

    texture_info = textures.get_dict()
    info = { 
        "meshes": meshes.get_dict(), 
        "materials": materials.get_dict(texture_info),
        "textures": texture_info
    }
    
    info_path = os.path.join(dir_path, "__unreal_assets__.json")
    with open(info_path, 'w') as info_file:
        json.dump(info, info_file, indent = 4, ensure_ascii = False)

    total_frames =  len(textures) + len(meshes)
    with unreal.ScopedSlowTask(total_frames, "Exporting...") as slow_task:
        slow_task.make_dialog(True)
        
        import itertools
        for name in itertools.chain(textures.export_iter(dir_path, texture_info), meshes.export_iter(dir_path)):
            if slow_task.should_cancel():
                break
            slow_task.enter_progress_frame(1, 'Exporting: ' + name)


utility_base = unreal.GlobalEditorUtilityBase.get_default_object()
assets = list(utility_base.get_selected_assets())

time_stamp = datetime.datetime.now().strftime('%y%m%d_%H%M%S')
dir_path = os.path.join(get_desktop(), "unreal_assets_" + time_stamp)

export(assets, dir_path)