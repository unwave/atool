import subprocess
import os
import sys
import argparse
import tempfile
import json

DIR_PATH = os.path.dirname(__file__)

def get_desktop():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return winreg.QueryValueEx(key, "Desktop")[0]
    except:
        return os.path.expanduser("~/Desktop")

parser = argparse.ArgumentParser()
parser.add_argument('-blender')
parser.add_argument('-dicing')
parser.add_argument('-file')

args = parser.parse_args(sys.argv[1:])

script = os.path.join(DIR_PATH, 'render_partial.py')

args = [args.blender, '-b', '--factory-startup', args.file, '--python', script, '--', '-dicing', args.dicing]

with tempfile.TemporaryDirectory() as temp_dir:

    args.extend(('-path', temp_dir))

    subprocess.run(args, check = True)

    with open(os.path.join(temp_dir, 'done.json'), 'r', encoding='utf-8') as json_file:
        columns = json.load(json_file)

    import site
    sys.path.insert(0, site.getusersitepackages())

    import cv2 as cv
    import numpy

    def get_image(path):
        return cv.imread(path, cv.IMREAD_UNCHANGED | cv.IMREAD_ANYCOLOR | cv.IMREAD_ANYDEPTH)

    render_columns = []

    for image_paths in columns:
        images = [get_image(path) for path in image_paths]
        render_columns.append(numpy.concatenate(images, axis=0))

    render = numpy.concatenate(render_columns, axis=1)

    from datetime import datetime

    ext ='.png'
    render_path = os.path.join(get_desktop(), f"render_{datetime.now().strftime('%y%m%d_%H%M%S')}{ext}")
    cv.imwrite(render_path, render)

input('Press any key to exit...')