import os
import sys
import argparse

# Force standard libraries
import hou

def main():
    parser = argparse.ArgumentParser(description="Render FBX clip preview headlessly in background")
    parser.add_argument("--fbx", required=True, help="Path to FBX file")
    parser.add_argument("--clip", required=True, help="Clip name")
    parser.add_argument("--outdir", required=True, help="Output folder")
    parser.add_argument("--maxframes", type=int, default=30, help="Max frames to render")
    args = parser.parse_args()
    
    fbx_path = args.fbx.replace("\\", "/")
    clip_name = args.clip
    out_dir = args.outdir.replace("\\", "/")
    max_frames = args.maxframes
    
    os.makedirs(out_dir, exist_ok=True)
    
    obj = hou.node("/obj")
    out = hou.node("/out")
    
    # Create temporary nodes
    temp_geo = obj.createNode("geo", "render_geo")
    agent = temp_geo.createNode("agent", "agent_node")
    agent.parm("input").set("fbx")
    agent.parm("fbxfile").set(fbx_path)
    agent.parm("fbxlocomotionnode").set("root") # Will be overridden after cook if needed
    agent.parm("createlocomotionjoint").set(1)
    agent.parm("applylocomotion").set(0) # IN-PLACE
    
    # Cook the agent SOP to load the rig definition
    agent.cook()
    
    # Resolve the locomotion joint name dynamically
    locomotion_joint = "root"
    try:
        geo = agent.geometry()
        if geo and geo.prims():
            definition = geo.prims()[0].definition()
            rig = definition.rig()
            # Heuristic 1: Find a joint containing "hips" or "pelvis" (standard for character rigs)
            for i in range(rig.transformCount()):
                name = rig.transformName(i)
                if name != "__locomotion__" and ("hips" in name.lower() or "pelvis" in name.lower()):
                    locomotion_joint = name
                    break
            # Heuristic 2: If not found, look for "root" or "locomotion" (excluding __locomotion__)
            if locomotion_joint == "root":
                for i in range(rig.transformCount()):
                    name = rig.transformName(i)
                    if name != "__locomotion__" and ("root" in name.lower() or "locomotion" in name.lower()):
                        locomotion_joint = name
                        break
            # Heuristic 3: Fallback to the top-level parent index == -1 (excluding __locomotion__)
            if locomotion_joint == "root":
                for i in range(rig.transformCount()):
                    name = rig.transformName(i)
                    if name != "__locomotion__" and rig.parentIndex(i) == -1:
                        locomotion_joint = name
                        break
    except Exception as re:
        print(f"Warning: Failed to resolve locomotion joint from rig: {re}")
        
    # Apply correct locomotion node to agent
    agent.parm("fbxlocomotionnode").set(locomotion_joint)
    agent.cook(force=True)
        
    # Connect agentclip to convert to in-place
    agentclip = temp_geo.createNode("agentclip", "agent_inplace_clip")
    agentclip.setInput(0, agent)
    agentclip.parm("clips").set(1)
    agentclip.parm("source1").set("fbx")
    agentclip.parm("file1").set(fbx_path)
    agentclip.parm("name1").set(clip_name)
    agentclip.parm("converttoinplace1").set(1) # IN-PLACE
    agentclip.parm("locomotionnode").set(locomotion_joint)
    agentclip.parm("applylocomotion").set(0) # IN-PLACE
    
    # Set current clip on agentclip
    agentclip.parm("setcurrentclip").set(1)
    agentclip.parm("currentclip").set(clip_name)
    
    # Cook agentclip to compute geometry
    agentclip.cook()
    
    geo = agentclip.geometry()
    prims = geo.prims()
    if not prims:
        print("Error: No agent primitives cooked.")
        sys.exit(1)
        
    prim = prims[0]
    definition = prim.definition()
    clips = list(definition.clips())
    if not clips:
        print("Error: No clips found in definition.")
        sys.exit(1)
        
    # Find matching clip
    target_clip = None
    for c in clips:
        if c.name() == clip_name:
            target_clip = c
            break
    if not target_clip:
        target_clip = clips[0]
        
    sample_count = target_clip.sampleCount()
    render_end_frame = min(max_frames, sample_count)
    
    # 2. Unpack agent temporarily to get true character height and bounding box center
    unpack = temp_geo.createNode("agentunpack", "temp_unpack")
    unpack.setInput(0, agentclip)
    unpack.cook()
    bbox = unpack.geometry().boundingBox()
    center = bbox.center()
    size = bbox.maxvec() - bbox.minvec()
    height = size.y() if size.y() > 0.001 else 1.8
    unpack.destroy()
    
    # Ensure agentclip remains the display/render node
    agentclip.setDisplayFlag(True)
    agentclip.setRenderFlag(True)
    
    # Target height: center of the character body
    lookat_target = obj.createNode("null", "lookat_target")
    lookat_target.parm("tx").set(center.x())
    lookat_target.parm("ty").set(center.y())
    lookat_target.parm("tz").set(center.z())
    lookat_target.setDisplayFlag(False) # Hide from viewport render
    
    # 45 degrees lateral, tight low-angle (contrapicado)
    # Pitch yaw distance math
    distance = height * 2.5
    # 45 degrees to the right-front
    import math
    rad_45 = math.radians(45)
    dx = distance * math.sin(rad_45)
    dz = distance * math.cos(rad_45)
    
    cam = obj.createNode("cam", "render_cam")
    # Position camera low (18% of height below center) looking up for a dramatic contrapicado
    cam.parm("tx").set(center.x() + dx)
    cam.parm("ty").set(center.y() - height * 0.18)
    cam.parm("tz").set(center.z() + dz)
    
    # Point camera to lookat_target
    cam.parm("lookatpath").set(lookat_target.path())
    
    # 3. Setup OpenGL ROP
    opengl = out.createNode("opengl", "render_rop")
    opengl.parm("camera").set(cam.path())
    
    output_pattern = os.path.join(out_dir, f"{clip_name}.$F4.png").replace("\\", "/")
    opengl.parm("picture").set(output_pattern)
    
    opengl.parm("trange").set(1) # Render Range
    opengl.parm("f1").set(1)
    opengl.parm("f2").set(render_end_frame)
    opengl.parm("f3").set(1)
    
    # Hide HUD overlays
    for p_name in ["drawgrid", "draworigin", "drawhud"]:
        p = opengl.parm(p_name)
        if p:
            p.set(0)
            
    print(f"Starting render of {clip_name}: frames 1 to {render_end_frame}...")
    opengl.render()
    print("Render finished successfully.")

if __name__ == "__main__":
    main()
