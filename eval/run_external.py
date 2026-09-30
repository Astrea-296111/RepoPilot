"""Isolated, paired evaluation on pinned historical open-source module bugs."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import logging
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time

from repopilot.agent.agent import RepoPilot
from repopilot.config import Settings
from repopilot.context.excerpts import source_excerpt
from repopilot.context.repo_map import build_repo_map, render_repo_map
from repopilot.context.retrieval import retrieve_with_imports
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from repopilot.sandbox.docker import DockerExecutor
from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ApplyPatch
from model_retry import RetryingLLM
from run_one_shot import Answer, SYSTEM, prepare_repo, git_changed_files

ROOT=Path(__file__).resolve().parents[1]
TASKS=ROOT/'eval/external/tasks.json'
PROTECTED=('tests','.git','.repopilot')


def execute(repo, command, settings, local=False):
    if local:  # Trusted reference validation only, never model-generated code.
        p=subprocess.run(command,shell=True,cwd=repo,capture_output=True,text=True,timeout=60)
        return {'exit_code':p.returncode,'output':(p.stdout+p.stderr)[-12000:]}
    result=DockerExecutor(repo,settings.docker_image,PROTECTED).run(command,60)
    return {'exit_code':result.exit_code,'output':result.output}


def suite_hash():
    digest=hashlib.sha256()
    for p in sorted((ROOT/'eval/external').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            digest.update(p.relative_to(ROOT).as_posix().encode())
            digest.update(p.read_bytes())
    return digest.hexdigest()


def validate(task, settings, local=False):
    with tempfile.TemporaryDirectory(prefix='reference-') as temp:
        repo=prepare_repo(task,temp)
        before=execute(repo,task['test_command'],settings,local)
        if before['exit_code'] != 1 or 'FAILED' not in before['output']:
            raise RuntimeError(f"Invalid failing baseline {task['id']}: {before}")
        for source in (ROOT/'eval/external/reference'/task['id']).rglob('*.py'):
            target=repo/source.relative_to(ROOT/'eval/external/reference'/task['id'])
            shutil.copyfile(source,target)
        shutil.copyfile(ROOT/task['hidden_test'],repo/'tests/test_hidden.py')
        after=execute(repo,task['test_command'],settings,local)
        if after['exit_code'] != 0 or 'passed' not in after['output']:
            raise RuntimeError(f"Invalid reference {task['id']}: {after}")
        return {'task_id':task['id'],'baseline':before,'reference':after}


def trial(task, run, mode, settings):
    record={'task_id':task['id'],'upstream':task['upstream'],'run':run,'mode':mode,'resolved':False}
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='external-') as temp:
            repo=prepare_repo(task,temp)
            baseline=execute(repo,task['test_command'],settings)
            record['baseline_test']=baseline
            if baseline['exit_code'] != 1 or 'FAILED' not in baseline['output']:
                raise RuntimeError('Invalid public failing baseline')
            llm=RetryingLLM(OpenAICompatibleLLM(settings))
            public_task=task['task']+'\nTests are protected. Run '+task['test_command']+'\nInitial public failure:\n'+baseline['output']
            model_started=time.monotonic()
            if mode=='agent':
                pilot=RepoPilot(repo,llm,settings,executor='docker',approval='auto',protected_paths=PROTECTED)
                state=pilot.run(public_task)
                record.update(status=state.status,error=state.error,steps=state.current_step,
                              tool_calls=len(state.tool_history),token_usage=state.token_usage,
                              retrieved_files=state.retrieved_files,
                              trace=state.model_dump(mode='json'))
            else:
                entries=build_repo_map(repo)
                paths=retrieve_with_imports(repo,entries,public_task)[:3]
                code='\n\n'.join('FILE '+p+'\n'+source_excerpt((repo/p).read_text(),public_task) for p,_ in paths)
                context=public_task+'\nRepo map:\n'+render_repo_map(entries)+'\nSelected public source:\n'+code
                record['retrieved_files']=[p for p,_ in paths]
                response=llm.chat(SYSTEM,context)
                record['model_response']=response.content
                record['token_usage']={'prompt_tokens':response.prompt_tokens,'completion_tokens':response.completion_tokens,'total_tokens':response.prompt_tokens+response.completion_tokens}
                answer=Answer.model_validate_json(response.content)
                patcher=ApplyPatch(Workspace(repo,PROTECTED))
                for patch in answer.patches:
                    patcher.execute(patch.model_dump())
                record['patches']=len(answer.patches)
            record['repair_seconds']=round(time.monotonic()-model_started,3)
            record['llm_transport_retries']=llm.retries
            changed=git_changed_files(repo)
            record['changed_files']=changed
            allowed=task['allowed_source_dir']+'/'
            invalid=[p for p in changed if not p.startswith(allowed) or not p.endswith('.py')]
            record['invalid_changes']=invalid
            diff=subprocess.run(['git','-C',str(repo),'diff'],capture_output=True,text=True,check=True).stdout
            record['diff']=diff
            # Fresh grading checkout: copy only allowed source files, never agent test/config files.
            with tempfile.TemporaryDirectory(prefix='grader-') as grade_temp:
                grade=prepare_repo(task,grade_temp)
                for path in changed:
                    if path not in invalid:
                        source=repo/path
                        target=grade/path
                        if source.is_file():
                            target.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copyfile(source,target)
                        elif target.exists(): target.unlink()
                shutil.copyfile(ROOT/task['hidden_test'],grade/'tests/test_hidden.py')
                grader=execute(grade,task['test_command'],settings)
                record['grader']=grader
            record['resolved']=not invalid and record['grader']['exit_code']==0 and 'passed' in record['grader']['output']
            if not record['resolved']:
                record['failure_category']='invalid_changes' if invalid else ('agent_'+str(record.get('error')) if mode=='agent' and record.get('error') else 'behavior_failure')
    except Exception as exc:
        record['error']=f'{type(exc).__name__}: {exc}'
        record['failure_category']='transport_failure' if isinstance(exc,RuntimeError) and '模型' in str(exc) else 'runner_or_protocol_failure'
    finally:
        record['end_to_end_seconds']=round(time.monotonic()-started,3)
    return record


def aggregate(records):
    per_task=defaultdict(list)
    for r in records: per_task[r['task_id']].append(r)
    return {'trials':len(records),'resolved':sum(r['resolved'] for r in records),
            'task_successes':{k:sum(r['resolved'] for r in v) for k,v in sorted(per_task.items())},
            'median_end_to_end_seconds':statistics.median(r['end_to_end_seconds'] for r in records) if records else None,
            'median_tokens':statistics.median(r['token_usage']['total_tokens'] for r in records if 'token_usage' in r) if any('token_usage' in r for r in records) else None,
            'total_tokens':sum(r.get('token_usage',{}).get('total_tokens',0) for r in records),
            'failure_categories':dict(Counter(r['failure_category'] for r in records if not r['resolved']))}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['agent','oneshot','reference'],required=True)
    parser.add_argument('--runs',type=int,default=3)
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--shards',type=int,default=5)
    parser.add_argument('--local-reference',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.local_reference and args.mode!='reference': parser.error('Local execution is only allowed for trusted reference validation')
    if not 0<=args.shard<args.shards or args.runs<1: parser.error('Invalid shard or runs')
    settings=Settings.load()
    tasks=json.loads(TASKS.read_text())
    out=args.output or ROOT/f'eval/results/external-{args.mode}-{args.shard}.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    if args.mode=='reference':
        results=[validate(t,settings,args.local_reference) for t in tasks]
        out.write_text(json.dumps({'suite_sha256':suite_hash(),'tasks':results},ensure_ascii=False,indent=2))
        print(f'Validated all {len(results)} failing baselines and reference fixes',flush=True)
        return
    document={'schema_version':1,'suite_sha256':suite_hash(),'model':settings.llm_model,
              'reasoning_effort':settings.llm_reasoning_effort,'stream':settings.llm_stream,
              'max_steps':settings.max_steps,'max_context_chars':settings.max_context_chars,
              'mode':args.mode,'runs':args.runs,'shard':args.shard,'shards':args.shards,
              'timing_scope':'Preparation + baseline Docker test + model/repair + fresh Docker grading', 'records':[]}
    for t in tasks[args.shard::args.shards]:
        for run in range(1,args.runs+1):
            print(f"START {args.mode} {t['id']} repeat {run}/{args.runs}",flush=True)
            record=trial(t,run,args.mode,settings)
            document['records'].append(record)
            document['summary']=aggregate(document['records'])
            out.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(f"END resolved={record['resolved']} seconds={record['end_to_end_seconds']} tokens={record.get('token_usage',{}).get('total_tokens')} error={record.get('error')}",flush=True)
    print(json.dumps(document['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(name)s %(message)s')
    main()
