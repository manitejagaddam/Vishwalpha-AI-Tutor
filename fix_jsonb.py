import glob
search_str = 'server_default="\'[]\'::jsonb"'
replace_str = 'server_default=sa.text("\'[]\'::jsonb")'
for path in glob.glob('app/data/migrations/versions/*.py'):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if search_str in content:
        content = content.replace(search_str, replace_str)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated {path}')
