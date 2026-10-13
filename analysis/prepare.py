#!/usr/bin/env python3
"""解析微信导出 txt → 北京时间消息表 + 统计 + 给本地模型的分块。
用法: python3 -I analysis/prepare.py <导出txt> <输出目录> [--tz-shift-hours 12] [--chunk-msgs 450]
导出的时间戳是本机时区(美东 -04:00)，默认 +12h 换成北京时间。
"""
import re, sys, json, os, argparse, statistics, collections
from datetime import datetime, timedelta

HEAD = re.compile(r'^\[#(\d{6}) (\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2}):(\d{2})\] ([^:]+?): (.*)$')
TYPE = re.compile(r'^\[(图片|文件|语音|视频|表情|动画表情|链接|位置|名片|转账|红包|小程序|合并转发|通话|语音通话|视频通话)\]')

def parse(path, shift):
    msgs = []
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        m = HEAD.match(line)
        if m:
            seq, y, mo, d, hh, mm, ss, sender, body = m.groups()
            ts = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss)) + shift
            t = TYPE.match(body)
            msgs.append(dict(id=int(seq), ts=ts, sender=sender, type=t.group(1) if t else 'text', text=body))
        elif msgs and line and not line.startswith('=====') :
            msgs[-1]['text'] += '\n' + line
    return msgs

def stats(msgs):
    senders = sorted({m['sender'] for m in msgs}, key=lambda s: -sum(1 for m in msgs if m['sender']==s))
    out = dict(senders=senders, total=len(msgs), days=len({m['ts'].date() for m in msgs}),
               range=[msgs[0]['ts'].strftime('%Y-%m-%d'), msgs[-1]['ts'].strftime('%Y-%m-%d')], weekly=[])
    # 周（ISO 周一起）
    by_week = collections.defaultdict(list)
    for m in msgs:
        wk = (m['ts'] - timedelta(days=m['ts'].weekday())).date()
        by_week[wk].append(m)
    GAP = timedelta(hours=4)  # 间隔 ≥4h 视为新一轮对话，首句者=发起方
    for wk in sorted(by_week):
        ms = by_week[wk]
        row = dict(week_start=str(wk), week_end=str(wk+timedelta(days=6)), total=len(ms), active_days=len({m['ts'].date() for m in ms}))
        for s in senders:
            mine = [m for m in ms if m['sender']==s]
            texts = [m for m in mine if m['type']=='text']
            row[s] = dict(count=len(mine), share=round(len(mine)/len(ms),3) if ms else 0,
                          avg_text_len=round(statistics.mean(len(m['text']) for m in texts),1) if texts else 0,
                          sticker=sum(1 for m in mine if m['type'] in ('表情','动画表情')),
                          image=sum(1 for m in mine if m['type']=='图片'),
                          voice_video=sum(1 for m in mine if m['type'] in ('语音','视频','通话','语音通话','视频通话')))
        # 发起方 & 回复延迟
        init = collections.Counter(); lat = collections.defaultdict(list)
        prev = None
        for m in ms:
            if prev is None or m['ts']-prev['ts'] >= GAP:
                init[m['sender']] += 1
            elif m['sender'] != prev['sender']:
                lat[m['sender']].append((m['ts']-prev['ts']).total_seconds())
            prev = m
        row['conversations'] = sum(init.values())
        row['initiated_by'] = {s: init.get(s,0) for s in senders}
        row['median_reply_sec'] = {s: round(statistics.median(lat[s])) if lat[s] else None for s in senders}
        hours = collections.Counter(m['ts'].hour for m in ms)
        row['late_night_share'] = round(sum(v for h,v in hours.items() if h>=23 or h<5)/len(ms),3)
        row['peak_hours'] = [h for h,_ in hours.most_common(3)]
        out['weekly'].append(row)
    # 最长静默
    gaps = sorted(((msgs[i+1]['ts']-msgs[i]['ts'], msgs[i]['id']) for i in range(len(msgs)-1)), reverse=True)[:5]
    out['longest_silences'] = [dict(hours=round(g.total_seconds()/3600,1), after_id=i) for g,i in gaps]
    return out

