#!/usr/bin/env python3
"""用本地 OpenAI 兼容模型（vLLM / Ollama 等）做两段式分析：map(每块一份结构化笔记) → reduce(关系变化报告)。
用法: python3 -I analysis/run_local.py map|reduce|verify <outdir> [--workers 4]
端点由 LOCAL_LLM_ENDPOINTS 或 llm_endpoints.json 配置；只连你自己的主机，正文不出内网。可中断重跑，已完成的块自动跳过。
"""
import sys, os, json, glob, re, time, argparse, urllib.request, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.llm_endpoints import pick_endpoint  # 端点配置见 core/llm_endpoints.py

URL, MODEL = pick_endpoint()
print(f'→ {URL} ({MODEL})', file=sys.stderr)

def chat(system, user, max_tokens=4000, thinking=False, temperature=0.3, timeout=900):
    body = dict(model=MODEL, temperature=temperature, max_tokens=max_tokens,
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                chat_template_kwargs={'enable_thinking': thinking})
    req = urllib.request.Request(URL + '/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    msg = r['choices'][0]['message']; content = msg.get('content') or ''
    if not content.strip():
        raise RuntimeError(f"模型正文为空(finish={r['choices'][0].get('finish_reason')}, reasoning={len(msg.get('reasoning_content') or '')}字)")
    return content, r.get('usage', {})

def parse_json(s):
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s.strip(), flags=re.M)
    i, j = s.find('{'), s.rfind('}')
    return json.loads(s[i:j+1])

MAP_SYS = """你是一位冷静、克制的人际关系分析师。下面是两个人一段连续的微信聊天原文（北京时间，每条以 #编号 开头）。
请只依据原文给出结构化观察，不臆测、不美化、不下道德评判。所有引用必须给出真实的 #编号，引文 ≤30 字且与原文一致。
严格输出一个 JSON 对象，不要任何多余文字：
{
 "date_range": "YYYY-MM-DD ~ YYYY-MM-DD",
 "summary": "这段时间两人在聊什么、怎么相处（≤120字）",
 "topics": ["话题1","话题2",...],              // 3-8 个
 "tone": {"<发送者A>": "语气/态度 ≤40字", "<发送者B>": "语气/态度 ≤40字"},
 "driver": "谁更主动推进对话、怎么推进（≤60字）",
 "closeness_signals": [{"id":"#000123","note":"亲近/信任/依赖的具体表现 ≤40字"}],   // 0-6 个
 "tension_signals": [{"id":"#000123","note":"疏远/回避/不满/矛盾的具体表现 ≤40字"}], // 0-6 个
 "events": [{"id":"#000123","what":"对关系有影响的具体事件 ≤40字"}],               // 0-6 个
 "stage": "用一个短语概括此时的关系阶段（如：工作对接 / 开始闲聊 / 日常分享 / 暧昧升温 / 稳定亲密 / 出现摩擦 / 降温 等，可自拟）",
 "change_vs_before": "与片段开头相比到结尾有什么变化（≤60字）"
}"""

REDUCE_SYS = """你是一位冷静、克制的人际关系分析师。你将收到：(1) 两人 70 天微信聊天的逐周统计表；(2) 按时间顺序排列的 42 份片段观察笔记（每份覆盖一两天，含真实 #编号引用）。
请据此写一份《聊天关系变化分析》，中文 Markdown，面向导出聊天记录的本人（即统计表里的第一位发送者）。要求：
1. 只基于给定材料，不编造；每个关键判断都要引用笔记里已有的 #编号，不要发明新编号。
2. 结构：
   # 聊天关系变化分析
   ## 一、总览（3-5 句）
   ## 二、阶段划分（时间轴表：阶段 | 日期范围 | 关系状态 | 特征 | 代表证据 #编号）
   ## 三、转折点（逐条：日期、发生了什么、引用、为什么算转折）
   ## 四、互动模式的量变（结合统计表：谁发起、回复速度、消息占比、深夜聊天、表情使用的走势；给出解读而不是复述数字）
   ## 五、双方各自的态度轨迹（分别写两人）
   ## 六、当前状态与值得留意的信号（克制，不替本人下结论，不给恋爱/道德建议）
3. 语气客观、具体，不煽情，不用「可能性很大」之类空话；不确定就说不确定。
4. 总长 1500-2500 字。"""

