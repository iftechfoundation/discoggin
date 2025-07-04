import re

pat_cmd = re.compile('^[\\s]*>(.*)$')
pat_linkinput = re.compile('^#([0-9]+)$')

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

def command_is_hyperlink(cmd):
    """See whether a command looks like a hyperlink reference: "#12",
    etc. Returns a number or None.
    This is theoretically ambiguous, but it's only a problem if a game
    expects both hyperlinks and line input of that form.
    ### TODO: accept a bare number if there is no line/char input pending.
    """
    match = pat_linkinput.match(cmd)
    if match:
        return int(match.group(1))
    return None

def content_to_markup(dat, hyperlinklabels=None):
    """Convert a ContentLine object into a Discord message, using
    Discord markup as much as possible.
    Hyperlinks are rendered as "[#1][text]" -- that isn't Discord markup,
    mind you. The user gets to figure it out.
    """
    ### has some bugs to do with whitespace. E.g. "_This _not_ that._"
    res = []
    curlink = None

    uniformlink = None
    if hyperlinklabels:
        uniformlink = dat.uniformlink()
        if uniformlink:
            label = hyperlinklabels.get(uniformlink, '???')
            res.append('[#%s] ' % (label,))
            curlink = uniformlink
    
    for tup in dat.arr:
        text = tup[0]
        style = tup[1] if len(tup) > 1 else 'normal'
        link = tup[2] if (len(tup) > 2 and hyperlinklabels) else None
        if link != curlink:
            if curlink is not None:
                res.append(']')
            curlink = link
            if curlink is not None:
                label = hyperlinklabels.get(curlink, '???')
                res.append('[#%s][' % (label,))
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

    if not uniformlink:
        if curlink is not None:
            res.append(']')
    
    return ''.join(res)

pat_singlechar = re.compile('[`*_<>\\[\\]\\\\]')

def escape(val):
    """Escape a string so that Discord will interpret it as plain text.
    """
    val = pat_singlechar.sub(lambda match:'\\'+match.group(0), val)
    ### more?
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
