"""Score timestamped inspection logs against independent video annotations."""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean


def ratio(a, b):
    return a/b if b else None


def cause_matches(event, row):
    snap = row['snapshot']
    confirmed = snap.get('confirmed')
    if snap['status'] != 'NG' or not confirmed or confirmed['status'] != 'NG':
        return False
    kind = event['error_type']
    phase = 'CHECK_MATERIALS' if kind == 'EXCESS_MATERIAL' else 'ASSEMBLING'
    if snap['phase'] != phase:
        return False
    for issue in confirmed['issues']:
        code = issue['code']
        if kind == 'EXCESS_MATERIAL':
            if code == 'MATERIAL_EXCESS' and issue['observed'].split(':')[0] == event['part']:
                return True
        elif kind == 'WRONG_HOLE':
            hole = issue['hole_id']
            if row.get('confirmed_hole_numbering') == 'mirrored':
                hole = 6-hole
            if code == 'UNEXPECTED_COMPONENT' and hole == event['actual_hole']:
                return True
        else:
            codes = {'PART_ORIENTATION_ERROR', 'PART_WRONG_SIDE'} if kind == 'PART_ORIENTATION_ERROR' else {kind}
            if code not in codes:
                continue
            checks = [('hole_id', 'hole_id'), ('actual_part', 'observed'), ('required_part', 'expected')]
            if all(event.get(a) is None or event[a] == issue[b] for a, b in checks):
                return True
    return False


def validate(annotation, rows, metadata):
    if annotation.get('schema_version') != 1 or metadata.get('schema_version') != 1:
        raise ValueError('Unsupported schema version')
    start, end = annotation['annotated_range_ms']
    ids = set()
    for s in annotation['segments']:
        if s['id'] in ids or s['start_ms'] != start or s['end_ms'] <= start:
            raise ValueError('Annotation segments must be contiguous with unique ids')
        ids.add(s['id'])
        start = s['end_ms']
        if s['expected_status'] not in (None, 'READY', 'IN_PROGRESS', 'PASS', 'NG', 'HOLD'):
            raise ValueError('Unknown annotation status')
    if start != end or not rows:
        raise ValueError('Invalid annotation range or empty log')
    if metadata['recipe_id'] != annotation['recipe_id']:
        raise ValueError('Recipe mismatch')
    if not math.isfinite(metadata['video_fps']) or metadata['video_fps'] <= 0:
        raise ValueError('Invalid FPS')
    previous_t, previous_i = -1, -1
    for row in rows:
        t, i = row['video_timestamp_ms'], row['frame_index']
        if not math.isfinite(t) or t <= previous_t or i <= previous_i:
            raise ValueError('Non-increasing timestamp/frame index')
        snap = row['snapshot']
        if snap['recipe_id'] != annotation['recipe_id'] or snap['status'] not in ('READY','IN_PROGRESS','PASS','NG','HOLD'):
            raise ValueError('Invalid snapshot')
        if not math.isfinite(row['processing_ms']) or row['processing_ms'] < 0:
            raise ValueError('Invalid processing time')
        previous_t, previous_i = t, i
    if metadata['frame_count'] != len(rows):
        raise ValueError('Metadata frame count mismatch')


