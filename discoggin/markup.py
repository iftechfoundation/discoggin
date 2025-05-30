import re

### what to do about multiline inputs?
pat_cmd = re.compile('^[\\s]*>(.*)$')

def extract_command(msg):
    match = pat_cmd.match(msg)
    if match is None:
        return None
    val = match.group(1)
    return val.strip()

def content_to_markup(dat):
    res = []
    for tup in dat.arr:
        text = tup[0]
        style = tup[1] if len(tup) > 1 else 'normal'
        val = escape(text)
        if style == 'header' or style == 'subheader' or style == 'input':
            val = '**'+val+'**'
        elif style == 'emphasized':
            val = '_'+val+'_'
        elif style == 'preformatted':
            val = '`'+val+'`'
        res.append(val)
    return ''.join(res)

pat_singlechar = re.compile('[`*_<>\\[\\]\\\\]')

def escape(val):
    val = pat_singlechar.sub(lambda match:'\\'+match.group(0), val)
    ### more?
    ### don't escape inside `` spans? Can't escape ` in there, looks like
    return val

MSG_LIMIT = 1990

def rebalance_output(ls):
    res = []
    cur = None
    for val in ls:
        if cur is not None:
            if len(cur)+1+len(val) < MSG_LIMIT:
                cur += '\n'
                cur += val
                continue
        if cur:
            res.append(cur)
            cur = None
        if len(val) < MSG_LIMIT:
            cur = val
            continue
        # This paragraph is over MSG_LIMIT by itself. Try to split it
        # up at word boundaries. If we can't do that, just split it.
        # BUG: This can split a markup span like "_italics_", which will
        # break the markup.
        while len(val) > MSG_LIMIT:
            pos = val[ : MSG_LIMIT ].rfind(' ')
            if pos >= 0:
                res.append(val[ : pos ])
                val = val[ pos+1 : ]
                continue
            res.append(val[ : MSG_LIMIT ])
            val = val[ MSG_LIMIT : ]
        if val:
            res.append(val)
            
    if cur:
        res.append(cur)
        cur = None
    return res
