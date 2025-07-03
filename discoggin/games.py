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
    ls = get_gamelist(app)
    for game in ls:
        if game.hash == val:
            return game
    lval = val.lower()
    for game in ls:
        if lval in game.filename.lower():
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

def delete_game(app, hash):
    """Delete a game and all its files.
    This is called from the command-line.
    """
    game = get_game_by_hash(app, hash)
    if game is None:
        return
    
    gamefiledir = os.path.join(app.gamesdir, hash)
    delete_flat_dir(gamefiledir)

    curs = app.db.cursor()
    curs.execute('DELETE FROM games WHERE hash = ?', (hash,))

# Matches empty string, ".", "..", and so on.
pat_alldots = re.compile('^[.]*$')

download_nonce = 1

async def download_game_url(app, url, filename=None):
    """Download a game and install it in gamesdir.
    If filename is not provided, slice it off the URL.
    On success, return a GameFile. On error, return a string describing
    the error. (Sorry, that's messy. Pretend it's a Result sort of thing.)
    """
    global download_nonce
    
    app.logger.info('Requested download: %s', url)

    if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
        return 'Download URL must start with `http://` or `https://`'

    ### reject .zip here too?

    if not filename:
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
        return 'Game is already installed (try **/select %s**)' % (filename,)

    format = detect_format(filename, tmppath)
    if not format:
        os.remove(tmppath)
        return 'Format not recognized: %s' % (url,)

    ### this would be a great place to pull ifiction from blorbs
    ### and unpack resources, too
    app.logger.info('Downloaded %s (hash %s, format %s)', url, hash, format)

    finaldir = os.path.join(app.gamesdir, hash)
    finalpath = os.path.join(app.gamesdir, hash, filename)

    tup = (hash, filename, url, format)
    game = GameFile(*tup)
    curs.execute('INSERT INTO games (hash, filename, url, format) VALUES (?, ?, ?, ?)', tup)

    if not os.path.exists(finaldir):
        os.mkdir(finaldir)
    os.rename(tmppath, finalpath)

    return game

def detect_format(filename, path=None):
    """Figure out the type of a file given its bare filename and, optionally,
    its full path.
    In the path=None case, we really only care whether the filename
    *might* be an IF game, so it's okay that we can't distinguish the
    type completely. We may return '?' there.
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in ('.ulx', '.gblorb'):
        ### verify first word, if possible
        return 'glulx'
    if ext in ('.z1', '.z2', '.z3', '.z4', '.z5', '.z6', '.z7', '.z8', '.zblorb'):
        ### verify first byte, if possible
        return 'zcode'
    if ext in ('.json', '.js'):
        # We could check for the full '.ink.json' suffix, but that's not
        # reliable; Ink files may be found with just '.js' (and perhaps
        # JSONP at that).
        # Instead, we'll check the contents, if possible.
        if not path:
            return '?'
        try:
            obj = load_json(path)
        except:
            return None
        if 'inkVersion' in obj:
            return 'ink'
        if 'program' in obj and 'strings' in obj:
            return 'ys'
        return None
    return None

def format_interpreter_args(format, firstrun, *, gamefile, terpsdir, savefiledir, autosavedir):
    """Return an argument list and environment variables for the interpreter
    to run the given format.
    """
    if format == 'glulx':
        terp = os.path.join(terpsdir, 'glulxe')
        if firstrun:
            args = [ terp, '-singleturn', '-filedir', savefiledir, '-onlyfiledir', '--autosave', '--autodir', autosavedir, gamefile ]
        else:
            args = [ terp, '-singleturn', '-filedir', savefiledir, '-onlyfiledir', '-autometrics', '--autosave', '--autorestore', '--autodir', autosavedir, gamefile ]
        return (args, {})

    if format == 'zcode':
        terp = os.path.join(terpsdir, 'bocfel')
        env = {
            'BOCFEL_AUTOSAVE': '1',
            'BOCFEL_AUTOSAVE_DIRECTORY': autosavedir,
            'BOCFEL_AUTOSAVE_LIBRARYSTATE': '1',
        }
        # -C is BOCFEL_DISABLE_CONFIG
        # -H is BOCFEL_DISABLE_HISTORY_PLAYBACK
        # -m is BOCFEL_DISABLE_META_COMMANDS
        # -T is BOCFEL_TRANSCRIPT_NAME
        if firstrun:
            env['BOCFEL_SKIP_AUTORESTORE'] = '1'
            args = [ terp, '-C', '-H', '-m', '-T', 'transcript.txt', '-singleturn', '-filedir', savefiledir, '-onlyfiledir', gamefile ]
        else:
            args = [ terp, '-C', '-H', '-m', '-T', 'transcript.txt', '-singleturn', '-filedir', savefiledir, '-onlyfiledir', '-autometrics', gamefile ]
        return (args, env)
        
    if format == 'ink':
        terp = os.path.join(terpsdir, 'inkrun.js')
        if firstrun:
            args = [ terp, '--start', '--autodir', autosavedir, gamefile ]
        else:
            args = [ terp, '--autodir', autosavedir, gamefile ]
        return (args, {})
        
    if format == 'ys':
        terp = os.path.join(terpsdir, 'ysrun')
        if firstrun:
            args = [ terp, '--start', '--autodir', autosavedir, gamefile ]
        else:
            args = [ terp, '--autodir', autosavedir, gamefile ]
        return (args, {})
        
    return (None, None)
        

# Late imports
from .sessions import get_playchannel, get_session_by_id
from .util import delete_flat_dir, load_json


