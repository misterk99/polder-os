#!/usr/bin/env python3
"""Exercise the real FX-to-pixman handoff in a Linux container without DRM.

The supplied directory must contain polder-compositor, polder-comp-fx and
polder-comp. Requires foot, wtype, grim and Pillow; never uses a host desktop.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    binary_dir = args.bin_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('headless_smoke', root / 'compositor/polder-comp/tests/headless-smoke.py')
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    session = smoke.Session(binary_dir / 'polder-compositor', output, 10)
    session.env['PATH'] = f'{binary_dir}:{session.env.get("PATH", os.defpath)}'
    session.env.pop('WLR_RENDERER', None)
    success = False
    error = None
    try:
        probe = subprocess.run([str(binary_dir / 'polder-comp-fx')], env=session.env,
                               cwd=session.root, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=10)
        (output / 'effects-probe.log').write_bytes(probe.stdout + probe.stderr)
        if probe.returncode != 78:
            raise AssertionError(f'expected unavailable renderer status78, got {probe.returncode}; run without DRM')
        if list(session.runtime.glob('wayland-*')):
            raise AssertionError('effects published a display socket before returning unsupported status')
        session.passed('unsupported FX renderer returns78 before publishing its display')
        session.start()
        log = (output / 'compositor.log').read_text()
        if 'Effects renderer unavailable' not in log or 'Creating pixman renderer' not in log:
            raise AssertionError('wrapper did not fall back to the pixman renderer')
        session.passed('production wrapper starts pixman after real FX initialization failure')
        _window_id, receiver = session.client('fallback')
        session.type_marker('fallback', receiver, session.root / 'other-input')
        from PIL import Image
        session.run(['grim', str(output / 'fallback.png')])
        with Image.open(output / 'fallback.png') as screenshot:
            if screenshot.size != (1366, 768) or len(screenshot.convert('RGB').getcolors(1000000) or []) < 10:
                raise AssertionError('fallback screenshot does not contain the mapped client')
        session.passed('fallback produces a visible native client screenshot')
        success = True
    except Exception:
        error = traceback.format_exc()
        print(error, flush=True)
    finally:
        session.close()
        (output / 'report.json').write_text(json.dumps({'success': success, 'checks': session.checks,
                                                       'error': error}, indent=2) + '\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