def do_map(out, workers):
    chunks = sorted(glob.glob(f'{out}/chunks/[0-9][0-9][0-9].txt'))
    os.makedirs(f'{out}/notes', exist_ok=True)
    todo = [c for c in chunks if not os.path.exists(f"{out}/notes/{os.path.basename(c)[:-4]}.json")]
    print(f'{len(chunks)} 块，待处理 {len(todo)}', file=sys.stderr)
    def one(c):
        name = os.path.basename(c)[:-4]; txt = open(c, encoding='utf-8').read()
        for attempt in range(3):
            try:
                t0 = time.time(); content, usage = chat(MAP_SYS, txt, max_tokens=3000)
                note = parse_json(content); note['chunk'] = name
                json.dump(note, open(f'{out}/notes/{name}.json', 'w'), ensure_ascii=False, indent=1)
                return f"{name} ok {time.time()-t0:.0f}s in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}"
            except Exception as e:
                err = f'{type(e).__name__}: {str(e)[:120]}'; time.sleep(5)
        open(f'{out}/notes/{name}.fail', 'w').write(err); return f'{name} FAIL {err}'
    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, todo): print(r, file=sys.stderr, flush=True)

def do_reduce(out):
    notes = [json.load(open(p)) for p in sorted(glob.glob(f'{out}/notes/[0-9]*.json'))]
    stats = open(f'{out}/stats.md', encoding='utf-8').read()
    user = f"## 逐周统计\n{stats}\n\n## 片段笔记（按时间顺序）\n" + '\n'.join(f"### 片段 {n['chunk']}\n```json\n{json.dumps(n, ensure_ascii=False)}\n```" for n in notes)
    t0 = time.time(); content, usage = chat(REDUCE_SYS, user, max_tokens=10000, thinking=False, temperature=0.4, timeout=1800)
    open(f'{out}/report.md', 'w', encoding='utf-8').write(content.strip() + '\n')
    print(f"report.md 写出 {len(content)} 字 {time.time()-t0:.0f}s usage={usage}", file=sys.stderr)

PERSONA_SYS = """你是一位冷静、克制的性格分析师。你将收到两人 70 天微信聊天的逐周统计表和 42 份按时间排列的片段观察笔记（含对方的语气描述、亲近/疏远信号、事件与真实 #编号引用）。统计表里第二位发送者是「对方」，请只分析「对方」这个人。
写一份《对方的人格画像》，中文 Markdown，面向本人阅读。要求：
1. 只基于材料归纳，每个判断给出至少一个 #编号或笔记里的具体行为作依据；证据不足就明确写「证据不足」。
2. 结构：
   # 对方的人格画像
   ## 一、一句话概括
   ## 二、核心特质（4-6 条，每条：特质 → 表现 → 依据）
   ## 三、沟通风格（主动性、回复节奏、表达方式、情绪表达、幽默感；结合统计表解读）
   ## 四、需求与在意的东西（从她反复提起、反应强烈的事推断）
   ## 五、压力与回避模式（遇到不适、矛盾、被推进时怎么反应）
   ## 六、大五人格倾向（开放性/尽责性/外向性/宜人性/神经质，各给 高/中/低 + 一句依据 + 置信度）
   ## 七、与她相处的几点提示（克制、具体，不给恋爱策略，不做道德评判）
   ## 八、这份画像的局限
3. 语气客观，不贴标签式下结论，不用星座/MBTI 式的空泛描述。总长 1500-2500 字。"""

def do_persona(out):
    notes = [json.load(open(p)) for p in sorted(glob.glob(f'{out}/notes/[0-9]*.json'))]
    stats = open(f'{out}/stats.md', encoding='utf-8').read()
    user = f"## 逐周统计\n{stats}\n\n## 片段笔记（按时间顺序）\n" + '\n'.join(f"### 片段 {n['chunk']}\n```json\n{json.dumps(n, ensure_ascii=False)}\n```" for n in notes)
    t0 = time.time(); content, usage = chat(PERSONA_SYS, user, max_tokens=10000, thinking=False, temperature=0.4, timeout=1800)
    open(f'{out}/persona.md', 'w', encoding='utf-8').write(content.strip() + '\n')
    print(f"persona.md 写出 {len(content)} 字 {time.time()-t0:.0f}s usage={usage}", file=sys.stderr)

