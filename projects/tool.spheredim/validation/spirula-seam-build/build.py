"""Build a bounded, fixture-only Vulkan seam test against a pinned projection.

The resulting executable deliberately omits unrelated shader families and is
not a general trainer. Missing runtime entries fail through the Vulkan backend.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

LIMIT = 400 * 1024**2
RESERVE = 35 * 1024**3
ENTRIES = {
    'projection_fwd.projection_fwd_3dgs', 'projection_fwd.projection_fwd_3dgut',
    'projection_fwd.projection_packed_mask', 'projection_fwd.projection_packed_fwd',
    'rasterize_fwd.rasterize_fwd_2d', 'rasterize_fwd.rasterize_fwd_3dgut',
    'rasterize_bwd.rasterize_bwd_2d', 'rasterize_bwd.rasterize_bwd_3dgut',
    'rasterize_bwd_nodepth.rasterize_bwd_3dgut_nodepth',
}
OMIT = ('fpbo.', 'meshing.', 'pca_reg.')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())


def run_guarded(command, output, log):
    log.write('$ ' + repr(command) + '\n'); log.flush()
    p = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    while p.poll() is None:
        if size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait()
            raise RuntimeError('Build stopped by storage guard')
        time.sleep(1)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {command[0]}')
    if size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE:
        raise RuntimeError('Storage guard exceeded after command')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Clean layerctl projection with layer 0006 enabled')
    parser.add_argument('base_build', type=Path, help='Completed compact baseline build')
    parser.add_argument('fixture', type=Path)
    parser.add_argument('output', type=Path, help='New directory on the same volume')
    parser.add_argument('--slangc', type=Path, required=True)
    parser.add_argument('--molten-root', type=Path, required=True)
    args = parser.parse_args()
    source, base, fixture, slangc, molten = [p.resolve(strict=True) for p in (args.source, args.base_build, args.fixture, args.slangc, args.molten_root)]
    output = args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        parser.error('Output must be a new path in an existing directory')
    if shutil.disk_usage(output.parent).free < RESERVE + LIMIT:
        parser.error('Need 35 GiB reserve plus the 400 MiB build budget')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        parser.error('Source projection has uncommitted modifications')
    src = source / 'src'
    original = [Path(line) for line in (base / 'spirv/blobs.txt').read_text().splitlines() if line]
    wanted = []
    for p in original:
        name = p.name.removesuffix('.spv')
        entry = name.split('.atomicadd')[0].split('.int8')[0].split('.noint64')[0]
        if entry in ENTRIES:
            wanted.append((p, entry))
    if len(wanted) != 32 or {entry for _, entry in wanted} != ENTRIES:
        parser.error('Unexpected targeted shader variant set')
    output.mkdir(); (output / 'spirv').mkdir()
    metadata = {'source_commit': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(), 'fixture_sha256': digest(fixture), 'slangc_sha256': digest(slangc), 'baseline_blobs': {str(p): digest(p) for p in original}, 'selected': [], 'omitted_families': list(OMIT)}
    with (output / 'build.log').open('x') as log:
        replacements = {}
        for old, entry in wanted:
            dest = output / 'spirv' / old.name
            family, function = entry.split('.')
            command = [str(slangc), str(src / 'backend/vulkan/shaders' / f'{family}.slang'), '-entry', function, '-o', str(dest), f'-I{src}', f'-I{src}/shaders', f'-I{src}/backend/vulkan/shaders', '-target', 'spirv', '-stage', 'compute', '-O2', '-ignore-capabilities', '-line-directive-mode', 'none']
            for suffix, define in (('.atomicadd', 'SS_NATIVE_F32_ATOMIC_ADD'), ('.int8', 'SS_NATIVE_INT8'), ('.noint64', 'SS_EMULATE_INT64')):
                if suffix in old.name:
                    command.append('-D' + define)
            run_guarded(command, output, log)
            replacements[old] = dest
            metadata['selected'].append({'name': old.name, 'baseline_sha256': metadata['baseline_blobs'][str(old)], 'candidate_sha256': digest(dest)})
        listed = [replacements.get(p, p) for p in original if not p.name.startswith(OMIT)]
        (output / 'blobs.txt').write_text(''.join(str(p) + '\n' for p in listed))
        embed = output / 'embed.cpp'
        run_guarded([str(base / 'spirv_tool'), 'embed', '--incbin', str(embed), '--list', str(output / 'blobs.txt')], output, log)
        includes = [f'-I{src}', f'-I{src}/external/apriltag', f'-I{base}', '-isystem', str(molten / 'MoltenVK/include')]
        flags = ['c++', '-std=gnu++17', '-O2', '-DSS_BACKEND_VULKAN', '-DSS_DEFAULT_LANG=en', *includes]
        objects = []
        for index, file in enumerate([embed, src / 'backend/vulkan/kernels/RasterizeFwd.cpp', src / 'backend/vulkan/kernels/RasterizeBwd.cpp', src / 'engine/EngineForward.cpp', src / 'engine/EngineLoss.cpp', fixture]):
            obj = output / f'object-{index}.o'; objects.append(obj)
            run_guarded([*flags, '-c', str(file), '-o', str(obj)], output, log)
        molten_lib = molten / 'MoltenVK/static/MoltenVK.xcframework/macos-arm64_x86_64/libMoltenVK.a'
        archives = [base / 'libcsrc_portable.a', base / 'libss_backend_vulkan.a', base / 'libcsrc_portable.a', base / 'libss_i18n.a', molten_lib]
        frameworks = sum((['-framework', name] for name in ('Metal', 'Foundation', 'QuartzCore', 'IOSurface', 'IOKit', 'CoreGraphics', 'AppKit', 'CoreFoundation')), [])
        executable = output / 'seam-fixture'
        run_guarded(['c++', *map(str, objects), *map(str, archives), *frameworks, '-o', str(executable)], output, log)
    metadata['executable_sha256'] = digest(executable)
    metadata['output_bytes'] = size(output)
    (output / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Built fixture-only executable: {executable}')


if __name__ == '__main__':
    main()