def evaluate(annotation, rows, metadata, grace_ms=0):
    validate(annotation, rows, metadata)
    if not math.isfinite(grace_ms) or grace_ms < 0:
        raise ValueError('Grace must be finite and nonnegative')
    dt = 1000/metadata['video_fps']
    spans = []
    for i, row in enumerate(rows):
        start = row['video_timestamp_ms']
        end = start+dt
        if i+1 < len(rows):
            nxt = rows[i+1]
            end = nxt['video_timestamp_ms'] if nxt['frame_index'] == row['frame_index']+1 else min(end, nxt['video_timestamp_ms'])
        spans.append((row, start, end))

    def window(a, b):
        return [(r, max(0, min(end,b)-max(start,a))) for r,start,end in spans if start < b and end > a]

    summaries, confusion = [], {}
    correct = candidate_correct = scored = covered = 0.0
    normal_ms = false_ng_ms = false_pass_ms = early_ms = false_pass_all = 0.0
    episodes = 0
    for s in annotation['segments']:
        a, b = s['start_ms'], s['end_ms']
        all_samples = window(a,b)
        duration = sum(w for _,w in all_samples)
        covered += duration
        expected = s['expected_status']
        samples = window(min(a+grace_ms,b),b) if expected is not None else []
        counts = Counter()
        matches = candidates = 0.0
        for row, w in samples:
            snap = row['snapshot']
            counts[snap['status']] += w
            matches += w*(snap['status'] == expected)
            candidates += w*(snap['candidate']['status'] == expected)
            confusion.setdefault(expected, Counter())[snap['status']] += w
        total = sum(counts.values())
        scored += total
        correct += matches
        candidate_correct += candidates
        if expected == 'IN_PROGRESS' and s['expected_phase'] == 'ASSEMBLING':
            false_pass_ms += counts['PASS']
        if expected is not None and expected != 'PASS':
            false_pass_all += counts['PASS']
        if expected in ('IN_PROGRESS','PASS'):
            normal_ms += total
            false_ng_ms += counts['NG']
            prev_ng, prev_index = False, -2
            for row,_ in samples:
                ng, index = row['snapshot']['status'] == 'NG', row['frame_index']
                if ng and (not prev_ng or index != prev_index+1):
                    episodes += 1
                prev_ng, prev_index = ng,index
        phase = s.get('expected_phase')
        phase_ok = sum(w for r,w in all_samples if r['snapshot']['phase'] == phase) if phase else None
        forbidden = sum(w for r,w in all_samples if r['snapshot']['phase'] == 'ASSEMBLING') if s.get('forbid_assembly_start') else 0
        early_ms += forbidden
        transitions = [r for r,_ in all_samples if any(e['event_type'] == 'ASSEMBLY_STARTED' for e in r['snapshot']['events'])]
        summaries.append({'id':s['id'], 'description':s['description'], 'start_ms':a, 'end_ms':b,
                          'expected_status':expected, 'scoring':s['scoring'], 'coverage_ratio':ratio(duration,b-a),
                          'covered_ms':duration, 'scored_ms':total, 'status_accuracy':ratio(matches,total),
                          'candidate_accuracy':ratio(candidates,total),
                          'phase_accuracy':ratio(phase_ok,duration) if phase is not None else None,
                          'display_status_ms':dict(counts), 'forbidden_assembly_ms':forbidden,
                          'assembly_transition_in_window':bool(transitions) if s['scoring']=='phase_transition' else None})
    events = []
    for event in annotation['error_events']:
        a,b = event['must_detect_window_ms']
        samples = window(a,b)
        coverage = sum(w for _,w in samples)
        hits = [r for r,_ in samples if cause_matches(event,r)]
        ng = [r for r,_ in samples if r['snapshot']['status'] == 'NG']
        onset = event.get('observable_error_start_ms')
        latency = None
        if onset is not None:
            later = [r for r in rows if onset <= r['video_timestamp_ms'] < b and cause_matches(event,r)]
            if later:
                latency = later[0]['video_timestamp_ms']-onset
        events.append({'event_id':event['event_id'], 'error_type':event['error_type'],
                       'coverage_ratio':ratio(coverage,b-a), 'fully_covered':coverage>0 and coverage>=b-a-1e-3,
                       'ng_detected':bool(ng) if coverage else None, 'cause_matched':bool(hits) if coverage else None,
                       'first_cause_match_in_window_ms':hits[0]['video_timestamp_ms'] if hits else None,
                       'ng_time_ratio':ratio(sum(w for r,w in samples if r['snapshot']['status']=='NG'),coverage),
                       'cause_match_time_ratio':ratio(sum(w for r,w in samples if cause_matches(event,r)),coverage),
                       'latency_ms':latency,
                       'latency_note':'onset_not_annotated' if onset is None else 'detected' if latency is not None else 'not_detected'})
    full = [e for e in events if e['fully_covered']]
    total_duration = annotation['annotated_range_ms'][1]-annotation['annotated_range_ms'][0]
    processing = sorted(r['processing_ms'] for r in rows)
    return {
        'schema_version':1, 'video_id':annotation['video_id'], 'recipe_id':annotation['recipe_id'],
        'provisional':not metadata.get('completed') or covered < total_duration-1e-3,
        'run_completed':metadata.get('completed',False), 'grace_ms':grace_ms,
        'coverage_ratio':ratio(covered,total_duration), 'annotated_ms':total_duration, 'covered_ms':covered,
        'status_scored_ms':scored, 'unscored_covered_ms':covered-scored,
        'display_status_accuracy':ratio(correct,scored), 'candidate_status_accuracy':ratio(candidate_correct,scored),
        'confusion_duration_ms':confusion, 'normal_scored_ms':normal_ms, 'false_ng_ms':false_ng_ms,
        'false_ng_time_ratio':ratio(false_ng_ms,normal_ms), 'false_ng_episodes_within_normal_segments':episodes,
        'false_ng_episodes_per_normal_minute':ratio(episodes,normal_ms/60000),
        'false_pass_in_labeled_incomplete_assembly_ms':false_pass_ms,
        'false_pass_in_all_labeled_nonpass_ms':false_pass_all, 'forbidden_assembly_ms':early_ms,
        'event_summary':{'annotated_events':len(events), 'fully_covered_events':len(full),
                         'ng_detected_count':sum(e['ng_detected'] for e in full),
                         'cause_matched_count':sum(e['cause_matched'] for e in full),
                         'ng_detection_rate':ratio(sum(e['ng_detected'] for e in full),len(full)),
                         'cause_match_rate':ratio(sum(e['cause_matched'] for e in full),len(full))},
        'processing':{'mean_ms':mean(processing), 'p50_ms':processing[round((len(processing)-1)*.5)],
                      'p95_ms':processing[round((len(processing)-1)*.95)],
                      'offline_processing_fps':1000/mean(processing) if mean(processing) else None},
        'segments':summaries, 'events':events,
        'limitations':[
            'Time ratios use consecutive-frame PTS intervals; missing indices are not bridged. Last-frame duration uses nominal FPS.',
            'Null-label transitions are excluded from status accuracy, not silently labeled IN_PROGRESS.',
            'NG event success means a matching confirmed sample exists in the window; see duration ratio for persistence.',
            'Missing event onset means no latency estimate; no latency deadline is assumed.',
            'Offline processing FPS is not camera-to-UI latency and excludes output I/O.',
            'Wrong-hole matching checks observed unexpected hole, not proof of intended destination.',
            'Partial runs are provisional; event rates only use fully covered windows; always report coverage.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotation', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--grace-ms', type=float, default=None)
    parser.add_argument('--allow-video-mismatch', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; use a new report directory')
    annotation = json.loads(args.annotation.read_text(encoding='utf-8'))
    metadata = json.loads((args.run/'metadata.json').read_text(encoding='utf-8'))
    with (args.run/'predictions.jsonl').open(encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    from src.app.evaluation_log import file_identity
    video = (args.annotation.parent/annotation['video_path']).resolve()
    if not video.is_file():
        parser.error(f'Annotated video missing: {video}')
    mismatch = file_identity(video)['sha256'] != metadata['video']['sha256']
    if mismatch and not args.allow_video_mismatch:
        parser.error('Video SHA256 mismatch')
    grace = args.grace_ms if args.grace_ms is not None else annotation.get('policy',{}).get('display_status_grace_ms')
    report = evaluate(annotation,rows,metadata,0 if grace is None else grace)
    report.update(grace_policy='raw_no_grace_not_acceptance_threshold' if grace is None else 'explicit',
                  video_mismatch_override=mismatch,
                  annotation_sha256=hashlib.sha256(args.annotation.read_bytes()).hexdigest(),
                  run_directory=str(args.run.resolve()))
    report['provisional'] |= mismatch
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    fields = ['id','description','start_ms','end_ms','expected_status','coverage_ratio','scored_ms','status_accuracy','candidate_accuracy','phase_accuracy','forbidden_assembly_ms']
    for name, records, keys in [('segments.csv',report['segments'],fields),
                                ('events.csv',report['events'],list(report['events'][0]) if report['events'] else ['event_id'])]:
        with (args.output/name).open('w',newline='',encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream,keys,extrasaction='ignore')
            writer.writeheader()
            writer.writerows(records)
    def pct(value):
        return 'N/A' if value is None else f'{100*value:.2f}%'
    summary = (f"# {annotation['video_id']} evaluation\n\n"
               f"- Provisional: {report['provisional']}\n"
               f"- Coverage: {pct(report['coverage_ratio'])}\n"
               f"- Display status accuracy: {pct(report['display_status_accuracy'])}\n"
               f"- Candidate status accuracy: {pct(report['candidate_status_accuracy'])}\n"
               f"- Cause-matched events: {report['event_summary']['cause_matched_count']}/{report['event_summary']['fully_covered_events']} fully covered ({len(report['events'])} annotated)\n"
               f"- False NG time ratio: {pct(report['false_ng_time_ratio'])}\n"
               f"- Boundary grace: {report['grace_ms']} ms ({report['grace_policy']})\n\n"
               '## Limitations\n\n'+'\n'.join('- '+x for x in report['limitations'])+'\n')
    (args.output/'report.md').write_text(summary,encoding='utf-8')
    print(summary)
    print(f'Results: {args.output.resolve()}')


if __name__ == '__main__':
    main()
