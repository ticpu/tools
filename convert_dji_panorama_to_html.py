#!/usr/bin/env python3

import os
import sys
import subprocess
import base64
import urllib.request
import shutil
import glob
from pathlib import Path

def run_command(cmd, description=None):
    """Run a command with nice priority and error handling"""
    nice_cmd = ['nice', '-n19'] + cmd
    if description:
        print(f"  {description}...")

    try:
        result = subprocess.run(nice_cmd, capture_output=True, text=True, check=True)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print(f"Command output: {e.stdout}")
        print(f"Command error: {e.stderr}")
        raise

def extract_gimbal_positions(input_dir):
    """Extract gimbal positions from EXIF data"""
    positions = []
    jpg_files = sorted(glob.glob(os.path.join(input_dir, "*.JPG")))

    for i, jpg_file in enumerate(jpg_files):
        try:
            # Get yaw
            yaw_result = subprocess.run(['exiftool', '-GimbalYawDegree', '-s3', jpg_file],
                                      capture_output=True, text=True, check=True)
            yaw = yaw_result.stdout.strip()

            # Get pitch
            pitch_result = subprocess.run(['exiftool', '-GimbalPitchDegree', '-s3', jpg_file],
                                        capture_output=True, text=True, check=True)
            pitch = pitch_result.stdout.strip()

            positions.append(f"y{i}={yaw},p{i}={pitch}")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not extract EXIF from {jpg_file}")

    return positions

def create_standalone_viewer(image_file, output_html, temp_dir):
    """Create self-contained HTML viewer with embedded image and A-Frame"""
    print("  Creating self-contained HTML viewer...")

    # Download A-Frame if not cached
    aframe_path = os.path.join(temp_dir, "aframe.min.js")
    if not os.path.exists(aframe_path):
        print("    Downloading A-Frame JS...")
        with urllib.request.urlopen("https://aframe.io/releases/1.2.0/aframe.min.js") as response:
            aframe_js = response.read().decode('utf-8')
        with open(aframe_path, 'w') as f:
            f.write(aframe_js)
    else:
        with open(aframe_path, 'r') as f:
            aframe_js = f.read()

    # Base64 encode the image
    print("    Encoding image as base64...")
    with open(image_file, 'rb') as f:
        image_data = f.read()
    image_base64 = base64.b64encode(image_data).decode('utf-8')

    # Clean HTML template without controls
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>360° Photosphere Viewer</title>
<style>
body {{
    margin: 0;
    padding: 0;
    overflow: hidden;
    font-family: Arial, sans-serif;
    background: #111;
}}
.info {{
    position: absolute;
    bottom: 20px;
    left: 20px;
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
}}
</style>
<script>
{aframe_js}
</script>
</head>
<body>
  <div style="width: 100vw; height: 100vh;">
    <a-scene embedded background="color: #111">
      <a-sky id="sky" src="data:image/jpeg;base64,{image_base64}" rotation="0 -130 0"></a-sky>
      <a-camera id="camera" position="0 0 0" fov="80">
      </a-camera>
    </a-scene>
  </div>

  <div class="info">
    Use mouse to look around | Scroll to zoom
  </div>

  <script>
    document.querySelector('a-scene').addEventListener('wheel', (event) => {{
      event.preventDefault();
      const camera = document.getElementById('camera');
      let fov = camera.getAttribute('fov') - event.deltaY * 0.05;
      fov = Math.max(20, Math.min(100, fov));
      camera.setAttribute('fov', fov);
    }});
  </script>
