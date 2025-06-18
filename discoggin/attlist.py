import time

class AttachList:
    def __init__(self):
        # maps channels to lists of Attachments
        self.map = {}

    def tryadd(self, obj, chanid):
        try:
            att = Attachment(obj)
        except:
            return
        if not detect_format(None, att.filename):
            # Doesn't look like a game file.
            return

        print('### adding', att, att.url, 'to', chanid)
        if chanid not in self.map:
            self.map[chanid] = []
        for oatt in self.map[chanid]:
            if oatt.url == att.url:
                # Already got this one. Bump the timestamp.
                oatt.timestamp = att.timestamp
                return
        self.map[chanid].append(att)

    def getlist(self, chanid):
        if chanid not in self.map:
            return []
        return list(self.map[chanid])

class Attachment:
    def __init__(self, obj):
        """The argument is a Discord Attachment object.
        We'll pull the interesting info from it.
        """
        if not obj.filename or not obj.url:
            raise Exception('missing fields')
        self.filename = obj.filename
        self.url = obj.url
        self.timestamp = time.time()
        
    def __repr__(self):
        return '<Attachment "%s">' % (self.filename,)


# Late imports
from .games import detect_format
