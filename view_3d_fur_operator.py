import bpy
import mathutils
import json
import subprocess
import os
import threading

from . import bl_utils
from . import utils

register = bl_utils.Register(globals())

class ATOOL_OT_add_fur(bpy.types.Operator, bl_utils.Object_Mode_Poll):
    bl_idname = "atool.add_fur"
    bl_label = "Add Fur"
    bl_description = "Add fur particle system."
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name = "Name", default = 'Fur')
    length: bpy.props.FloatProperty(name = "Length", default = 0.02)
    number: bpy.props.IntProperty(name = "Number", default = 500)

    vertex_group_density: bpy.props.StringProperty(name = "Density")
    invert_vertex_group_density: bpy.props.BoolProperty(name = "Invert Density")

    material: bpy.props.StringProperty(name = "Material")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        col = layout.column()
        col.prop(self, "name")
        col.prop(self, "length")
        col.prop(self, "number")

        
        row = col.row(align=True)
        row.prop_search(self, "vertex_group_density", context.object, "vertex_groups")
        row.prop(self, "invert_vertex_group_density", text = "", toggle = True, icon = 'ARROW_LEFTRIGHT')

        col.prop_search(self, "material", context.object, "material_slots")
        
    @property
    def random(self):
        return int(mathutils.noise.random() * 9999)

    def set_settings(self, settings: bpy.types.ParticleSettings):

        settings.name = self.name

        base_length = 0.016
        def proportional(value):
            new_value = value * self.length / base_length
            if type(value) == int:
                return int(new_value)
            else:
                return new_value

        def proportional_step(value, multiplier = 0.01):
            return max(1, value + int((proportional(value) - value) * multiplier))

        settings.count = self.number

        settings.hair_length = self.length
        settings.hair_step = min(proportional_step(5), 16)

        settings.factor_random = proportional(0.0002)
        settings.brownian_factor = proportional(0.0005)

        settings.render_step = min(proportional_step(5), 8)
        settings.display_step = min(proportional_step(3), 6)

        settings.length_random = 1

        settings.child_nbr = 100
        settings.rendered_child_count = 600

        settings.child_length = 0.666667
        settings.child_length_threshold = 0.333333

        # settings.virtual_parents = 1
        
        settings.clump_factor = 0.25
        settings.clump_shape = -0.1

        settings.child_parting_factor = 1

        settings.roughness_1 = proportional(0.003)
        settings.roughness_1_size = proportional(0.5)
        settings.roughness_endpoint = proportional(0.0022)
        settings.roughness_end_shape = 0
        settings.roughness_2 = proportional(0.007)
        settings.roughness_2_size = proportional(2)
        settings.roughness_2_threshold = 0.666667

        settings.kink = 'CURL'
        settings.kink_amplitude = proportional(0.0025)
        settings.kink_amplitude_clump = 0.5
        settings.kink_flat = 0
        settings.kink_frequency = 1
        settings.kink_shape = -0.333333

        settings.root_radius = 0.01

    def setup_system(self, object: bpy.types.Object):
        particle_system_modifier = object.modifiers.new(name = self.name, type='PARTICLE_SYSTEM')
        particle_system = particle_system_modifier.particle_system # type: bpy.types.ParticleSystem

        particle_system.seed = self.seed
        particle_system.child_seed = self.child_seed


        if self.vertex_group_density not in (group.name for group in object.vertex_groups):
            self.vertex_group_density = ''
        
        particle_system.vertex_group_density = self.vertex_group_density
        particle_system.invert_vertex_group_density = self.invert_vertex_group_density


        settings = particle_system.settings # type: bpy.types.ParticleSettings

        settings.type = 'HAIR'
        settings.use_modifier_stack = True
        settings.use_advanced_hair = True
        settings.distribution = 'RAND'
        settings.use_hair_bspline = True
        settings.use_parent_particles = True
        settings.child_type = 'INTERPOLATED'

        if self.material not in (material_slot.name for material_slot in object.material_slots):
            self.material = ''

        if self.material:
            settings.material_slot = self.material

        return particle_system

    def invoke(self, context, event):

        selected_objects = context.selected_objects

        if not selected_objects:
            self.report({'INFO'}, f"No selected objects.")
            return {'CANCELLED'}

        target = context.object
        if not hasattr(target, 'modifiers'):
            self.report({'INFO'}, f"{target.name} cannot have particles.")
            return {'CANCELLED'}

        self.target = bl_utils.Reference(target)

        self.seed = self.random
        self.child_seed = self.random

        return self.execute(context)

    def execute(self, context):
        
        target = self.target.get() # type: bpy.types.Object
        self.object = target

        if tuple(target.scale) != (1.0, 1.0, 1.0):
            self.report({'WARNING'}, f"The object has a not applied scale. This shall effect the fur rending.")

        self.particle_system = self.setup_system(target)
        self.set_settings(self.particle_system.settings)

        return {'FINISHED'}