def stats_md(st):
    S = st['senders']; A, B = S[0], S[1]
    L = [f"# 统计摘要（北京时间）", f"- 双方: {A} / {B}；总消息 {st['total']} 条；{st['days']} 个活跃日；范围 {st['range'][0]} ~ {st['range'][1]}", "",
         f"| 周 | 总数 | {A} 条数(占比) | {B} 条数(占比) | 对话轮数 | 发起 {A}/{B} | 中位回复秒 {A}/{B} | {A} 均长 | {B} 均长 | 表情 {A}/{B} | 深夜占比 | 高峰小时 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in st['weekly']:
        a, b = r[A], r[B]
        L.append(f"| {r['week_start']}~{r['week_end'][5:]} | {r['total']} | {a['count']}({a['share']:.0%}) | {b['count']}({b['share']:.0%}) | {r['conversations']} | {r['initiated_by'][A]}/{r['initiated_by'][B]} | {r['median_reply_sec'][A]}/{r['median_reply_sec'][B]} | {a['avg_text_len']} | {b['avg_text_len']} | {a['sticker']}/{b['sticker']} | {r['late_night_share']:.0%} | {','.join(map(str,r['peak_hours']))} |")
    L += ["", "最长静默: " + "；".join(f"{g['hours']}h（#{g['after_id']:06d} 之后）" for g in st['longest_silences'])]
    return '\n'.join(L) + '\n'

def chunk(msgs, outdir, target):
    os.makedirs(outdir, exist_ok=True)
    by_day = collections.OrderedDict()
    for m in msgs: by_day.setdefault(m['ts'].date(), []).append(m)
    chunks, cur = [], []
    for day, ms in by_day.items():
        cur.extend(ms)
        if len(cur) >= target: chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    manifest = []
    for i, ms in enumerate(chunks, 1):
        name = f"{i:03d}.txt"
        with open(os.path.join(outdir, name), 'w', encoding='utf-8') as f:
            f.write(f"# 片段 {i:03d}  {ms[0]['ts']:%Y-%m-%d %H:%M} ~ {ms[-1]['ts']:%Y-%m-%d %H:%M}（北京时间） 共 {len(ms)} 条\n\n")
            last_day = None
            for m in ms:
                if m['ts'].date() != last_day:
                    last_day = m['ts'].date(); f.write(f"\n== {last_day} {'一二三四五六日'[last_day.weekday()]} ==\n")
                f.write(f"#{m['id']:06d} {m['ts']:%H:%M} {m['sender']}: {m['text']}\n")
        manifest.append(dict(chunk=name, start=str(ms[0]['ts']), end=str(ms[-1]['ts']), first_id=ms[0]['id'], last_id=ms[-1]['id'], count=len(ms)))
    json.dump(manifest, open(os.path.join(outdir, 'manifest.json'), 'w'), ensure_ascii=False, indent=1)
    return manifest

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--tz-shift-hours', type=float, default=12); ap.add_argument('--chunk-msgs', type=int, default=450)
    a = ap.parse_args()
    msgs = parse(a.src, timedelta(hours=a.tz_shift_hours))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'messages.jsonl'), 'w', encoding='utf-8') as f:
        for m in msgs: f.write(json.dumps({**m, 'ts': m['ts'].isoformat()}, ensure_ascii=False) + '\n')
    st = stats(msgs)
    json.dump(st, open(os.path.join(a.out, 'stats.json'), 'w'), ensure_ascii=False, indent=1)
    open(os.path.join(a.out, 'stats.md'), 'w').write(stats_md(st))
    man = chunk(msgs, os.path.join(a.out, 'chunks'), a.chunk_msgs)
    print(f"messages={len(msgs)} weeks={len(st['weekly'])} chunks={len(man)} -> {a.out}")
