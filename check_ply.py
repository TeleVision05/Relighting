"""Check PLY file structure and estimate render time."""
import math
from pathlib import Path

path = Path("Buttons.ply")
data = path.read_bytes()
idx = data.find(b"end_header")
header_text = data[:idx].decode("latin1", "ignore")
lines = header_text.splitlines()
property_names = []
vertex_count = None
for line in lines:
    if line.startswith("element vertex"):
        vertex_count = int(line.split()[-1])
    elif line.startswith("property float"):
        property_names.append(line.split()[-1])

print(f"PLY file size: {path.stat().st_size / 1024 / 1024:.2f} MB")
print(f"Vertex count: {vertex_count}")
print(f"Properties per vertex: {len(property_names)}")
print(f"Property names: {property_names}")
if vertex_count:
    total_floats = vertex_count * len(property_names)
    print(f"Total float values needed: {total_floats}")
    
    # Estimate render time based on the code analysis
    # The main loop does matrix operations for each splat
    # with nested loops over pixels in the bounding box
    
    # Check if all required properties exist
    required = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", 
                "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2",
                "rot_0", "rot_1", "rot_2", "rot_3"]
    missing = [r for r in required if r not in property_names]
    if missing:
        print(f"MISSING properties: {missing}")
    else:
        print("All required properties are present!")
