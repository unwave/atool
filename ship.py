import zipfile
import os
import tempfile
import subprocess
import sys
from datetime import datetime

BLENDER_PATH = "blender"

FILE_EXTENSION = (".blend", ".py", ".md", ".json")

current_dir = os.path.dirname(os.path.realpath(__file__))
dir_name = os.path.basename(current_dir)

files_to_pack = [file for file in os.scandir(current_dir) if file.is_file() and file.name.lower().endswith(FILE_EXTENSION)]

current_directory = os.path.dirname(os.path.realpath(__file__))

try:
    from win32com.shell import shell, shellcon # type: ignore
    desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, 0, 0)
except:
    try:
        if sys.platform == "win32":
            command = r'reg query "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders" /v "Desktop"'
            result = subprocess.run(command, stdout=subprocess.PIPE, text = True)
            desktop = result.stdout.splitlines()[2].split()[2]
        else:
            desktop = os.path.expanduser("~/Desktop")
    except:
        desktop = os.path.expanduser("~/Desktop")


time_stamp = datetime.now().strftime('%y%m%d_%H%M%S')
zipfile_path = os.path.join(desktop, "atool_" + time_stamp + ".zip")


with tempfile.TemporaryDirectory() as temp_dir:
    temp_blend = os.path.join(temp_dir, "temp.blend")

    script = "\n".join([
        "import bpy",
        "node_groups = {node_group for node_group in bpy.data.node_groups if not node_group.name.startswith('#')}",
        f"bpy.data.libraries.write(r'{temp_blend}', node_groups, compress=True, fake_user=True)",
        "bpy.ops.wm.quit_blender()"
    ])
    blend_data_path = os.path.join(current_directory, "data.blend")
    subprocess.run([BLENDER_PATH, "-b", blend_data_path,  "--python-expr", script, "--factory-startup"], check = True)

    with zipfile.ZipFile(zipfile_path, 'w') as zip_file:
        for file in files_to_pack:
            if file.name in ("ship.py", "config.json"):
                continue
            elif file.name == "data.blend":
                zip_file.write(temp_blend, arcname = os.path.join(dir_name, file.name), compress_type = zipfile.ZIP_DEFLATED)
            else:
                zip_file.write(file.path, arcname = os.path.join(dir_name, file.name), compress_type = zipfile.ZIP_DEFLATED)
                
        
print(zipfile_path)
print("Done")