bl_info = {
    "name": "Treatment Evaluation",
    "blender": (3, 0, 0),
    "category": "Object",
    "author": "Natalie Dunbar",
    "version": (3, 0),
    "description": "Analyze implant deviations and overlap using boolean mesh intersection"
}

import bpy
import math
import numpy as np
import bmesh
from mathutils import Vector

# ==========================================================
#                     MATH UTILITIES
# ==========================================================

def vector_components(p1, p2):
    return np.array(p2) - np.array(p1)

def distance(p1, p2):
    return np.linalg.norm(vector_components(p1, p2))

def angle_between_vectors(v1, v2):
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    cos_theta = np.dot(v1, v2) / (norm_v1 * norm_v2)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    return math.degrees(math.acos(cos_theta))

def cylinder_volume(r_top, r_bottom, h):
    """Calculate volume of truncated cone using standard geometric formula."""
    return (1/3) * math.pi * h * (r_top**2 + r_top * r_bottom + r_bottom**2)

# ==========================================================
#              MESH-BASED OVERLAP CALCULATION
# ==========================================================

def create_truncated_cone(name, base_pos, apex_pos, base_radius, apex_radius):
    """
    Create truncated cone mesh for 3D geometric analysis.
    
    Args:
        name: Object identifier
        base_pos: 3D coordinates of cone base
        apex_pos: 3D coordinates of cone apex  
        base_radius: Radius at base position (mm)
        apex_radius: Radius at apex position (mm)
    
    Returns:
        Blender mesh object or None if invalid input
    """
    # Calculate cone dimensions and direction vector
    direction = np.array(apex_pos) - np.array(base_pos)
    height = np.linalg.norm(direction)
    
    if height == 0:
        print(f"ERROR: Zero height cone - invalid geometry")
        return None

    # Position at midpoint between endpoints
    center = (np.array(base_pos) + np.array(apex_pos)) / 2
    
    # Create mesh primitive
    bpy.ops.mesh.primitive_cone_add(vertices=64, 
                                    radius1=base_radius,
                                    radius2=apex_radius,
                                    depth=height,
                                    location=center)
    obj = bpy.context.active_object
    obj.name = name

    # Align with direction vector
    direction_norm = direction / height
    up = np.array([0, 0, 1])
    down = np.array([0, 0, -1])
    
    if np.allclose(direction_norm, up, atol=1e-6):
        pass  # Already aligned
    elif np.allclose(direction_norm, down, atol=1e-6):
        # Flip 180° around X-axis
        obj.rotation_mode = 'AXIS_ANGLE'
        obj.rotation_axis_angle = (math.pi, 1.0, 0.0, 0.0)
    else:
        # Compute rotation axis using cross product
        axis = np.cross(up, direction_norm)
        axis_length = np.linalg.norm(axis)
        
        if axis_length > 1e-6:
            axis_norm = axis / axis_length
            angle = math.acos(np.clip(np.dot(up, direction_norm), -1.0, 1.0))
            obj.rotation_mode = 'AXIS_ANGLE'
            obj.rotation_axis_angle = (angle, axis_norm[0], axis_norm[1], axis_norm[2])
        else:
            print("WARNING: Cannot compute rotation axis")
    
    return obj

def boolean_intersection_volume(obj_a, obj_b):
    """Calculate volume of intersection between two mesh objects.
    
    Args:
        obj_a: First mesh object
        obj_b: Second mesh object
        
    Returns:
        float: Volume of intersection in cubic units
    """
    # Create mesh copies for boolean operation
    a_copy = obj_a.copy()
    b_copy = obj_b.copy()
    a_copy.data = obj_a.data.copy()
    b_copy.data = obj_b.data.copy()
    bpy.context.collection.objects.link(a_copy)
    bpy.context.collection.objects.link(b_copy)

    # Apply boolean intersection
    bool_obj = a_copy.copy()
    bool_obj.data = a_copy.data.copy()
    bpy.context.collection.objects.link(bool_obj)
    mod = bool_obj.modifiers.new(type="BOOLEAN", name="Intersect")
    mod.operation = 'INTERSECT'
    mod.object = b_copy
    bpy.context.view_layer.objects.active = bool_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    # Calculate volume using bmesh computational geometry
    bm = bmesh.new()
    bm.from_mesh(bool_obj.data)
    volume = bm.calc_volume()
    bm.free()

    # Clean up temporary objects
    bpy.data.objects.remove(a_copy, do_unlink=True)
    bpy.data.objects.remove(b_copy, do_unlink=True)
    bpy.data.objects.remove(bool_obj, do_unlink=True)

    return abs(volume)

# ==========================================================
#                  PROPERTY GROUPS
# ==========================================================

