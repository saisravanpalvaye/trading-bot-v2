import re

with open('paper_trades.csv', 'r') as f:
    content = f.read()

# Remove conflict markers and duplicate rows
# Keep HEAD version (between <<<< and ====)
def resolve_conflict(text):
    result = []
    in_ours = False
    in_theirs = False
    for line in text.splitlines():
        if line.startswith('<<<<<<<'):
            in_ours = True
        elif line.startswith('======='):
            in_ours = False
            in_theirs = True
        elif line.startswith('>>>>>>>'):
            in_theirs = False
        elif in_theirs:
            pass  # discard their version
        else:
            result.append(line)
    return '\n'.join(result) + '\n'

clean = resolve_conflict(content)

with open('paper_trades.csv', 'w') as f:
    f.write(clean)

print("Done — conflict resolved, file written.")
print("Rows:", len([l for l in clean.splitlines() if l.strip() and not l.startswith('id,')]))
