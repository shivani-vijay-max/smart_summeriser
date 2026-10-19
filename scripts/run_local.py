"""Start the local model server (if needed), index worker, and Django together."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
environment = os.environ.copy()
environment.setdefault('OLLAMA_MODELS', str(ROOT / '.ollama/models'))
base_url = environment.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
processes = []


def models():
    with urlopen(base_url + '/api/tags', timeout=2) as response:
        return {m['name'] for m in json.load(response)['models']}


try:
    subprocess.run([sys.executable, 'manage.py', 'migrate'], check=True, env=environment)
    try:
        available = models()
    except OSError:
        binary = ROOT / '.ollama/runtime/ollama'
        executable = str(binary) if binary.exists() else shutil.which('ollama')
        if not executable:
            raise RuntimeError('Install Ollama and download the models. See README.md.')
        processes.append(subprocess.Popen([executable, 'serve'], env=environment))
        for attempt in range(60):
            try:
                available = models()
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Ollama did not start; inspect the output above.')
    for name in [environment.get('EMBED_MODEL', 'embeddinggemma'), environment.get('CHAT_MODEL', 'llama3.2:3b')]:
        if name not in available and name + ':latest' not in available:
            raise RuntimeError(f'Missing model {name}. Pull it using Ollama, as explained in README.md.')
    processes.append(subprocess.Popen([sys.executable, 'manage.py', 'process_documents'], env=environment))
    processes.append(subprocess.Popen([sys.executable, 'manage.py', 'runserver', '--noreload'], env=environment))
    print('\nOpen http://127.0.0.1:8000/knowledge/ — Ctrl+C stops processes started here.\n', flush=True)
    while all(p.poll() is None for p in processes):
        time.sleep(1)
except KeyboardInterrupt:
    print('\nStopping local services…')
except (RuntimeError, subprocess.CalledProcessError) as exc:
    print(str(exc), file=sys.stderr)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
