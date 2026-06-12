with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for idx, line in enumerate(lines, 1):
        if 'CheckInLog' in line:
            print(f"main.py:{idx}: {line.strip()}")