PSYCH_SYS = """你是一位受过系统训练、措辞克制的心理学工作者（非临床诊断场景）。你将收到两人 70 天微信聊天的逐周统计表和 42 份按时间排列的片段观察笔记（含语气描述、亲近/疏远信号、事件与真实 #编号引用）。统计表第一位发送者是「本人」，第二位是「对方」。
请从心理学角度写一份《心理学视角分析》，中文 Markdown，面向本人阅读。要求：
1. 用明确的理论框架组织，每个框架先用一两句说明它看什么，再对照材料分析；每个判断至少给一个 #编号或笔记里的具体行为作依据，证据不足就写「证据不足」。
2. 结构：
   # 心理学视角分析
   ## 一、依恋风格（成人依恋：安全/焦虑/回避/恐惧-回避；分别看对方与本人，重点看靠近与拉开距离时的反应、对回复延迟的敏感度）
   ## 二、情绪调节与防御（她在不适、尴尬、被推进时用什么方式处理：幽默化、转移话题、沉默、合理化等；本人同样分析）
   ## 三、基本心理需求（自我决定理论：自主、胜任、归属——各自在这段关系里哪些被满足、哪些在求而不得）
   ## 四、互动模式（戈特曼的「邀请-回应」：谁发出靠近的邀请、对方是转向、转开还是对抗；有无追逐-退缩循环；结合统计表的发起/回复/占比走势）
   ## 五、自我呈现与边界（她在聊天里展示什么、回避什么；边界在哪、怎么表达；本人有没有越界或过度自我暴露）
   ## 六、关系动力的整体判断（这段关系的能量来自哪里、卡在哪里、各自可能的内在动机；给出不确定性）
   ## 七、给本人的心理学提示（克制、可操作、不替本人决定、不给追求策略，不做道德评判）
   ## 八、边界与局限（文字聊天的局限、不是诊断、理论框架的适用范围）
3. 语气专业而温和，不贴病理标签（不说「她有XX障碍」），不用绝对化措辞。总长 2000-3000 字。"""

def do_psych(out):
    notes = [json.load(open(p)) for p in sorted(glob.glob(f'{out}/notes/[0-9]*.json'))]
    stats = open(f'{out}/stats.md', encoding='utf-8').read()
    user = f"## 逐周统计\n{stats}\n\n## 片段笔记（按时间顺序）\n" + '\n'.join(f"### 片段 {n['chunk']}\n```json\n{json.dumps(n, ensure_ascii=False)}\n```" for n in notes)
    t0 = time.time(); content, usage = chat(PSYCH_SYS, user, max_tokens=12000, thinking=False, temperature=0.4, timeout=1800)
    open(f'{out}/psych.md', 'w', encoding='utf-8').write(content.strip() + '\n')
    print(f"psych.md 写出 {len(content)} 字 {time.time()-t0:.0f}s usage={usage}", file=sys.stderr)

RULES_SYS = """你将收到关于一位联系人（对方）的《人格画像》和《心理学视角分析》，以及统计表。请把它们浓缩成一份给「本人」用的《回复守则》，用于指导本人之后每一条微信回复的措辞与节奏。要求：
- 中文 Markdown，总长 400-700 字，只写可直接执行的规则，不复述分析。
- 结构：
  ## 她的核心需求与雷区（3-5 条，每条一句）
  ## 回复节奏（什么时候马上回、什么时候等、什么时候先别回；她冷处理/沉默时怎么办；一句一条）
  ## 措辞规则（长度、语气、幽默的用法、什么词和句式别用、怎么回应她的暗示和拒绝；一句一条）
  ## 禁止事项（本人过去做过且引起反弹的具体行为，写成禁止句）
  ## 她脆弱或求助时（怎么接住又不越界）
- 规则要具体到能照着写消息，避免空话（如「多理解她」）。"""

