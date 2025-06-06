import os, os.path

def delete_flat_dir(path):
    if not os.path.exists(path):
        return
    if os.path.isfile(path):
        raise Exception('not a directory: %s' % (path,))
    files = list(os.scandir(path))
    for ent in files:
        if ent.is_dir():
            raise Exception('contains a directory: %s' % (ent.path,))
    for ent in files:
        os.remove(ent.path)
    os.rmdir(path)
    
