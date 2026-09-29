"""Non-mutating, append-only evidence for offline video evaluation."""
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


def file_identity(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': str(path), 'size_bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def git_identity(root):
    def query(*args):
        try:
            return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                           encoding='utf-8', stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {'branch': query('branch', '--show-current'), 'commit': query('rev-parse', 'HEAD'),
            'working_tree_status': query('status', '--short')}


class EvaluationLog:
    def __init__(self, directory, metadata):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = dict(metadata, schema_version=1, completed=False, frame_count=0,
                             started_utc=datetime.now(timezone.utc).isoformat(),
                             python_version=platform.python_version())
        self.confirmed_hole_numbering = None
        self.stream = (self.directory/'predictions.jsonl').open('x', encoding='utf-8')
        self._save()

    def _save(self):
        (self.directory/'metadata.json').write_text(
            json.dumps(self.metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

    def __enter__(self):
        return self

    def write(self, frame_index, timestamp_ms, snapshot, detection_frame, info, processing_ms):
        if snapshot.stable and snapshot.confirmed is not None:
            self.confirmed_hole_numbering = snapshot.geometry.get('hole_numbering')
        if snapshot.confirmed is None:
            self.confirmed_hole_numbering = None
        record = {'schema_version': 1, 'frame_index': frame_index, 'video_timestamp_ms': timestamp_ms,
                  'processing_ms': processing_ms, 'snapshot': asdict(snapshot),
                  'confirmed_hole_numbering': self.confirmed_hole_numbering,
                  'detections': asdict(detection_frame), 'adapter_info': info}
        self.stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
        self.stream.flush()
        self.metadata['frame_count'] += 1
        self.metadata['last_timestamp_ms'] = timestamp_ms

    def __exit__(self, exc_type, exc, traceback):
        self.stream.close()
        self.metadata['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if exc is not None:
            self.metadata.update(completed=False, stop_reason='exception', error=str(exc))
        self._save()
