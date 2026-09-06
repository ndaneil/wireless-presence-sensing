"""Build an App Lab source ZIP using only the standard library."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def package():
    target = ROOT / 'dist/lan-presence.zip'
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
        for name in ('app.yaml', 'README.md', 'python', 'sketch', 'bricks'):
            source = ROOT / name
            files = [source] if source.is_file() else sorted(source.rglob('*'))
            for path in files:
                if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc' or path.suffix == '.DS_Store':
                    continue
                archive.write(path, path.relative_to(ROOT))
    print(target)


if __name__ == '__main__':
    package()
