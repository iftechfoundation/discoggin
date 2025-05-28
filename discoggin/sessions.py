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

def get_sessions(app):
    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM sessions')
    sessls = [ Session(*tup) for tup in res.fetchall() ]
    return sessls
    
