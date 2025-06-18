import time

class AttachList:
    def __init__(self):
        # maps channels to lists of Attachments
        self.map = {}

    def tryadd(self, obj, chan):
        """Add an attachment to the list associated with a channel, if
        it looks like a game file.
        The arguments are a Discord attachment and a Discord channel.
        """
        chanid = chan.id
        try:
            att = Attachment(obj)
        except:
            return
        if not detect_format(None, att.filename):
            # Doesn't look like a game file.
            return

        if chanid not in self.map:
            self.map[chanid] = []
        for oatt in self.map[chanid]:
            if oatt.url == att.url:
                # Already got this one. Bump the timestamp.
                # (This doesn't really help; Discord doesn't check for duplicate files. Let's pretend it will someday.)
                oatt.timestamp = att.timestamp
                return
        self.map[chanid].append(att)

    def getlist(self, chan):
        """Get the list of attachments associated with a channel.
        The argument is a Discord channel; the result is a list of
        our Attachment objects.
        """
        chanid = chan.id
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
