"""Build a complete seam-trial trainer by replacing every affected object/blob."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

LIMIT = 600 * 1024**2
RESERVE = 35 * 1024**3
DEPENDENCIES = ('primitive_3dgs.slang', 'raster_common.slang', 'rasterize_fwd.slang', 'rasterize_bwd.slang')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())


def read_completions(journal, compiler, output, context_hash):
    """Return only durable compiler records whose current output still matches."""
    if not journal.exists(): return {}
    raw = journal.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Incomplete completion journal; refuse resume')
    completed = {}
    for line in raw.splitlines():
        try: record = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc: raise ValueError('Malformed completion journal; refuse resume') from exc
        if not isinstance(record, dict) or not isinstance(record.get('command'), list): raise ValueError('Invalid completion record')
        command = record['command']
        if not command or command[0] != str(compiler): continue
        # Old records without an explicit destination are not trusted.
        if 'destination' not in record or record.get('context_sha256') != context_hash: continue
        if not all(isinstance(x, str) for x in command) or command.count('-o') != 1 or command.index('-o') + 1 >= len(command): raise ValueError('Invalid compiler completion command')
        dest = Path(record['destination']) if isinstance(record['destination'], str) else None
        if dest is None or str(dest) != command[command.index('-o') + 1] or dest.parent != output / 'spirv': raise ValueError('Invalid compiler completion destination')
        expected = record.get('output_sha256')
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected): raise ValueError('Invalid completion hash')
        # The latest recorded result governs that destination; a missing or changed
        # output is recompiled rather than trusted.
        completed.pop(dest.name, None)
        if dest.is_file() and not dest.is_symlink():
            with dest.open('rb') as f: magic = f.read(4)
            if magic == b'\x03\x02\x23\x07' and digest(dest) == expected: completed[dest.name] = command
    return completed


def guarded(command, output, log, context_hash, cwd=None):
    log.write('$ ' + repr(command) + '\n'); log.flush()
    p = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True)
    while p.poll() is None:
        if size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE:
            os.killpg(p.pid, signal.SIGTERM); p.wait()
            raise RuntimeError('Build stopped by storage guard')
        time.sleep(1)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {command[0]}')
    if size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE:
        raise RuntimeError('Storage guard exceeded after command')
    result = Path(command[command.index('-o') + 1]) if '-o' in command else None
    if result and result.is_file():
        with result.open('rb') as f: os.fsync(f.fileno())
        result_dir = os.open(result.parent, os.O_RDONLY)
        try: os.fsync(result_dir)
        finally: os.close(result_dir)
    journal_path = output / 'completion.jsonl'
    with journal_path.open('a') as journal:
        journal.write(json.dumps({'command': command, 'context_sha256': context_hash, 'destination': str(result) if result else None, 'output_sha256': digest(result) if result and result.is_file() else None}) + '\n')
        journal.flush(); os.fsync(journal.fileno())
    directory = os.open(output, os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)


def write_context(output, context):
    """Persist the exact current context before appending completion records."""
    content = (json.dumps(context, sort_keys=True, separators=(',', ':')) + '\n').encode()
    temp = output / '.build-context.tmp'
    with temp.open('wb') as f:
        f.write(content); f.flush(); os.fsync(f.fileno())
    temp.replace(output / 'build-context.json')
    directory = os.open(output, os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)
    return hashlib.sha256(content).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='Clean seam-enabled layerctl projection')
    p.add_argument('base_build', type=Path, help='Completed compact baseline build')
    p.add_argument('fixture_build', type=Path, help='Successful seam fixture build')
    p.add_argument('output', type=Path, help='New scratch directory')
    p.add_argument('--resume', action='store_true', help='Resume a storage-guarded run from its successful compiler commands')
    p.add_argument('--slangc', type=Path, required=True)
    p.add_argument('--molten-root', type=Path, required=True)
    a = p.parse_args()
    source, base, fixture, slangc, molten = [x.resolve(strict=True) for x in (a.source, a.base_build, a.fixture_build, a.slangc, a.molten_root)]
    output = a.output.resolve()
    if not output.parent.is_dir() or (output.exists() and not a.resume) or (a.resume and not output.is_dir()): p.error('Output must be new, or an existing stopped build with --resume')
    if shutil.disk_usage(output.parent).free < RESERVE + LIMIT: p.error('Need 35 GiB reserve plus 600 MiB build budget')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip(): p.error('Source projection is dirty')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    fm = json.loads((fixture / 'manifest.json').read_text())
    if fm['source_commit'] != commit or len(fm['selected']) != 32 or fm['slangc_sha256'] != digest(slangc): p.error('Fixture source, compiler or variant set differs')
    selected = {r['name']: r for r in fm['selected']}
    old = [Path(line) for line in (base / 'spirv/blobs.txt').read_text().splitlines() if line]
    rules = (base / 'CMakeFiles/ss_spirv_blobs.dir/build.make').read_text().splitlines()
    affected = set()
    for line in rules:
        if line.startswith('spirv/') and ': ' in line and any(line.rstrip().endswith('/' + dep) for dep in DEPENDENCIES):
            affected.add(line.split(':', 1)[0].removeprefix('spirv/'))
    if len(old) != 1210 or len(affected) != 82 or not set(selected).issubset(affected): p.error('Unexpected shader dependency graph')
    tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    context = {'source_commit': commit, 'source_tree': tree, 'slangc_sha256': digest(slangc),
               'fixture_manifest_sha256': digest(fixture / 'manifest.json'),
               'baseline_executable_sha256': digest(base / 'spirula'),
               'baseline_blob_list_sha256': digest(base / 'spirv/blobs.txt'),
               'baseline_shader_recipe_sha256': digest(base / 'CMakeFiles/ss_spirv_blobs.dir/build.make'),
               'baseline_link_recipe_sha256': digest(base / 'CMakeFiles/spirula.dir/link.txt'),
               'baseline_blobs': [{'path': str(blob), 'sha256': digest(blob)} for blob in old]}
    if not a.resume:
        output.mkdir(); (output / 'spirv').mkdir()
    context_hash = write_context(output, context)
    completed = read_completions(output / 'completion.jsonl', slangc, output, context_hash) if a.resume else {}
    src = source / 'src'; replacements = {}; records = []
    metadata = {'build_context_sha256': context_hash, 'source_commit': commit, 'fixture_manifest_sha256': digest(fixture / 'manifest.json'), 'baseline_executable_sha256': digest(base / 'spirula'), 'slangc_sha256': digest(slangc), 'affected': records}
    with (output / 'build.log').open('a' if a.resume else 'x') as log:
        for old_blob in old:
            if old_blob.name not in affected: continue
            if old_blob.name in selected:
                dest = fixture / 'spirv' / old_blob.name
                if digest(dest) != selected[old_blob.name]['candidate_sha256']: raise ValueError(f'Fixture blob changed: {dest}')
            else:
                dest = output / 'spirv' / old_blob.name
                name = old_blob.name.removesuffix('.spv')
                entry = name.split('.atomicadd')[0].split('.int8')[0].split('.noint64')[0]
                family, function = entry.split('.')
                command = [str(slangc), str(src / 'backend/vulkan/shaders' / f'{family}.slang'), '-entry', function, '-o', str(dest), f'-I{src}', f'-I{src}/shaders', f'-I{src}/backend/vulkan/shaders', '-target', 'spirv', '-stage', 'compute', '-O2', '-ignore-capabilities', '-line-directive-mode', 'none']
                for suffix, define in (('.atomicadd', 'SS_NATIVE_F32_ATOMIC_ADD'), ('.int8', 'SS_NATIVE_INT8'), ('.noint64', 'SS_EMULATE_INT64')):
                    if suffix in old_blob.name: command.append('-D' + define)
                if completed.get(dest.name) != command:
                    guarded(command, output, log, context_hash)
            replacements[old_blob] = dest
            records.append({'name': old_blob.name, 'baseline_sha256': digest(old_blob), 'candidate_sha256': digest(dest), 'reused_fixture': old_blob.name in selected})
        if len(records) != 82: raise ValueError('Incomplete affected shader set')
        listed = [replacements.get(x, x) for x in old]
        (output / 'blobs.txt').write_text(''.join(str(x) + '\n' for x in listed))
        inventory = {'blobs': [{'path': str(x), 'bytes': x.stat().st_size, 'sha256': digest(x)} for x in listed]}
        (output / 'blob-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
        embed = output / 'embed.cpp'
        guarded([str(base / 'spirv_tool'), 'embed', '--incbin', str(embed), '--list', str(output / 'blobs.txt')], output, log, context_hash)
        includes = [f'-I{src}', f'-I{src}/external/apriltag', f'-I{base}', '-isystem', str(molten / 'MoltenVK/include')]
        flags = ['c++', '-std=gnu++17', '-O2', '-DSS_BACKEND_VULKAN', '-DSS_DEFAULT_LANG=en', *includes]
        objects = []
        for i, file in enumerate([embed, src / 'backend/vulkan/kernels/RasterizeFwd.cpp', src / 'backend/vulkan/kernels/RasterizeBwd.cpp', src / 'engine/EngineForward.cpp', src / 'engine/EngineLoss.cpp']):
            obj = output / f'object-{i}.o'; objects.append(obj)
            guarded([*flags, '-c', str(file), '-o', str(obj)], output, log, context_hash)
        audit = Path(__file__).resolve().parents[1] / 'spirula-zero-tiles/audit_macho_registry.py'
        guarded(['python3', str(audit), str(embed), str(objects[0]), str(output / 'blob-inventory.json')], output, log, context_hash)
        command = shlex.split((base / 'CMakeFiles/spirula.dir/link.txt').read_text())
        output_index = command.index('-o') + 1
        command[output_index] = str(output / 'spirula')
        first_archive = next(i for i, arg in enumerate(command) if arg.endswith('.a'))
        command[first_archive:first_archive] = list(map(str, objects))
        guarded(command, output, log, context_hash, cwd=base)
    metadata['candidate_executable_sha256'] = digest(output / 'spirula')
    if metadata['candidate_executable_sha256'] == metadata['baseline_executable_sha256']: raise ValueError('Identical trainer binaries')
    metadata['output_bytes'] = size(output)
    (output / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Built full-registry seam trial trainer: {output / "spirula"}')


if __name__ == '__main__': main()