</body>
</html>'''

    # Write the HTML file
    with open(output_html, 'w') as f:
        f.write(html_content)

    print(f"    ✓ Self-contained viewer saved to {output_html}")

def process_photosphere(input_dir, output_path, temp_dir):
    """Process photosphere (360° panorama)"""
    print("Processing photosphere panorama...")

    # Create output directory
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Step 1: Generate initial PTO
    pto_file = os.path.join(temp_dir, "photosphere.pto")
    jpg_pattern = os.path.join(input_dir, "*.JPG")
    run_command(['pto_gen', '-o', pto_file, '-p', '0', '-f', '73.7'] + glob.glob(jpg_pattern),
                "Generating initial PTO file")

    # Step 2: Set equirectangular projection
    run_command(['pano_modify', '--projection=2', '--fov=360x180', '--canvas=8192x4096',
                '-o', pto_file, pto_file], "Setting equirectangular projection")

    # Step 3: Extract and apply positions
    positions = extract_gimbal_positions(input_dir)
    positions_file = os.path.join(temp_dir, "positions.txt")
    with open(positions_file, 'w') as f:
        f.write('\n'.join(positions))

    run_command(['pto_var', f'--set-from-file={positions_file}', '-o', pto_file, pto_file],
                "Applying gimbal positions")

    # Step 4: Find control points
    cp_pto = os.path.join(temp_dir, "photosphere_cp.pto")
    run_command(['cpfind', '--multirow', '--celeste', '-o', cp_pto, pto_file],
                "Finding control points")

    # Step 5: Optimize
    opt_pto = os.path.join(temp_dir, "photosphere_opt.pto")
    run_command(['autooptimiser', '-a', '-m', '-l', '-s', '-o', opt_pto, cp_pto],
                "Optimizing alignment")

    # Step 6: Stitch
    run_command(['nona', '-m', 'JPEG', '-o', output_path, opt_pto],
                "Stitching panorama")

    jpg_file = f"{output_path}.jpg"

    # Step 7: Copy EXIF from first source image and add XMP metadata
    first_image = sorted(glob.glob(os.path.join(input_dir, "*.JPG")))[0]
    run_command(['exiftool',
                f'-tagsFromFile={first_image}',
                '-ProjectionType=equirectangular',
                '-UsePanoramaViewer=True',
                '-CroppedAreaImageWidthPixels=8192',
                '-CroppedAreaImageHeightPixels=4096',
                '-CroppedAreaLeftPixels=0',
                '-CroppedAreaTopPixels=0',
                '-FullPanoWidthPixels=8192',
                '-FullPanoHeightPixels=4096',
                '-overwrite_original',
                jpg_file], "Copying EXIF data and adding XMP metadata")

    print(f"✓ Photosphere saved to {jpg_file}")

    # Step 8: Create self-contained HTML viewer
    html_file = f"{output_path}_viewer.html"
    create_standalone_viewer(jpg_file, html_file, temp_dir)

def process_wide(input_dir, output_path, temp_dir):
    """Process wide panorama"""
    print("Processing wide panorama...")

    # Create output directory
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Step 1: Generate initial PTO
    pto_file = os.path.join(temp_dir, "wide.pto")
    jpg_pattern = os.path.join(input_dir, "*.JPG")
    run_command(['pto_gen', '-o', pto_file, '-p', '0', '-f', '73.7'] + glob.glob(jpg_pattern),
                "Generating initial PTO file")

    # Step 2: Set cylindrical projection
    run_command(['pano_modify', '--projection=1', '--fov=120x80', '--canvas=4000x2000',
                '-o', pto_file, pto_file], "Setting cylindrical projection")

    # Step 3: Extract and apply positions
    positions = extract_gimbal_positions(input_dir)
    positions_file = os.path.join(temp_dir, "positions.txt")
    with open(positions_file, 'w') as f:
        f.write('\n'.join(positions))

    run_command(['pto_var', f'--set-from-file={positions_file}', '-o', pto_file, pto_file],
                "Applying gimbal positions")

    # Step 4: Find control points
    cp_pto = os.path.join(temp_dir, "wide_cp.pto")
    run_command(['cpfind', '--multirow', '--celeste', '-o', cp_pto, pto_file],
                "Finding control points")

    # Step 5: Optimize
    opt_pto = os.path.join(temp_dir, "wide_opt.pto")
    run_command(['autooptimiser', '-a', '-m', '-l', '-s', '-o', opt_pto, cp_pto],
                "Optimizing alignment")

    # Step 6: Stitch
    run_command(['nona', '-m', 'JPEG', '-o', output_path, opt_pto],
                "Stitching panorama")

    jpg_file = f"{output_path}.jpg"

    # Copy EXIF from first source image
    first_image = sorted(glob.glob(os.path.join(input_dir, "*.JPG")))[0]
    run_command(['exiftool', f'-tagsFromFile={first_image}', '-overwrite_original', jpg_file],
                "Copying EXIF data")

    print(f"✓ Wide panorama saved to {jpg_file}")
    print("  (View directly - no special viewer needed)")

def cleanup_temp_files(temp_dir):
    """Clean up large temporary files"""
    print("Cleaning up temporary files...")

    # Remove large files
    for pattern in ['*.tif', '*.tiff', '*.TIF', '*.TIFF', 'photosphere*.pto', 'wide*.pto', 'positions.txt']:
        for file_path in glob.glob(os.path.join(temp_dir, pattern)):
            try:
                os.remove(file_path)
                print(f"  Removed {os.path.basename(file_path)}")
            except OSError:
                pass

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 convert_panorama.py <input_directory> <output_path>")
        print("Examples:")
        print("  python3 convert_panorama.py panoramas/100_0345 pictures/vacation_360")
        print("  python3 convert_panorama.py panoramas/100_0344 pictures/")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_arg = sys.argv[2]
    temp_dir = "temp"

    # Check if input directory exists
    if not os.path.exists(input_dir):
        print(f"Error: Directory {input_dir} does not exist")
        sys.exit(1)

    # Determine output path
    if os.path.isdir(output_arg):
        # If output is a directory, use input directory name as base
        input_name = os.path.basename(input_dir.rstrip('/'))
        output_path = os.path.join(output_arg, input_name)
    else:
        # Use the provided path as-is
        output_path = output_arg

    # Create temp directory
    os.makedirs(temp_dir, exist_ok=True)

    # Count images to determine panorama type
    jpg_files = glob.glob(os.path.join(input_dir, "*.JPG")) + glob.glob(os.path.join(input_dir, "*.jpg"))
    image_count = len(jpg_files)

    print(f"Found {image_count} images in {input_dir}")

    try:
        if image_count == 26:
            process_photosphere(input_dir, output_path, temp_dir)
        elif image_count == 9:
            process_wide(input_dir, output_path, temp_dir)
        else:
            print(f"Error: Unknown panorama type (found {image_count} images)")
            print("Expected 26 images for photosphere or 9 images for wide panorama")
            sys.exit(1)

        print("✓ Conversion complete!")

    finally:
        # Always cleanup temp files
        cleanup_temp_files(temp_dir)

if __name__ == "__main__":
    main()