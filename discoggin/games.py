import re
import os, os.path
import urllib.parse
import time
import logging
import hashlib

class GameFile:
    def __init__(self, hash, filename, url, format):
        self.hash = hash
        self.filename = filename
        self.url = url
        self.format = format

    def __repr__(self):
        return '<GameFile "%s" (%s) %s>' % (self.filename, self.format, self.hash,)

def get_gamelist(app):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM games')
    gamels = [ GameFile(*tup) for tup in res.fetchall() ]
    return gamels

def get_gamemap(app):
    ls = get_gamelist(app)
    res = {}
    for game in ls:
        res[game.hash] = game
    return res

def get_game_by_hash(app, hash):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM games WHERE hash = ?', (hash,))
    tup = res.fetchone()
    if not tup:
        return None
    return GameFile(*tup)

def get_game_by_name(app, val):
    val = val.lower()
    ls = get_gamelist(app)
    for game in ls:
        if val in game.filename.lower():
            return game
    return None

def get_game_by_session(app, sessid):
    session = get_session_by_id(app, sessid)
    if not session:
        return None
    return get_game_by_hash(app, session.hash)
    
def get_game_by_channel(app, gckey):
    playchan = get_playchannel(app, gckey)
    if not playchan:
        return None
    if not playchan.sessid:
        return None
    return get_game_by_session(app, playchan.sessid)

# Matches empty string, ".", "..", and so on.
pat_alldots = re.compile('^[.]*$')

download_nonce = 1

async def download_game_url(app, url):
    """Download a game and install it in gamesdir.
    On success, return a GameFile. On error, return a string describing
    the error. (Sorry, that's messy. Pretend it's a Result sort of thing.)
    """
    global download_nonce
    
    logging.info('Requested download: %s', url)

    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        return 'Download URL must start with `http://` or `https://`'

    ### reject .zip here too?
    
    _, _, filename = url.rpartition('/')
    filename = urllib.parse.unquote(filename)
    if pat_alldots.match(filename) or '/' in filename:
        return 'URL does not appear to be a file: %s' % (url,)

    download_nonce += 1
    tmpfile = '_tmp_%d_%d_%s' % (time.time(), download_nonce, filename,)
    tmppath = os.path.join(app.gamesdir, tmpfile)
    
    async with app.httpsession.get(url) as resp:
        if resp.status != 200:
            return 'Download error: %s %s: %s' % (resp.status, resp.reason, url,)
        
        totallen = 0
        md5 = hashlib.md5()
        with open(tmppath, 'wb') as outfl:
            async for dat in resp.content.iter_chunked(4096):
                totallen += len(dat)
                outfl.write(dat)
                md5.update(dat)
            dat = None
            hash = md5.hexdigest()

    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM games WHERE hash = ?', (hash,))
    tup = res.fetchone()
    if tup:
        os.remove(tmppath)
        return 'Game is already installed: %s' % (url,)

    format = detect_format(tmppath, filename)
    if not format:
        os.remove(tmppath)
        return 'Format not recognized: %s' % (url,)

    ### this would be a great place to pull ifiction from blorbs
    ### and unpack resources, too
    logging.info('Downloaded %s (hash %s, format %s)', url, hash, format)

    finaldir = os.path.join(app.gamesdir, hash)
    finalpath = os.path.join(app.gamesdir, hash, filename)

    tup = (hash, filename, url, format)
    game = GameFile(*tup)
    curs.execute('INSERT INTO games (hash, filename, url, format) VALUES (?, ?, ?, ?)', tup)

    if not os.path.exists(finaldir):
        os.mkdir(finaldir)
    os.rename(tmppath, finalpath)

    return game

def detect_format(path, filename):
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in ('.ulx', '.gblorb'):
        return 'glulx'
    if ext in ('.z1', '.z2', '.z3', '.z4', '.z5', '.z6', '.z7', '.z8', '.zblorb'):
        return 'zcode'
    return None


# Late imports
from .sessions import get_playchannel, get_session_by_id