class ATOOL_OT_isolate_particle_system(bpy.types.Operator, bl_utils.Object_Mode_Poll):
    bl_idname = "atool.isolate_particle_system"
    bl_label = "Isolate Particle System"
    bl_description = "Isolate the fur in the viewport display"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, "name", context.object, "particle_systems", text = 'Name')

    def execute(self, context):

        object = context.object

        modifiers = [modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM']
        for modifier in modifiers:
            particle_system = modifier.particle_system

            if self.name == particle_system.name:
                modifier.show_viewport = True
            else:
                modifier.show_viewport = False

        for index, particle_system in enumerate(object.particle_systems):
            if particle_system.name == self.name:
                object.particle_systems.active_index = index

        return {'FINISHED'}


class ATOOL_OT_show_all_particle_systems(bpy.types.Operator, bl_utils.Object_Mode_Poll):
    bl_idname = "atool.show_all_particle_systems"
    bl_label = "Show All"
    bl_description = "Show all the fur in the viewport display"
    bl_options = {'REGISTER', 'UNDO'}

    show_viewport: bpy.props.BoolProperty(name = 'Show Viewport', default = True)

    def execute(self, context):

        object = context.object

        modifiers = [modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM']
        for modifier in modifiers:
            particle_system = modifier.particle_system

            settings = particle_system.settings # type: bpy.types.ParticleSettings
            if settings.type == 'HAIR':
                modifier.show_viewport = self.show_viewport

        return {'FINISHED'}


class ATOOL_OT_render_view(bpy.types.Operator, bl_utils.Object_Mode_Poll):
    bl_idname = "atool.render_view"
    bl_label = "Render View"
    bl_description = "Render in background the current camera position with respect to viewport object and modifier visibility and save in the Desktop folder"
    bl_options = {'REGISTER'}

    resolution: bpy.props.IntProperty(name = 'Resolution', default = 512)
    samples: bpy.props.IntProperty(name = 'Samples', default = 10)

    use_default_world: bpy.props.BoolProperty(name = 'Default World', default = False)
    use_film_transparent: bpy.props.BoolProperty(name = 'Film Transparent', default = False)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def execute(self, context: bpy.context):

        space_view_3d = context.space_data
        region_3d = context.space_data.region_3d

        is_local_view = bool(space_view_3d.local_view)
        if is_local_view:
            local_view_objects = [object.name for object in bl_utils.get_local_view_objects(context)]
        else:
            local_view_objects = []

        view_matrix = region_3d.view_matrix.inverted()
        view_matrix_serializable = [list(row) for row in view_matrix]
    
        filepath = os.path.join(bpy.app.tempdir, utils.get_time_stamp() + '.blend')
        bpy.ops.wm.save_as_mainfile(filepath = filepath, copy=True, compress = False, check_existing = False)

        data = {
            'resolution': self.resolution,
            'samples': self.samples,
            'use_default_world': self.use_default_world,
            'use_film_transparent': self.use_film_transparent,

            'view_matrix': view_matrix_serializable,
            'lens': context.space_data.lens,
            'clip_start': context.space_data.clip_start,
            'clip_end': context.space_data.clip_end,

            'is_local_view': is_local_view,
            'local_view_objects': local_view_objects,

            'filepath': filepath
        }

        render_preview = utils.get_script('preview.py')
        argv = ['-job', json.dumps(data)]

        def run():
            bl_utils.run_blender(script = render_preview, argv = argv, use_atool = False) #, stdout = subprocess.DEVNULL)

        threading.Thread(target = run, args = ()).start()

        return {'FINISHED'}


class ATOOL_OT_rename_particle_system(bpy.types.Operator, bl_utils.Object_Mode_Poll):
    bl_idname = "atool.rename_particle_system"
    bl_label = "Rename Particle System"
    bl_description = "Rename the system, the modifier and the settings"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()
    new_name: bpy.props.StringProperty()

    def invoke(self, context, event):
        self.new_name = self.name
        return context.window_manager.invoke_props_dialog(self, width = 300)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name", text = 'New Name')

    def execute(self, context):

        object = context.object

        modifiers = [modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM']
        for modifier in modifiers:
            particle_system = modifier.particle_system

            if self.name == particle_system.name:
                modifier.name = self.new_name
                particle_system.name = self.new_name
                particle_system.settings.name = self.new_name

        return {'FINISHED'}
        