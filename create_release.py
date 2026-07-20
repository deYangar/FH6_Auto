import subprocess, json, urllib.request, os

token = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True).stdout.strip()

with open('release_notes_v1.2.6.0.md', 'r', encoding='utf-8') as f:
    body = f.read()

data = json.dumps({
    'tag_name': 'v1.2.6.0',
    'name': 'v1.2.6.0',
    'body': body,
    'prerelease': False
}).encode('utf-8')

req = urllib.request.Request(
    'https://api.github.com/repos/deYangar/FH6_Auto/releases',
    data=data,
    headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
)
resp = urllib.request.urlopen(req)
release = json.loads(resp.read())
print(f"Release: {release['html_url']}")

def upload_asset(release, filepath, label):
    with open(filepath, 'rb') as f:
        data = f.read()
    basename = os.path.basename(filepath)
    url = release['upload_url'].replace('{?name,label}', f'?name={basename}')
    req = urllib.request.Request(url, data=data, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/octet-stream'
    })
    req.method = 'POST'
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    print(f"Uploaded: {result['name']} ({len(data)} bytes)")

upload_asset(release, 'dist/FH6Auto.exe', 'Steam (v1.2.6.0)')
upload_asset(release, 'dist/FH6Auto_xbox.exe', 'Xbox (v1.2.6.0)')
print('All done!')
