import sys
import argparse

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('-atool_path')
parser.add_argument('-atool_library_path')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

ATOOL_PATH = args.atool_path
ATOOL_LIBRARY = args.atool_library_path

import re
re_name = re.compile('plane(\.\d{3})?', flags = re.IGNORECASE)

planes = []
for object in bpy.data.objects:
    if object.data and object.data.__class__.__name__ == 'Mesh':
        if re_name.match(object.name) or len(object.data.vertices) == 4:
            planes.append(object)

# assert len(planes) == 1 # ?
plane = planes[0]
x, y, z = plane.dimensions
z = None

# assert len(plane.material_slots) == 1 # ?
material = plane.material_slots[0].material

import site
sys.path.append(site.getusersitepackages())
sys.path.append(ATOOL_PATH)

import node_utils

node_tree = node_utils.Node_Tree_Wrapper(material.node_tree)
output = node_tree.output

mappings = []
for node in output.all_children:

    if node.type == 'DISPLACEMENT':
        z = round(node.inputs['Scale'].default_value, 6)
    
    elif node.type == 'MAPPING':
        mappings.append(node)
        
if mappings:
    mapping = mappings[0]
    mapping_x, mapping_y, mapping_z = mapping.inputs['Scale'].default_value
else:
    mapping_x = mapping_y = 1

dimensions = {
    "x": x/mapping_x,
    "y": y/mapping_y,
    "z": z if z else 0.05
}

import json
print(json.dumps(dimensions))
