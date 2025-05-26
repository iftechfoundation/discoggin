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
    for (text, style, link) in dat.arr:
        val = escape(text)
        if style == 'header' or style == 'subheader' or style == 'input':
            val = '**'+val+'**'
        elif style == 'emphasized':
            val = '_'+val+'_'
        elif style == 'preformatted':
            val = '`'+val+'`'
        res.append(val)
    return ''.join(res)

def escape(val):
    return val
