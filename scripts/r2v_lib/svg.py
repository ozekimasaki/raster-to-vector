"""Conservative, non-executing SVG subset inspection; not a geometry proof."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .images import digest

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
TAGS = set('svg g defs path rect circle ellipse line polyline polygon linearGradient radialGradient stop clipPath title desc'.split())
PRESENTATION = set('fill stroke stroke-width stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray stroke-dashoffset fill-rule clip-rule opacity fill-opacity stroke-opacity clip-path color stop-color stop-opacity color-interpolation shape-rendering mix-blend-mode isolation display visibility'.split())
ATTRS = PRESENTATION | set('id width height viewBox preserveAspectRatio x y x1 y1 x2 y2 cx cy r rx ry fx fy fr d points transform gradientTransform gradientUnits spreadMethod offset clipPathUnits style version'.split())
NUMBER = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
NUMERIC = set('width height x y x1 y1 x2 y2 cx cy r rx ry fx fy fr stroke-width stroke-miterlimit stroke-dashoffset opacity fill-opacity stroke-opacity stop-opacity offset'.split())
ARITY = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}


def finite(value):
    n = float(value)
    if not math.isfinite(n) or abs(n) > 1e9:
        raise ValueError('Non-finite or excessively large coordinate')
    return n


def numbers(value):
    parts = re.findall(NUMBER, value)
    rest = re.sub(NUMBER, '', value)
    if rest.strip(' ,\t\n\r'):
        raise ValueError('Malformed numeric list')
    return [finite(x) for x in parts]


def path_segments(value):
    tokens = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUMBER, value)
    rest = re.sub(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUMBER, '', value)
    if rest.strip(' ,\t\n\r'):
        raise ValueError('Unsupported/malformed path syntax')
    if not tokens: return 0
    if tokens[0] not in ('M', 'm'): raise ValueError('Path must start with M')
    i = 0; segments = 0
    while i < len(tokens):
        command = tokens[i]
        if command.upper() not in ARITY: raise ValueError('Path command expected')
        i += 1; start = i
        while i < len(tokens) and tokens[i].upper() not in ARITY:
            finite(tokens[i]); i += 1
        count = i-start; arity = ARITY[command.upper()]
        if arity == 0:
            if count: raise ValueError('Numbers after closepath')
            segments += 1
        else:
            if count == 0 or count % arity: raise ValueError('Wrong path command arity')
            if command.upper() == 'A':
                for j in range(start, i, 7):
                    if finite(tokens[j]) < 0 or finite(tokens[j+1]) < 0:
                        raise ValueError('Negative arc radius')
                    if tokens[j+3] not in ('0', '1') or tokens[j+4] not in ('0', '1'):
                        raise ValueError('Arc flags must be 0 or 1')
            segments += count // arity
    return segments


def local_name(key):
    if key.startswith('{'):
        namespace, name = key[1:].split('}', 1)
        if namespace != NS: raise ValueError('Foreign namespace rejected')
        return name
    return key


def inspect(path):
    data = Path(path).read_bytes()
    report = {'status': 'failed', 'svg_sha256': digest(path), 'bytes': len(data),
              'geometry_certificate': 'indeterminate', 'topology': 'indeterminate', 'errors': []}
    try:
        if len(data) > 10_000_000: raise ValueError('SVG exceeds 10 MB tool limit')
        text = data.decode('utf-8-sig')
        if re.search(r'<!DOCTYPE|<!ENTITY|<\?(?!xml\s)', text, re.I):
            raise ValueError('DTD/entities/processing instructions rejected')
        root = ET.fromstring(text)
        if local_name(root.tag) != 'svg': raise ValueError('Root must be svg')
        ids = {}; refs = []; counts = Counter(); segments = 0; additive = False
        for el in root.iter():
            tag = local_name(el.tag)
            if tag not in TAGS: raise ValueError(f'Unsupported SVG element: {tag}')
            counts[tag] += 1
            if sum(counts.values()) > 100000: raise ValueError('Too many elements')
            for key, value in el.attrib.items():
                key = local_name(key)
                if re.fullmatch(r'data-[a-z][a-z0-9-]*', key):
                    continue  # Inert editing metadata; never executed or interpreted as instructions.
                if key not in ATTRS: raise ValueError(f'Unsupported attribute: {key}')
                if key == 'id':
                    if not re.fullmatch(r'[A-Za-z_][\w.-]*', value): raise ValueError('Unsupported ID syntax')
                    if value in ids: raise ValueError('Duplicate ID')
                    ids[value] = tag
                attrs = [(key, value)]
                if key == 'style':
                    attrs = []
                    for declaration in value.split(';'):
                        if not declaration.strip(): continue
                        pair = declaration.split(':', 1)
                        if len(pair) != 2 or pair[0].strip() not in PRESENTATION:
                            raise ValueError('Unsupported style declaration')
                        attrs.append((pair[0].strip(), pair[1].strip()))
                for prop, val in attrs:
                    if any(c in val for c in ('\\', '@', '{', '}', '<', '>')) or '/*' in val:
                        raise ValueError('CSS escape/import/comment/markup rejected')
                    # The only accepted resource operation is a local gradient or clip reference.
                    if 'url' in val.lower():
                        match = re.fullmatch(r'url\(\s*#([A-Za-z_][\w.-]*)\s*\)', val)
                        if prop not in ('fill', 'stroke', 'clip-path') or not match:
                            raise ValueError('External or unsupported resource reference')
                        refs.append((prop, match[1]))
                    if re.search(r'(?:https?:|file:|data:|javascript:|expression\s*\()', val, re.I):
                        raise ValueError('External/active content rejected')
                    if re.search(r'\b(?:var|env|calc|attr)\s*\(', val, re.I):
                        raise ValueError('Dynamic CSS values are outside this subset')
                    if prop == 'stroke-dasharray' and val != 'none':
                        if any(n < 0 for n in numbers(val)): raise ValueError('Negative dash length')
                    if prop in NUMERIC:
                        m = re.fullmatch('(' + NUMBER + r')(px|%)?', val)
                        if not m: raise ValueError(f'Malformed numeric attribute: {prop}')
                        n = finite(m[1])
                        if prop in ('opacity','fill-opacity','stroke-opacity','stop-opacity'):
                            opacity = n/100 if m[2] == '%' else n
                            if not 0 <= opacity <= 1 or m[2] == 'px':
                                raise ValueError('Opacity must be within 0..1 (or 0..100%)')
                        if prop in ('width', 'height', 'r', 'rx', 'ry', 'fr', 'stroke-width') and n < 0:
                            raise ValueError('Negative dimension')
                    if prop == 'mix-blend-mode':
                        if val not in ('normal', 'plus-lighter'): raise ValueError('Unsupported blend mode')
                        additive |= val == 'plus-lighter'
                    if prop in ('transform', 'gradientTransform'):
                        matches = list(re.finditer(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^()]*)\)', val))
                        remainder = re.sub(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^()]*)\)', '', val)
                        if remainder.strip(' ,\t\n\r') or not matches: raise ValueError('Malformed transform')
                        for m in matches:
                            n = len(numbers(m[2])); allowed = {'matrix': (6,), 'translate': (1,2), 'scale': (1,2), 'rotate': (1,3), 'skewX': (1,), 'skewY': (1,)}
                            if n not in allowed[m[1]]: raise ValueError('Transform arity')
                    if prop == 'points':
                        pts = numbers(val)
                        if len(pts) < 4 or len(pts) % 2: raise ValueError('Malformed points')
                    if prop == 'd': segments += path_segments(val)
        for prop, ref in refs:
            if ref not in ids: raise ValueError(f'Missing local reference: {ref}')
            targets = ('clipPath',) if prop == 'clip-path' else ('linearGradient', 'radialGradient')
            if ids[ref] not in targets: raise ValueError('Wrong reference target type')
        vb = numbers(root.attrib.get('viewBox', ''))
        if vb and (len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0): raise ValueError('Invalid viewBox')
        dims = []
        for index, key in enumerate(('width', 'height')):
            val = root.attrib.get(key)
            if val is None and vb: dims.append(vb[index+2]); continue
            if val is None or not re.fullmatch(NUMBER + r'(px)?', val):
                raise ValueError('Root needs absolute pixel dimensions or viewBox')
            dims.append(finite(val.removesuffix('px')))
        if min(dims) <= 0: raise ValueError('Empty canvas')
        if max(dims) > 8192 or dims[0]*dims[1] > 25_000_000: raise ValueError('Canvas exceeds renderer limits')
        report.update(status='passed', width=dims[0], height=dims[1], viewBox=vb or [0,0,*dims],
                      elements=dict(counts), path_count=counts['path'], path_segment_count=segments,
                      plus_lighter=additive, notes=['Conservative SVG subset; not a topology/coverage certificate'])
        return report, root
    except (ValueError, ET.ParseError, UnicodeError) as exc:
        report['errors'].append(str(exc))
        return report, None
