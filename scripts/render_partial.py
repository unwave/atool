import bpy
import os
import sys
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('-dicing', type=int)
parser.add_argument('-path')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

print(args)

camera = bpy.context.scene.camera.data
render = bpy.context.scene.render
cycles =  bpy.context.scene.cycles

if cycles.device == 'GPU':
    print(cycles.device == 'GPU')
    cycles_preferences = bpy.context.preferences.addons['cycles'].preferences
    cycles_preferences.compute_device_type = 'CUDA'
    for devices in cycles_preferences.get_devices():
        for device in devices:
            device.use = True

cycles.offscreen_dicing_scale = 32
render.use_persistent_data = True

initial_shift_x = camera.shift_x
initial_shift_y = camera.shift_y

k = render.resolution_x/render.resolution_y
m = args.dicing

shift_step_x = 1
shift_step_y = 1

shift_lim_x = abs(1-m)/2
shift_lim_y = abs(1-m)/2
if k >= 1:
    shift_step_y = 1/k
    shift_lim_y /= k
else:
    shift_step_x = 1*k
    shift_lim_x *= k

camera.lens *= m
render.resolution_x /= m 
render.resolution_y /= m

columns = []
index = 1
max_index = m*m

x = -shift_lim_x
while x <= shift_lim_x:
    camera.shift_x = x  + m * initial_shift_x
    
    rows = []

    y = -shift_lim_y
    while y <= shift_lim_y:
        camera.shift_y = y + m * initial_shift_y
        
        print('--------------------------')
        print(f'Part: {index}/{max_index}')
        print('--------------------------')
        bpy.ops.render.render()
        image = bpy.data.images['Render Result']
        path = os.path.join(args.path, f"{y}_{x}.png")
        rows.append(path)
        image.save_render(path)
        
        index += 1
        y += shift_step_y
        
    columns.append(list(reversed(rows)))
    x += shift_step_x  

with open(os.path.join(args.path, 'done.json'), 'w', encoding='utf-8') as json_file:
    json.dump(columns, json_file, indent = 4, ensure_ascii = False)