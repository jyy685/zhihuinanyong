"""Run the one-file EXE in an empty directory with Python removed from PATH."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
exe = root / 'dist' / 'ZhihuiNanyong.exe'
with tempfile.TemporaryDirectory(prefix='nju_exe_check_') as temp:
    folder = Path(temp)
    target = folder / exe.name
    shutil.copy2(exe, target)
    report = folder / 'report.json'
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env['PATH'] = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32')
    result = subprocess.run([str(target), '--smoke-test', str(report)], cwd=folder, env=env, timeout=90)
    if not report.exists():
        raise RuntimeError('Standalone executable did not write the diagnostic report.')
    data = json.loads(report.read_text(encoding='utf-8'))
    if result.returncode != 0 or not data.get('ok'):
        raise RuntimeError('Standalone verification failed: ' + json.dumps(data))
    (exe.parent / 'verification.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
digest = hashlib.sha256(exe.read_bytes()).hexdigest()
(exe.parent / 'SHA256SUMS.txt').write_text(f'{digest}  {exe.name}\n', encoding='ascii')
print(f'PASS: isolated Windows EXE, {exe.stat().st_size:,} bytes; SHA256 {digest}')
