import subprocess, json, urllib.request, os

token = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True).stdout.strip()

# Get release ID
req = urllib.request.Request(
    'https://api.github.com/repos/deYangar/FH6_Auto/releases/tags/v1.2.6.0',
    headers={'Authorization': f'Bearer {token}'}
)
resp = urllib.request.urlopen(req)
release = json.loads(resp.read())
print(f"Release ID: {release['id']}")
upload_url = release['upload_url']

for filepath, label in [
    ('dist/FH6Auto.exe', 'Steam v1.2.6.0'),
    ('dist/FH6Auto_xbox.exe', 'Xbox v1.2.6.0'),
]:
    basename = os.path.basename(filepath)
    size = os.path.getsize(filepath)
    print(f"Uploading {basename} ({size/1024/1024:.1f}MB)...")
    
    with open(filepath, 'rb') as f:
        data = f.read()
    
    url = upload_url.replace('{?name,label}', f'?name={basename}')
    req = urllib.request.Request(url, data=data, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/octet-stream',
        'Content-Length': str(len(data))
    })
    req.method = 'POST'
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        result = json.loads(resp.read())
        print(f"  OK: {result['browser_download_url']}")
    except Exception as e:
        print(f"  FAILED: {e}")

print('Done')
