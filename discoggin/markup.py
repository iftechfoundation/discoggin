import re

pat_cmd = re.compile('^[\\s]*>(.*)$')

def extract_command(msg):
    """See whether a Discord message is meant as a command input.
    A command input is one line starting with ">" (perhaps whitespace too).
    Multi-line inputs, or inputs containing a command plus commentary,
    do not count.
    """
    match = pat_cmd.match(msg.strip())
    if match is None:
        return None
    val = match.group(1)
    return val.strip()

def content_to_markup(dat):
    """Convert a ContentLine object into a Discord message, using
    Discord markup as much as possible.
    """
    ### has some bugs to do with whitespace. E.g. "_This _not_ that._"
    res = []
    for tup in dat.arr:
        text = tup[0]
        style = tup[1] if len(tup) > 1 else 'normal'
        val = escape(text)
        if style == 'header' or style == 'subheader' or style == 'input':
            sval = '**'+val+'**'
        elif style == 'emphasized':
            sval = '_'+val+'_'
        elif style == 'preformatted':
            # use the unescaped text here
            sval = '`'+text+'`'
        else:
            sval = val
        res.append(sval)
    return ''.join(res)

pat_singlechar = re.compile('[`*_<>\\[\\]\\\\]')

def escape(val):
    """Escape a string so that Discord will interpret it as plain text.
    """
    val = pat_singlechar.sub(lambda match:'\\'+match.group(0), val)
    ### more?
    ### don't escape inside `` spans? Can't escape ` in there, looks like
    return val

# Maximum size of a Discord message (minus a safety margin).
MSG_LIMIT = 1990

def rebalance_output(ls):
    """Given a list of lines (paragraphs) to be sent as a Discord message,
    combine them as much as possible while staying under the Discord
    size limit. If there are any lines longer than the limit, break
    them up (preferably at word boundaries).

    This will introduce paragraph breaks into very long paragraphs;
    no help for that.
    """
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

    # Make sure no completely blank or whitespace lines remain.
    # (Discord doesn't like to print those.)
    res = [ val.rstrip() for val in res ]
    res = [ val for val in res if val ]
    return res
