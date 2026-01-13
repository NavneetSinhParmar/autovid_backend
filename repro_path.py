import os
import urllib.parse

# Mock setup
DEBUG = True
if DEBUG:
    # Windows Local
    # FFMPEG = r"C:\ffmpeg-2025-12-28-git-9ab2a437a1-full_build\bin\ffmpeg.exe"
    pass
else:
    # Docker / Linux Server
    FFMPEG = "ffmpeg"

def to_local_path(url_or_path):
    if not url_or_path:
        return None
    # Try absolute path first
    if os.path.isabs(url_or_path) and os.path.exists(url_or_path):
        return url_or_path

    # Build media base directory
    base_dir = os.path.abspath("media")
    # Mocking base_dir for the test to match the user's environment structure roughly
    # In this script, it will be the current directory/media

    print(f"Base Dir: {base_dir}")

    # If URL contains '/media/' use the part after it as relative path
    if "/media/" in url_or_path:
        relative_part = url_or_path.split("/media/")[-1]
        
        # PROPOSED FIX: unquote
        # relative_part = urllib.parse.unquote(relative_part)
        
        abs_path = os.path.join(base_dir, *relative_part.split("/"))
        print(f"DEBUG: Checking file at -> {abs_path}")
        if os.path.exists(abs_path):
            return abs_path

    # If path starts with 'media/' or './media/' handle that
    if url_or_path.startswith("media/") or url_or_path.startswith("./media/") or url_or_path.startswith("media\\"):
        rel = url_or_path.split("media/", 1)[-1] if "media/" in url_or_path else url_or_path.split("media\\", 1)[-1]
        abs_path = os.path.join(base_dir, *rel.split("/"))
        print(f"DEBUG: Checking file at -> {abs_path}")
        if os.path.exists(abs_path):
            return abs_path

    # Fall back to searching by filename in media folder (recursively)
    filename = url_or_path.split("/")[-1].split("\\")[-1]
    
    # PROPOSED FIX: unquote filename
    # filename = urllib.parse.unquote(filename)

    abs_path = os.path.join(base_dir, filename)
    print(f"DEBUG: Looking for file at -> {abs_path}")
    if os.path.exists(abs_path):
        return abs_path

    # Search recursively for the filename inside media directory
    for root, dirs, files in os.walk(base_dir):
        if filename in files:
            found = os.path.join(root, filename)
            print(f"DEBUG: Found file in nested folder -> {found}")
            return found

    print(f"❌ FILE NOT FOUND: {filename} is missing in {base_dir}")
    return None

# Test setup
os.makedirs("media/test_company", exist_ok=True)
with open("media/test_company/test video.mp4", "w") as f:
    f.write("dummy content")

# Test Cases
print("--- Test 1: Standard URL ---")
url1 = "https://testtemplate.online/media/test_company/test video.mp4"
# Note: In reality, URL would likely be encoded: "test%20video.mp4"
to_local_path(url1)

print("\n--- Test 2: Encoded URL ---")
url2 = "https://testtemplate.online/media/test_company/test%20video.mp4"
to_local_path(url2)

print("\n--- Test 3: Relative Path ---")
path3 = "./media/test_company/test video.mp4"
to_local_path(path3)
