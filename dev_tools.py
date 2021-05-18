import bpy
import pyperclip

class Shader_Editor_Poll():
    @classmethod
    def poll(cls, context):
        return context.space_data.type == 'NODE_EDITOR' and context.space_data.tree_type == 'ShaderNodeTree'

class ATOOL_OT_copy_to_clipboard(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "nodeinsp.copy_to_clipboard"
    bl_label = "Copy To clipboard"
    bl_description = "Click to copy the content"
    bl_options = {'REGISTER'}
    
    string: bpy.props.StringProperty()

    def execute(self, context):
        
        pyperclip.copy(self.string)
        
        return {'FINISHED'}
    
class ATOOL_OT_copy_all_to_clipboard(bpy.types.Operator, Shader_Editor_Poll):
    bl_idname = "nodeinsp.copy_all_to_clipboard"
    bl_label = ""
    bl_description = "Click to copy the content for all the selected nodes"
    bl_options = {'REGISTER'}
    
    attribute: bpy.props.StringProperty()

    def execute(self, context):
        
        attributes = [getattr(node, self.attribute) for node in context.selected_nodes]
        
        pyperclip.copy(attributes.__repr__())
        
        return {'FINISHED'}

class ATOOL_PT_node_inspector(bpy.types.Panel):
    bl_idname = "ATOOL_PT_node_inspector"
    bl_label = "Node Inspector"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'
    
    def draw(self, context):
        
        layout = self.layout
        column = layout.column()
        
        def row(name, object, attribute):
            value = getattr(object, attribute)
            
            if attribute.startswith("_"):
                return
            class_name = type(value).__name__
            module = type(value).__module__
            if class_name == "bpy_func":
                return
            if module == "bpy.types":
                return
            if class_name in ("Color", "Vector"):
                value = tuple(value) 
            
            value = str(value)
            
            row = column.row(align=True)
            row.operator("nodeinsp.copy_to_clipboard", text=name, emboss=False).string = name
            row.operator("nodeinsp.copy_to_clipboard", text=value).string = value
            row.operator("nodeinsp.copy_all_to_clipboard", text='', icon='COPYDOWN').attribute = attribute
        
        selected_nodes = context.selected_nodes
        if selected_nodes:
            active_node = selected_nodes[0]
            row("name", active_node, "name")
            row("type", active_node, "type")
            row("bl_idname:", active_node, "bl_idname")
            
            column.separator()
            for output in active_node.outputs:
                row("Ouput:", output, "identifier")
            column.separator()
            for input in active_node.inputs:
                row("Input:", input, "identifier")
            column.separator()
            
            for attribute in dir(active_node):
                row(attribute, active_node, attribute)
