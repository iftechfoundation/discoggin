import time

class Session:
    def __init__(self, sessid, hash, movecount=0, lastupdate=None):
        if lastupdate is None:
            lastupdate = int(time.time())
        self.sessid = sessid
        self.hash = hash
        self.movecount = movecount
        self.lastupdate = lastupdate

    def __repr__(self):
        timestr = time.ctime(self.lastupdate)
        return '<Session %s (%s): %d moves, %s>' % (self.sessid, self.hash, self.movecount, timestr,)

class PlayChannel:
    def __init__(self, gckey, gid, chanid, sessid=None):
        self.gckey = gckey
        self.gid = gid
        self.chanid = chanid
        self.sessid = sessid

    def __repr__(self):
        val = ''
        if self.sessid:
            val = ' session %s' % (self.sessid,)
        return '<PlayChannel %s%s>' % (self.gckey, val,)
    
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

def get_available_session_for_hash(app, hash):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions WHERE hash = ?', (hash,))
    sessls = [ Session(*tup) for tup in res.fetchall() ]
    
    chanls = get_playchannels(app)
    chanmap = {}
    for playchan in chanls:
        if playchan.sessid:
            chanmap[playchan.sessid] = playchan

    availls = [ sess for sess in sessls if sess.sessid not in chanmap ]
    if not availls:
        return None
    availls.sort(key=lambda sess: sess.lastupdate)
    return availls[0]

def create_session(app, game):
    curs = app.db.cursor()
    res = curs.execute('SELECT sessid FROM sessions')
    idlist = [ tup[0] for tup in res.fetchall() ]
    if not idlist:
        sessid = 1
    else:
        sessid = 1 + max(idlist)
    tup = (sessid, game.hash, 0, int(time.time()))
    curs.execute('INSERT INTO sessions (sessid, hash, movecount, lastupdate) VALUES (?, ?, ?, ?)', tup)
    return Session(*tup)

def get_playchannels(app):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels')
    chanls = [ PlayChannel(*tup) for tup in res.fetchall() ]
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

def get_valid_playchannel(app, interaction):
    gid = interaction.guild_id
    if not gid:
        return None
    if not interaction.channel:
        return None
    chanid = interaction.channel.id
    if not chanid:
        return None
    
    gckey = '%s-%s' % (gid, chanid,)
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gckey = ?', (gckey,))
    tup = res.fetchone()
    if not tup:
        return None
    return PlayChannel(*tup)

def set_channel_session(app, playchan, session):
    curs = app.db.cursor()
    curs.execute('UPDATE channels SET sessid = ? WHERE gckey = ?', (session.sessid, playchan.gckey,))

