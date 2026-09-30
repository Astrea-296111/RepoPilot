"""Strict paired merge and uncertainty over tasks (not iid repeated trials)."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import statistics
from run_external import aggregate


def summarize(inputs):
    documents=[json.loads(p.read_text(encoding="utf-8")) for p in inputs]
    docs=[d for d in documents if 'records' in d]
    if len(docs)!=10: raise ValueError('Need exactly 5 shards for each of 2 methods')
    fields=('suite_sha256','model','reasoning_effort','stream','max_steps','max_context_chars','runs','shards','timing_scope')
    reference={f:docs[0][f] for f in fields}
    if reference['runs']!=3 or reference['shards']!=5: raise ValueError('Expected fixed 10-task, 3-repeat design')
    paired=defaultdict(dict)
    for doc in docs:
        if any(doc[f]!=reference[f] for f in fields): raise ValueError('Configuration mismatch')
        for r in doc['records']:
            key=(r['task_id'],r['run'])
            if r['mode'] in paired[key]: raise ValueError('Duplicate trial')
            paired[key][r['mode']]=r
    task_ids=sorted({t for t,_ in paired})
    if len(task_ids)!=10 or len(paired)!=30: raise ValueError('Missing tasks/repeats')
    agent_runtimes={d.get('runtime','custom') for d in docs if d.get('mode')=='agent'}
    if len(agent_runtimes)!=1: raise ValueError('Mixed Agent runtimes')
    reference['agent_runtime']=agent_runtimes.pop()
    reference['runtime_policy_revision']=docs[0].get('runtime_policy_revision','legacy')
    if any(set(v)!= {'agent','oneshot'} for v in paired.values()): raise ValueError('Unpaired trial')
    if any({n for (t,n) in paired if t==task}!={1,2,3} for task in task_ids): raise ValueError('Missing repeat index')
    methods={m:aggregate([v[m] for v in paired.values()]) for m in ('agent','oneshot')}
    for mode,summary in methods.items():
        runs=[v[mode] for v in paired.values()]
        summary['completed_and_resolved']=sum(r['resolved'] and (mode=='oneshot' or r.get('status')=='completed') for r in runs)
        summary['terminal_errors']={}
        for r in runs:
            error=r.get('error')
            if error:
                summary['terminal_errors'][error]=summary['terminal_errors'].get(error,0)+1
        summary['max_end_to_end_seconds']=max(r['end_to_end_seconds'] for r in runs)
        summary['median_steps']=statistics.median(r['steps'] for r in runs if 'steps' in r) if any('steps' in r for r in runs) else None
        summary['median_tool_records']=statistics.median(r['tool_calls'] for r in runs if 'tool_calls' in r) if any('tool_calls' in r for r in runs) else None
        summary['median_executed_tool_calls']=statistics.median(r.get('executed_tool_calls',r['tool_calls']) for r in runs if 'tool_calls' in r) if any('tool_calls' in r for r in runs) else None
        summary['loop_detection']=sum(r.get('error')=='loop_detection' for r in runs)
        summary['max_steps']=sum(r.get('error')=='max_steps' for r in runs)
        summary['protocol_failures']=sum('JSON' in r.get('error','') or 'ValidationError' in r.get('error','') for r in runs)
    by_task=[]
    for task in task_ids:
        a=[paired[(task,n)]['agent'] for n in (1,2,3)]
        b=[paired[(task,n)]['oneshot'] for n in (1,2,3)]
        by_task.append({'task_id':task,'upstream':a[0]['upstream'],'agent_successes':sum(r['resolved'] for r in a),
                        'oneshot_successes':sum(r['resolved'] for r in b), 'agent_completed_and_resolved':sum(r['resolved'] and r.get('status')=='completed' for r in a)})
    gaps=[(t['agent_successes']-t['oneshot_successes'])/3 for t in by_task]
    rng=random.Random(20260930)
    bootstrap=sorted(statistics.mean(rng.choices(gaps,k=10)) for _ in range(10000))
    pair_counts={'both':0,'agent_only':0,'oneshot_only':0,'neither':0}
    for v in paired.values():
        a,b=v['agent']['resolved'],v['oneshot']['resolved']
        pair_counts['both' if a and b else 'agent_only' if a else 'oneshot_only' if b else 'neither']+=1
    return {'config':reference,'methods':methods,'by_task':by_task,'paired_outcomes':pair_counts,
            'success_gap_percentage_points':100*statistics.mean(gaps),
            'task_cluster_bootstrap_95_percent_gap':[100*bootstrap[249],100*bootstrap[9749]],
            'notes':['10 historical module-scoped bugs in 3 upstream projects, each repeated 3 times; not SWE-bench.',
                     'Repeated trials on one task are correlated; bootstrap resamples tasks, only 10 clusters.',
                     'Additional completed_and_resolved metric audits saved Agent terminal status; patch grading remains the preregistered resolved outcome.',
                     'Public historical fixes may have been in model training data; no guarantee of contamination-free holdout.',
                     ('Runtime repeat/termination feedback was revised using historical failure trajectories; current outcomes did not retune task definitions or graders.' if reference['runtime_policy_revision']!='legacy' else 'No harness/prompt tuning based on these real-model outcomes.'),
                     'Public reproducers + custom frozen hidden edge cases; not the entire upstream test suite.']}


def main():
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,default=Path('eval/results/external-comparison.json'))
    a=p.parse_args();report=summarize(sorted(a.input.rglob('external-*.json')))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    text=['# RepoPilot 外部历史 Bug 评测','',f"模型：{report['config']['model']}；10 个任务 × 3 次 × 2 种方法，共 60 次。",'',
          '| 方法 | 补丁评分通过 | 正常结束且评分通过 | Token 中位数 | 同口径端到端耗时中位数 |','|---|---:|---:|---:|---:|']
    for m,s in report['methods'].items():
        text.append(f"| {m} | {s['resolved']}/{s['trials']} | {s['completed_and_resolved']}/{s['trials']} | {s['median_tokens']} | {s['median_end_to_end_seconds']:.3f}s |")
    text += ['','| 任务 | Agent | One-shot |','|---|---:|---:|']
    text += [f"| {t['task_id']} | {t['agent_successes']}/3 | {t['oneshot_successes']}/3 |" for t in report['by_task']]
    text += ['',f"成功率差：{report['success_gap_percentage_points']:.1f} 个百分点；按任务重采样的 95% 区间：{report['task_cluster_bootstrap_95_percent_gap']}。",'',
             '注意：只有 10 个独立任务，重复次数不能当成 30 个独立 Bug。范围为上游模块快照及固定回归用例，不能声称完整仓库集成修复能力或行业 Benchmark 得分。']
    a.output.with_suffix('.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(report['methods'],ensure_ascii=False),flush=True)

if __name__=='__main__': main()
