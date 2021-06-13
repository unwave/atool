import bpy
import os
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-dicing', type=int)
parser.add_argument('-render_path')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

import site
sys.path.insert(0, site.getusersitepackages())

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
        path = os.path.join(bpy.app.tempdir, f"{y}_{x}.png")
        rows.append(path)
        image.save_render(path)
        
        index += 1
        y += shift_step_y
        
    columns.append(reversed(rows))
    x += shift_step_x  

import cv2 as cv
import numpy

def get_image(path):
    return cv.imread(path, cv.IMREAD_UNCHANGED | cv.IMREAD_ANYCOLOR | cv.IMREAD_ANYDEPTH)

render_columns = []

for image_paths in columns:
    images = [get_image(path) for path in  image_paths]
    render_columns.append(numpy.concatenate(images, axis=0))

render = numpy.concatenate(render_columns, axis=1)

from datetime import datetime

ext ='.png'
render_path = os.path.join(args.render_path, f"render_{datetime.now().strftime('%y%m%d_%H%M%S')}{ext}")
cv.imwrite(render_path, render)