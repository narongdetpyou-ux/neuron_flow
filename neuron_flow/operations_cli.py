"""Explicit local operations commands, separate from the stable CSV commands."""

import base64
import os
from pathlib import Path
import time

from .document_input import read_source
from .supervision import load_json


def add_commands(commands):
    root = commands.add_parser('ops', help='Supervised local document operations')
    actions = root.add_subparsers(dest='operation', required=True)
    for name in ('submit', 'work', 'status', 'cancel', 'events', 'metrics', 'serve', 'stage', 'memory-learn', 'memory-retrieve'):
        command = actions.add_parser(name)
        command.add_argument('--workspace', default='batch_workspace')
        if name in {'submit', 'stage'}:
            command.add_argument('source', type=Path)
            command.add_argument('--timeout', type=float, default=120)
            command.add_argument('--ocr', action='store_true')
            command.add_argument('--language', default='eng')
            command.add_argument('--sheet')
            command.add_argument('--strategy', action='append', choices=('native', 'pdf-text', 'pdf-ocr'))
            if name == 'submit':
                command.add_argument('--key', required=True)
                command.add_argument('--stage-only', action='store_true')
            else:
                command.add_argument('--policy', type=Path)
        if name in {'status', 'cancel', 'events', 'memory-learn'}:
            command.add_argument('identifier')
        if name == 'events':
            command.add_argument('--after', type=int, default=0)
        if name == 'work':
            command.add_argument('--once', action='store_true')
        if name == 'serve':
            command.add_argument('--port', type=int, default=8765)
            command.add_argument('--read-token-env', default='NEURON_READ_TOKEN')
            command.add_argument('--write-token-env', default='NEURON_WRITE_TOKEN')
        if name.startswith('memory-'):
            command.add_argument('--profile', required=True, help='JSON array of six 0-1 process features')
            command.add_argument('--policy-version', required=True)
            if name == 'memory-learn':
                command.add_argument('candidate_csv', type=Path)
                command.add_argument('--method', required=True)
                command.add_argument('--cluster-id', required=True)
    for name in ('gate', 'policy-accept', 'shadow', 'integrity', 'backup', 'restore', 'drift'):
        command = actions.add_parser(name)
        command.add_argument('source', type=Path)
        if name in {'gate', 'policy-accept'}:
            command.add_argument('--max-p95-ratio', type=float)
            command.add_argument('--max-attempt-ratio', type=float)
            if name == 'policy-accept':
                command.add_argument('destination', type=Path)
                command.add_argument('--timeout', type=float, default=120)
                command.add_argument('--strategy', action='append', required=True, choices=('native', 'pdf-text', 'pdf-ocr'))
        if name == 'shadow':
            command.add_argument('--candidate-factory')
            command.add_argument('--timeout', type=float, default=120)
        if name in {'backup', 'restore', 'drift'}:
            command.add_argument('destination', type=Path)


def execute(args):
    action = args.operation
    if action in {'integrity', 'backup', 'restore'}:
        from .integrity import verify_manifest, stage_backup, restore_backup
        if action == 'integrity':
            return verify_manifest(args.source)
        return (stage_backup if action == 'backup' else restore_backup)(args.source, args.destination)
    if action == 'shadow':
        from .evaluation import run_shadow
        return run_shadow(args.source, candidate_factory=args.candidate_factory, timeout_s=args.timeout)
    if action in {'gate', 'policy-accept'}:
        from .evaluation import candidate_gate, accept_policy
        value = load_json(read_source(args.source))
        options = {'training_clusters': value.get('training_clusters', []),
                   'max_p95_ratio': args.max_p95_ratio, 'max_attempt_ratio': args.max_attempt_ratio}
        if action == 'gate':
            return candidate_gate(value['reference'], value['candidate'], **options)
        return accept_policy(args.destination, args.strategy, value['reference'], value['candidate'], timeout_s=args.timeout, **options)
    if action == 'drift':
        from .telemetry import drift_report
        return drift_report(load_json(read_source(args.source)), load_json(read_source(args.destination)))
    if action == 'stage':
        from .evaluation import load_policy
        from .extraction import ExtractionEngine
        from .intake import stage_document
        engine = load_policy(args.policy) if args.policy else ExtractionEngine(strategies=args.strategy or ['native'], timeout_s=args.timeout)
        return stage_document(args.workspace, read_source(args.source), args.source.name, sheet=args.sheet,
                              ocr=args.ocr, language=args.language, extraction_engine=engine)
    if action.startswith('memory-'):
        from .case_memory import CaseMemory
        memory = CaseMemory(args.workspace)
        try:
            profile = load_json(args.profile)
            if action == 'memory-retrieve':
                return {'cases': memory.retrieve(profile, args.policy_version)}
            return memory.learn(args.workspace, args.identifier, read_source(args.candidate_csv), profile=profile,
                                method=args.method, policy_version=args.policy_version, cluster_id=args.cluster_id)
        finally:
            memory.close()
    if action == 'serve':
        from .service import serve
        return serve(args.workspace, os.environ.get(args.read_token_env, ''), os.environ.get(args.write_token_env, ''), args.port)
    from .operations import JobQueue
    queue = JobQueue(args.workspace)
    try:
        if action == 'submit':
            return queue.submit({'idempotency_key': args.key, 'filename': args.source.name,
                'source_base64': base64.b64encode(read_source(args.source)).decode(), 'timeout_s': args.timeout,
                'ocr': args.ocr, 'language': args.language, 'sheet': args.sheet,
                'strategies': args.strategy or ['native'], 'run': not args.stage_only})
        if action == 'metrics':
            return queue.metrics()
        if action in {'status', 'cancel'}:
            return getattr(queue, action)(args.identifier)
        if action == 'events':
            return {'events': queue.events(args.identifier, args.after)}
        try:
            while True:
                result = queue.drain_one()
                if args.once:
                    return result or {'status': 'IDLE'}
                if result is None:
                    time.sleep(.1)
        except KeyboardInterrupt:
            return {'status': 'STOPPED'}
    finally:
        queue.close()