class SingleImplantProperties(bpy.types.PropertyGroup):
    planned_base: bpy.props.PointerProperty(type=bpy.types.Object)
    planned_apex: bpy.props.PointerProperty(type=bpy.types.Object)
    real_base: bpy.props.PointerProperty(type=bpy.types.Object)
    real_apex: bpy.props.PointerProperty(type=bpy.types.Object)
    r_planned_top: bpy.props.FloatProperty(name="Planned Apex Radius", default=2.0)
    r_planned_bottom: bpy.props.FloatProperty(name="Planned Base Radius", default=2.0)
    r_real_top: bpy.props.FloatProperty(name="Real Apex Radius", default=2.0)
    r_real_bottom: bpy.props.FloatProperty(name="Real Base Radius", default=2.0)
    result: bpy.props.StringProperty(default="")

class ImplantSlotProperties(bpy.types.PropertyGroup):
    planned_base: bpy.props.PointerProperty(type=bpy.types.Object)
    planned_apex: bpy.props.PointerProperty(type=bpy.types.Object)
    real_base: bpy.props.PointerProperty(type=bpy.types.Object)
    real_apex: bpy.props.PointerProperty(type=bpy.types.Object)
    r_planned_top: bpy.props.FloatProperty(default=2.0)
    r_planned_bottom: bpy.props.FloatProperty(default=2.0)
    r_real_top: bpy.props.FloatProperty(default=2.0)
    r_real_bottom: bpy.props.FloatProperty(default=2.0)
    result: bpy.props.StringProperty(default="")

# ==========================================================
#                        OPERATORS
# ==========================================================

def analyze_implant(pb, pa, rb, ra, r_ptop, r_pbot, r_rtop, r_rbot):
    """Analyze implant placement accuracy through geometric comparison.
    
    Args:
        pb, pa: Planned implant base and apex coordinates
        rb, ra: Actual implant base and apex coordinates 
        r_ptop, r_pbot: Planned implant radii at apex and base
        r_rtop, r_rbot: Actual implant radii at apex and base
        
    Returns:
        str: Formatted analysis results
    """
    print("\n=== IMPLANT ANALYSIS ===")
    
    # Calculate position deviations at endpoints
    base_dev_vec = vector_components(pb, rb)
    apex_dev_vec = vector_components(pa, ra)
    base_dev_dist = np.linalg.norm(base_dev_vec)
    apex_dev_dist = np.linalg.norm(apex_dev_vec)
    
    # Calculate angular deviation between implant axes
    ang_dev = angle_between_vectors(vector_components(pb, pa), vector_components(rb, ra))

    print(f"Position deviations: Base={base_dev_dist:.2f}mm, Apex={apex_dev_dist:.2f}mm")
    print(f"Angular deviation: {ang_dev:.1f}°")

    # Generate 3D models for volumetric analysis
    print("Creating implant geometries...")
    planned_obj = create_truncated_cone("PlannedImplantTemp", pb, pa, base_radius=r_pbot, apex_radius=r_ptop)
    real_obj = create_truncated_cone("RealImplantTemp", rb, ra, base_radius=r_rbot, apex_radius=r_rtop)
    
    overlap_vol = 0.0
    if planned_obj and real_obj:
        print("Computing intersection volume...")
        overlap_vol = boolean_intersection_volume(planned_obj, real_obj)
        print(f"✓ Analysis complete - Overlap: {overlap_vol:.2f} mm³")
        print("Note: Temp objects created in scene")
    else:
        print("✗ Failed to create geometries")

    # Calculate overlap percentage
    planned_vol = cylinder_volume(r_ptop, r_pbot, distance(pb, pa))
    overlap_pct = 100.0 * overlap_vol / planned_vol if planned_vol > 0 else 0.0
    print(f"Overlap: {overlap_pct:.1f}% of planned volume\n")

    result = (
        f"Base deviation vector: ({base_dev_vec[0]:.3f}, {base_dev_vec[1]:.3f}, {base_dev_vec[2]:.3f}) mm\n"
        f"Base deviation distance: {base_dev_dist:.3f} mm\n"
        f"Apex deviation vector: ({apex_dev_vec[0]:.3f}, {apex_dev_vec[1]:.3f}, {apex_dev_vec[2]:.3f}) mm\n"
        f"Apex deviation distance: {apex_dev_dist:.3f} mm\n"
        f"Angular deviation: {ang_dev:.2f}°\n"
        f"Overlap volume: {overlap_vol:.2f} mm³\n"
        f"Overlap percentage: {overlap_pct:.2f} %"
    )
    return result