def do_rules(out):
    persona = open(f'{out}/persona.md', encoding='utf-8').read(); psych = open(f'{out}/psych.md', encoding='utf-8').read()
    stats = open(f'{out}/stats.md', encoding='utf-8').read()
    user = f"## 统计\n{stats}\n\n## 人格画像\n{persona}\n\n## 心理学视角分析\n{psych}"
    t0 = time.time(); content, usage = chat(RULES_SYS, user, max_tokens=3000, thinking=False, temperature=0.3, timeout=600)
    open(f'{out}/rules.md', 'w', encoding='utf-8').write(content.strip() + '\n')
    print(f"rules.md 写出 {len(content)} 字 {time.time()-t0:.0f}s", file=sys.stderr)

def do_verify(out):
    """机器可判的复验：覆盖率、引用编号真实性、引文与原文一致。"""
    man = json.load(open(f'{out}/chunks/manifest.json'))
    notes = {os.path.basename(p)[:-5]: json.load(open(p)) for p in glob.glob(f'{out}/notes/[0-9]*.json')}
    fails = glob.glob(f'{out}/notes/*.fail')
    msgs = {}
    for line in open(f'{out}/messages.jsonl', encoding='utf-8'):
        m = json.loads(line); msgs[m['id']] = m
    print(f"块 {len(man)} / 笔记 {len(notes)} / 失败 {len(fails)}")
    bad_range = bad_id = total_ids = 0
    for c in man:
        n = notes.get(c['chunk'][:-4]);
        if not n: continue
        for key in ('closeness_signals', 'tension_signals', 'events'):
            for item in n.get(key, []):
                total_ids += 1
                mm = re.search(r'\d{6}', str(item.get('id', '')))
                if not mm or int(mm.group()) not in msgs: bad_id += 1; continue
                if not (c['first_id'] <= int(mm.group()) <= c['last_id']): bad_range += 1
    print(f"笔记引用编号 {total_ids} 个：不存在 {bad_id}，越出本块范围 {bad_range}")
    if os.path.exists(f'{out}/report.md'):
        rep = open(f'{out}/report.md', encoding='utf-8').read()
        ids = sorted({int(x) for x in re.findall(r'#(\d{6})', rep)})
        cited_in_notes = {int(re.search(r'\d{6}', str(i['id'])).group()) for n in notes.values() for k in ('closeness_signals','tension_signals','events') for i in n.get(k, []) if re.search(r'\d{6}', str(i.get('id','')))}
        missing = [i for i in ids if i not in msgs]; novel = [i for i in ids if i in msgs and i not in cited_in_notes]
        print(f"报告引用 {len(ids)} 个编号：不存在 {len(missing)} {missing[:10]}；笔记里没有、报告自创的 {len(novel)} {novel[:10]}")
        print(f"报告字数 {len(rep)}；章节: {re.findall(r'^## .*', rep, flags=re.M)}")
    for name in ('persona', 'psych'):
        if not os.path.exists(f'{out}/{name}.md'): continue
        rep = open(f'{out}/{name}.md', encoding='utf-8').read()
        ids = sorted({int(x) for x in re.findall(r'#(\d{6})', rep)})
        missing = [i for i in ids if i not in msgs]
        print(f"{name} 引用 {len(ids)} 个编号：不存在 {len(missing)} {missing[:10]}；字数 {len(rep)}；章节 {len(re.findall(r'^## ', rep, flags=re.M))}")
    if False:
        rep = open(f'{out}/persona.md', encoding='utf-8').read()
        ids = sorted({int(x) for x in re.findall(r'#(\d{6})', rep)})
        missing = [i for i in ids if i not in msgs]
        print(f"画像引用 {len(ids)} 个编号：不存在 {len(missing)} {missing[:10]}；字数 {len(rep)}；章节 {len(re.findall(r'^## ', rep, flags=re.M))}")

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('stage', choices=['map', 'reduce', 'persona', 'psych', 'rules', 'verify']); ap.add_argument('out'); ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    {'map': lambda: do_map(a.out, a.workers), 'reduce': lambda: do_reduce(a.out), 'persona': lambda: do_persona(a.out), 'psych': lambda: do_psych(a.out), 'rules': lambda: do_rules(a.out), 'verify': lambda: do_verify(a.out)}[a.stage]()
