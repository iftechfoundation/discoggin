import time
import os, os.path
import logging

class Session:
    def __init__(self, sessid, gid, hash, movecount=0, lastupdate=None):
        if lastupdate is None:
            lastupdate = int(time.time())
        self.sessid = sessid
        self.gid = gid
        self.hash = hash
        self.movecount = movecount
        self.lastupdate = lastupdate

        self.sessdir = 's%d' % (self.sessid,)

    def __repr__(self):
        timestr = time.ctime(self.lastupdate)
        return '<Session %s (%s): %d moves, %s>' % (self.sessid, self.hash, self.movecount, timestr,)

    def logger(self):
        return logging.getLogger('cli.s%d' % (self.sessid,))

class PlayChannel:
    def __init__(self, gckey, gid, chanid, sessid=None):
        self.gckey = gckey
        self.gid = gid
        self.chanid = chanid
        self.sessid = sessid

        # Filled in by accessors that offer the withgame option
        self.game = None
        self.session = None

    def __repr__(self):
        val = ''
        if self.sessid:
            val = ' session %s' % (self.sessid,)
        return '<PlayChannel %s%s>' % (self.gckey, val,)

    def logger(self):
        if self.sessid:
            return logging.getLogger('cli.s%d' % (self.sessid,))
        else:
            return logging.getLogger('cli.s-')
    
def get_sessions(app):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions')
    sessls = [ Session(*tup) for tup in res.fetchall() ]
    return sessls
    
def get_session_by_id(app, sessid):
    try:
        sessid = int(sessid)
    except:
        return None
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions WHERE sessid = ?', (sessid,))
    tup = res.fetchone()
    if not tup:
        return None
    return Session(*tup)

def get_sessions_for_server(app, gid):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions WHERE gid = ?', (gid,))
    sessls = [ Session(*tup) for tup in res.fetchall() ]
    return sessls
    
def get_available_session_for_hash(app, hash, gid):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions WHERE hash = ? AND gid = ?', (hash, gid,))
    sessls = [ Session(*tup) for tup in res.fetchall() ]
    
    chanls = get_playchannels(app)
    chanmap = {}
    for playchan in chanls:
        if playchan.sessid:
            chanmap[playchan.sessid] = playchan

    availls = [ sess for sess in sessls if sess.sessid not in chanmap ]
    if not availls:
        return None
    availls.sort(key=lambda sess: -sess.lastupdate)
    return availls[0]

def create_session(app, game, gid):
    curs = app.db.cursor()
    res = curs.execute('SELECT sessid FROM sessions')
    idlist = [ tup[0] for tup in res.fetchall() ]
    if not idlist:
        sessid = 1
    else:
        sessid = 1 + max(idlist)
    tup = (sessid, gid, game.hash, 0, int(time.time()))
    curs.execute('INSERT INTO sessions (sessid, gid, hash, movecount, lastupdate) VALUES (?, ?, ?, ?, ?)', tup)
    return Session(*tup)

def delete_session(app, sessid):
    session = get_session_by_id(app, sessid)
    if session is None:
        return
    
    autosavedir = os.path.join(app.autosavedir, session.sessdir)
    delete_flat_dir(autosavedir)
    savefiledir = os.path.join(app.savefiledir, session.sessdir)
    delete_flat_dir(savefiledir)

    curs = app.db.cursor()
    curs.execute('UPDATE channels SET sessid = ? WHERE sessid = ?', (None, sessid,))
    curs.execute('DELETE FROM sessions WHERE sessid = ?', (sessid,))

def get_playchannels(app):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels')
    chanls = [ PlayChannel(*tup) for tup in res.fetchall() ]
    return chanls

def get_playchannels_for_server(app, gid, withgame=False):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gid = ?', (str(gid),))
    chanls = [ PlayChannel(*tup) for tup in res.fetchall() ]
    if withgame:
        for playchan in chanls:
            if playchan.sessid:
                playchan.session = get_session_by_id(app, playchan.sessid)
                if playchan.session.gid != gid:
                    raise Exception('session gid mismatch')
                if playchan.session and playchan.session.hash:
                    playchan.game = get_game_by_hash(app, playchan.session.hash)
    return chanls

def get_playchannel(app, gckey):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gckey = ?', (gckey,))
    tup = res.fetchone()
    if not tup:
        return None
    return PlayChannel(*tup)

def get_playchannel_for_session(app, sessid):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels where sessid = ?', (sessid,))
    # There shouldn't be more than one.
    tup = res.fetchone()
    if not tup:
        return None
    return PlayChannel(*tup)

def get_valid_playchannel(app, interaction=None, message=None, withgame=False):
    ### We call this on every message event, so it would be really good to cache the channel list.
    if interaction:
        gid = interaction.guild_id
        if not gid:
            return None
        if not interaction.channel:
            return None
        chanid = interaction.channel.id
        if not chanid:
            return None
    elif message:
        if not message.guild:
            return None
        gid = message.guild.id
        if not gid:
            return None
        if not message.channel:
            return None
        chanid = message.channel.id
        if not chanid:
            return None
    else:
        return None
    
    gckey = '%s-%s' % (gid, chanid,)
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gckey = ?', (gckey,))
    tup = res.fetchone()
    if not tup:
        return None
    playchan = PlayChannel(*tup)

    if withgame:
        if playchan.sessid:
            playchan.session = get_session_by_id(app, playchan.sessid)
            if playchan.session and playchan.session.hash:
                playchan.game = get_game_by_hash(app, playchan.session.hash)
    return playchan

def set_channel_session(app, playchan, session):
    curs = app.db.cursor()
    curs.execute('UPDATE channels SET sessid = ? WHERE gckey = ?', (session.sessid, playchan.gckey,))

def update_session_movecount(app, session, movecount=None):
    if movecount is None:
        movecount = session.movecount + 1
    curs = app.db.cursor()
    lastupdate = int(time.time())
    curs.execute('UPDATE sessions SET movecount = ?, lastupdate = ? WHERE sessid = ?', (movecount, lastupdate, session.sessid,))
    


# Late imports
from .games import get_game_by_hash
from .util import delete_flat_dir