class OBJECT_OT_RunSingleImplant(bpy.types.Operator):
    bl_idname = "object.run_single_implant"
    bl_label = "Run Single Implant Analysis"

    def execute(self, context):
        props = context.scene.single_implant
        
        if not all([props.planned_base, props.planned_apex, props.real_base, props.real_apex]):
            self.report({'ERROR'}, "Select all 4 spheres.")
            return {'CANCELLED'}

        # Extract coordinates - use mesh center instead of object origin
        def get_mesh_center(obj):
            """Get the center of the object's mesh geometry in world coordinates."""
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            center = sum(bbox_corners, Vector()) / len(bbox_corners)
            return np.array(center)
        
        pb = get_mesh_center(props.planned_base)
        pa = get_mesh_center(props.planned_apex)
        rb = get_mesh_center(props.real_base)
        ra = get_mesh_center(props.real_apex)
        
        planned_distance = np.linalg.norm(pa - pb)
        real_distance = np.linalg.norm(ra - rb)
        
        # Validate geometric constraints for implant positioning
        min_distance = 0.1  # 0.1mm minimum distance between markers
        if planned_distance < min_distance:
            self.report({'WARNING'}, f"Planned base and apex are very close ({planned_distance:.3f}mm apart).")
        if real_distance < min_distance:
            self.report({'WARNING'}, f"Real base and apex are very close ({real_distance:.3f}mm apart).")
        if np.allclose(pb, [0, 0, 0], atol=0.1) and np.allclose(pa, [0, 0, 0], atol=0.1):
            self.report({'WARNING'}, "Planned implant spheres appear to be at origin. Check object selection.")

        props.result = analyze_implant(pb, pa, rb, ra,
                                       props.r_planned_top, props.r_planned_bottom,
                                       props.r_real_top, props.r_real_bottom)
        return {'FINISHED'}

class OBJECT_OT_RunSingleImplantSlot(bpy.types.Operator):
    bl_idname = "object.run_single_implant_slot"
    bl_label = "Run Single Implant Slot Analysis"
    
    implant_index = bpy.props.IntProperty()

    def execute(self, context):
        if self.implant_index >= len(context.scene.multiple_implants):
            self.report({'ERROR'}, f"Invalid implant index: {self.implant_index}")
            return {'CANCELLED'}
            
        slot = context.scene.multiple_implants[self.implant_index]
        print(f"Running analysis for implant slot {self.implant_index + 1}...")
        
        if not all([slot.planned_base, slot.planned_apex, slot.real_base, slot.real_apex]):
            self.report({'ERROR'}, f"Select all 4 spheres for implant {self.implant_index + 1}.")
            return {'CANCELLED'}

        # Extract coordinates - use mesh center instead of object origin
        def get_mesh_center(obj):
            """Get the center of the object's mesh geometry in world coordinates."""
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            center = sum(bbox_corners, Vector()) / len(bbox_corners)
            return np.array(center)
        
        pb = get_mesh_center(slot.planned_base)
        pa = get_mesh_center(slot.planned_apex)
        rb = get_mesh_center(slot.real_base)
        ra = get_mesh_center(slot.real_apex)

        print(f"Implant {self.implant_index + 1} - Mesh center coordinates:")
        print("  Planned Base:", pb)
        print("  Planned Apex:", pa)
        print("  Real Base:", rb)
        print("  Real Apex:", ra)
        
        planned_distance = np.linalg.norm(pa - pb)
        real_distance = np.linalg.norm(ra - rb)
        
        print(f"Implant {self.implant_index + 1} - Distance between planned base and apex: {planned_distance:.6f}")
        print(f"Implant {self.implant_index + 1} - Distance between real base and apex: {real_distance:.6f}")
        
        # Validate that we have different positions
        min_distance = 0.1
        if planned_distance < min_distance:
            self.report({'WARNING'}, f"Planned base and apex are very close ({planned_distance:.6f}mm apart) for implant {self.implant_index + 1}.")
        if real_distance < min_distance:
            self.report({'WARNING'}, f"Real base and apex are very close ({real_distance:.6f}mm apart) for implant {self.implant_index + 1}.")

        slot.result = analyze_implant(pb, pa, rb, ra,
                                    slot.r_planned_top, slot.r_planned_bottom,
                                    slot.r_real_top, slot.r_real_bottom)
        return {'FINISHED'}

class OBJECT_OT_RunMultipleImplants(bpy.types.Operator):
    bl_idname = "object.run_multiple_implants"
    bl_label = "Run Multiple Implant Analysis"

    def execute(self, context):
        for i, slot in enumerate(context.scene.multiple_implants):
            if not all([slot.planned_base, slot.planned_apex, slot.real_base, slot.real_apex]):
                slot.result = f"Error: Select all 4 spheres for implant {i+1}."
                continue

            # Extract coordinates - use mesh center instead of object origin
            def get_mesh_center(obj):
                """Get the center of the object's mesh geometry in world coordinates."""
                bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
                center = sum(bbox_corners, Vector()) / len(bbox_corners)
                return np.array(center)
            
            pb = get_mesh_center(slot.planned_base)
            pa = get_mesh_center(slot.planned_apex)
            rb = get_mesh_center(slot.real_base)
            ra = get_mesh_center(slot.real_apex)
            
            planned_distance = np.linalg.norm(pa - pb)
            real_distance = np.linalg.norm(ra - rb)
            
            # Validate distances
            min_distance = 0.1
            if planned_distance < min_distance or real_distance < min_distance:
                slot.result = f"Warning: Very close spheres in implant {i+1}"
                continue

            slot.result = analyze_implant(pb, pa, rb, ra,
                                        slot.r_planned_top, slot.r_planned_bottom,
                                        slot.r_real_top, slot.r_real_bottom)
        return {'FINISHED'}

