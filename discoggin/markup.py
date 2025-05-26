import re

pat_cmd = re.compile('^[\\s]*>(.*)$')

def extract_command(msg):
    match = pat_cmd.match(msg)
    if match is None:
        return None
    val = match.group(1)
    return val.strip()
