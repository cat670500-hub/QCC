import os

src_path = r'C:\Users\user\.gemini\antigravity-ide\brain\7f176787-647d-4932-b612-4693633212d3\.system_generated\steps\824\content.md'
dest_dir = r'c:\Users\user\新增資料夾\QCC\static\js'
dest_path = os.path.join(dest_dir, 'socket.io.js')

if not os.path.exists(dest_dir):
    os.makedirs(dest_dir)

with open(src_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Skip the first 8 lines which are metadata
js_content = "".join(lines[8:])

with open(dest_path, 'w', encoding='utf-8') as f:
    f.write(js_content)

print(f"Successfully wrote {len(js_content)} characters to {dest_path}")