class OBJECT_OT_AddImplant(bpy.types.Operator):
    bl_idname = "object.add_implant"
    bl_label = "Add Implant"

    def execute(self, context):
        context.scene.multiple_implants.add()
        return {'FINISHED'}

class OBJECT_OT_RemoveImplant(bpy.types.Operator):
    bl_idname = "object.remove_implant"
    bl_label = "Remove Implant"
    
    implant_index: bpy.props.IntProperty(name="Implant Index", default=0)

    def execute(self, context):
        implants = context.scene.multiple_implants
        if 0 <= self.implant_index < len(implants):
            implants.remove(self.implant_index)
            self.report({'INFO'}, f"Removed implant {self.implant_index + 1}")
        else:
            self.report({'ERROR'}, f"Invalid implant index: {self.implant_index}")
        return {'FINISHED'}

# ==========================================================
#                         PANELS
# ==========================================================

class OBJECT_PT_SingleImplant(bpy.types.Panel):
    bl_label = "Single Implant"
    bl_idname = "OBJECT_PT_single_implant"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Treatment'

    def draw(self, context):
        layout = self.layout
        props = context.scene.single_implant

        layout.prop(props, "planned_base")
        layout.prop(props, "planned_apex")
        layout.prop(props, "real_base")
        layout.prop(props, "real_apex")
        layout.prop(props, "r_planned_top")
        layout.prop(props, "r_planned_bottom")
        layout.prop(props, "r_real_top")
        layout.prop(props, "r_real_bottom")

        layout.operator("object.run_single_implant", icon="PLAY")
        layout.label(text="Results:")
        for line in props.result.splitlines():
            layout.label(text=line)

class OBJECT_PT_MultipleImplants(bpy.types.Panel):
    bl_label = "Multiple Implants"
    bl_idname = "OBJECT_PT_multiple_implants"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Treatment'

    def draw(self, context):
        layout = self.layout
        
        for i, slot in enumerate(context.scene.multiple_implants):
            box = layout.box()
            
            # Header with implant number and remove button
            header = box.row()
            header.label(text=f"Implant {i+1}", icon="MESH_CYLINDER")
            remove_op = header.operator("object.remove_implant", text="", icon="X")
            remove_op.implant_index = i
            
            # Input fields (identical to single implant)
            box.prop(slot, "planned_base")
            box.prop(slot, "planned_apex")
            box.prop(slot, "real_base")
            box.prop(slot, "real_apex")
            box.prop(slot, "r_planned_top")
            box.prop(slot, "r_planned_bottom")
            box.prop(slot, "r_real_top")
            box.prop(slot, "r_real_bottom")

            # Individual run button for this implant
            run_row = box.row()
            run_op = run_row.operator("object.run_single_implant_slot", text=f"Run Implant {i+1} Analysis", icon="PLAY")
            run_op.implant_index = i
            
            # Results display
            if slot.result:
                box.label(text="Results:")
                for line in slot.result.splitlines():
                    box.label(text=line)
        
        # Add implant button at the bottom
        layout.separator()
        layout.operator("object.add_implant", text="Add Implant", icon="ADD")

# ==========================================================
#                    REGISTRATION
# ==========================================================

classes = [
    SingleImplantProperties,
    ImplantSlotProperties,
    OBJECT_OT_RunSingleImplant,
    OBJECT_OT_RunSingleImplantSlot,
    OBJECT_OT_RunMultipleImplants,
    OBJECT_OT_AddImplant,
    OBJECT_OT_RemoveImplant,
    OBJECT_PT_SingleImplant,
    OBJECT_PT_MultipleImplants
]

def init_properties(scene):
    if len(scene.multiple_implants) == 0:
        for _ in range(6):
            scene.multiple_implants.add()

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.single_implant = bpy.props.PointerProperty(type=SingleImplantProperties)
    bpy.types.Scene.multiple_implants = bpy.props.CollectionProperty(type=ImplantSlotProperties)
    bpy.app.timers.register(lambda: init_properties(bpy.context.scene), first_interval=0.1)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.single_implant
    del bpy.types.Scene.multiple_implants

if __name__ == "__main__":
    register()
