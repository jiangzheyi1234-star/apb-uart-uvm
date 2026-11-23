#!/usr/bin/env python3
"""Export an actual VCD time window as a portable SVG, without invented samples."""
import argparse
import hashlib
import html
import re
from pathlib import Path


def read_vcd(path, duration_ns, start_ns):
    wanted = ('apb.rst_n','uart.rx','uart.tx','uart.irq','apb.psel','apb.penable','apb.pwrite')
    selected, signals, scope = {}, {}, []
    tick_ns = 0.001
    timestamp = 0
    header = True
    with path.open(encoding='utf-8') as stream:
        for raw in stream:
            line = raw.strip()
            if header:
                if line.startswith('$scope'):
                    scope.append(line.split()[2])
                elif line.startswith('$upscope'):
                    scope.pop()
                elif line.startswith('$timescale'):
                    match = re.search(r'(\d+)\s*(s|ms|us|ns|ps|fs)',line)
                    if match:
                        tick_ns=int(match[1])*{'s':1e9,'ms':1e6,'us':1e3,'ns':1,'ps':1e-3,'fs':1e-6}[match[2]]
                elif line.startswith('$var'):
                    parts=line.split()
                    full='.'.join(scope+[parts[4]])
                    for name in wanted:
                        if parts[2]=='1' and full.endswith('.'+name) and name not in signals:
                            signals[name]={'full_name':full,'events':[]}
                            selected.setdefault(parts[3],[]).append(name)
                elif line.startswith('$enddefinitions'):
                    header=False
                continue
            if line.startswith('#'):
                timestamp=int(line[1:])*tick_ns
                if timestamp>start_ns+duration_ns:
                    break
            elif line and line[0] in '01xXzZ':
                for name in selected.get(line[1:],[]):
                    signals[name]['events'].append((timestamp,line[0].lower()))
    if not signals or not any(s['events'] for s in signals.values()):
        raise ValueError('No requested interface samples found in VCD')
    return signals


def render(path, output, start_ns=0, duration_ns=5000):
    if duration_ns<=0 or start_ns<0:
        raise ValueError('Time window must be positive')
    signals=read_vcd(path,duration_ns,start_ns)
    width,left,right,top,row=1280,160,30,100,68
    plot_width=width-left-right
    height=top+row*len(signals)+85
    end_ns=start_ns+duration_ns
    x=lambda t:left+(t-start_ns)/duration_ns*plot_width
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         '<rect width="100%" height="100%" fill="#0b1424"/>',
         '<g font-family="Segoe UI,Arial,sans-serif" fill="#e6edf6">',
         '<text x="28" y="35" font-size="23" font-weight="600">APB UART — measured RTL waveform</text>',
         f'<text x="28" y="61" font-size="13" fill="#9eb0c8">Source: {html.escape(path.name)} | {start_ns:g}–{end_ns:g} ns | actual VCD samples</text>']
    for i in range(11):
        t=start_ns+duration_ns*i/10
        xx=x(t)
        svg += [f'<path d="M{xx:.2f},82 V{height-70}" stroke="#22334b"/>',
                f'<text x="{xx:.2f}" y="{height-48}" font-size="11" text-anchor="middle" fill="#9eb0c8">{t:g}</text>']
    for i,(name,signal) in enumerate(signals.items()):
        center=top+i*row+25
        y=lambda value:center-14 if value=='1' else center+14 if value=='0' else center
        svg.append(f'<text x="24" y="{center+4}" font-size="15">{html.escape(name)}</text>')
        previous='x'
        events=[]
        for t,v in signal['events']:
            if t<=start_ns:
                previous=v
            elif t<=end_ns:
                events.append((t,v))
        points=[(left,y(previous))]
        for t,v in events:
            points.extend([(x(t),y(previous)),(x(t),y(v))])
            previous=v
        points.append((x(end_ns),y(previous)))
        coords=' '.join(f'{a:.2f},{b:.2f}' for a,b in points)
        svg.append(f'<polyline points="{coords}" fill="none" stroke="{["#a5b4fc","#34d399","#60a5fa","#fbbf24"][i%4]}" stroke-width="2"/>')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    svg += [f'<text x="28" y="{height-17}" font-size="10" fill="#9eb0c8">VCD SHA-256: {digest}</text>','</g></svg>']
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('\n'.join(svg)+'\n',encoding='utf-8')
    return len(signals)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('vcd',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--start-ns',type=float,default=0)
    p.add_argument('--duration-ns',type=float,default=5000)
    a=p.parse_args()
    try:
        n=render(a.vcd,a.out,a.start_ns,a.duration_ns)
    except (OSError,ValueError) as e:
        p.exit(2,f'WAVEFORM_EXPORT_ERROR: {e}\n')
    print(f'WAVEFORM_EXPORTED: {n} observed signals; {a.out}')


if __name__=='__main__':
    main()
