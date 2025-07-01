import os, os.path
import json

def delete_flat_dir(path):
    """Delete a directory and all the files it contains. This is *not*
    recursive; if the directory contains subdirs, it will raise an
    exception (before deleting anything).
    """
    if not os.path.exists(path):
        return
    if os.path.isfile(path):
        raise Exception('not a directory: %s' % (path,))
    files = list(os.scandir(path))
    for ent in files:
        if ent.is_dir(follow_symlinks=False):
            raise Exception('contains a directory: %s' % (ent.path,))
    for ent in files:
        os.remove(ent.path)
    os.rmdir(path)
    
def load_json(path):
    """
    Read and parse a JSON file. Allow for the possibility of JSONP
    ("var foo = {...};").
    """
    with open(path) as fl:
        dat = fl.read()
    startpos = dat.index('{')
    endpos = dat.rindex('}')
    dat = dat[ startpos : endpos+1 ]
    return json.loads(dat)

