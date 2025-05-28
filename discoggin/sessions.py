import time

class Session:
    def __init__(self, sessid, hash, lastupdate=None):
        if lastupdate is None:
            lastupdate = int(time.time())
        self.sessid = sessid
        self.hash = hash
        self.lastupdate = lastupdate

    def __repr__(self):
        timestr = time.ctime(self.lastupdate)
        return '<Session %s (%s): %s>' % (self.sessid, self.hash, timestr,)

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

